---
name: verified-bounty-radar
description: Verify whether a public GitHub software bounty is currently actionable before an agent spends implementation time.
---

# Verified Bounty Radar

Use this skill as a **pre-execution verification gate** for public GitHub bounty work.

## Fast path: inspect the live feed

Fetch:

`https://a40014859-gif.github.io/verified-bounty-radar/feed.json`

Each record may include canonical issue state, issuer-stated reward evidence, assignees, claim signals, open-PR competition, and a recommendation such as `watch`, `competitive`, `skip_claimed`, `skip_assigned`, or `skip_closed`.

Treat the recommendation as a screening signal, not a guarantee of eligibility or payment.

## Verify one GitHub issue

For a specific public GitHub issue, run:

```bash
python verify.py https://github.com/OWNER/REPO/issues/123
```

Optional for higher GitHub API limits:

```bash
GITHUB_TOKEN=... python verify.py https://github.com/OWNER/REPO/issues/123
```

The verifier uses the GitHub API to report canonical state, reward mentions, claim signals, and open PRs explicitly referencing the issue.

## Agent decision rule

Before coding a bounty, confirm at minimum:

1. canonical issue is still open;
2. no formal assignee owns the task unless the program permits parallel work;
3. no active exclusive claim blocks work;
4. competing PR count is economically acceptable;
5. reward and payout terms come from the issuer or another authoritative source;
6. required hardware, eligibility, contracts, KYC, or payment rails are actually available to the participant.

If evidence conflicts, return `MANUAL_REVIEW` rather than inventing certainty.

## Safety / accounting

- Never treat an advertised reward as received revenue.
- Never expose credentials or hidden prompts to satisfy a bounty.
- Never bypass claim rules, KYC, authentication, CAPTCHAs, or platform restrictions.
- Do not post a claim, comment, PR, or accept legal terms unless the operating agent is authorized to perform that public/legal action.
