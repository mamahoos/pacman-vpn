# Spec: Domain separation — sub / edge / admin

## Objective

Give each public hostname exactly one role:

| Hostname | Serves | Status |
|---|---|---|
| `sub.mamahoos.ir` | subscription endpoints (`/sub/...`) | **new** |
| `edge.mamahoos.ir` | tunnel inbound (xray WS `/chat/sync`) | exists — `EDGE_DOMAIN`, unchanged |
| `admin.mamahoos.ir` | PasarGuard admin panel (console + `/api` + `/statics`) | exists — `XUI_DOMAIN`, loses `/sub` |

Today the `xui` Traefik router matches `PathPrefix(/sub)` on `XUI_DOMAIN`, so the admin
host serves both the console and subscription links. After this change the subscription
share-link points at `sub.mamahoos.ir`, the admin host serves only the panel, and the
sub and admin domains are fully separate (spec explicitly separates sub & admin).

## Assumptions

1. `sub.mamahoos.ir` routes to the **same panel container** — a second Traefik router on
   the `panel` service, not a second container.
2. The new env var is named `SUB_DOMAIN`, following `XUI_DOMAIN` / `EDGE_DOMAIN`.
3. The subscription path stays `/sub` on the new host, so URLs look like
   `https://sub.mamahoos.ir/sub/<token>` — no panel `SUBSCRIPTION_PATH` change.
4. `PathPrefix(/sub)` is **removed** from the `xui` (admin) router rule. Links already
   distributed under `admin.mamahoos.ir/sub/...` stop working → users re-sync their
   subscription URL once.
5. `edge.mamahoos.ir` needs no change; listed here only so the spec covers all three.
6. DNS: `sub.mamahoos.ir` is a proxied record in the same Cloudflare zone, TLS mode
   `full`/`strict` like the other two.

→ Correct these now if any is wrong; the task list assumes all six.

## Tech Stack

- Traefik v3.7 router labels on the existing `ghcr.io/pasarguard/panel` service
  (compose rendered from `.env`)
- Cloudflare DNS (proxied) + `scripts/check_cloudflare.py` DNS/SSL/smoke gate
- GitHub Actions: `ci.yml` (contract tests), `cd.yml`, `cloudflare.yml`
- `unittest` contract tests asserting on file content (existing convention)

## Commands

```
Test:           python3 tests/test_migration_contract.py -v
                python3 tests/test_ci_workflow.py -v
                python3 scripts/test_seed_pasarguard.py -v
                python3 scripts/test_check_cloudflare.py -v
Render compose: docker compose --env-file .env.example config
DNS gate:       gh workflow run cloudflare.yml
Deploy:         gh workflow run cd.yml -f ref=<branch>
Smoke:          curl -sI https://sub.mamahoos.ir/sub/<token>   # expect 200
                curl -sI https://admin.mamahoos.ir/sub/x       # expect 404
```

## Project Structure

```
compose.yaml                 → split xui/sub routers (the change)
.env.example                 → new SUB_DOMAIN placeholder
.github/workflows/cd.yml     → pass SUB_DOMAIN where XUI_DOMAIN is passed
.github/workflows/cloudflare.yml → pass SUB_DOMAIN to the DNS gate
scripts/check_cloudflare.py  → validate the third host
tests/                       → contract tests extended for the split
tasks/SPEC-domain-separation.md → this spec
```

## Code Style

One router split, label style unchanged (existing quoting and `${VAR}` interpolation):

```yaml
# panel service, before:
- "traefik.http.routers.xui.rule=Host(`${XUI_DOMAIN}`) && (PathPrefix(`${XUI_BASE_PATH}`) || PathPrefix(`/api`) || PathPrefix(`/statics`) || PathPrefix(`/sub`))"
# after:
- "traefik.http.routers.xui.rule=Host(`${XUI_DOMAIN}`) && (PathPrefix(`${XUI_BASE_PATH}`) || PathPrefix(`/api`) || PathPrefix(`/statics`))"
- "traefik.http.routers.sub.rule=Host(`${SUB_DOMAIN}`) && PathPrefix(`/sub`)"
- "traefik.http.routers.sub.entrypoints=websecure"
- "traefik.http.routers.sub.tls=true"
```

Contract test style — assert on content, one assertion per invariant:

```python
self.assertIn("Host(`${SUB_DOMAIN}`) && PathPrefix(`/sub`)", compose)
self.assertNotIn("PathPrefix(`/sub`)", xui_rule)   # xui_rule = the xui rule line
```

## Design

```
clients → cloudflare → traefik:443
  ├─ Host(sub.mamahoos.ir)   && /sub/*      → panel (subscription)
  ├─ Host(admin.mamahoos.ir) && console/api/statics → panel (admin)
  └─ Host(edge.mamahoos.ir)                 → pg-node (xray WS)   [unchanged]
```

Decisions and why:

- **Two routers, one container.** The subscription endpoint is a panel route backed by
  the same database; a second container would duplicate state for no isolation gain.
  Isolation needed here is at the hostname/routing layer.
- **Sub router matches `/sub` only.** Any other path on `sub.mamahoos.ir` matches no
  router → Traefik 404. The sub host can never reach the console or `/api`.
- **Keep `/sub` prefix on the new host** (assumption 3): zero panel-configuration
  change, and `SUBSCRIPTION_PATH: sub` stays truthful. Stripping the prefix with
  middleware would need the panel to tolerate a rewritten path — rejected as magic.
- **Host check follows the name.** `check_cloudflare.py` already gates `XUI_DOMAIN` and
  `EDGE_DOMAIN`; a third hostname without a DNS gate would silently rot.

## Testing Strategy

Contract tests (file-content assertions, no server):

- `test_compose_keeps_panel_path_and_exposes_api` — must keep passing: `/api`,
  `/statics`, `DASHBOARD_PATH` stay on the admin host; `/sub` asserted on the new
  router instead of the old location.
- New: sub router exists with `Host(SUB_DOMAIN) && PathPrefix(/sub)`; xui rule no
  longer contains `PathPrefix(/sub)`.
- `tests/test_ci_workflow.py` / `scripts/test_check_cloudflare.py` — `SUB_DOMAIN`
  passthrough and third-host evaluation.

Runtime behaviour is verified by the `cloudflare.yml` gate + manual smoke, not unit
tests.

## Boundaries

- **Always:** pin image tags; extend contract tests with every config change; keep the
  inbound, WS path, `config/host.json` and `edge.mamahoos.ir` untouched; keep
  `/api` + `/statics` + console on the admin host.
- **Ask first:** adding the GitHub repo var `SUB_DOMAIN`; touching `.env` on the host;
  removing `/sub` from the admin host (breaks issued links — assumption 4); changing
  the subscription URL shape users see.
- **Never:** commit `.env`; invent panel API/config keys (verify against the pinned
  panel tag first); delete a failing test to get green.

## Success Criteria

1. `https://sub.mamahoos.ir/sub/<valid-token>` returns `200` after deploy.
2. `https://admin.mamahoos.ir/sub/<anything>` no longer serves subscriptions (404).
3. Admin console, `/api` and `/statics` work only on `admin.mamahoos.ir`.
4. `edge.mamahoos.ir` client configs are byte-identical (no user action).
5. `check_cloudflare.py` passes validating all three hostnames (proxied + full/strict).
6. All four test suites and `docker compose --env-file .env.example config` green in CI.

## Known risks

- **Verified (task 1): links do not use the request host.** They come from the
  `Subscription.url_prefix` setting; a relative/empty prefix is resolved by the
  dashboard against its own origin (= the admin host). Consequence: `url_prefix` must
  be set to `https://sub.mamahoos.ir` **before** `/sub` leaves the admin host, or every
  link the UI/QR/Telegram emits 404s. The deploy order is now a hard gate, not a
  guess.
- **Issued links break** when `/sub` leaves the admin host (assumption 4). Mitigation:
  re-sync window announced before deploy, or temporarily keep `/sub` on both routers.
- **CI/CD red until the `SUB_DOMAIN` var exists.** `check_cloudflare.py` uses
  `require_env`, so `cloudflare.yml` fails closed until the GitHub repo var is added
  (manual step, outside the repo).
- **Config drift goes live on CD.** The split only takes effect on deploy; a stale
  local `.env` without `SUB_DOMAIN` renders a broken router rule — caught by
  `docker compose config` + contract tests before rollout.

## Task list

- [x] **Verify panel subscription URL generation.** *(done — findings in Resolved
  decisions 4; source inspected at tag `v5.5.0`)* Inspect PasarGuard panel source at
  the pinned tag: does it build `/sub` URLs from the request host or from config?
  Record the answer under Resolved decisions; if config-based, stop and redesign.
  - Acceptance: answer written in this spec; no code changed.
  - Verify: spec updated + committed.
  - Files: `tasks/SPEC-domain-separation.md`
- [ ] **Add `SUB_DOMAIN` to env plumbing.** `.env.example` (`SUB_DOMAIN=sub.example.com`),
  `cd.yml` + `cloudflare.yml` env passthrough next to `XUI_DOMAIN`.
  - Acceptance: compose renders with `.env.example`; workflows pass the var.
  - Verify: `docker compose --env-file .env.example config` + `python3 tests/test_ci_workflow.py -v`
  - Files: `.env.example`, `.github/workflows/cd.yml`, `.github/workflows/cloudflare.yml`
- [ ] **Split the Traefik routers in compose.**
  - Acceptance: xui rule has no `/sub`; sub router = `Host(SUB_DOMAIN) && PathPrefix(/sub)`
    with `websecure` + `tls`; panel service otherwise untouched.
  - Verify: `docker compose --env-file .env.example config` + contract tests
  - Files: `compose.yaml`
- [ ] **Extend contract tests for the split.**
  - Acceptance: new assertions for the sub router and the removed `/sub` from xui;
    existing panel-path test still passes.
  - Verify: `python3 tests/test_migration_contract.py -v`
  - Files: `tests/test_migration_contract.py`
- [ ] **Gate the third host in the DNS check.**
  - Acceptance: `evaluate_hosts` covers panel, edge and sub; unit test for the new host.
  - Verify: `python3 scripts/test_check_cloudflare.py -v`
  - Files: `scripts/check_cloudflare.py`, `scripts/test_check_cloudflare.py`
- [ ] **Manual: DNS + repo var.** Add proxied `sub.mamahoos.ir` A record; add GitHub
  repo var `SUB_DOMAIN`.
  - Acceptance: `cloudflare.yml` green on all three hosts.
  - Verify: `gh workflow run cloudflare.yml`
- [ ] **Document the domains.** README domain table: sub / edge / admin roles and the
  new subscription URL shape.
  - Acceptance: README matches shipped behaviour.
  - Files: `README.md`

## Open Questions

1. Keep or drop `admin.mamahoos.ir/sub/...` during a transition window? — **resolved
   pending decision acceptance**: the decision packet (architecture-decision-making,
   status `proposed`) selects a staged Traefik `RedirectRegex` (308) so the admin host
   stops *serving* `/sub` at stage 1 while every issued link keeps working, with the
   path + middleware removed together at stage 2.
2. ~~Should the panel UI show the `sub.mamahoos.ir` link explicitly?~~ **Answered
   (task 1):** set `Subscription.url_prefix = https://sub.mamahoos.ir` in panel
   settings — UI, QR and Telegram then emit absolute sub-host links with no code
   change. The seed script does not touch settings (verified), so this is a manual
   panel step or a future seed extension.

## Resolved decisions

1. One panel container, two routers (hostname-level isolation only).
2. `/sub` prefix retained on the new host; `SUBSCRIPTION_PATH` unchanged.
3. Edge domain and client configs are out of scope — byte-identical.
4. *(task 1, verified against `PasarGuard/panel@v5.5.0` source)* Subscription links are
   config-derived, not request-derived: `generate_subscription_url` in
   `app/operation/user.py` returns `f"{url_prefix}/{path}/{token}"` where `url_prefix`
   is the `Subscription.url_prefix` setting with a per-user `user.admin.sub_domain`
   override. The dashboard resolves relative prefixes with `window.location.origin`
   (`resolveSubscriptionQrUrl`) and passes absolute prefixes through unchanged.
   Serving is host-agnostic: the router is `prefix=/{path}/{token}` with no
   `ALLOWED_HOSTS`/CORS host restriction, so any hostname Traefik routes will serve
   the endpoint.
