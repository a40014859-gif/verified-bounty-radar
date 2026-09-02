#!/usr/bin/env python3
"""Verify canonical GitHub bounty signals without third-party aggregators."""

import json
import os
import re
import sys
import urllib.parse
import urllib.request

URL_RE = re.compile(r"^https://github\.com/([^/]+)/([^/]+)/issues/(\d+)(?:$|[?#])")
REWARD_RE = re.compile(r"(?i)(?:\$\s?\d+(?:\.\d+)?|\d+(?:\.\d+)?\s?(?:USDC|USD|EUR|BTC|ETH|SOL|RTC|LT))")
CLAIM_RE = re.compile(r"(?im)^\s*/(?:claim|try|attempt)\b.*$")


def api_get(path):
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "verified-bounty-radar/0.1",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    token = os.getenv("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request("https://api.github.com" + path, headers=headers)
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.load(r)


def all_comments(owner, repo, number):
    out = []
    for page in range(1, 11):
        batch = api_get(f"/repos/{owner}/{repo}/issues/{number}/comments?per_page=100&page={page}")
        out.extend(batch)
        if len(batch) < 100:
            break
    return out


def matching_prs(owner, repo, number):
    # Search explicit issue-number references in open PRs. This is a lower-bound,
    # not a perfect semantic linker; callers should treat it as competition evidence.
    q = f'repo:{owner}/{repo} is:pr is:open "#{number}"'
    data = api_get("/search/issues?q=" + urllib.parse.quote(q) + "&per_page=100")
    return [
        {"number": i["number"], "title": i["title"], "url": i["html_url"], "created_at": i["created_at"]}
        for i in data.get("items", [])
    ]


def main(url):
    m = URL_RE.match(url)
    if not m:
        raise SystemExit("Expected https://github.com/OWNER/REPO/issues/NUMBER")
    owner, repo, raw_number = m.groups()
    number = int(raw_number)
    issue = api_get(f"/repos/{owner}/{repo}/issues/{number}")
    comments = all_comments(owner, repo, number)
    text = "\n".join([issue.get("title", ""), issue.get("body") or ""] + [c.get("body") or "" for c in comments])
    reward_mentions = sorted(set(REWARD_RE.findall(text)))
    claims = []
    for c in comments:
        body = c.get("body") or ""
        if CLAIM_RE.search(body):
            claims.append({
                "actor": (c.get("user") or {}).get("login"),
                "created_at": c.get("created_at"),
                "matches": CLAIM_RE.findall(body),
                "url": c.get("html_url"),
            })
    prs = matching_prs(owner, repo, number)
    result = {
        "canonical": {
            "url": issue.get("html_url"),
            "state": issue.get("state"),
            "state_reason": issue.get("state_reason"),
            "closed_at": issue.get("closed_at"),
            "updated_at": issue.get("updated_at"),
            "title": issue.get("title"),
            "labels": [x.get("name") for x in issue.get("labels", [])],
        },
        "reward_mentions": reward_mentions,
        "claim_signals": claims,
        "matching_open_pr_count": len(prs),
        "matching_open_prs": prs,
        "notes": [
            "Reward text is issuer/community text, not proof of payment.",
            "PR matching is a lower-bound heuristic based on explicit issue-number references."
        ],
    }
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: verify.py https://github.com/OWNER/REPO/issues/NUMBER")
    main(sys.argv[1])
