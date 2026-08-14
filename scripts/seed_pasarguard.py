#!/usr/bin/env python3
"""Idempotently seed PasarGuard core, group, host, node, and users."""

from __future__ import annotations

import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


def require_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise SystemExit(f"missing env {name}")
    return value


def panel_root() -> str:
    host = os.environ.get("PANEL_IP", "").strip() or os.environ.get("XUI_HOST", "pasarguard")
    port = os.environ.get("UVICORN_PORT", "8000").strip()
    return f"http://{host}:{port}"


def load_json(path: Path) -> Any:
    return json.loads(path.read_text())


def fill_xray(config: dict[str, Any], edge_domain: str, edge_port: int, ws_path: str) -> dict[str, Any]:
    inbound = config["inbounds"][0]
    inbound["port"] = edge_port
    inbound["streamSettings"]["security"] = "none"
    inbound["streamSettings"]["network"] = "ws"
    inbound["streamSettings"]["wsSettings"]["path"] = ws_path
    inbound["streamSettings"]["wsSettings"]["host"] = edge_domain
    return config


def fill_host(host: dict[str, Any], edge_domain: str, ws_path: str) -> dict[str, Any]:
    filled = json.loads(json.dumps(host))
    filled["address"] = [edge_domain]
    filled["sni"] = [edge_domain]
    filled["host"] = [edge_domain]
    filled["path"] = ws_path
    filled["port"] = 443
    filled["security"] = "tls"
    filled["fingerprint"] = "chrome"
    return filled


def normalize_username(email: str) -> str:
    raw = re.sub(r"[^a-zA-Z0-9_]", "_", email.strip()).strip("_")
    raw = raw.lower()
    if len(raw) < 3:
        raw = (raw + "_user")[:32]
    return raw[:32]


class Panel:
    def __init__(self, root: str, username: str, password: str) -> None:
        self.root = root.rstrip("/")
        self.username = username
        self.password = password
        self.token = ""

    def _request(self, method: str, path: str, payload: Any | None = None, form: dict[str, str] | None = None) -> tuple[int, Any]:
        data = None
        headers = {"User-Agent": "pacman-pasarguard-seed"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        if form is not None:
            data = urllib.parse.urlencode(form).encode()
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        elif payload is not None:
            data = json.dumps(payload).encode()
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(self.root + path, data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                body = resp.read().decode("utf-8", "replace")
                try:
                    parsed: Any = json.loads(body) if body else {}
                except json.JSONDecodeError:
                    parsed = body
                return resp.status, parsed
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", "replace")
            try:
                parsed = json.loads(body) if body else {"detail": body}
            except json.JSONDecodeError:
                parsed = {"detail": body[:300]}
            return exc.code, parsed

    def wait_ready(self, attempts: int = 40, delay: float = 3.0) -> None:
        last = ""
        for _ in range(attempts):
            try:
                code, _ = self._request("GET", "/")
                last = str(code)
                if code in (200, 307, 308, 404):
                    return
            except urllib.error.URLError as exc:
                last = str(exc)
            time.sleep(delay)
        raise SystemExit(f"panel not ready at {self.root}: {last}")

    def login(self) -> None:
        code, payload = self._request(
            "POST",
            "/api/admin/token",
            form={"username": self.username, "password": self.password, "grant_type": "password"},
        )
        if code != 200 or not isinstance(payload, dict) or not payload.get("access_token"):
            raise SystemExit(f"login failed HTTP {code}: {payload}")
        self.token = payload["access_token"]

    def api(self, method: str, path: str, payload: Any | None = None) -> Any:
        code, body = self._request(method, path, payload=payload)
        if code >= 400:
            raise SystemExit(f"api {method} {path} HTTP {code}: {body}")
        return body


def find_named(items: list[dict[str, Any]], name: str) -> dict[str, Any] | None:
    for item in items:
        if item.get("name") == name:
            return item
    return None


def seed(panel: Panel) -> None:
    edge_domain = require_env("EDGE_DOMAIN")
    edge_port = int(os.environ.get("EDGE_PORT", "10086"))
    ws_path = os.environ.get("INBOUND_WS_PATH", "/chat/sync").strip() or "/chat/sync"
    xray_path = Path(os.environ.get("XRAY_TEMPLATE", "/config/xray.json"))
    host_path = Path(os.environ.get("HOST_TEMPLATE", "/config/host.json"))
    clients_path = Path(os.environ.get("CLIENTS_FILE", "/config/clients.json"))
    node_ip = os.environ.get("NODE_IP", "").strip() or "node.pasarguard"
    node_api_key = require_env("NODE_API_KEY")
    node_ca_path = Path(os.environ.get("NODE_CA_FILE", "/node-certs/ssl_cert.pem"))

    xray = fill_xray(load_json(xray_path), edge_domain, edge_port, ws_path)
    host = fill_host(load_json(host_path), edge_domain, ws_path)
    clients = load_json(clients_path)
    if not isinstance(clients, list) or not clients:
        raise SystemExit("clients file must be a non-empty list")

    cores = panel.api("GET", "/api/cores").get("cores") or []
    core = find_named(cores, "xray-edge")
    if core is None:
        core = panel.api(
            "POST",
            "/api/core",
            {
                "name": "xray-edge",
                "type": "xray",
                "config": xray,
                "exclude_inbound_tags": [],
                "fallbacks_inbound_tags": [],
            },
        )
        print("created core id=", core.get("id"))
    else:
        print("core exists id=", core.get("id"))
    core_id = int(core["id"])

    groups = (panel.api("GET", "/api/groups") or {}).get("groups") or []
    group = find_named(groups, "edge")
    if group is None:
        group = panel.api("POST", "/api/group", {"name": "edge", "inbound_tags": ["VLESS_WS"]})
        print("created group id=", group.get("id"))
    group_id = int(group["id"])

    hosts = panel.api("GET", "/api/hosts") or []
    existing_host = next((item for item in hosts if item.get("inbound_tag") == "VLESS_WS"), None)
    if existing_host is None:
        created_host = panel.api("POST", "/api/host/", host)
        print("created host id=", created_host.get("id"))
    else:
        print("host exists id=", existing_host.get("id"))

    if not node_ca_path.is_file():
        raise SystemExit(f"missing node cert {node_ca_path}")
    server_ca = node_ca_path.read_text().strip()
    nodes = (panel.api("GET", "/api/nodes") or {}).get("nodes") or []
    node = find_named(nodes, "local")
    if node is None:
        node = panel.api(
            "POST",
            "/api/node",
            {
                "name": "local",
                "address": node_ip,
                "port": 62050,
                "connection_type": "grpc",
                "server_ca": server_ca,
                "keep_alive": 60,
                "core_config_id": core_id,
                "api_key": node_api_key,
            },
        )
        print("created node id=", node.get("id"), "status=", node.get("status"))
    else:
        print("node exists id=", node.get("id"), "status=", node.get("status"))

    existing_users = (panel.api("GET", "/api/users") or {}).get("users") or []
    existing_names = {item.get("username") for item in existing_users}
    for client in clients:
        username = normalize_username(str(client.get("email") or client.get("username") or ""))
        uuid = str(client.get("id") or "").strip()
        if not username or not uuid:
            raise SystemExit(f"client missing email/id: {client.keys()}")
        if username in existing_names:
            print("user exists", username)
            continue
        panel.api(
            "POST",
            "/api/user",
            {
                "username": username,
                "status": "active",
                "group_ids": [group_id],
                "proxy_settings": {"vless": {"id": uuid}},
            },
        )
        print("created user", username)

    print("seed complete users=", len(clients))


def main() -> None:
    panel = Panel(panel_root(), require_env("SUDO_USERNAME"), require_env("SUDO_PASSWORD"))
    panel.wait_ready()
    panel.login()
    seed(panel)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
