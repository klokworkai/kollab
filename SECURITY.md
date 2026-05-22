# Security Policy

## Scope

koll♠b is a local single-user demo tool. It is not designed for multi-user deployments, public internet exposure, or production use. The attack surface is intentionally minimal:

- No user accounts, no stored credentials, no database
- All config and session data lives in `~/.kollab/` on the local filesystem
- The server binds to `localhost` by default and is not intended to be exposed externally
- Agent API keys (Anthropic, OpenAI) are managed entirely by the Claude Code and Codex CLIs — koll♠b never reads or stores them

## API key (`api_key` in config)

If you set `api_key` in `~/.kollab/config.toml` and expose the koll♠b server over a network, treat that key as a bearer token secret. Do not commit `config.toml` to version control. The default is an empty string (no auth), which is safe for local use only.

## Reporting a vulnerability

If you find a security issue, please do not open a public GitHub issue.

Email: **kollab@klokwork.ai**

Include:
- A description of the issue and its potential impact
- Steps to reproduce
- Any relevant environment details (OS, Python version, deployment setup)

We'll respond within 5 business days. For a local demo tool, most findings will be low severity — but we take all reports seriously and will acknowledge and credit reporters where appropriate.

## Out of scope

- Vulnerabilities requiring physical access to the machine
- Issues in the Claude Code or Codex CLIs themselves (report those to Anthropic or OpenAI respectively)
- Social engineering or phishing
- Theoretical vulnerabilities with no practical exploit path on a localhost-bound service
