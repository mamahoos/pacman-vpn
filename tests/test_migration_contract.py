#!/usr/bin/env python3
import json
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
