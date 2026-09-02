# pacman-vpn

Personal VLESS VPN stack (PasarGuard panel + node, Traefik, PostgreSQL).

Production is deployed via GitHub Actions CI/CD.

## CI/CD

| Workflow | Trigger | What it does |
|----------|---------|--------------|
| **CI** | push/PR to `main` | Python tests, `docker compose config` render check |
| **Secret Scan** | push/PR to `main` | Gitleaks secret scan |
| **Cloudflare** | push/PR, daily cron | DNS, SSL mode, public edge smoke test |
| **CD** | manual (`workflow_dispatch`) | SSH deploy to production |

**CD flow:** backup remote stack → copy `compose.yaml` + config/scripts → `docker compose pull && up -d` → WARP egress gate → Cloudflare health check → rollback from `.deploy-backup` on failure.

Repo vars/secrets for Actions are documented in `.env.example`.

## WARP egress for AI services

Google, OpenAI and Anthropic block the hosting provider's IP range, so those destinations
leave through a Cloudflare WARP sidecar (AS13335) instead of the server's own address.
Everything else keeps using the direct outbound. Clients need no configuration change.

Routed domains are the single `WARP` rule in `config/xray.json`. The sidecar exposes SOCKS5
only inside `infra_proxy_net` and never publishes a port. Design notes and trade-offs:
`tasks/SPEC-warp-egress.md`.

The core config lives in the panel database, so editing `config/xray.json` is not enough —
re-run the seed to push it. The seed sends `restart_nodes=true`, which briefly drops
connected users:

```bash
set -a; . ./.env; set +a
docker compose exec \
  -e EDGE_DOMAIN -e EDGE_PORT -e INBOUND_WS_PATH -e NODE_API_KEY -e NODE_IP \
  panel python3 /scripts/seed_pasarguard.py
```

Verify egress:

```bash
# tunnel is up and which country it exits from
docker compose exec warp curl -s --socks5-hostname 127.0.0.1:1080 \
  https://cloudflare.com/cdn-cgi/trace | grep -E '^(warp|loc)='

# the block is actually gone through the tunnel, and still present without it
docker compose exec warp curl -s -o /dev/null -w 'via warp: %{http_code}\n' \
  --socks5-hostname 127.0.0.1:1080 https://gemini.google.com/
curl -s -o /dev/null -w 'direct:   %{http_code}\n' https://gemini.google.com/
```

If the sidecar is down, only the routed domains fail; the rest of the tunnel keeps working.

## Local run

```bash
cp .env.example .env   # edit domains, passwords, paths
docker compose -f compose.infra.yml --env-file .env up -d --wait
mkdir -p data/pg-node/certs
openssl req -x509 -newkey rsa:2048 \
  -keyout data/pg-node/certs/ssl_key.pem \
  -out data/pg-node/certs/ssl_cert.pem \
  -days 3650 -nodes -subj '/CN=node.pasarguard'
docker compose --env-file .env up -d
```

`compose.infra.yml` starts Traefik and PostgreSQL and creates the shared Docker networks (`infra_proxy_net`, `infra_db_net`) that `compose.yaml` expects.

Point DNS for `XUI_DOMAIN` and `EDGE_DOMAIN` at this host (or `/etc/hosts` for local testing). Traefik serves HTTPS with its built-in default certificate for local use.

If `infra_proxy_net` or `infra_db_net` already exist, remove them first or reuse them as-is (`docker network rm infra_proxy_net infra_db_net`).
