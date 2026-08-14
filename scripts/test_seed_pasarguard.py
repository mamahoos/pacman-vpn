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
        filled = seed.fill_xray(template, "edge.mamahoos.ir", 10086, "/chat/sync")
        inbound = filled["inbounds"][0]
        self.assertEqual(inbound["streamSettings"]["security"], "none")
        self.assertEqual(inbound["streamSettings"]["wsSettings"]["host"], "edge.mamahoos.ir")
        self.assertEqual(inbound["port"], 10086)

    def test_fill_host_uses_public_tls_edge(self):
        template = json.loads((ROOT / "config" / "host.json").read_text())
        filled = seed.fill_host(template, "edge.mamahoos.ir", "/chat/sync")
        self.assertEqual(filled["address"], ["edge.mamahoos.ir"])
        self.assertEqual(filled["sni"], ["edge.mamahoos.ir"])
        self.assertEqual(filled["port"], 443)
        self.assertEqual(filled["security"], "tls")
        self.assertEqual(filled["fingerprint"], "chrome")

    def test_normalize_username_keeps_login_safe(self):
        self.assertEqual(seed.normalize_username("Nora"), "nora")
        self.assertEqual(seed.normalize_username("Baba"), "baba")
        self.assertEqual(seed.normalize_username("mamahoos"), "mamahoos")


if __name__ == "__main__":
    unittest.main()
