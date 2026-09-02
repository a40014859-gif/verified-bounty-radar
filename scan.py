#!/usr/bin/env python3
"""Build a conservative, canonicalized bounty feed from public GitHub data.

The scanner is intentionally biased toward false negatives over false positives:
if reward, canonical source, or competitive state is unclear, it asks for manual review.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import re
import urllib.parse
import urllib.request
from pathlib import Path

API = "https://api.github.com"
OUT = Path("live_feed.json")
MAX_CANDIDATES = int(os.getenv("RADAR_MAX_CANDIDATES", "15"))
LOOKBACK_DAYS = int(os.getenv("RADAR_LOOKBACK_DAYS", "3"))
PR_SKIP_THRESHOLD = int(os.getenv("RADAR_PR_SKIP_THRESHOLD", "3"))
CLAIM_HOURS = int(os.getenv("RADAR_CLAIM_HOURS", "8"))

ISSUE_URL_RE = re.compile(r"https://github\.com/([^/\s]+)/([^/\s]+)/issues/(\d+)", re.I)
REWARD_RE = re.compile(
    r"(?i)(?:\$\s?\d+(?:\.\d+)?(?:\s?(?:USD|USDC))?|\d+(?:\.\d+)?\s?(?:USDC|USD|EUR|BTC|ETH|SOL|RTC|LT))"
)
CLAIM_RE = re.compile(r"(?im)^\s*/(claim|try|attempt)\b.*$")
CLOSING_RE_TEMPLATE = r"(?i)(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?|claim(?:s|ed)?|issue)\s*:?[ \t]*#%d\b"


def now_utc() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def api_get(path: str):
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "verified-bounty-radar/0.2",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    token = os.getenv("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(API + path, headers=headers)
    with urllib.request.urlopen(req, timeout=25) as response:
        return json.load(response)


def issue_parts(url: str):
    match = ISSUE_URL_RE.search(url or "")
    return match.groups() if match else None


def issue_url(owner: str, repo: str, number: int | str) -> str:
    return f"https://github.com/{owner}/{repo}/issues/{number}"


def source_issue_from_body(body: str, current_url: str) -> str | None:
    """Only canonicalize when the text explicitly presents a GitHub issue as a source/original."""
    for line in (body or "").splitlines():
        low = line.lower()
        if not any(tag in low for tag in ("source url", "source:", "original link", "original issue", "原始链接")):
            continue
        match = ISSUE_URL_RE.search(line)
        if match:
            candidate = issue_url(match.group(1), match.group(2), match.group(3))
            if candidate.rstrip("/") != current_url.rstrip("/"):
                return candidate
    return None


def get_issue(url: str):
    parts = issue_parts(url)
    if not parts:
        raise ValueError(f"not a GitHub issue URL: {url}")
    owner, repo, number = parts
    return api_get(f"/repos/{owner}/{repo}/issues/{number}")


def comments_for(owner: str, repo: str, number: int):
    # Bounty threads are normally small. Cap at 200 comments to bound cost.
    out = []
    for page in (1, 2):
        batch = api_get(f"/repos/{owner}/{repo}/issues/{number}/comments?per_page=100&page={page}")
        out.extend(batch)
        if len(batch) < 100:
            break
    return out


def strip_boilerplate(text: str) -> str:
    text = re.sub(r"(?is)<details.*?</details>", " ", text or "")
    keep = []
    for line in text.splitlines():
        low = line.lower()
        if "/reward" in low or "/tip" in low or "what does it mean" in low:
            continue
        keep.append(line)
    return "\n".join(keep)


def reward_mentions(issue: dict) -> list[str]:
    # Prefer issuer-authored title/body. Do not infer reward from generic bot boilerplate/comments.
    text = strip_boilerplate((issue.get("title") or "") + "\n" + (issue.get("body") or ""))
    return list(dict.fromkeys(m.group(0).strip() for m in REWARD_RE.finditer(text)))[:8]


def claim_signals(comments: list[dict]):
    signals = []
    cutoff = now_utc() - dt.timedelta(hours=CLAIM_HOURS)
    for comment in comments:
        body = comment.get("body") or ""
        match = CLAIM_RE.search(body)
        if not match:
            continue
        created_raw = comment.get("created_at")
        try:
            created = dt.datetime.fromisoformat(created_raw.replace("Z", "+00:00"))
        except Exception:
            created = None
        signals.append(
            {
                "actor": (comment.get("user") or {}).get("login"),
                "command": match.group(0).strip(),
                "created_at": created_raw,
                "recent": bool(created and created >= cutoff),
                "url": comment.get("html_url"),
            }
        )
    return signals


def matching_open_prs(owner: str, repo: str, number: int):
    q = f'repo:{owner}/{repo} is:pr is:open "#{number}"'
    data = api_get("/search/issues?q=" + urllib.parse.quote(q) + "&per_page=100")
    closing_re = re.compile(CLOSING_RE_TEMPLATE % number)
    exact_url = issue_url(owner, repo, number).lower()
    matches = []
    for item in data.get("items", []):
        haystack = ((item.get("title") or "") + "\n" + (item.get("body") or "")).lower()
        if closing_re.search(haystack) or exact_url in haystack:
            matches.append(
                {
                    "number": item.get("number"),
                    "title": item.get("title"),
                    "url": item.get("html_url"),
                    "created_at": item.get("created_at"),
                }
            )
    return matches


def verify(candidate: dict) -> dict:
    discovered_url = candidate["html_url"]
    source_url = source_issue_from_body(candidate.get("body") or "", discovered_url)
    canonical_url = source_url or discovered_url
    canonical = get_issue(canonical_url) if source_url else candidate
    owner = canonical["repository_url"].split("/")[-2]
    repo = canonical["repository_url"].split("/")[-1]
    number = int(canonical["number"])

    rewards = reward_mentions(canonical)
    labels = [x.get("name") for x in canonical.get("labels", [])]
    comments = comments_for(owner, repo, number) if canonical.get("comments", 0) else []
    claims = claim_signals(comments)
    prs = matching_open_prs(owner, repo, number) if canonical.get("state") == "open" else []

    reasons = []
    if source_url:
        reasons.append("Discovery item points to a separate canonical GitHub source issue; source state controls the decision.")

    if canonical.get("state") != "open":
        decision = "skip"
        reasons.append("Canonical source issue is not open.")
    elif not rewards:
        decision = "manual_review"
        reasons.append("No trustworthy reward amount found in the issuer-authored title/body.")
    elif any(c["recent"] for c in claims):
        decision = "hold"
        reasons.append(f"A /claim, /try, or /attempt signal was posted within the last {CLAIM_HOURS} hours.")
    elif len(prs) >= PR_SKIP_THRESHOLD:
        decision = "skip"
        reasons.append(f"At least {len(prs)} open PRs explicitly reference the canonical issue.")
    else:
        decision = "pursue"
        reasons.append("Canonical issue is open, reward text is present, no recent claim signal was detected, and explicit PR competition is below threshold.")

    return {
        "id": f"github:{owner}/{repo}#{number}",
        "discovered_url": discovered_url,
        "canonical_url": canonical.get("html_url") or canonical_url,
        "canonicalized_from_mirror": bool(source_url),
        "title": canonical.get("title"),
        "canonical_state": canonical.get("state"),
        "closed_at": canonical.get("closed_at"),
        "updated_at": canonical.get("updated_at"),
        "labels": labels,
        "reward_mentions": rewards,
        "recent_claim_count": sum(1 for c in claims if c["recent"]),
        "claim_signals": claims[-10:],
        "matching_open_pr_count": len(prs),
        "matching_open_prs": prs[:20],
        "decision": decision,
        "decision_reasons": reasons,
        "verification_confidence": "high" if decision in ("skip", "hold") else "medium",
        "caveats": [
            "Reward text is not proof of escrow, payment, or asset convertibility.",
            "PR competition is a lower bound based on explicit issue references.",
            "Claim commands are signals; project-specific reservation semantics may differ."
        ],
    }


def discover():
    since = (now_utc() - dt.timedelta(days=LOOKBACK_DAYS)).date().isoformat()
    q = f"is:issue is:open label:bounty updated:>={since}"
    data = api_get(
        "/search/issues?q=" + urllib.parse.quote(q) + f"&sort=updated&order=desc&per_page={MAX_CANDIDATES}"
    )
    return data.get("items", [])[:MAX_CANDIDATES]


def main():
    entries = []
    errors = []
    seen = set()
    for candidate in discover():
        try:
            item = verify(candidate)
            # Mirrors can collapse to the same canonical issue.
            if item["id"] in seen:
                continue
            seen.add(item["id"])
            entries.append(item)
        except Exception as exc:
            errors.append({"url": candidate.get("html_url"), "error": str(exc)[:500]})

    rank = {"pursue": 0, "hold": 1, "manual_review": 2, "skip": 3}
    entries.sort(key=lambda x: (rank.get(x["decision"], 9), x.get("matching_open_pr_count", 0)))
    payload = {
        "product": "verified-bounty-radar",
        "version": "0.2.0",
        "generated_at": now_utc().isoformat().replace("+00:00", "Z"),
        "policy": {
            "lookback_days": LOOKBACK_DAYS,
            "max_candidates": MAX_CANDIDATES,
            "claim_hours": CLAIM_HOURS,
            "pr_skip_threshold": PR_SKIP_THRESHOLD,
        },
        "counts": {
            "pursue": sum(x["decision"] == "pursue" for x in entries),
            "hold": sum(x["decision"] == "hold" for x in entries),
            "manual_review": sum(x["decision"] == "manual_review" for x in entries),
            "skip": sum(x["decision"] == "skip" for x in entries),
            "errors": len(errors),
        },
        "entries": entries,
        "errors": errors,
    }
    OUT.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(payload["counts"], sort_keys=True))


if __name__ == "__main__":
    main()
