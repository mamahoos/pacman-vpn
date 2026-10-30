#!/usr/bin/env python3
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

os.environ.setdefault("EDGE_DOMAIN", "edge.example.com")
os.environ.setdefault("EDGE_PORT", "10086")
os.environ.setdefault("XUI_BASE_PATH", "/console-test/")

import seed_pasarguard as seed  # noqa: E402


class SeedPayloadTests(unittest.TestCase):
    def test_fill_xray_keeps_plaintext_ws(self):
        template = json.loads((ROOT / "config" / "xray.json").read_text())
        filled = seed.fill_xray(template, "edge.example.com", 10086, "/chat/sync")
        inbound = filled["inbounds"][0]
        self.assertEqual(inbound["streamSettings"]["security"], "none")
        self.assertEqual(inbound["streamSettings"]["wsSettings"]["host"], "edge.example.com")
        self.assertEqual(inbound["port"], 10086)

    def test_fill_host_uses_public_tls_edge(self):
        template = json.loads((ROOT / "config" / "host.json").read_text())[0]
        filled = seed.fill_host(template, "edge.example.com", "/chat/sync")
        self.assertEqual(filled["address"], ["edge.example.com"])
        self.assertEqual(filled["sni"], ["edge.example.com"])
        self.assertEqual(filled["port"], 443)
        self.assertEqual(filled["security"], "tls")
        self.assertEqual(filled["fingerprint"], "chrome")

    def test_fill_hosts_keeps_secondary_paths(self):
        templates = json.loads((ROOT / "config" / "host.json").read_text())
        filled = seed.fill_hosts(templates, "edge.filled.example", "/chat/sync", "VLESS_WS")
        self.assertEqual(len(filled), len(templates))
        by_remark = {item["remark"]: item for item in filled}
        # primary inbound follows INBOUND_WS_PATH, secondary keeps its own path
        self.assertEqual(by_remark["edge ({USERNAME})"]["path"], "/chat/sync")
        self.assertEqual(
            by_remark["edge-chat ({USERNAME})"]["path"], "/chat/api/v4/websocket"
        )
        # placeholder entries resolve to the live edge domain
        for remark in (
            "edge ({USERNAME})",
            "edge-chat ({USERNAME})",
            "edge-xhttp ({USERNAME})",
        ):
            self.assertEqual(by_remark[remark]["address"], ["edge.filled.example"])
            self.assertEqual(by_remark[remark]["sni"], ["edge.filled.example"])
            self.assertEqual(by_remark[remark]["port"], 443)
            self.assertEqual(by_remark[remark]["security"], "tls")
            self.assertEqual(by_remark[remark]["fingerprint"], "chrome")
        # explicit addresses survive: domain fronting and the TCP passthrough
        front = by_remark["edge-front ({USERNAME})"]
        self.assertEqual(front["address"], ["chatgpt.com"])
        self.assertEqual(front["sni"], ["edge.filled.example"])
        self.assertEqual(front["path"], "/chat/api/v4/websocket")
        tcp = by_remark["edge-tcp ({USERNAME})"]
        self.assertEqual(tcp["address"], ["files.mamahoos.ir"])
        self.assertEqual(tcp["sni"], ["files.mamahoos.ir"])
        # node cert pin travels through fill_hosts untouched (no placeholder)
        self.assertEqual(
            tcp["pinned_peer_cert_sha256"],
            "439877c03fd3308211420dfe2fca1570345f6a2d6eb32f901018f61da72901ad",
        )
        self.assertNotIn("allowinsecure", tcp)
        # raw TCP has no Host header
        self.assertNotIn("host", tcp)
        # packet-up over h2 is required to traverse the CDN HTTP chain
        xhttp = by_remark["edge-xhttp ({USERNAME})"]
        self.assertEqual(xhttp["alpn"], ["h2"])
        self.assertEqual(xhttp["transport_settings"]["xhttp_settings"]["mode"], "packet-up")
        self.assertEqual(by_remark["edge-chat ({USERNAME})"]["alpn"], ["http/1.1"])
        # templates must not be mutated in place
        self.assertEqual(templates[0]["path"], "/chat/sync")
        self.assertEqual(templates[1]["path"], "/chat/api/v4/websocket")

    def test_host_key_separates_flavours_sharing_an_inbound(self):
        direct = {
            "inbound_tag": "VLESS_WS_CHAT",
            "path": "/chat/api/v4/websocket",
            "address": ["edge.mamahoos.ir"],
        }
        fronted = {**direct, "address": ["chatgpt.com"]}
        self.assertNotEqual(seed.host_key(direct), seed.host_key(fronted))
        # same row still matches when the API returns a different list order
        self.assertEqual(
            seed.host_key(direct), seed.host_key({**direct, "address": ["edge.mamahoos.ir"]})
        )
        # str address (defensive) and missing path normalize too
        self.assertEqual(
            seed.host_key({**direct, "address": "edge.mamahoos.ir", "path": None}),
            ("VLESS_WS_CHAT", "", "edge.mamahoos.ir"),
        )
        tcp = {"inbound_tag": "VLESS_TCP_TLS", "address": ["files.mamahoos.ir"]}
        self.assertEqual(seed.host_key(tcp), ("VLESS_TCP_TLS", "", "files.mamahoos.ir"))

    def test_load_hosts_accepts_single_object_and_list(self):
        with tempfile.TemporaryDirectory() as tmp:
            single = Path(tmp) / "single.json"
            single.write_text(json.dumps({"remark": "one", "inbound_tag": "A"}))
            self.assertEqual(seed.load_hosts(single)[0]["inbound_tag"], "A")

            many = Path(tmp) / "many.json"
            many.write_text(
                json.dumps(
                    [
                        {"remark": "one", "inbound_tag": "A"},
                        {"remark": "two", "inbound_tag": "B"},
                    ]
                )
            )
            self.assertEqual([h["inbound_tag"] for h in seed.load_hosts(many)], ["A", "B"])

            empty = Path(tmp) / "empty.json"
            empty.write_text("[]")
            with self.assertRaises(SystemExit):
                seed.load_hosts(empty)

    def test_merge_inbound_tags_preserves_foreign_tags(self):
        self.assertEqual(
            seed.merge_inbound_tags(["VLESS_WS", "VLESS_WS_CHAT"], ["Shadowsocks TCP"]),
            ["Shadowsocks TCP", "VLESS_WS", "VLESS_WS_CHAT"],
        )
        self.assertEqual(
            seed.merge_inbound_tags(["VLESS_WS"], None), ["VLESS_WS"]
        )
        # idempotent: no duplicates when already present
        self.assertEqual(
            seed.merge_inbound_tags(["VLESS_WS"], ["VLESS_WS"]),
            ["VLESS_WS"],
        )

    def test_core_needs_update_only_on_config_drift(self):
        desired = {"inbounds": [{"tag": "VLESS_WS"}], "outbounds": [{"tag": "DIRECT"}]}
        self.assertFalse(seed.core_needs_update({"id": 1, "config": desired}, desired))
        self.assertTrue(seed.core_needs_update({"id": 1, "config": {}}, desired))
        self.assertTrue(seed.core_needs_update({"id": 1}, desired))

    def test_core_payload_matches_create_schema(self):
        desired = {"inbounds": [], "outbounds": []}
        payload = seed.core_payload(desired)
        self.assertEqual(payload["name"], "xray-edge")
        self.assertEqual(payload["type"], "xray")
        self.assertEqual(payload["config"], desired)
        self.assertEqual(payload["exclude_inbound_tags"], [])
        self.assertEqual(payload["fallbacks_inbound_tags"], [])

    def test_normalize_username_keeps_login_safe(self):
        self.assertEqual(seed.normalize_username("Nora"), "nora")
        self.assertEqual(seed.normalize_username("Baba"), "baba")
        self.assertEqual(seed.normalize_username("mamahoos"), "mamahoos")


if __name__ == "__main__":
    unittest.main()
