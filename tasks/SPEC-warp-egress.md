# Spec: WARP egress for AI services

## Objective

Google returns `403 — Your client does not have permission to get URL / from this server`
to the edge node's egress IP. The server is in Germany, so this is not a geo restriction:
it is an IP/ASN reputation block on the hosting provider's range.

Route only the affected destinations through a Cloudflare WARP sidecar so they leave on
AS13335 instead of the hosting ASN. Every other destination keeps using the current
`DIRECT` outbound.

Users must not need to change their client configuration: the inbound, the WS path, the
edge domain and the subscription links stay byte-identical.

## Tech Stack

- Cloudflare WARP in a container: `caomingjun/warp:2026.6.880.0-2.12.0` (WARP client +
  GOST, SOCKS5/HTTP on port 1080, free tier, no license key)
- Xray core inside `ghcr.io/pasarguard/node:v0.5.4`, config stored in the PasarGuard
  panel database and seeded through the panel API
- Docker Compose, Traefik v3.7, GitHub Actions (CI + workflow_dispatch CD over SSH)

## Commands

```
Test:           python3 tests/test_migration_contract.py -v
                python3 tests/test_ci_workflow.py -v
                python3 scripts/test_seed_pasarguard.py -v
                python3 scripts/test_check_cloudflare.py -v
Render compose: docker compose --env-file .env.example config
Deploy:         gh workflow run cd.yml -f ref=<branch>
Verify egress:  docker exec pg-node sh -c 'curl -s https://cloudflare.com/cdn-cgi/trace'
```

## Project Structure

```
compose.yaml        → panel, node, and the new warp sidecar
compose.infra.yml   → traefik, postgres, shared networks (untouched)
config/xray.json    → core template: inbound, outbounds, routing
config/host.json    → subscription link template (untouched)
scripts/            → seed and health-check scripts + their unit tests
tests/              → compose and workflow contract tests
tasks/              → this spec
```

## Design

```
clients → Cloudflare → traefik:443 → pg-node (xray)
                                       ├── routing match → WARP outbound (socks5 warp:1080) → AS13335
                                       └── no match      → DIRECT (freedom)
```

Decisions and why:

- **Sidecar over host WARP.** Installing WARP on the host puts the default route in a
  tunnel and breaks the reply path for inbound SSH and 443. The sidecar keeps its tunnel
  inside its own network namespace, so the host routing table is untouched.
- **SOCKS5 outbound over Xray's native WireGuard outbound.** WireGuard-in-Xray would need
  `wgcf`-generated keys committed as secrets and depends on the core version bundled in the
  node image. SOCKS5 keeps the credential surface at zero.
- **No published port for the sidecar.** It is reachable only on `infra_proxy_net`. An
  open SOCKS5 proxy on a public port is an open relay.
- **Explicit domain suffixes, no `geosite:`.** `geosite:google` needs `geosite.dat` in the
  node image; if it is missing, the whole core config fails to load and every user drops.
  A literal suffix list has no runtime dependency.
- **Sniffing enabled with `destOverride: [http, tls]`.** Clients that resolve DNS locally
  send an IP, not a domain, and would bypass every domain rule. `domainStrategy: AsIs`
  keeps DNS resolution client-side.
- **Login domains travel with the service.** `accounts.google.com` and
  `googleusercontent.com` go through WARP too, so sign-in and the API call share one
  egress IP.

Routed through WARP:

| Service | Domains |
|---|---|
| Google AI | `gemini.google.com`, `aistudio.google.com`, `generativelanguage.googleapis.com` |
| Google sign-in and user content | `accounts.google.com`, `googleusercontent.com` |
| OpenAI | `openai.com`, `chatgpt.com`, `oaistatic.com`, `oaiusercontent.com` |
| Anthropic | `anthropic.com`, `claude.ai` |
| Copilot | `githubcopilot.com`, `copilot.microsoft.com` |

`googleusercontent.com` also serves user content for other Google products, so a little
non-AI traffic takes the tunnel as a side effect. Kept anyway, because Gemini loads its
attachments from it. `github.com` is deliberately not routed: Copilot works through
`githubcopilot.com`, and tunnelling git traffic would be a real slowdown.

Panel core updates use `PUT /api/core/{id}?restart_nodes=true` (verified against
`app/routers/core.py` at tag `v5.3.0`; `restart_nodes` is a required query parameter and
the node will not pick up new routing without it). `GET /api/cores` already returns each
core's full `config`, so drift detection needs no extra request.

## Testing Strategy

`unittest`, no external dependencies, run directly as scripts (existing convention).
Contract tests assert on file content, so they catch drift in compose, xray config and
workflows without needing a server. Unit tests cover the seed payload builders.
Runtime behaviour is verified by the CD egress gate, not by unit tests.

## Boundaries

- **Always:** keep the inbound, WS path and host template unchanged; keep the sidecar off
  public ports; pin image tags; extend the contract tests with every config change.
- **Ask first:** touching `.env` on the host, adding a paid WARP/Zero Trust subscription,
  widening the routed domain list, changing rollback semantics.
- **Never:** commit WARP registration data or secrets; publish port 1080; route all user
  traffic through the tunnel by default.

## Success Criteria

1. `docker exec pg-node curl -s -o /dev/null -w '%{http_code}' https://gemini.google.com/`
   returns `200`, and the same request from the host without the tunnel still returns `403`.
2. `cloudflare.com/cdn-cgi/trace` through the sidecar reports `warp=on` and `loc=DE`.
3. A non-routed destination still egresses on the server's own IP (no accidental
   full-tunnel).
4. Existing clients keep working with unchanged config; subscription links are unchanged.
5. Changing `config/xray.json` and re-running the seed updates the core config already
   stored in the panel database, instead of being silently skipped.
6. CD fails and rolls back if the tunnel is down or the routed destination is still
   blocked; rollback leaves no orphan sidecar container behind.
7. All four test suites and `docker compose --env-file .env.example config` pass in CI.

## Known risks

- **WARP reputation is shared.** Google can block AS13335 ranges too. If that happens the
  fix is an egress with a dedicated IP, not more WARP tuning.
- **Tunnel-in-tunnel MTU.** WARP uses 1280; large TLS records inside WS inside WireGuard
  can stall. Mitigation is the sidecar healthcheck plus the CD egress gate catching it
  before rollout completes.
- **Single point of failure for routed domains.** If the sidecar is down, the routed
  domains blackhole for all users while everything else keeps working. Mitigated by
  `restart: unless-stopped` and a healthcheck; an Xray balancer with DIRECT fallback is
  deliberately out of scope because it would silently re-expose the blocked IP.
- **Config drift becomes live on seed.** Once the core is updated in place with
  `restart_nodes=true`, a bad `config/xray.json` restarts the node and drops every
  connected user for a few seconds. The contract tests are the guard; keep them strict.

## Task list

- [ ] **Fix core update on drift.** `seed_pasarguard.py` only creates the core when absent,
  so config changes never reach the panel database.
  - Acceptance: seed sends `PUT` when the stored config differs, no write when identical.
  - Verify: `python3 scripts/test_seed_pasarguard.py -v`
  - Files: `scripts/seed_pasarguard.py`, `scripts/test_seed_pasarguard.py`
- [ ] **Add WARP outbound and routing to the core template.**
  - Acceptance: `WARP` socks outbound to `warp:1080`, routing rules for every routed
    domain, sniffing on, inbound unchanged.
  - Verify: `python3 tests/test_migration_contract.py -v`
  - Files: `config/xray.json`, `tests/test_migration_contract.py`
- [ ] **Add the warp sidecar to compose.**
  - Acceptance: pinned image, no `ports:`, `NET_ADMIN`, tun device rule, required sysctls,
    persistent registration under `./data/warp`, healthcheck, `infra_proxy_net` alias `warp`.
  - Verify: `docker compose --env-file .env.example config` + contract test
  - Files: `compose.yaml`, `tests/test_migration_contract.py`
- [ ] **Add the CD egress gate.**
  - Acceptance: after `up -d`, CD asserts `warp=on` through the sidecar and a `200` from a
    routed domain inside `pg-node`; failure triggers the existing rollback path.
  - Verify: `python3 tests/test_ci_workflow.py -v`
  - Files: `.github/workflows/cd.yml`, `tests/test_ci_workflow.py`
- [ ] **Make rollback complete.**
  - Acceptance: the restore step removes the sidecar when reverting to a compose file that
    does not define it.
  - Verify: `python3 tests/test_ci_workflow.py -v`
  - Files: `.github/workflows/cd.yml`, `tests/test_ci_workflow.py`
- [ ] **Document the change.**
  - Acceptance: README states which domains are tunnelled and how to verify egress.
  - Files: `README.md`

## Resolved decisions

1. Routed domains cover Google AI, OpenAI, Anthropic and Copilot (table above).
2. CD creates `data/warp` with `mkdir -p` before `up -d`; it is idempotent and keeps the
   host free of manual bootstrap steps.
