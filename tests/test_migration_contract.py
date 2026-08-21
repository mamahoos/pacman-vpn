#!/usr/bin/env python3
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class PasarGuardMigrationContractTests(unittest.TestCase):
    def test_compose_pins_latest_stable_images(self):
        compose = (ROOT / "compose.yaml").read_text()
        self.assertIn("ghcr.io/pasarguard/panel:v5.2.1", compose)
        self.assertIn("ghcr.io/pasarguard/node:v0.5.3", compose)
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
        self.assertIn("loadbalancer.proxyprotocol.version=2", compose)
        self.assertIn("container_name: pg-node", compose)

    def test_xray_inbound_stays_plaintext_vless_ws(self):
        xray = json.loads((ROOT / "config" / "xray.json").read_text())
        inbound = xray["inbounds"][0]
        self.assertEqual(inbound["protocol"], "vless")
        self.assertEqual(inbound["port"], 10086)
        self.assertEqual(inbound["streamSettings"]["network"], "ws")
        self.assertEqual(inbound["streamSettings"]["security"], "none")
        self.assertEqual(inbound["streamSettings"]["wsSettings"]["path"], "/chat/sync")
        self.assertEqual(inbound["tag"], "VLESS_WS")
        self.assertTrue(xray["policy"]["levels"]["0"]["statsUserOnline"])
        self.assertTrue(inbound["streamSettings"]["wsSettings"]["acceptProxyProtocol"])
        self.assertNotIn("sockopt", inbound["streamSettings"])

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
