import { Hono } from "hono";
import { paymentMiddleware } from "x402-hono";

const app = new Hono();
const FEED_URL = "https://raw.githubusercontent.com/a40014859-gif/verified-bounty-radar/main/live_feed.json";
const PRICE = "$0.003";

async function loadFeed() {
  const response = await fetch(FEED_URL, {
    headers: { "user-agent": "verified-bounty-radar-worker/0.1" },
    cf: { cacheTtl: 120, cacheEverything: true },
  });
  if (!response.ok) throw new Error(`feed upstream ${response.status}`);
  return response.json();
}

function filterFeed(feed, query) {
  let entries = Array.isArray(feed.entries) ? feed.entries : [];
  const decision = query.get("decision") || "pursue";
  const minReward = Number(query.get("min_reward") || "0");
  const maxOpenPrs = Number(query.get("max_open_prs") || "999");
  const language = (query.get("language") || "").toLowerCase();

  entries = entries.filter((entry) => {
    if (decision !== "any" && entry.decision !== decision) return false;
    if ((entry.matching_open_pr_count || 0) > maxOpenPrs) return false;
    if (language) {
      const haystack = `${entry.title || ""} ${(entry.labels || []).join(" ")}`.toLowerCase();
      if (!haystack.includes(language)) return false;
    }
    if (minReward > 0) {
      if (entry.reward_usd_max == null || Number(entry.reward_usd_max) < minReward) return false;
    }
    return true;
  });

  return {
    product: feed.product,
    version: feed.version,
    generated_at: feed.generated_at,
    query: Object.fromEntries(query.entries()),
    count: entries.length,
    entries,
    caveat: "Reward text is not proof of payment; verify settlement terms before committing substantial work. min_reward applies only to explicit $, USD or USDC amounts.",
  };
}

app.get("/health", (c) => c.json({ ok: true, product: "verified-bounty-radar", paid: Boolean(c.env.PAY_TO) }));

app.get("/.well-known/x402", (c) =>
  c.json({
    name: "Verified Bounty Radar",
    description: "Canonical GitHub bounty verification and competition filtering for autonomous agents.",
    homepage: "https://github.com/a40014859-gif/verified-bounty-radar",
    payment: { protocol: "x402", currency: "USDC", network: "base", price: PRICE },
    capabilities: {
      tools: [
        {
          name: "verified_bounties",
          method: "GET",
          path: "/v1/bounties",
          price: PRICE,
          description: "Return verified bounty candidates after canonical-state, claim-signal and open-PR filtering."
        }
      ]
    }
  })
);

app.get("/openapi.json", (c) =>
  c.json({
    openapi: "3.1.0",
    info: { title: "Verified Bounty Radar", version: "0.2.1" },
    paths: {
      "/health": { get: { summary: "Health check", responses: { "200": { description: "OK" } } } },
      "/v1/preview": { get: { summary: "Free preview", responses: { "200": { description: "Preview" } } } },
      "/v1/bounties": {
        get: {
          summary: "Paid verified bounty query",
          parameters: [
            { name: "decision", in: "query", schema: { type: "string", enum: ["pursue", "hold", "skip", "manual_review", "any"] } },
            { name: "language", in: "query", schema: { type: "string" } },
            { name: "min_reward", in: "query", description: "Minimum explicit USD/USDC reward; non-USD assets are excluded from this numeric filter.", schema: { type: "number" } },
            { name: "max_open_prs", in: "query", schema: { type: "integer" } }
          ],
          responses: { "200": { description: "Verified feed results" }, "402": { description: "Payment Required" } }
        }
      }
    }
  })
);

app.get("/v1/preview", async (c) => {
  try {
    const feed = await loadFeed();
    const entries = (feed.entries || []).slice(0, 3).map((x) => ({
      title: x.title,
      canonical_url: x.canonical_url,
      decision: x.decision,
      decision_reasons: x.decision_reasons,
      reward_mentions: x.reward_mentions,
      reward_usd_max: x.reward_usd_max,
      matching_open_pr_count: x.matching_open_pr_count,
    }));
    return c.json({ generated_at: feed.generated_at, count: entries.length, entries });
  } catch (error) {
    return c.json({ error: "feed_unavailable", detail: String(error) }, 503);
  }
});

app.use("/v1/bounties", async (c, next) => {
  if (!c.env.PAY_TO) {
    return c.json({ error: "payments_not_configured", message: "Set the PAY_TO Worker variable before public listing." }, 503);
  }
  const gate = paymentMiddleware(
    c.env.PAY_TO,
    {
      "/v1/bounties": {
        price: PRICE,
        network: "base",
        config: { description: "Verified live bounty intelligence: canonical state, claim signals and open-PR competition." },
      },
    },
    { url: "https://x402.org/facilitator" },
  );
  return gate(c, next);
});

app.get("/v1/bounties", async (c) => {
  try {
    const feed = await loadFeed();
    return c.json(filterFeed(feed, new URL(c.req.url).searchParams));
  } catch (error) {
    return c.json({ error: "feed_unavailable", detail: String(error) }, 503);
  }
});

app.notFound((c) => c.json({ error: "not_found" }, 404));

export default app;
