#!/usr/bin/env python3
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"


class CiWorkflowContractTests(unittest.TestCase):
    def test_ci_runs_quality_gates_without_secret_scan(self):
        workflow = (WORKFLOWS / "ci.yml").read_text()
        self.assertIn("docker compose --env-file .env.example config", workflow)
        self.assertIn("python3 tests/test_migration_contract.py", workflow)
        self.assertIn("python3 scripts/test_seed_pasarguard.py", workflow)
        self.assertIn("python3 scripts/test_check_cloudflare.py", workflow)
        self.assertIn("actions/checkout@v7", workflow)
        self.assertNotIn("gitleaks", workflow)
        self.assertNotIn("wrangler", workflow)
        self.assertNotIn("cloudflare/pages", workflow)
        self.assertNotIn("npx vercel", workflow)

    def test_secret_scan_uses_gitleaks_action(self):
        workflow = (WORKFLOWS / "gitleaks.yml").read_text()
        self.assertIn("uses: actions/checkout@v7", workflow)
        self.assertIn("fetch-depth: 0", workflow)
        self.assertIn("uses: gitleaks/gitleaks-action@v3", workflow)
        self.assertIn("GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}", workflow)
        self.assertIn("pull-requests: read", workflow)
        self.assertNotIn("curl", workflow)

    def test_cloudflare_checks_dns_not_pages(self):
        workflow = (WORKFLOWS / "cloudflare.yml").read_text()
        self.assertIn("scripts/check_cloudflare.py", workflow)
        self.assertIn("CLOUDFLARE_API_TOKEN", workflow)
        self.assertIn("actions/checkout@v7", workflow)
        self.assertNotIn("wrangler", workflow)
        self.assertNotIn("cloudflare/pages", workflow)

    def test_cd_deploys_via_ssh_not_pages(self):
        workflow = (WORKFLOWS / "cd.yml").read_text()
        self.assertIn("workflow_dispatch", workflow)
        self.assertIn("cancel-in-progress: false", workflow)
        self.assertIn("appleboy/scp-action@v1", workflow)
        self.assertIn("appleboy/ssh-action@v1.2.5", workflow)
        self.assertIn("compose.yaml", workflow)
        self.assertIn("config/host.json", workflow)
        self.assertIn("config/xray.json", workflow)
        self.assertIn("docker compose pull", workflow)
        self.assertIn("docker compose up -d", workflow)
        self.assertIn(".deploy-backup", workflow)
        self.assertIn("scripts/check_cloudflare.py", workflow)
        self.assertIn("DEPLOY_SSH_KEY", workflow)
        self.assertIn("if [ -f scripts/check_cloudflare.py ]", workflow)
        self.assertIn("SMOKE_ATTEMPTS", workflow)
        self.assertIn("SMOKE_DELAY_SECONDS", workflow)
        self.assertNotIn("script_stop", workflow)
        self.assertNotIn(".env", workflow)
        self.assertNotIn("config/clients.json", workflow)
        self.assertNotIn("wrangler", workflow)
        self.assertNotIn("cloudflare/pages", workflow)
        self.assertNotIn("npx vercel", workflow)


if __name__ == "__main__":
    unittest.main()
