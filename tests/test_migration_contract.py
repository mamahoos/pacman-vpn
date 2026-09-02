#!/usr/bin/env python3
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class PasarGuardMigrationContractTests(unittest.TestCase):
    def test_compose_pins_latest_stable_images(self):
        compose = (ROOT / "compose.yaml").read_text()
        self.assertIn("ghcr.io/pasarguard/panel:v5.3.0", compose)
        self.assertIn("ghcr.io/pasarguard/node:v0.5.4", compose)
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

    def test_xray_warp_outbound_targets_sidecar_socks(self):
        outbounds = json.loads((ROOT / "config" / "xray.json").read_text())["outbounds"]
        warp = next(item for item in outbounds if item["tag"] == "WARP")
        self.assertEqual(warp["protocol"], "socks")
        self.assertEqual(warp["targetStrategy"], "ForceIPv4")
        server = warp["settings"]["servers"][0]
        self.assertEqual(server["address"], "warp")
        self.assertEqual(server["port"], 1080)

    def test_xray_routes_ai_domains_through_warp_only(self):
        config = json.loads((ROOT / "config" / "xray.json").read_text())
        routing = config["routing"]
        self.assertEqual(routing["domainStrategy"], "ForceIPv6")
        warp_rules = [rule for rule in routing["rules"] if rule["outboundTag"] == "WARP"]
        self.assertEqual(len(warp_rules), 1)
        domains = warp_rules[0]["domain"]
        for expected in (
            "domain:google.com",
            "domain:googleapis.com",
            "domain:gstatic.com",
            "domain:gemini.google.com",
            "domain:generativelanguage.googleapis.com",
            "domain:accounts.google.com",
            "domain:googleusercontent.com",
            "domain:chatgpt.com",
            "domain:anthropic.com",
            "domain:githubcopilot.com",
        ):
            self.assertIn(expected, domains)
        self.assertNotIn("domain:github.com", domains)
        self.assertNotIn("geosite:google", json.dumps(config))

    def test_compose_keeps_warp_sidecar_private(self):
        compose = (ROOT / "compose.yaml").read_text()
        self.assertIn("caomingjun/warp:2026.6.880.0-2.12.0", compose)
        self.assertIn("container_name: warp", compose)
        self.assertIn("./data/warp:/var/lib/cloudflare-warp", compose)
        self.assertIn("net.ipv4.conf.all.src_valid_mark=1", compose)
        self.assertNotIn('"1080:1080"', compose)

    def test_host_link_uses_edge_tls_on_443(self):
        host = json.loads((ROOT / "config" / "host.json").read_text())
        self.assertIn("edge.example.com", host["address"])
        self.assertEqual(host["port"], 443)
        self.assertEqual(host["security"], "tls")
        self.assertEqual(host["fingerprint"], "chrome")
        self.assertEqual(host["path"], "/chat/sync")
        self.assertEqual(host["inbound_tag"], "VLESS_WS")


if __name__ == "__main__":
    unittest.main()
