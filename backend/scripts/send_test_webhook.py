#!/usr/bin/env python
"""Send a correctly-signed GitHub webhook to your local server.

GitHub itself cannot reach `http://localhost`, so during development you have
to fake a delivery. This script does exactly what GitHub does:

  1. builds a `pull_request` payload,
  2. computes HMAC-SHA256 over the RAW body with your webhook secret,
  3. POSTs it with the X-Hub-Signature-256 / X-GitHub-Event headers.

Usage (server must be running):

    cd backend
    python scripts/send_test_webhook.py
    python scripts/send_test_webhook.py --action synchronize --sha deadbeef
    python scripts/send_test_webhook.py --repo acme/shop --pr 12 --url http://127.0.0.1:8000

It uses only the standard library, so it works before you install anything.
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def load_dotenv(path: Path) -> dict[str, str]:
    """Tiny .env reader (KEY=VALUE, # comments) so this script has no deps."""
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def build_payload(repo: str, pr: int, sha: str, action: str, title: str) -> dict:
    owner, _, name = repo.partition("/")
    return {
        "action": action,
        "number": pr,
        "pull_request": {
            "number": pr,
            "title": title,
            "html_url": f"https://github.com/{repo}/pull/{pr}",
            "state": "open",
            "draft": False,
            "user": {"login": "octocat"},
            "head": {"sha": sha, "ref": "feature/demo"},
            "base": {"ref": "main"},
        },
        "repository": {"full_name": repo, "name": name, "owner": {"login": owner}},
        "sender": {"login": "octocat"},
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Send a signed test webhook to ReviewPilot")
    parser.add_argument("--url", default="http://127.0.0.1:8000/webhook/github")
    parser.add_argument("--repo", default="acme/demo-shop")
    parser.add_argument("--pr", type=int, default=42)
    parser.add_argument("--sha", default="9f2c1ab7d3e4f5a6b7c8d9e0f1a2b3c4d5e6f7a8")
    parser.add_argument("--action", default="opened", help="opened|synchronize|reopened|closed")
    parser.add_argument("--title", default="Add coupon support to checkout")
    args = parser.parse_args()

    env = load_dotenv(REPO_ROOT / ".env")
    secret = os.environ.get("GITHUB_WEBHOOK_SECRET") or env.get("GITHUB_WEBHOOK_SECRET", "")
    if not secret:
        print("ERROR: GITHUB_WEBHOOK_SECRET is not set in the environment or .env", file=sys.stderr)
        return 2

    payload = build_payload(args.repo, args.pr, args.sha, args.action, args.title)
    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    signature = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()

    request = urllib.request.Request(
        args.url,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "X-GitHub-Event": "pull_request",
            "X-GitHub-Delivery": "local-test-delivery",
            "X-Hub-Signature-256": signature,
            "User-Agent": "ReviewPilot-Test-Webhook",
        },
    )

    print(f"POST {args.url}")
    print(f"  repo={args.repo} pr={args.pr} sha={args.sha[:8]} action={args.action}")
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            print(f"HTTP {response.status}")
            print(response.read().decode("utf-8", errors="replace"))
    except urllib.error.HTTPError as exc:
        print(f"HTTP {exc.code} {exc.reason}", file=sys.stderr)
        print(exc.read().decode("utf-8", errors="replace"), file=sys.stderr)
        return 1
    except urllib.error.URLError as exc:
        print(f"Could not reach the server: {exc.reason}", file=sys.stderr)
        print("Is `uvicorn app.main:app --reload` running on port 8000?", file=sys.stderr)
        return 1

    print("\nIf the response was 202 'queued', watch the worker terminal.")
    print("Without a real GITHUB_TOKEN the job will fail at the GitHub step - that is expected.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
