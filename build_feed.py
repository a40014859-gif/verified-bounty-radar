import json
import os
import re
import urllib.parse
import urllib.request
from datetime import datetime, timezone, timedelta

API = "https://api.github.com"
TOKEN = os.environ.get("GITHUB_TOKEN", "")
HEADERS = {
    "Accept": "application/vnd.github+json",
    "User-Agent": "verified-bounty-radar",
}
if TOKEN:
    HEADERS["Authorization"] = f"Bearer {TOKEN}"


def request(path, params=None):
    url = API + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=20) as response:
        return json.load(response)


def parse_issue_url(url):
    m = re.search(r"github\.com/([^/]+)/([^/]+)/issues/(\d+)", url or "")
    if not m:
        return None
    return m.group(1), m.group(2), int(m.group(3))


def canonical_from_body(issue):
    body = issue.get("body") or ""
    for line in body.splitlines():
        if "source url" in line.lower() or "original" in line.lower() or "canonical" in line.lower():
            m = re.search(r"https://github\.com/[^\s)]+/issues/\d+", line)
            if m:
                return m.group(0)
    return issue.get("html_url")


def reward_from_text(title, body):
    clean_body = (body or "").split("<details", 1)[0][:1200]
    text = f"{title}\n{clean_body}"
    num = r"([0-9][0-9,]*(?:\.[0-9]+)?)"
    patterns = [
        rf"(?i)(?:prize|reward|bounty)\s*[:\-]?\s*\$\s*{num}",
        rf"(?i)(?:prize|reward|bounty)\s*[:\-]?\s*{num}\s*(USDC|USD)",
        rf"(?i)\$\s*{num}\s*(?:bounty|prize|reward)?",
        rf"(?i){num}\s*(USDC|USD)\b",
    ]
    for p in patterns:
        m = re.search(p, text)
        if not m:
            continue
        amount_text = m.group(1).replace(",", "")
        try:
            amount = float(amount_text)
        except ValueError:
            continue
        currency = "USD"
        if m.lastindex and m.lastindex >= 2 and m.group(2):
            currency = m.group(2).upper()
        elif "USDC" in m.group(0).upper():
            currency = "USDC"
        return {"amount": amount, "currency": currency, "evidence": m.group(0)[:120]}
    return None


def competition(owner, repo, number):
    q = f'repo:{owner}/{repo} is:pr is:open "#{number}"'
    try:
        data = request("/search/issues", {"q": q, "per_page": 1})
        return int(data.get("total_count", 0))
    except Exception:
        return None


def claim_state(owner, repo, number, issue_body):
    try:
        comments = request(f"/repos/{owner}/{repo}/issues/{number}/comments", {"per_page": 100})
    except Exception:
        return {"state": "unknown"}

    window_hours = None
    all_text = (issue_body or "") + "\n" + "\n".join((c.get("body") or "") for c in comments)
    m = re.search(r"(?i)(\d+)\s*[- ]?hour\s+exclusive", all_text)
    if m:
        window_hours = int(m.group(1))

    claims = []
    releases = []
    for c in comments:
        body = (c.get("body") or "").strip().lower()
        if re.search(r"(?m)^/claim\b", body):
            claims.append(c)
        if re.search(r"(?m)^/(?:unclaim|release)\b", body) or "claim withdrawn" in body:
            releases.append(c)

    if not claims:
        return {"state": "none"}

    last_claim = claims[-1]
    claim_time = datetime.fromisoformat(last_claim["created_at"].replace("Z", "+00:00"))
    release_time = None
    if releases:
        release_time = datetime.fromisoformat(releases[-1]["created_at"].replace("Z", "+00:00"))
    if release_time and release_time > claim_time:
        return {"state": "released", "claimed_at": last_claim["created_at"]}

    result = {
        "state": "present_unknown",
        "claimed_at": last_claim["created_at"],
        "claimant": (last_claim.get("user") or {}).get("login"),
    }
    if window_hours:
        expires = claim_time + timedelta(hours=window_hours)
        active = datetime.now(timezone.utc) < expires
        result.update({
            "state": "active" if active else "expired",
            "window_hours": window_hours,
            "expires_at": expires.isoformat().replace("+00:00", "Z"),
        })
    return result


def recommendation(state, reward, pr_count, claim, assignees):
    if state != "open":
        return "skip_closed"
    if assignees:
        return "skip_assigned"
    if claim.get("state") == "active":
        return "skip_claimed"
    if pr_count is not None and pr_count >= 5:
        return "avoid_crowded"
    if not reward:
        return "verify_reward"
    if pr_count is not None and pr_count >= 2:
        return "competitive"
    return "watch"


def verify(candidate):
    source_url = candidate.get("html_url")
    canonical_url = canonical_from_body(candidate)
    parsed = parse_issue_url(canonical_url)
    if not parsed:
        return None
    owner, repo, number = parsed
    try:
        canonical = request(f"/repos/{owner}/{repo}/issues/{number}")
    except Exception:
        return {
            "source_url": source_url,
            "canonical_url": canonical_url,
            "verification": "canonical_fetch_failed",
            "recommendation": "skip_unverifiable",
        }
    if "pull_request" in canonical:
        return None

    state = canonical.get("state")
    assignees = [a.get("login") for a in (canonical.get("assignees") or []) if a.get("login")]
    reward = reward_from_text(canonical.get("title") or "", canonical.get("body") or "")
    pr_count = competition(owner, repo, number) if state == "open" else 0
    claim = claim_state(owner, repo, number, canonical.get("body") or "") if state == "open" else {"state": "none"}

    score = None
    if reward and pr_count is not None:
        score = round(reward["amount"] / (1 + pr_count), 2)

    return {
        "repository": f"{owner}/{repo}",
        "issue_number": number,
        "title": canonical.get("title"),
        "source_url": source_url,
        "canonical_url": canonical.get("html_url"),
        "state": state,
        "closed_at": canonical.get("closed_at"),
        "reward": reward,
        "open_pr_competition": pr_count,
        "assignees": assignees,
        "claim": claim,
        "value_per_competitor": score,
        "recommendation": recommendation(state, reward, pr_count, claim, assignees),
        "verified_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }


def discover():
    queries = [
        "bounty in:title is:issue",
        "label:bounty is:issue",
    ]
    merged = []
    seen = set()
    for q in queries:
        data = request("/search/issues", {
            "q": q,
            "sort": "updated",
            "order": "desc",
            "per_page": 30,
        })
        for item in data.get("items", []):
            key = item.get("html_url")
            if key and key not in seen:
                seen.add(key)
                merged.append(item)
    merged.sort(key=lambda x: x.get("updated_at") or "", reverse=True)
    return merged


def main():
    records = []
    seen = set()
    for candidate in discover():
        record = verify(candidate)
        if not record:
            continue
        key = record.get("canonical_url") or record.get("source_url")
        if key in seen:
            continue
        seen.add(key)
        records.append(record)
        if len(records) >= 25:
            break

    priority = {
        "watch": 0,
        "competitive": 1,
        "verify_reward": 2,
        "avoid_crowded": 3,
        "skip_claimed": 4,
        "skip_assigned": 5,
        "skip_closed": 6,
        "skip_unverifiable": 7,
    }
    records.sort(key=lambda x: (priority.get(x.get("recommendation"), 9), -(x.get("value_per_competitor") or 0)))
    output = {
        "product": "Verified Bounty Radar",
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "record_count": len(records),
        "method": "Bounty-title/label discovery, canonical GitHub verification, open-PR competition search, and claim-window detection.",
        "records": records,
    }
    with open("feed.json", "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
        f.write("\n")


if __name__ == "__main__":
    main()
