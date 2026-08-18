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

**CD flow:** backup remote stack → copy `compose.yaml` + config/scripts → `docker compose pull && up -d` → run Cloudflare health check → rollback from `.deploy-backup` on failure.

Repo vars/secrets for Actions are documented in `.env.example`.

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
