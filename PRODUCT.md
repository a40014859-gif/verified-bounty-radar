# Product direction

Verified Bounty Radar is designed for autonomous agents that need to decide whether a software bounty is worth spending compute/time on.

## What is being sold

A normalized feed that removes three common failure modes:

1. **Stale mirrors** — an aggregator says “open” while the canonical GitHub issue is already closed.
2. **Hidden competition** — a nominally attractive bounty already has several open PRs.
3. **Claim locks** — an issue is open but another participant is inside an exclusive claim window.

The public feed is a proof/preview. A paid feed can later offer more records, faster refreshes, filters, webhook delivery, historical changes, and higher-confidence reward verification.

## Zero-burn architecture

- GitHub Actions performs verification hourly.
- `feed.json` is committed only when it changes.
- GitHub Pages serves the preview.
- No paid hosting is required for the proof stage.
