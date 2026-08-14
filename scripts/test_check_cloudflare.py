#!/usr/bin/env python3
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import check_cloudflare as cf  # noqa: E402


def record(name: str, type_: str, proxied: bool) -> dict:
    return {"name": name, "type": type_, "proxied": proxied}


class CloudflareCheckTests(unittest.TestCase):
    def test_evaluate_hosts_requires_proxied_edge_and_panel(self):
        records = [
            record("admin.example.com", "A", True),
            record("edge.example.com", "CNAME", True),
        ]
        errors = cf.evaluate_hosts(
            records,
            panel_host="admin.example.com",
            edge_host="edge.example.com",
        )
        self.assertEqual(errors, [])

    def test_evaluate_hosts_rejects_missing_and_dns_only(self):
        records = [record("edge.example.com", "A", False)]
        errors = cf.evaluate_hosts(
            records,
            panel_host="admin.example.com",
            edge_host="edge.example.com",
        )
        self.assertTrue(any("admin.example.com" in error for error in errors))
        self.assertTrue(any("DNS-only" in error for error in errors))

    def test_evaluate_ssl_accepts_full_or_strict(self):
        self.assertEqual(cf.evaluate_ssl("strict"), [])
        self.assertEqual(cf.evaluate_ssl("full"), [])
        self.assertTrue(cf.evaluate_ssl("flexible"))
        self.assertTrue(cf.evaluate_ssl("off"))

    def test_ssl_errors_skips_when_settings_unread(self):
        self.assertEqual(cf.ssl_errors(None), [])
        self.assertEqual(cf.ssl_errors("strict"), [])
        self.assertTrue(cf.ssl_errors("flexible"))
        self.assertEqual(cf.evaluate_ssl("strict"), [])
        self.assertEqual(cf.evaluate_ssl("full"), [])
        self.assertTrue(cf.evaluate_ssl("flexible"))
        self.assertTrue(cf.evaluate_ssl("off"))

    def test_evaluate_smoke_accepts_panel_200_and_edge_websocket(self):
        self.assertEqual(cf.evaluate_smoke(panel_status=200, edge_status=400), [])
        self.assertEqual(cf.evaluate_smoke(panel_status=200, edge_status=426), [])
        self.assertTrue(cf.evaluate_smoke(panel_status=502, edge_status=400))
        self.assertTrue(cf.evaluate_smoke(panel_status=200, edge_status=200))


if __name__ == "__main__":
    unittest.main()
