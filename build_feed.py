import json
import os
import re
import urllib.parse
import urllib.request
from datetime import datetime, timezone

API = "https://api.github.com"
TOKEN = os.environ.get("GITHUB_TOKEN", "")
HEADERS = {
    "Accept": "application/vnd.github+json",
    "User-Agent": "verified-bounty-radar",
}
if TOKEN:
    HEADERS["Authorization"] = f"Bearer {TOKEN}"


def api(path, params=None):
    url = API + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=25) as r:
        return json.load(r)


def issue_tuple(url):
    m = re.search(r"github\.com/([^/]+)/([^/]+)/issues/(\d+)", url or "")
    return (m.group(1), m.group(2), int(m.group(3))) if m else None


def github_issue_urls(text):
    return re.findall(r"https://github\.com/[^\s)\]>]+/issues/\d+", text or "")


def canonical_url(issue):
    body = issue.get("body") or ""
    source = issue.get("html_url")
    lines = body.splitlines()
    marker = re.compile(r"(?i)(source\s*url|original|canonical|upstream|原始链接)")
    for i, line in enumerate(lines):
        if marker.search(line):
            window = "\n".join(lines[i:i + 4])
            urls = github_issue_urls(window)
            for url in urls:
                if url != source:
                    return url
    # Aggregator fallback: only trust an early explicit GitHub issue link in obvious bounty mirrors.
    repo_url = issue.get("repository_url") or ""
    if re.search(r"(?i)(bounty|scout|plaza|board)", repo_url):
        for url in github_issue_urls("\n".join(lines[:40])):
            if url != source:
                return url
    return source


def reward_from_text(title, body):
    text = f"{title}\n{(body or '')[:1800]}"
    num = r"([0-9][0-9,]*(?:\.[0-9]+)?)"
    patterns = [
        rf"(?i)(?:prize|reward|bounty)\s*[:\-]?\s*\$\s*{num}",
        rf"(?i)(?:prize|reward|bounty)\s*[:\-]?\s*{num}\s*(USDC|USD)\b",
        rf"(?i)\$\s*{num}\s*(?:bounty|prize|reward)?",
        rf"(?i){num}\s*(USDC|USD)\b",
    ]
    for p in patterns:
        m = re.search(p, text)
        if not m:
            continue
        raw = m.group(1).replace(",", "")
        try:
            amount = float(raw)
        except ValueError:
            continue
        currency = "USDC" if "USDC" in m.group(0).upper() else "USD"
        return {"amount": amount, "currency": currency, "evidence": m.group(0)[:120]}
    return None


def open_pr_count(owner, repo, number):
    try:
        q = f'repo:{owner}/{repo} is:pr is:open "#{number}"'
        return int(api("/search/issues", {"q": q, "per_page": 1}).get("total_count", 0))
    except Exception:
        return None


def claim_state(owner, repo, number):
    try:
        comments = api(f"/repos/{owner}/{repo}/issues/{number}/comments", {"per_page": 100})
    except Exception:
        return {"state": "unknown"}
    latest_claim = None
    latest_release = None
    attempts = 0
    submissions = 0
    for c in comments:
        body = (c.get("body") or "").strip().lower()
        if re.search(r"(?m)^/claim\b", body):
            latest_claim = c
        if re.search(r"(?m)^/(?:unclaim|release)\b", body) or "claim withdrawn" in body:
            latest_release = c
        if re.search(r"(?m)^/attempt\b", body):
            attempts += 1
        if "submission completed" in body or re.search(r"github\.com/[^/]+/[^/]+/pull/\d+", body):
            submissions += 1
    if latest_claim:
        claim_t = latest_claim.get("created_at") or ""
        release_t = (latest_release or {}).get("created_at") or ""
        if not release_t or release_t < claim_t:
            return {
                "state": "present",
                "claimant": (latest_claim.get("user") or {}).get("login"),
                "claimed_at": claim_t,
                "attempt_count": attempts,
                "submission_signals": submissions,
            }
    return {"state": "none", "attempt_count": attempts, "submission_signals": submissions}


def recommendation(state, reward, prs, assignees, claim):
    if state != "open":
        return "skip_closed"
    if assignees:
        return "skip_assigned"
    if claim.get("state") == "present":
        return "skip_claimed"
    if claim.get("submission_signals", 0) > 0:
        return "avoid_active_submissions"
    if claim.get("attempt_count", 0) >= 3:
        return "avoid_crowded"
    if prs is not None and prs >= 5:
        return "avoid_crowded"
    if not reward or reward.get("amount", 0) <= 0:
        return "verify_reward"
    if prs is not None and prs >= 2:
        return "competitive"
    return "watch"


def verify(candidate):
    source_url = candidate.get("html_url")
    canon_url = canonical_url(candidate)
    parsed = issue_tuple(canon_url)
    if not parsed:
        return None
    owner, repo, number = parsed
    try:
        issue = api(f"/repos/{owner}/{repo}/issues/{number}")
    except Exception:
        return {
            "source_url": source_url,
            "canonical_url": canon_url,
            "recommendation": "skip_unverifiable",
        }
    if "pull_request" in issue:
        return None
    state = issue.get("state")
    assignees = [a.get("login") for a in issue.get("assignees") or [] if a.get("login")]
    reward = reward_from_text(issue.get("title") or "", issue.get("body") or "")
    prs = open_pr_count(owner, repo, number) if state == "open" else 0
    claim = claim_state(owner, repo, number) if state == "open" else {"state": "none"}
    rec = recommendation(state, reward, prs, assignees, claim)
    score = None
    if reward and prs is not None:
        score = round(reward["amount"] / (1 + prs), 2)
    return {
        "repository": f"{owner}/{repo}",
        "issue_number": number,
        "title": issue.get("title"),
        "source_url": source_url,
        "canonical_url": issue.get("html_url"),
        "state": state,
        "closed_at": issue.get("closed_at"),
        "reward": reward,
        "open_pr_competition": prs,
        "assignees": assignees,
        "claim": claim,
        "value_per_competitor": score,
        "recommendation": rec,
        "verified_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }


def discover():
    queries = [
        "bounty in:title is:issue is:open",
        "label:bounty is:issue is:open",
    ]
    merged, seen = [], set()
    for q in queries:
        for page in (1, 2):
            try:
                data = api("/search/issues", {
                    "q": q,
                    "sort": "updated",
                    "order": "desc",
                    "per_page": 100,
                    "page": page,
                })
            except Exception:
                continue
            items = data.get("items", [])
            for item in items:
                u = item.get("html_url")
                if u and u not in seen:
                    seen.add(u)
                    merged.append(item)
            if len(items) < 100:
                break
    merged.sort(key=lambda x: x.get("updated_at") or "", reverse=True)
    return merged


def main():
    records, canonical_seen = [], set()
    for candidate in discover():
        record = verify(candidate)
        if not record:
            continue
        key = record.get("canonical_url") or record.get("source_url")
        if key in canonical_seen:
            continue
        canonical_seen.add(key)
        records.append(record)
        if len(records) >= 100:
            break

    priority = {
        "watch": 0,
        "competitive": 1,
        "verify_reward": 2,
        "avoid_crowded": 3,
        "avoid_active_submissions": 4,
        "skip_claimed": 5,
        "skip_assigned": 6,
        "skip_closed": 7,
        "skip_unverifiable": 8,
    }
    records.sort(key=lambda x: (
        priority.get(x.get("recommendation"), 9),
        -(x.get("value_per_competitor") or 0),
    ))
    output = {
        "product": "Verified Bounty Radar",
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "record_count": min(len(records), 50),
        "method": "Deep bounty search; mirror-to-canonical tracing; canonical issue, reward, assignment, claim and PR verification.",
        "records": records[:50],
    }
    with open("feed.json", "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
        f.write("\n")


if __name__ == "__main__":
    main()
