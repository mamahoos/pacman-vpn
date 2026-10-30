#!/usr/bin/env python3
import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class PasarGuardMigrationContractTests(unittest.TestCase):
    def test_compose_pins_latest_stable_images(self):
        compose = (ROOT / "compose.yaml").read_text()
        self.assertIn("ghcr.io/pasarguard/panel:", compose)
        self.assertIn("ghcr.io/pasarguard/node:", compose)
        self.assertNotIn(":latest", compose)
        self.assertNotIn("ghcr.io/mhsanaei/3x-ui", compose)

    def test_compose_keeps_panel_path_and_exposes_api(self):
        compose = (ROOT / "compose.yaml").read_text()
        self.assertIn("PathPrefix(`${XUI_BASE_PATH}`)", compose)
        self.assertIn("PathPrefix(`/api`)", compose)
        self.assertIn("PathPrefix(`/statics`)", compose)
        self.assertIn("DASHBOARD_PATH: ${XUI_BASE_PATH}", compose)
        self.assertIn("UVICORN_HOST", compose)

    def test_compose_routes_edge_to_node_inbound_port(self):
        compose = (ROOT / "compose.yaml").read_text()
        self.assertIn("traefik.http.routers.edge.rule=Host(`${EDGE_DOMAIN}`)", compose)
        self.assertIn("loadbalancer.server.port=${EDGE_PORT}", compose)
        self.assertIn("container_name: pg-node", compose)

    def test_xray_inbound_stays_plaintext_vless_ws(self):
        inbound = json.loads((ROOT / "config" / "xray.json").read_text())["inbounds"][0]
        self.assertEqual(inbound["protocol"], "vless")
        self.assertEqual(inbound["port"], 10086)
        self.assertEqual(inbound["streamSettings"]["network"], "ws")
        self.assertEqual(inbound["streamSettings"]["security"], "none")
        self.assertEqual(inbound["streamSettings"]["wsSettings"]["path"], "/chat/sync")
        self.assertEqual(inbound["tag"], "VLESS_WS")

    def test_xray_sniffs_destination_for_domain_routing(self):
        inbound = json.loads((ROOT / "config" / "xray.json").read_text())["inbounds"][0]
        sniffing = inbound["sniffing"]
        self.assertTrue(sniffing["enabled"])
        self.assertEqual(sniffing["destOverride"], ["http", "tls"])

    def test_xray_keeps_direct_as_default_outbound(self):
        outbounds = json.loads((ROOT / "config" / "xray.json").read_text())["outbounds"]
        self.assertEqual(outbounds[0]["tag"], "DIRECT")
        self.assertEqual(outbounds[0]["protocol"], "freedom")
        self.assertIn("BLOCK", [item["tag"] for item in outbounds])

    def test_warp_egress_removed_from_stack(self):
        compose = (ROOT / "compose.yaml").read_text().lower()
        xray_text = (ROOT / "config" / "xray.json").read_text()
        self.assertNotIn("warp", compose)
        self.assertNotIn("warp", xray_text.lower())
        self.assertNotIn("caomingjun/warp", compose)
        self.assertNotIn("./data/warp", compose)
        config = json.loads(xray_text)
        self.assertEqual(config["routing"]["rules"], [])
        self.assertEqual(
            [item["tag"] for item in config["outbounds"]],
            ["DIRECT", "BLOCK"],
        )

    def test_compose_splits_subscription_to_third_host(self):
        compose = (ROOT / "compose.yaml").read_text()
        self.assertIn(
            "traefik.http.routers.sub.rule=Host(`${SUB_DOMAIN:-sub.mamahoos.ir}`) && PathPrefix(`/sub`)",
            compose,
        )
        self.assertIn("traefik.http.routers.sub.entrypoints=websecure", compose)
        self.assertIn("traefik.http.routers.sub.tls=true", compose)
        self.assertIn("traefik.http.routers.sub.service=xui", compose)
        xui_rule = next(
            line for line in compose.splitlines() if "traefik.http.routers.xui.rule=" in line
        )
        self.assertNotIn("PathPrefix(`/sub`)", xui_rule)
        self.assertIn("PathPrefix(`/api`)", xui_rule)
        self.assertIn("PathPrefix(`/statics`)", xui_rule)

    def test_dns_config_manages_four_hosts_without_hardcoded_ip(self):
        cfg = (ROOT / ".github" / "dns" / "dnsconfig.js").read_text()
        self.assertIn("NO_PURGE", cfg)
        self.assertIn('cloudflare_proxy: "on"', cfg)
        for host in ("admin", "sub", "edge"):
            self.assertIn(f'A("{host}", "__ORIGIN_IP__"', cfg)
            self.assertIn(f'A("{host}", "__ORIGIN_IP__", TTL(1), CF_PROXY_ON)', cfg)
        # TCP+TLS flavour must bypass the CF HTTP proxy: grey-cloud record
        self.assertIn('A("files", "__ORIGIN_IP__"', cfg)
        self.assertIn('A("files", "__ORIGIN_IP__", TTL(1), CF_PROXY_OFF)', cfg)
        self.assertIsNone(re.search(r"\b\d{1,3}(?:\.\d{1,3}){3}\b", cfg))
        creds = json.loads((ROOT / ".github" / "dns" / "creds.json").read_text())
        self.assertEqual(
            creds["cloudflare"]["apitoken"], "$CLOUDFLARE_API_TOKEN"
        )

    def test_host_link_uses_edge_tls_on_443(self):
        hosts = json.loads((ROOT / "config" / "host.json").read_text())
        self.assertIsInstance(hosts, list)
        self.assertEqual(len(hosts), 5)
        host = next(h for h in hosts if h["inbound_tag"] == "VLESS_WS")
        self.assertIn("edge.example.com", host["address"])
        self.assertEqual(host["port"], 443)
        self.assertEqual(host["security"], "tls")
        self.assertEqual(host["fingerprint"], "chrome")
        self.assertEqual(host["path"], "/chat/sync")

    def test_chat_inbound_is_routed_and_seeded_consistently(self):
        """The secondary inbound must agree on tag/port/path in all three files."""
        config = json.loads((ROOT / "config" / "xray.json").read_text())
        inbound = next(
            (i for i in config["inbounds"] if i["tag"] == "VLESS_WS_CHAT"), None
        )
        self.assertIsNotNone(inbound, "VLESS_WS_CHAT inbound missing")
        self.assertEqual(inbound["protocol"], "vless")
        self.assertEqual(inbound["streamSettings"]["network"], "ws")
        self.assertEqual(inbound["streamSettings"]["security"], "none")
        path = inbound["streamSettings"]["wsSettings"]["path"]
        self.assertEqual(path, "/chat/api/v4/websocket")
        self.assertNotEqual(inbound["port"], config["inbounds"][0]["port"])

        compose = (ROOT / "compose.yaml").read_text()
        self.assertIn(
            "traefik.http.routers.edge-chat.rule=Host(`${EDGE_DOMAIN}`) && "
            f"PathPrefix(`{path}`)",
            compose,
        )
        self.assertIn("traefik.http.routers.edge-chat.tls=true", compose)
        self.assertIn(
            "traefik.http.services.edge-chat-svc.loadbalancer.server.port="
            f"{inbound['port']}",
            compose,
        )
        # priority beats the host-only edge router regardless of rule length
        self.assertIn("traefik.http.routers.edge-chat.priority=", compose)

        hosts = json.loads((ROOT / "config" / "host.json").read_text())
        chat_host = next(h for h in hosts if h["remark"].startswith("edge-chat"))
        self.assertEqual(chat_host["inbound_tag"], "VLESS_WS_CHAT")
        self.assertEqual(chat_host["path"], path)
        self.assertEqual(chat_host["security"], "tls")
        self.assertIn("http/1.1", chat_host.get("alpn", []))

    def test_xhttp_flavour_agrees_across_config_files(self):
        """VLESS_XHTTP inbound, edge-xhttp router, and host must agree on
        tag/port/path so the subscription link hits the routed endpoint."""
        config = json.loads((ROOT / "config" / "xray.json").read_text())
        inbound = next(
            (i for i in config["inbounds"] if i["tag"] == "VLESS_XHTTP"), None
        )
        self.assertIsNotNone(inbound, "VLESS_XHTTP inbound missing")
        stream = inbound["streamSettings"]
        self.assertEqual(inbound["protocol"], "vless")
        self.assertEqual(stream["network"], "xhttp")
        self.assertEqual(stream["security"], "none")
        path = stream["xhttpSettings"]["path"]
        self.assertEqual(path, "/chat/api/v6/xhttp")

        compose = (ROOT / "compose.yaml").read_text()
        self.assertIn(
            "traefik.http.routers.edge-xhttp.rule=Host(`${EDGE_DOMAIN}`) && "
            f"PathPrefix(`{path}`)",
            compose,
        )
        self.assertIn("traefik.http.routers.edge-xhttp.tls=true", compose)
        self.assertIn(
            "traefik.http.services.edge-xhttp-svc.loadbalancer.server.port="
            f"{inbound['port']}",
            compose,
        )

        hosts = json.loads((ROOT / "config" / "host.json").read_text())
        host = next(h for h in hosts if h["remark"].startswith("edge-xhttp"))
        self.assertEqual(host["inbound_tag"], "VLESS_XHTTP")
        self.assertEqual(host["path"], path)
        self.assertEqual(host["security"], "tls")
        self.assertIn("edge.example.com", host["address"])
        # stream-one mirrors the reference client config; xmux keys use the
        # panel's serialized aliases so seed upserts stay idempotent
        xhttp = host["transport_settings"]["xhttp_settings"]
        self.assertEqual(xhttp["mode"], "stream-one")
        self.assertEqual(xhttp["xmux"]["maxConcurrency"], "16-32")
        self.assertEqual(xhttp["xmux"]["hKeepAlivePeriod"], 45)

    def test_tcp_tls_flavour_agrees_across_config_files(self):
        """VLESS_TCP_TLS inbound, edge-tcp SNI router, host, and grey DNS
        record must agree on files.mamahoos.ir and port 443."""
        config = json.loads((ROOT / "config" / "xray.json").read_text())
        inbound = next(
            (i for i in config["inbounds"] if i["tag"] == "VLESS_TCP_TLS"), None
        )
        self.assertIsNotNone(inbound, "VLESS_TCP_TLS inbound missing")
        stream = inbound["streamSettings"]
        self.assertEqual(stream["network"], "tcp")
        self.assertEqual(stream["security"], "tls")
        # cert lives in the node container only: panel must not read the file
        cert = stream["tlsSettings"]["certificates"][0]
        self.assertEqual(cert["certificateFile"], "/var/lib/pg-node/certs/ssl_cert.pem")
        self.assertTrue(cert["serveOnNode"])

        compose = (ROOT / "compose.yaml").read_text()
        self.assertIn("traefik.tcp.routers.edge-tcp.rule=HostSNI(`files.mamahoos.ir`)", compose)
        self.assertIn("traefik.tcp.routers.edge-tcp.entrypoints=websecure", compose)
        self.assertIn("traefik.tcp.routers.edge-tcp.tls.passthrough=true", compose)
        self.assertIn(
            "traefik.tcp.services.edge-tcp-svc.loadbalancer.server.port="
            f"{inbound['port']}",
            compose,
        )

        hosts = json.loads((ROOT / "config" / "host.json").read_text())
        host = next(h for h in hosts if h["remark"].startswith("edge-tcp"))
        self.assertEqual(host["inbound_tag"], "VLESS_TCP_TLS")
        self.assertEqual(host["address"], ["files.mamahoos.ir"])
        self.assertEqual(host["sni"], ["files.mamahoos.ir"])
        self.assertEqual(host["port"], 443)
        self.assertEqual(host["security"], "tls")
        # self-signed node certificate: verification must be skipped client-side
        self.assertTrue(host["allowinsecure"])
        self.assertNotIn("host", host)

        cfg = (ROOT / ".github" / "dns" / "dnsconfig.js").read_text()
        self.assertIn('A("files", "__ORIGIN_IP__", TTL(1), CF_PROXY_OFF)', cfg)

    def test_domain_fronted_flavour_reuses_the_chat_inbound(self):
        """The fronting flavour is a second host on VLESS_WS_CHAT: connect to
        a clean address while SNI/Host stay on the edge domain."""
        hosts = json.loads((ROOT / "config" / "host.json").read_text())
        chat_hosts = [h for h in hosts if h["inbound_tag"] == "VLESS_WS_CHAT"]
        self.assertEqual(len(chat_hosts), 2)
        front = next(h for h in chat_hosts if h["remark"].startswith("edge-front"))
        direct = next(h for h in chat_hosts if h["remark"].startswith("edge-chat"))
        self.assertEqual(front["address"], ["chatgpt.com"])
        self.assertEqual(front["sni"], ["edge.example.com"])
        self.assertEqual(front["host"], ["edge.example.com"])
        self.assertEqual(front["path"], direct["path"])
        self.assertEqual(front["security"], "tls")
        # host upsert key (inbound_tag, path, address) must separate them
        self.assertNotEqual(
            (front["inbound_tag"], front["path"], front["address"]),
            (direct["inbound_tag"], direct["path"], direct["address"]),
        )


if __name__ == "__main__":
    unittest.main()
