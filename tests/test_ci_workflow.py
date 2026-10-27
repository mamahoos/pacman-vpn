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
        self.assertIn("default: panel", workflow)
        self.assertIn("docker compose pull panel", workflow)
        self.assertIn("docker compose up -d --no-deps panel", workflow)
        self.assertIn("docker compose pull", workflow)
        self.assertIn("docker compose up -d --remove-orphans", workflow)
        self.assertIn(". ./.env", workflow)
        self.assertIn("panel python3 /scripts/seed_pasarguard.py", workflow)
        self.assertIn("DEPLOY_SCOPE", workflow)
        self.assertIn(".deploy-backup", workflow)
        self.assertIn("scripts/check_cloudflare.py", workflow)
        self.assertIn("DEPLOY_SSH_KEY", workflow)
        self.assertIn("if [ -f scripts/check_cloudflare.py ]", workflow)
        self.assertIn("SMOKE_ATTEMPTS", workflow)
        self.assertIn("SMOKE_DELAY_SECONDS", workflow)
        self.assertIn("Temporarily allow SCP through UFW", workflow)
        self.assertIn("ufw insert 1 allow 52222/tcp", workflow)
        self.assertIn("Remove temporary UFW rule", workflow)
        self.assertIn("ufw delete allow 52222/tcp", workflow)
        self.assertNotIn("script_stop", workflow)
        self.assertNotIn("source .env", workflow)
        self.assertNotIn("config/clients.json", workflow)
        self.assertNotIn("wrangler", workflow)
        self.assertNotIn("cloudflare/pages", workflow)
        self.assertNotIn("npx vercel", workflow)

    def test_cd_gates_on_warp_egress_and_rolls_back(self):
        workflow = (WORKFLOWS / "cd.yml").read_text()
        self.assertIn("mkdir -p data/warp", workflow)
        self.assertIn("id: egress", workflow)
        self.assertIn("--socks5-hostname 127.0.0.1:1080", workflow)
        self.assertIn("cdn-cgi/trace", workflow)
        self.assertIn("gemini.google.com", workflow)
        self.assertIn("steps.egress.outcome == 'failure'", workflow)
        self.assertIn("inputs.scope == 'all'", workflow)
        self.assertIn("docker compose up -d --remove-orphans", workflow)
        self.assertIn("docker compose up -d --no-deps panel", workflow)


if __name__ == "__main__":
    unittest.main()
