---
name: flashclaw-cli-plugin-flashrev-aiflow
description: Agent-friendly CLI for FlashRev AIFlow (email outreach automation), routed via auth-gateway-svc
version: 0.1.0
commands:
  - name: auth login
    description: Save API Key (sk_... format) to local credentials file
    args: --token API_KEY
    examples:
      - auth login --token sk_aBcDeFgHiJkLmNoPqRsTuVwXyZ01234
      - auth login
  - name: auth logout
    description: Remove the saved API Key
  - name: auth whoami
    description: Validate API Key and show current account / company info
  - name: auth status
    description: Show local API Key + gateway configuration (no network call)
  - name: config show
    description: Show current configuration (base_url, env, prefixes)
  - name: config set
    description: Set a config value (base_url, timeout, discover_prefix, engage_prefix, mailsvc_prefix)
    args: KEY VALUE
    examples:
      - config set base_url https://open-ai-api-test.eape.mobi
      - config set discover_prefix /flashrev
      - config set timeout 60
  - name: config unset
    description: Remove a config value (revert to default)
    args: KEY
  - name: aiflow create
    description: Create a new AIFlow (Strategy -> AIFlow -> Settings -> Launch). Default wizard prompts for missing fields; --no-wizard turns every missing field into a USAGE_* error (CI-friendly). --dry-run validates inputs and probes read-only endpoints (mailbox list + token balance) without calling any write endpoint.
    args: --no-wizard --dry-run --csv PATH --sheet URL --website URL --pitch-file PATH --language LANG --country-column COL --email-rounds N --mailboxes MODE --auto-approve/--no-auto-approve --launch/--no-launch -y --force
    examples:
      - aiflow create
      - aiflow create --csv ./contacts.csv --website acme.com --pitch-file ./pitch.json --language en --country-column country --mailboxes all-active -y
      - aiflow create --no-wizard --csv ./contacts.csv --pitch-file ./pitch.json --country-column country --dry-run
      - aiflow create --no-wizard --sheet https://docs.google.com/spreadsheets/d/ABC/edit --pitch-file ./pitch.json --country-column country --launch -y
  - name: aiflow list
    description: List AIFlows
    args: --status S --page N --page-size N
    examples:
      - aiflow list
      - aiflow list --status running --page 1 --page-size 20
  - name: aiflow show
    description: Show a single AIFlow
    args: FLOW_ID
  - name: aiflow start
    description: Start / launch an AIFlow (runs a token pre-check, --force to skip)
    args: FLOW_ID --status TOKEN --required-tokens N --force
  - name: aiflow pause
    description: Pause an AIFlow
    args: FLOW_ID
  - name: aiflow resume
    description: Resume a paused AIFlow (runs a token pre-check, --force to skip)
    args: FLOW_ID --status TOKEN --required-tokens N --force
  - name: aiflow delete
    description: Delete an AIFlow
    args: FLOW_ID -y
  - name: aiflow rename
    description: Rename an AIFlow
    args: FLOW_ID NEW_NAME
  - name: aiflow pitch show
    description: Show the 6-section pitch saved for an AIFlow
    args: FLOW_ID
  - name: aiflow pitch init
    description: Write a local pitch.json scaffold (6 sections + optional url/language) ready to edit and pass to `aiflow create --pitch-file`. No network call.
    args: --out PATH --force
    examples:
      - aiflow pitch init --out ./pitch.json
      - aiflow pitch init --out ./pitch.json --force
  - name: aiflow test-connection
    description: Test whether a company website URL is reachable for pitch generation
    args: URL
  - name: aiflow template
    description: Show the default email-sequence time template
  - name: token balance
    description: Show token balance derived from data.limit.{tokenTotal, tokenCost} of /api/v2/oauth/me
  - name: token check
    description: Exit 2 (TOKEN_INSUFFICIENT) if remaining tokens are below --required (or <= 0 if --required omitted)
    args: --required N
  - name: mailboxes list
    description: List bound mailboxes from mailsvc
    args: --status S --warmup W
  - name: mailboxes bind-list
    description: Show mailboxes currently bound to the AIFlow account
  - name: mailboxes has-active
    description: Check whether the current account has any active mailbox
  - name: health
    description: Check connectivity to auth-gateway-svc (no API Key required)
---

# flashclaw-cli-plugin-flashrev-aiflow

Agent-friendly CLI for **FlashRev AIFlow** — email outreach automation — routed via **auth-gateway-svc**.

Request chain:
```
CLI --[X-API-Key: sk_xxx]-> auth-gateway-svc --[Bearer+X-Auth-Company]-> FlashRev upstream
```

Upstream services reached through the gateway:
- `discover-api` — user info, AIFlow CRUD, pitch, templates
- `engage-api`   — mailbox pool detail (paths begin with `/engage`)
- `mailsvc`      — bound mailbox listing (paths begin with `/mailsvc`)

The API key (`FLASHREV_SVC_API_KEY`) is shared across all FlashRev skills that route through the same gateway.

## Installation

```bash
npx clawhub install flashclaw-cli-plugin-flashrev-aiflow
flashclaw-cli-plugin-flashrev-aiflow auth login --token sk_aBcDeFgH...
flashclaw-cli-plugin-flashrev-aiflow --json auth whoami
```

## Quick start

```bash
flashclaw-cli-plugin-flashrev-aiflow --json aiflow list
flashclaw-cli-plugin-flashrev-aiflow --json aiflow show af_xxx
flashclaw-cli-plugin-flashrev-aiflow --json mailboxes list
```

## Environments

Switch via `FLASHREV_AIFLOW_ENV` (default `prod`):

```bash
FLASHREV_AIFLOW_ENV=test flashclaw-cli-plugin-flashrev-aiflow --json health
```

## Gateway prefix

The CLI injects a configurable prefix for discover-api requests so that
`auth-gateway-svc` can route them (discover-api paths have no natural prefix,
unlike `/engage/...` and `/mailsvc/...`). Default is `/flashrev`; change with:

```bash
flashclaw-cli-plugin-flashrev-aiflow config set discover_prefix /flashrev
```

The value must match the `proxy.routes` entry configured in
`auth-gateway-svc/config-*.yaml`.
