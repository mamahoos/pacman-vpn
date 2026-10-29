# pacman-vpn

Personal VLESS VPN stack (PasarGuard panel + node, Traefik, PostgreSQL).

Production is deployed via GitHub Actions CI/CD.

## CI/CD

| Workflow | Trigger | What it does |
|----------|---------|--------------|
| **CI** | push/PR to `main` | Python tests, `docker compose config` render check |
| **Secret Scan** | push/PR to `main` | Gitleaks secret scan |
| **Cloudflare** | push/PR, daily cron | DNS, SSL mode, public edge smoke test |
| **CD** | manual (`workflow_dispatch`) | SSH deploy to production (`scope=panel` default) |

**CD flow:** backup remote stack → copy `compose.yaml` + config/scripts → deploy by `scope` → Cloudflare health check → rollback from `.deploy-backup` on failure.

- `scope=panel` (default): `docker compose pull panel && up -d --no-deps panel`. Does not seed or recreate `node`.
- `scope=all`: `docker compose pull && up -d --remove-orphans` then seed.

Repo vars/secrets for Actions are documented in `.env.example`.

## Seeding the core config

The core config lives in the panel database, so editing `config/xray.json` is not enough —
re-run the seed to push it. The seed sends `restart_nodes=true`, which briefly drops
connected users:

```bash
set -a; . ./.env; set +a
docker compose exec \
  -e EDGE_DOMAIN -e EDGE_PORT -e INBOUND_WS_PATH -e NODE_API_KEY -e NODE_IP \
  panel python3 /scripts/seed_pasarguard.py
```

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
