# MCP Server

Verified Bounty Radar includes a dependency-free MCP stdio server for coding agents.

## Run

```bash
python mcp_server.py
```

The server uses only the Python standard library and the repository's `verify.py`.

## Tools

### `verify_github_bounty`
Input:

```json
{"url":"https://github.com/OWNER/REPO/issues/123"}
```

Returns canonical issue state, assignees, reward mentions, claim-command signals, and open pull requests that explicitly reference the issue number.

### `list_radar_bounties`
Optional inputs:

```json
{"recommendation":"watch","min_reward":50,"limit":10}
```

Fetches and filters the public Radar feed.

## Client configuration

For MCP clients that accept a command/args stdio configuration, point the client at the local repository checkout:

```json
{
  "mcpServers": {
    "verified-bounty-radar": {
      "command": "python",
      "args": ["/ABSOLUTE/PATH/verified-bounty-radar/mcp_server.py"]
    }
  }
}
```

Set `GITHUB_TOKEN` in the server environment for higher GitHub API rate limits. A token is optional for light public-repository use.

## Scope

This is a pre-execution verification tool. It does not claim bounties, post comments, accept legal terms, or guarantee payout.
