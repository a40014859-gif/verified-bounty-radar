#!/usr/bin/env python3
"""Verify canonical GitHub bounty signals without third-party aggregators."""

import json
import os
import re
import sys
import urllib.parse
import urllib.request

URL_RE = re.compile(r"^https://github\.com/([^/]+)/([^/]+)/issues/(\d+)(?:$|[?#])")
NUMBER = r"\d[\d,]*(?:\.\d+)?"
REWARD_RE = re.compile(rf"(?i)(?:\$\s?{NUMBER}(?:\s?(?:USD|USDC))?|{NUMBER}\s?(?:USDC|USD|EUR|BTC|ETH|SOL|RTC|LT))")
CLAIM_RE = re.compile(r"(?im)^\s*/(?:claim|try|attempt)\b.*$")


def api_get(path):
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "verified-bounty-radar/0.3",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    token = os.getenv("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request("https://api.github.com" + path, headers=headers)
    with urllib.request.urlopen(req, timeout=20) as response:
        return json.load(response)


def all_comments(owner, repo, number):
    out = []
    for page in range(1, 11):
        batch = api_get(f"/repos/{owner}/{repo}/issues/{number}/comments?per_page=100&page={page}")
        out.extend(batch)
        if len(batch) < 100:
            break
    return out


def matching_prs(owner, repo, number):
    query = f'repo:{owner}/{repo} is:pr is:open "#{number}"'
    data = api_get("/search/issues?q=" + urllib.parse.quote(query) + "&per_page=100")
    return [
        {
            "number": item["number"],
            "title": item["title"],
            "url": item["html_url"],
            "created_at": item["created_at"],
        }
        for item in data.get("items", [])
    ]


def main(url):
    match = URL_RE.match(url)
    if not match:
        raise SystemExit("Expected https://github.com/OWNER/REPO/issues/NUMBER")
    owner, repo, raw_number = match.groups()
    number = int(raw_number)
    issue = api_get(f"/repos/{owner}/{repo}/issues/{number}")
    comments = all_comments(owner, repo, number)
    text = "\n".join(
        [issue.get("title", ""), issue.get("body") or ""]
        + [comment.get("body") or "" for comment in comments]
    )
    reward_mentions = sorted(set(REWARD_RE.findall(text)))
    claims = []
    for comment in comments:
        body = comment.get("body") or ""
        if CLAIM_RE.search(body):
            claims.append(
                {
                    "actor": (comment.get("user") or {}).get("login"),
                    "created_at": comment.get("created_at"),
                    "matches": CLAIM_RE.findall(body),
                    "url": comment.get("html_url"),
                }
            )
    prs = matching_prs(owner, repo, number)
    result = {
        "canonical": {
            "url": issue.get("html_url"),
            "state": issue.get("state"),
            "state_reason": issue.get("state_reason"),
            "closed_at": issue.get("closed_at"),
            "updated_at": issue.get("updated_at"),
            "title": issue.get("title"),
            "labels": [label.get("name") for label in issue.get("labels", [])],
            "assignees": [user.get("login") for user in issue.get("assignees", [])],
        },
        "reward_mentions": reward_mentions,
        "claim_signals": claims,
        "matching_open_pr_count": len(prs),
        "matching_open_prs": prs,
        "notes": [
            "Reward text is issuer/community text, not proof of payment.",
            "PR matching is a lower-bound heuristic based on explicit issue-number references.",
        ],
    }
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: verify.py https://github.com/OWNER/REPO/issues/NUMBER")
    main(sys.argv[1])
