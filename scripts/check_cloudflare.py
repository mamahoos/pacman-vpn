#!/usr/bin/env python3
"""Verify Cloudflare DNS, SSL mode, and public edge/panel smoke checks."""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

API_BASE = "https://api.cloudflare.com/client/v4"
RECORD_TYPES = {"A", "AAAA", "CNAME"}
OK_SSL = {"full", "strict"}
OK_EDGE_STATUS = {400, 426}


def require_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise SystemExit(f"missing env {name}")
    return value


def evaluate_hosts(records: list[dict[str, Any]], panel_host: str, edge_host: str) -> list[str]:
    errors: list[str] = []
    for hostname in (panel_host, edge_host):
        error = _evaluate_host(records, hostname)
        if error:
            errors.append(error)
    return errors


def _evaluate_host(records: list[dict[str, Any]], hostname: str) -> str | None:
    name = hostname.rstrip(".").lower()
    matches = [
        record
        for record in records
        if str(record.get("name", "")).rstrip(".").lower() == name
        and str(record.get("type", "")).upper() in RECORD_TYPES
    ]
    if not matches:
        return f"missing proxied A/AAAA/CNAME for {hostname}"
    dns_only = [record for record in matches if not record.get("proxied")]
    if dns_only:
        types = ",".join(sorted({str(record.get("type")) for record in dns_only}))
        return f"{hostname} has DNS-only {types} record(s); expected proxied"
    return None


def evaluate_ssl(value: str) -> list[str]:
    mode = value.strip().lower()
    if mode in OK_SSL:
        return []
    return [f"ssl mode {value!r} is not full or strict"]


def evaluate_smoke(panel_status: int, edge_status: int) -> list[str]:
    errors: list[str] = []
    if panel_status != 200:
        errors.append(f"panel HTTP {panel_status}, expected 200")
    if edge_status not in OK_EDGE_STATUS:
        errors.append(f"edge HTTP {edge_status}, expected 400 or 426 websocket")
    return errors


def _request_json(url: str, token: str) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            payload = json.loads(response.read().decode())
    except urllib.error.HTTPError as exc:
        body = exc.read().decode(errors="replace")
        raise SystemExit(f"cloudflare API HTTP {exc.code}: {body[:300]}") from exc
    if not isinstance(payload, dict) or not payload.get("success"):
        raise SystemExit(f"cloudflare API error: {payload}")
    return payload


def fetch_dns_records(zone_id: str, token: str, hostnames: list[str]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for hostname in hostnames:
        query = urllib.parse.urlencode({"name": hostname, "per_page": 100})
        url = f"{API_BASE}/zones/{zone_id}/dns_records?{query}"
        payload = _request_json(url, token)
        result = payload.get("result") or []
        if isinstance(result, list):
            records.extend(item for item in result if isinstance(item, dict))
    return records


def fetch_ssl_mode(zone_id: str, token: str) -> str:
    payload = _request_json(f"{API_BASE}/zones/{zone_id}/settings/ssl", token)
    result = payload.get("result") or {}
    if not isinstance(result, dict):
        raise SystemExit("cloudflare ssl setting missing")
    return str(result.get("value") or "")


def http_status(url: str) -> int:
    request = urllib.request.Request(
        url,
        method="GET",
        headers={"User-Agent": "pacman-vpn-ci/1.0"},
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return int(response.status)
    except urllib.error.HTTPError as exc:
        return int(exc.code)


def main() -> int:
    token = require_env("CLOUDFLARE_API_TOKEN")
    zone_id = require_env("CLOUDFLARE_ZONE_ID")
    panel_host = require_env("XUI_DOMAIN")
    edge_host = require_env("EDGE_DOMAIN")
    ws_path = os.environ.get("INBOUND_WS_PATH", "/chat/sync").strip() or "/chat/sync"
    panel_path = os.environ.get("XUI_BASE_PATH", "").strip()
    skip_smoke = os.environ.get("SKIP_SMOKE", "").strip() in {"1", "true", "yes"}

    records = fetch_dns_records(zone_id, token, [panel_host, edge_host])
    errors = evaluate_hosts(records, panel_host, edge_host)
    errors.extend(evaluate_ssl(fetch_ssl_mode(zone_id, token)))

    if skip_smoke or not panel_path:
        if not skip_smoke and not panel_path:
            print("skipping smoke: missing env XUI_BASE_PATH")
    else:
        panel_url = f"https://{panel_host}{panel_path}"
        edge_url = f"https://{edge_host}{ws_path}"
        errors.extend(evaluate_smoke(http_status(panel_url), http_status(edge_url)))

    if errors:
        print("cloudflare check failed:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1
    print("cloudflare check passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
