# Worker deployment

This directory is the zero-burn hosting target for the paid API.

## Before listing publicly

1. Create/connect a Cloudflare account on the Workers Free plan.
2. Set `PAY_TO` to a receiving EVM wallet address. Never commit a private key.
3. `npm install`
4. `npx wrangler deploy`
5. Verify `/health`, `/v1/preview`, and that an unpaid `/v1/bounties` request returns HTTP 402.
6. Submit the deployed origin on Agent402's seller page.

The paid route is currently priced at **$0.003 USDC-equivalent per request** to remain competitive with deterministic agent data tools. Change only after measuring actual routing and settlements.

The Worker uses Cloudflare's documented `x402-hono` integration pattern and the public `https://x402.org/facilitator`. Production payments target Base; do not list the origin until the receiving address is configured and the 402 challenge has been tested.
