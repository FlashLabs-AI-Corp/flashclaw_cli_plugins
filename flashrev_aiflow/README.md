# flashclaw-cli-plugin-flashrev-aiflow

Agent-friendly CLI for **FlashRev AIFlow** — email outreach automation — routed via **auth-gateway-svc**.

```
CLI --[X-API-Key: sk_xxx]-> auth-gateway-svc --[Bearer + X-Auth-Company]-> FlashRev upstream
```

The CLI only sends an API Key; `companyId` / `userId` are extracted by the gateway and injected into the upstream request.

Every request goes to `auth-gateway-svc`. The gateway picks the right
upstream based on path prefix; the CLI never talks to upstream services
directly and does not need to know their URLs:

| Route prefix          | Path shape                | Kind of calls handled |
|-----------------------|---------------------------|-----------------------|
| `{discover_prefix}`   | `/api/v1/...`, `/api/v2/...` | User / company info, AIFlow CRUD, pitch, default time template |
| `/engage`             | `/engage/...`             | Mailbox pool detail, sequence |
| `/mailsvc`            | `/mailsvc/...`            | Bound mailbox listing |

`discover_prefix` is configurable (default `/flashrev`) because the
underlying paths start plainly with `/api/v*` and need a routing tag for
the gateway. The value must match the `proxy.routes` entry configured in
`auth-gateway-svc/config-*.yaml`. `/engage` and `/mailsvc` already carry
their routing tag in the path, so the corresponding CLI config keys
(`engage_prefix`, `mailsvc_prefix`) default to empty.

---

## Installation

### Option 1 — Install via ClawHub (end users)

**Prerequisites:** Python 3.10+, OpenClaw installed.

```bash
# 1. Install the skill
npx clawhub install flashclaw-cli-plugin-flashrev-aiflow

# 2. Save your API Key (obtain from FlashRev console -> Settings -> Private Apps)
flashclaw-cli-plugin-flashrev-aiflow auth login --token sk_aBcDeFgHiJkLmNoPqRsTuVwXyZ01234

# 3. Verify connectivity + identity
flashclaw-cli-plugin-flashrev-aiflow --json auth whoami
```

The key is stored at `~/.claude/skills/flashrev-aiflow-assistant/.env`
(permissions `600` on POSIX).

`FLASHREV_SVC_API_KEY` is shared across all FlashRev skills that route through the same auth-gateway-svc — set it once and re-use.

### Option 2 — Install from source (developers)

```bash
cd flashrev_aiflow
pip install -e .
```

---

## Configuration

```bash
# Save / update API Key
flashclaw-cli-plugin-flashrev-aiflow auth login --token sk_aBcDeFgH...

# Inspect local config (no network call)
flashclaw-cli-plugin-flashrev-aiflow --json auth status
flashclaw-cli-plugin-flashrev-aiflow --json config show

# Override gateway routing prefixes if they differ from defaults
flashclaw-cli-plugin-flashrev-aiflow config set discover_prefix /flashrev
flashclaw-cli-plugin-flashrev-aiflow config set engage_prefix ""
flashclaw-cli-plugin-flashrev-aiflow config set mailsvc_prefix ""
flashclaw-cli-plugin-flashrev-aiflow config set timeout 60
```

### Environments

Switch via `FLASHREV_AIFLOW_ENV` (default `prod`):

| `FLASHREV_AIFLOW_ENV` | Gateway                        |
|-----------------------|--------------------------------|
| `prod` (default)      | auth-gateway-svc production    |
| `test`                | auth-gateway-svc test          |

```bash
FLASHREV_AIFLOW_ENV=test flashclaw-cli-plugin-flashrev-aiflow --json health
```

### Environment variables

| Variable                          | Purpose                                                                 |
|-----------------------------------|-------------------------------------------------------------------------|
| `FLASHREV_SVC_API_KEY`            | Override the saved API Key (shared across all FlashRev skills)          |
| `FLASHREV_AIFLOW_ENV`             | Switch between `prod` / `test` preset base URLs                          |
| `FLASHREV_AIFLOW_BASE_URL`        | Override the gateway base URL directly                                  |
| `FLASHREV_AIFLOW_TIMEOUT`         | Override HTTP timeout in seconds                                        |
| `FLASHREV_AIFLOW_DISCOVER_PREFIX` | Override the discover-api route prefix                                  |
| `FLASHREV_AIFLOW_ENGAGE_PREFIX`   | Override the engage-api route prefix                                    |
| `FLASHREV_AIFLOW_MAILSVC_PREFIX`  | Override the mailsvc route prefix                                       |

Priority (high -> low): env var > `.env` > `config.json` > code default.

---

## Commands

All commands accept `--json` for agent-friendly output.

### auth

| Command                           | Description                                              |
|-----------------------------------|----------------------------------------------------------|
| `auth login [--token KEY]`        | Save API Key (prompts if `--token` omitted)              |
| `auth logout`                     | Remove saved API Key                                     |
| `auth whoami`                     | Validate key and show account info (`GET /api/v2/oauth/me`) |
| `auth status`                     | Show local config (no network call)                      |

### config

| Command                           | Description                                              |
|-----------------------------------|----------------------------------------------------------|
| `config show`                     | Show current config                                      |
| `config set KEY VALUE`            | Set a config value                                       |
| `config unset KEY`                | Revert a config value to default                         |

Supported keys: `base_url`, `timeout`, `discover_prefix`, `engage_prefix`, `mailsvc_prefix`.

### aiflow

| Command                                   | Upstream endpoint                                                         |
|-------------------------------------------|---------------------------------------------------------------------------|
| `aiflow list [--status] [--page] [--page-size]` | `GET /api/v1/ai/workflow/agent/list`                              |
| `aiflow show FLOW_ID`                      | `GET /api/v1/ai/workflow/agent/get/flow/{flowId}`                         |
| `aiflow start FLOW_ID [--status TOKEN] [--required-tokens N] [--force]` | `GET /api/v1/ai/workflow/agent/sequence/status/{flowId}/{status}` + token pre-check |
| `aiflow pause FLOW_ID [--status TOKEN]`    | same endpoint, status defaults to `pause`                                 |
| `aiflow resume FLOW_ID [--status TOKEN] [--required-tokens N] [--force]` | same endpoint + token pre-check                                |
| `aiflow delete FLOW_ID [-y]`               | `GET /api/v1/ai/workflow/agent/delete/{flowId}`                           |
| `aiflow rename FLOW_ID NEW_NAME`           | `POST /api/v1/ai/workflow/agent/update/name`                              |
| `aiflow pitch show FLOW_ID`                | `GET /api/v1/ai/workflow/agent/get/pitch?flowId=...`                      |
| `aiflow pitch init [--out PATH] [--force]` | Emit a local pitch.json scaffold (no network call; mirrors `examples/pitch.example.json`) |
| `aiflow test-connection URL`               | `POST /api/v1/ai/workflow/agent/test/connection` (20s timeout)            |
| `aiflow template`                          | `GET /api/v1/ai/workflow/agent/get/time/template`                         |
| `aiflow create`                            | Interactive wizard; see "Create wizard" below                             |

### 60-second dry-run with the shipped example files

```bash
# From the flashrev_aiflow/ directory:
flashclaw-cli-plugin-flashrev-aiflow aiflow create --no-wizard --dry-run \
  --csv ./examples/contacts.example.csv \
  --pitch-file ./examples/pitch.example.json \
  --country-column country
```

The example pitch JSON carries a top-level `url` field so `--website` is
not required. See [`examples/README.md`](./examples/README.md) for more.

### Author a pitch from scratch

```bash
flashclaw-cli-plugin-flashrev-aiflow aiflow pitch init --out ./my-pitch.json
# edit ./my-pitch.json, then:
flashclaw-cli-plugin-flashrev-aiflow aiflow create --no-wizard \
  --csv ./contacts.csv \
  --pitch-file ./my-pitch.json \
  --country-column country \
  --launch -y
```

### Create wizard

`flashclaw-cli-plugin-flashrev-aiflow aiflow create` runs an interactive
wizard that mirrors the 3-step Strategy -> AIFlow -> Settings flow of the
web UI, ending with an optional launch. Contacts can come from a local CSV
or a public Google Sheet URL; pitch content is supplied either via
`--pitch-file <path.json>` or via `$EDITOR` when the flag is omitted.

```
# Interactive wizard (prompts fill in whatever you didn't pass)
flashclaw-cli-plugin-flashrev-aiflow aiflow create

# Wizard with flag pre-fills (skips those prompts)
flashclaw-cli-plugin-flashrev-aiflow aiflow create \
    --csv ./contacts.csv \
    --website acme.com \
    --pitch-file ./pitch.json \
    --language en \
    --email-rounds 2 \
    --mailboxes all-active \
    --launch -y

# Headless / CI — no prompts. Every missing field raises USAGE_*.
flashclaw-cli-plugin-flashrev-aiflow --json aiflow create --no-wizard \
    --csv ./contacts.csv \
    --pitch-file ./pitch.json \
    --country-column country \
    --website acme.com \
    --language en \
    --mailboxes all-active \
    --launch -y

# Validate inputs without creating anything on the backend.
flashclaw-cli-plugin-flashrev-aiflow aiflow create --no-wizard --dry-run \
    --csv ./contacts.csv --pitch-file ./pitch.json --country-column country
```

**`--no-wizard` required-field matrix**

| Field | Required when |
|---|---|
| `--csv` or `--sheet` | Always (exactly one; both given -> `USAGE_CONTACT_SOURCE_CONFLICT`) |
| `--pitch-file` | Always (no interactive editor in `--no-wizard`) |
| `--website` | Always — unless the pitch file has a top-level `"url"` field |
| `--country-column` | When `--language=auto` (default). Pass `none` to explicitly skip |
| `--mailboxes` | Optional (default `all-active`); a comma list that matches nothing -> `USAGE_MAILBOX_NO_MATCH` |
| `--launch` / `--no-launch` | Optional (default: save as draft in `--no-wizard`) |

**`--dry-run` semantics**

| Step | Dry-run behaviour |
|---|---|
| CSV parse / Sheet download / pitch-file validation / country-column check | Runs fully (local) |
| `POST /contacts/upload`, `POST /create/list`, `POST /save/pitch`, `POST /save/email/config`, launch | Skipped — printed as `[dry-run] would ...` |
| `GET /mailboxes`, `GET /time/template`, `GET /api/v2/oauth/me` (token balance) | Executed (read-only) so the summary shows actual mailbox count + token remaining |

`--dry-run` creates nothing on the backend — safe to run as a CI pre-flight before a real `aiflow create`.

Pipeline (all through auth-gateway-svc with the `/flashrev` prefix):

1. `POST /api/v1/ai/workflow/contacts/upload`        -> `{listId, listName}`
2. `POST /api/v1/ai/workflow/create/list`            -> `{flowId}`
3. `POST /api/v1/ai/workflow/save/pitch`             save 6-section pitch
4. `GET  /api/v1/ai/workflow/agent/get/time/template` preview default sequence
5. `POST /api/v1/ai/workflow/agent/get/email/config`  load current config
6. `POST /api/v1/ai/workflow/agent/save/email/config` save with user edits
7. `GET  /api/v1/ai/workflow/agent/sequence/status/{flowId}/ACTIVE` launch

**Pitch JSON schema** (keys accepted by `--pitch-file`):

```json
{
  "officialDescription": "Value Proposition paragraph",
  "painPoints":   ["..."],
  "solutions":    ["..."],
  "proofPoints":  ["..."],
  "callToActions":["..."],
  "leadMagnets":  ["..."]
}
```

`workflowId`, `url`, `language`, `useConfigLanguage` are filled in by the
wizard — do not include them in the file.

**Exit codes** for create:

| Code | Meaning |
|---|---|
| `0` | Success (or dry-run summary emitted) |
| `2` | User-input error: missing / conflicting flags, CSV not parseable, country column not found, mailbox filter matched nothing, token balance insufficient |
| `3` | Auth error (401) — reconfigure with `auth login` |
| `4` | Network error to the gateway |
| `5` | Backend error (5xx) |

---

### Backend endpoint to add — `POST /api/v1/ai/workflow/contacts/upload`

The frontend's CSV upload uses Tencent Cloud + a WebSocket `upload_csv`
callback, which is not practical for a headless CLI. For the wizard above
to work end-to-end, the backend needs a direct-multipart endpoint:

```
POST /api/v1/ai/workflow/contacts/upload
Headers
  X-API-Key: sk_xxx                 (via auth-gateway-svc)
  Content-Type: multipart/form-data
Body (multipart fields)
  file       CSV file (required)
  dataType   'People' | 'Company'   (optional, default 'People')
Response
  {
    "code": 200,
    "data": {
      "listId":   12345,                           // Long, required
                                                    // points to UnlockPersonGroupPO.id,
                                                    // consumed verbatim by /create/list
      "listName": "<original-filename>.csv"        // String, required
    }
  }
```

`listId` is a **`Long` (JSON number)**, not a string — it's the internal
primary key of the `UnlockPersonGroupPO` record the backend creates, and
the existing `AiWorkFlowListCreateDTO.listId` field on
`POST /api/v1/ai/workflow/create/list` is declared as `Long`. The CLI
treats the value opaquely; it just hands it back to `/create/list` in the
next step.

Follow-up metadata (`totalContacts`, `validContacts`, `preview`) is
intentionally **not** in the V1 response: the backend implementation
performs the contact-row validation asynchronously (mirroring the existing
`createList` -> `CompletableFuture.runAsync(initFlowData)` pattern), so
those counts are not yet available when the HTTP call returns. They can
be surfaced in a later version once the async job exposes a status
endpoint.

---

### Still to implement

The following PRD-level items are **not** wired yet. Please confirm the
owning backend project (or sign off on a minimal implementation) before
adding them to the CLI:

| PRD feature                          | Status            |
|--------------------------------------|-------------------|
| Blacklist upload / listing (company-wide) | Frontend only has per-workflow `exclude/list`; confirm whether company-level blacklist exists elsewhere |
| `GET /organization/token-pricing` (email generate/send rates) | No endpoint found in `search-website` or `dubbo-api-svc`; current CLI Token enforcement only checks balance > 0 (M5) |
| AI Reply Agent setting                | No frontend field observed; skipped for V1 |
| Per-workflow blacklist upload via `/save/exclude/list` | Can be added once we agree on whether it belongs in `aiflow create` |

### token

Balance is derived from `data.limit.{tokenTotal, tokenCost}` in the response
of `GET /api/v2/oauth/me`; `tokenRemaining = tokenTotal - tokenCost`.

| Command                           | Description                                              |
|-----------------------------------|----------------------------------------------------------|
| `token balance`                   | Show `{tokenTotal, tokenCost, tokenRemaining, sufficient}` |
| `token check [--required N]`      | Exit 2 (`TOKEN_INSUFFICIENT`) when the balance is below `N`; if `--required` is omitted, exits 2 (`TOKEN_EXHAUSTED`) when `remaining <= 0` |

`aiflow start` / `aiflow resume` run this same check before calling the
backend. Use `--force` to skip the CLI-side check — the upstream gateway is
still free to refuse the request (`auth-gateway-svc` already enforces a
similar rule for the `/callsvc` prefix; extending it to `/flashrev` requires
a small change on the gateway side, see the project note at the bottom).

### mailboxes

| Command               | Upstream endpoint                                       |
|-----------------------|---------------------------------------------------------|
| `mailboxes list [--status] [--warmup]` | `GET /mailsvc/mail-address/simple/v2/list` |
| `mailboxes bind-list` | `GET /api/v1/ai/workflow/agent/get/bind/email`          |
| `mailboxes has-active`| `GET /api/v1/ai/workflow/agent/has/active/email`        |

### health

```bash
flashclaw-cli-plugin-flashrev-aiflow health
```

Does a plain `GET` on the gateway base URL; no API Key required.

---

## Architecture

```
flashrev_aiflow/
├── pyproject.toml
├── README.md
└── flashclaw_cli_plugin/
    └── flashrev_aiflow/
        ├── flashrev_aiflow_cli.py   # Click CLI entry point
        ├── core/
        │   ├── client.py            # HTTP client — discover / engage / mailsvc routing
        │   └── session.py           # API Key + config persistence
        ├── utils/
        │   └── output.py            # JSON / human-readable output
        ├── skills/
        │   └── SKILL.md             # AI-discoverable skill definition
        └── tests/
            ├── test_core.py         # Unit tests (session + client URL building + mocks)
            └── TEST.md              # Test plan
```

---

## Development

```bash
cd flashrev_aiflow
pip install -e .

# Run the test suite
pytest flashclaw_cli_plugin/flashrev_aiflow/tests/ -v

# Try a command against the test gateway
FLASHREV_AIFLOW_ENV=test flashclaw-cli-plugin-flashrev-aiflow --json health
FLASHREV_AIFLOW_ENV=test flashclaw-cli-plugin-flashrev-aiflow --json aiflow list
```

### Publish to ClawHub

```bash
npx clawhub login

npx clawhub publish ./flashrev_aiflow \
  --slug flashclaw-cli-plugin-flashrev-aiflow \
  --name "FlashRev AIFlow CLI" \
  --version 0.1.0 \
  --changelog "Initial release"
```

---

## Endpoints that still need confirmation

The following PRD-level features are **not** implemented in this release
because no matching endpoint was found in the `search-website` frontend.
Please confirm the owning backend project (or sign off on a minimal
backend implementation) before wiring these into the CLI:

| PRD feature                          | Status            |
|--------------------------------------|-------------------|
| Google Sheet import of contacts      | Endpoint unknown  |
| Blacklist upload / listing (company-wide) | Endpoint unknown — frontend only has per-workflow `exclude/list` |
| Async pitch generation (`202 + /pitch/jobs/:jobId` polling) | Endpoint unknown — frontend only has synchronous `get/pitch` + `save/pitch` |
| `GET /organization/token-pricing`    | Endpoint unknown — frontend only has `POST /api/equity/package/feature/token/remain` |
| `aiflow create` full flow (CSV upload + targeting + pitch + mailbox bind + launch) | Request payload schemas for each step not documented; blocked on confirmation |
