# pacman-vpn

Personal VLESS VPN stack (PasarGuard panel + node, Traefik, PostgreSQL).

Production is deployed via GitHub Actions CI/CD.

## Domains

| Host | Env | Serves |
|---|---|---|
| `sub.example.com` | `SUB_DOMAIN` | subscriptions only — `https://…/sub/<token>`; any other path 404s |
| `edge.example.com` | `EDGE_DOMAIN` | tunnel inbounds over CF — legacy WS `/chat/sync`, WS `/chat/api/v4/websocket`, xhttp `/chat/api/v6/xhttp` |
| `xui-admin.example.com` | `XUI_DOMAIN` | admin console + `/api` + `/statics` — `/sub` is **not** served here |
| `files.mamahoos.ir` | — (fixed name) | TCP+TLS inbound — **grey-cloud on purpose**: the client dials the origin directly, Traefik routes by SNI; Cloudflare's HTTP proxy cannot carry raw TLS |

## Subscription flavours

Each subscription emits one link per host in the `edge` group:

| Flavour | Inbound | How it connects |
|---|---|---|
| chat WS | `VLESS_WS_CHAT` | WS through CF: `edge…/chat/api/v4/websocket` |
| fronted WS | `VLESS_WS_CHAT` (2nd host) | clean address (`chatgpt.com`), SNI/Host stay on `edge…` — domain fronting |
| xhttp | `VLESS_XHTTP` | `stream-one` xhttp through CF: `edge…/chat/api/v6/xhttp` |
| TCP+TLS | `VLESS_TCP_TLS` | raw TLS to `files.mamahoos.ir:443`, SNI-routed, no CF in the path |

The legacy `VLESS_WS` link (`edge…/chat/sync`) stays for already-active devices.

Caveats: the TCP+TLS link carries `allowinsecure=1` because the node serves its
self-signed certificate (`data/pg-node/certs`) — the cert is not verified on that
direct path. The grey-cloud `files` record exposes the origin IP for that name only.

New share-links come from the panel setting `Subscription.url_prefix`, which must be
set once to `https://<SUB_DOMAIN>` in panel settings — UI, QR codes and Telegram then
emit sub-host links. Links already issued under `<XUI_DOMAIN>/sub/...` stop working at
the router split, so users re-sync their subscription URL once. `SUB_DOMAIN` defaults
to `sub.mamahoos.ir` inside `compose.yaml` (no server `.env` change needed); the
Cloudflare gate reads the GitHub repo var of the same name and fails closed until it
exists.

## CI/CD

| Workflow | Trigger | What it does |
|----------|---------|--------------|
| **CI** | push/PR to `main` | Python tests, `docker compose config` render check |
| **Secret Scan** | push/PR to `main` | Gitleaks secret scan |
| **Cloudflare** | push/PR, daily cron | DNS, SSL mode, public edge smoke test |
| **DNS sync** | push (dns files), manual | dnscontrol creates/updates the `admin`/`sub`/`edge`/`files` A records (origin IP resolved over SSH) |
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

Point DNS for `XUI_DOMAIN`, `EDGE_DOMAIN` and `SUB_DOMAIN` at this host (or `/etc/hosts` for local testing). Traefik serves HTTPS with its built-in default certificate for local use.

If `infra_proxy_net` or `infra_db_net` already exist, remove them first or reuse them as-is (`docker network rm infra_proxy_net infra_db_net`).
