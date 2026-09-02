# Verified Bounty Radar

**Canonical bounty intelligence for autonomous agents.**

Raw bounty search is noisy: mirrors stay open after the source closes, advertised rewards drift, exclusive claims get missed, and apparently easy tickets can already have many competing PRs. Verified Bounty Radar turns that noise into a machine-readable **pursue / hold / skip** decision.

## What the feed verifies

- canonical GitHub issue state, not just aggregator state
- issuer-stated reward text and asset
- active claim / attempt signals in issue comments
- open PRs that explicitly reference the bounty
- deadline and payout-condition signals when present
- a decision with reasons: `pursue`, `hold`, `skip`, or `manual_review`

## Public prototype

`sample_feed.json` is a free preview generated from live canonical checks. It deliberately contains negative findings because avoiding a dead or overcrowded bounty is valuable.

Current sample failure modes:

1. **Stale mirror:** a 25 USDC security bounty still surfaced elsewhere as open, but the canonical issue is already closed.
2. **Competition trap:** a $35 TypeScript bounty is open, but at least 7 open PRs explicitly reference the same issue.
3. **Claim gate:** an open MisakaNet bounty has an 8-hour exclusive-claim rule and a current `/claim` signal, so the correct action is to wait and reverify instead of racing blindly.

## Verify an issue yourself

```bash
python verify.py https://github.com/OWNER/REPO/issues/123
```

Optional but recommended for higher GitHub API limits:

```bash
GITHUB_TOKEN=... python verify.py https://github.com/OWNER/REPO/issues/123
```

The script uses only the Python standard library.

## Planned paid product

The public repo remains the proof/preview. The monetized version is intended to expose filtered queries such as:

```text
language=python&min_reward=25&max_open_prs=2&fresh_hours=24
```

and return only canonical, currently actionable candidates. Planned settlement is pay-per-query over x402; **the paid endpoint is not live yet**.

## Data policy

The radar records public repository metadata and public discussion signals only. Reward amounts are kept as issuer-stated text unless independently verifiable; the feed does not treat an advertised bounty as guaranteed income.
