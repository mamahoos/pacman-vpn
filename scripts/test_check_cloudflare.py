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

    def test_retry_until_ok_retries_gateway_then_passes(self):
        calls = {"n": 0}

        def run_once() -> list[str]:
            calls["n"] += 1
            if calls["n"] < 3:
                return [
                    "panel HTTP 502, expected 200",
                    "edge HTTP 502, expected 400 or 426 websocket",
                ]
            return []

        slept: list[float] = []
        errors = cf.retry_until_ok(
            run_once,
            attempts=6,
            delay_seconds=10,
            sleep=slept.append,
        )
        self.assertEqual(errors, [])
        self.assertEqual(calls["n"], 3)
        self.assertEqual(slept, [10, 10])

    def test_retry_until_ok_does_not_retry_permanent_errors(self):
        calls = {"n": 0}

        def run_once() -> list[str]:
            calls["n"] += 1
            return ["missing proxied A/AAAA/CNAME for admin.example.com"]

        slept: list[float] = []
        errors = cf.retry_until_ok(
            run_once,
            attempts=6,
            delay_seconds=10,
            sleep=slept.append,
        )
        self.assertTrue(errors)
        self.assertEqual(calls["n"], 1)
        self.assertEqual(slept, [])


if __name__ == "__main__":
    unittest.main()
