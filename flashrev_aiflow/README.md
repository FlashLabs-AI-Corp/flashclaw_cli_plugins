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
| `aiflow list [--type T] [--view V]`        | `POST /api/v1/ai/workflow/type/rows`                                      |
| `aiflow show FLOW_ID`                      | `GET /api/v1/ai/workflow/detail/nodes/{flowId}`                           |
| `aiflow start FLOW_ID [--status TOKEN] [--required-tokens N] [--force]` | `POST /api/v1/ai/workflow/status` body `{id, status:"ACTIVE"}` + token pre-check |
| `aiflow pause FLOW_ID [--status TOKEN]`    | same endpoint, status defaults to `PAUSED`                                |
| `aiflow resume FLOW_ID [--status TOKEN] [--required-tokens N] [--force]` | same endpoint + token pre-check                                |
| `aiflow delete FLOW_ID [-y]`               | `POST /api/v1/ai/workflow/delete` body `{id}`                             |
| `aiflow rename FLOW_ID NEW_NAME`           | `POST /api/v1/ai/workflow/agent/update/name`                              |
| `aiflow pitch-show FLOW_ID`                | `GET /api/v1/ai/workflow/get/pitch/{flowId}` (returns ICP DTO, not 6-section text) |
| `aiflow pitch-update FLOW_ID --url URL [--language]` | `POST /test/connection` -> `POST /save/pitch`                   |
| `aiflow setting-show FLOW_ID`              | `GET /api/v1/ai/workflow/get/setting/{flowId}`                            |
| `aiflow settings-update FLOW_ID [--time-template-id N] [--mailboxes MODE] [--auto-approve] [--enable-agent-reply] [--agent-strategy S]` | `GET /get/setting` -> merge flags -> `POST /save/setting` |
| `aiflow prompt-show FLOW_ID [--step N] [--full]` | `POST /get/prompt` + per-step `POST /get/email/prompt` (short-circuit) |
| `aiflow prompt-update FLOW_ID --file F.json` | `POST /api/v1/ai/workflow/save/prompt` (REPLACE semantics)              |
| `aiflow draft`                             | `GET /api/v1/ai/workflow/draft` (read-only; no resume)                    |
| `aiflow test-connection URL [--language]`  | `POST /api/v1/ai/workflow/test/connection` (20s timeout)                  |
| `aiflow create`                            | Interactive wizard; see "Create wizard" below                             |

### 60-second dry-run with the shipped example CSV

```bash
flashclaw-cli-plugin-flashrev-aiflow aiflow create --no-wizard --dry-run \
  --csv ./examples/contacts.example.csv \
  --url acme.com --language en-us
```

`--dry-run` probes read-only endpoints only (mailboxes + token balance);
all write endpoints print `[dry-run] would ...` without firing.

### Create a fresh flow end-to-end

```bash
flashclaw-cli-plugin-flashrev-aiflow aiflow create --no-wizard \
  --csv ./contacts.csv \
  --url acme.com --language en-us \
  --launch -y
```

LLM generation of the per-step `emailContent` prompt templates is **on by
default** — every launched flow ships with non-empty prompts so the
scheduler can actually produce emails at send time.

**Every run creates a brand-new flow.** There is no resume. If you have a
stray DRAFT, inspect it with `aiflow draft` and clean up via
`aiflow delete <id>` before creating again.

### Create wizard

`flashclaw-cli-plugin-flashrev-aiflow aiflow create` drives a V2 pipeline
that mirrors the web UI's "URL → pitch → prompts → settings → launch"
flow. Pitch content is **LLM-generated from `--url`** (no more local
pitch.json input).

```
# Interactive wizard (prompts for missing fields)
flashclaw-cli-plugin-flashrev-aiflow aiflow create

# Wizard with flag pre-fills
flashclaw-cli-plugin-flashrev-aiflow aiflow create \
    --csv ./contacts.csv \
    --url acme.com \
    --language en-us \
    --mailboxes all-active \
    --launch -y

# Headless / CI — every missing field raises USAGE_*
flashclaw-cli-plugin-flashrev-aiflow --json aiflow create --no-wizard \
    --csv ./contacts.csv \
    --url acme.com \
    --language en-us \
    --launch -y

# Dry-run: no side effects
flashclaw-cli-plugin-flashrev-aiflow aiflow create --no-wizard --dry-run \
    --csv ./contacts.csv --url acme.com --language en-us

# Skip LLM regenerate (scaffolding only — launch will be blocked until
# you populate prompts via aiflow prompt-update)
flashclaw-cli-plugin-flashrev-aiflow aiflow create --no-wizard \
    --csv ./contacts.csv --url acme.com --language en-us \
    --no-regenerate-emails
```

**`--no-wizard` required-field matrix**

| Field | Required when |
|---|---|
| `--csv` or `--sheet` | Always (exactly one) |
| `--url` | Always (pitch content is LLM-generated from this) |
| `--language` | Optional (default `en-us`); pass `auto` for per-contact detection |
| `--country-column` | Required when `--language=auto`; pass `none` to skip |
| `--mailboxes` | Optional (default `all-active`) |
| `--regenerate-emails` / `--no-regenerate-emails` | Optional (default: ON — LLM-fills every step's emailContent) |
| `--launch` | Optional and now a no-op — `aiflow create` ALWAYS launches (fires `/save/setting`, transitions DRAFT → ACTIVE, binds sequence + mailbox + time template). Kept only as a documentation flag. |
| `--no-launch` | **FORBIDDEN** — passing it returns `AIFLOW_NO_LAUNCH_FORBIDDEN` (exit 1) before any side-effect call. The flag previously left orphan DRAFTs (no sequenceId, no bound mailbox, no time template). To create a flow without sending right now, run `aiflow create ...` (always launches) then `aiflow pause FLOW_ID`. |

**Launch-time completeness gate**

`--launch` is blocked with exit code 2 + `AIFLOW_LAUNCH_PROMPTS_INCOMPLETE`
when any step still has empty `emailContent` — launching such a flow would
produce zero sends. With `--regenerate-emails` default-on, this normally
only fires when the LLM flaked on one or more steps after the built-in
retries; the fix is to re-run `aiflow create` or populate the failing
step(s) via `aiflow prompt-update FLOW_ID --file prompts.json`. If you
passed `--no-regenerate-emails`, all steps will be empty → populate them
before launching.

**`--dry-run` semantics**

| Step | Dry-run behaviour |
|---|---|
| CSV parse / Sheet download / country-column check | Runs fully (local) |
| `/contacts/upload`, `/create/list`, `/test/connection`, `/save/pitch`, `/get/prompt`, `/save/prompt`, `/save/setting` | Skipped — printed as `[dry-run] would ...` |
| `/mailboxes`, `/api/v2/oauth/me` (token balance) | Executed (read-only) |

### V2 Pipeline

Every `aiflow create` flows through auth-gateway-svc with the `/flashrev` prefix:

1. `POST /api/v1/ai/workflow/contacts/upload`   -> `{listId, listName}`
2. `POST /api/v1/ai/workflow/create/list`       -> `{flowId}`  (NEW flow)
3. `POST /api/v1/ai/workflow/test/connection`   `{url, language}` -> ICP DTO (LLM-generated pitch)
4. `POST /api/v1/ai/workflow/save/pitch`        persist pitch with `workflowId`
5. `POST /api/v1/ai/workflow/get/prompt`        check + seed default step rows (3× delays 1h/3d/7d)
6. **`POST /api/v1/ai/workflow/get/email/prompt`** per-step, with `beforStep` history
   — default on (`--regenerate-emails=True`); fills the emailContent prompt
   template so the scheduler has something to feed into the LLM at send time.
7. `POST /api/v1/ai/workflow/save/prompt`       persist the step prompts
8. *(always — launch is mandatory)*
   - `GET  /api/v1/ai/workflow/get/setting/{flowId}`  -> `agentPromptList`, `emailTrack`, defaults
   - `GET  /engage/api/v1/time/template/list`         -> pick `timeTemplateConfig`
   - `POST /meeting-svc/api/v1/meeting/personal/list` -> first `id` -> Book Meeting `meetingRouteId`
   - `POST /api/v1/ai/workflow/save/setting`          persist settings + DRAFT -> ACTIVE

`--no-launch` is FORBIDDEN. To create a flow without immediately sending,
run `aiflow create ...` then `aiflow pause FLOW_ID`.

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
| `mailboxes bind-list FLOW_ID`   | `GET /api/v1/ai/workflow/get/bind/email/{flowId}`       |
| `mailboxes unbind-list FLOW_ID` | `GET /api/v1/ai/workflow/get/unbind/email/{flowId}`     |
| `mailboxes has-active`          | `GET /api/v1/ai/workflow/has/active/email`              |

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
