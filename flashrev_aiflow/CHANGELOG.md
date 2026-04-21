# Changelog — flashclaw-cli-plugin-flashrev-aiflow

All notable changes to this module are recorded here. The format loosely
follows [Keep a Changelog](https://keepachangelog.com/). Versions follow
[SemVer](https://semver.org/); until the first `1.0.0` release,
command-level breaking changes are acceptable within `0.x` versions.

## Unreleased

### Added
- `aiflow pitch init [--out PATH] [--force]` — writes a ready-to-edit
  6-section pitch JSON scaffold (no network call). Matches the schema
  accepted by `aiflow create --pitch-file`.
- `examples/` directory with `contacts.example.csv` (5 rows, canonical
  columns) and `pitch.example.json`; `examples/README.md` walks through
  a 60-second dry-run using them.

### Changed
- **BREAKING:** `aiflow pitch FLOW_ID` is now `aiflow pitch show FLOW_ID`.
  `aiflow pitch` was promoted from a single command to a group so that
  `show` and `init` can coexist. Scripts that invoked the old form will
  need `show` inserted.

### Fixed
- `wizard.validate_pitch_schema` now retains the top-level `url` field on
  the returned dict, so pitch JSON files can carry the website URL and
  make `--website` optional on `aiflow create --no-wizard`.

---

## 0.1.0 — initial milestones

Milestones M1–M5 from the PRD are implemented. Endpoints are all real
paths observed in the `search-website` frontend; no endpoint was invented
from the PRD spec.

### M1 — project skeleton + auth
- `pyproject.toml` declaring the package as `flashclaw-cli-plugin-flashrev-aiflow`
- Nested `flashclaw_cli_plugin/flashrev_aiflow/` PEP 420 namespace package
  (shared with `flashclaw-cli-plugin-call-svc`); see `flashclaw_cli_plugin/NAMESPACE.md`
- `auth login --token KEY` — saves API key to `~/.claude/skills/flashrev-aiflow-assistant/.env`
- `auth logout` — clears the saved key
- `auth whoami` — calls `GET /api/v2/oauth/me`, validates the key, returns identity + equity
- `auth status` — shows local-only config without any network call
- `config show / set / unset` — runtime config for `base_url`, `timeout`, and
  the three gateway prefixes (`discover_prefix` default `/flashrev`,
  `engage_prefix` default empty, `mailsvc_prefix` default empty)
- `health` — unauthenticated gateway reachability check
- Click-based CLI with global `--json` for agent-friendly structured output
- `utils/output.py` emits JSON or human output + structured errors with an
  `error` code + exit code 1

### M2 — read-only AIFlow / mailbox operations
- `aiflow list [--status] [--page] [--page-size]` → `GET /api/v1/ai/workflow/agent/list`
- `aiflow show FLOW_ID` → `GET /api/v1/ai/workflow/agent/get/flow/{flowId}`
- `aiflow pitch FLOW_ID` → `GET /api/v1/ai/workflow/agent/get/pitch` (now `aiflow pitch show`)
- `aiflow template` → `GET /api/v1/ai/workflow/agent/get/time/template`
- `aiflow test-connection URL` → `POST /api/v1/ai/workflow/agent/test/connection`
- `aiflow delete FLOW_ID [-y]` / `aiflow rename FLOW_ID NEW_NAME`
- `mailboxes list [--status] [--warmup]` → `GET /mailsvc/mail-address/simple/v2/list`
- `mailboxes bind-list` / `mailboxes has-active`

### M3 — interactive AIFlow creation wizard
- `aiflow create` wizard spanning Strategy → AIFlow → Settings → Launch, using:
  - `POST /api/v1/ai/workflow/contacts/upload` (new backend endpoint — see `README.md`)
  - `POST /api/v1/ai/workflow/create/list` → returns `{id: flowId}`
  - `POST /api/v1/ai/workflow/save/pitch` → persists the 6 sections
  - `GET /api/v1/ai/workflow/agent/get/time/template` → read-only preview
  - `POST /api/v1/ai/workflow/agent/get/email/config` → load current settings
  - `POST /api/v1/ai/workflow/agent/save/email/config` → save with edits
  - `GET /api/v1/ai/workflow/agent/sequence/status/{flowId}/ACTIVE` → launch
- `wizard.py` helpers: CSV/Google-Sheet loading (`/export?format=csv` trick),
  BOM-safe CSV preview + email-dedup, EN/CN heuristic country-column detection
  (`country / region / location / 国家 / 地区`), interactive `click.edit`-based
  pitch editor with retry, mailbox filter for active-only entries
- Pitch via either `--pitch-file path.json` or `$EDITOR`; pitch file may
  carry the `url` / `language` fields so `--website` is optional
- Correct status tokens (`ACTIVE` / `PAUSED`) derived from frontend code

### M4 — non-wizard + dry-run
- `--no-wizard` — every missing required field raises a `USAGE_*` error with
  exit code 2 (CI-friendly, no prompts)
- `--dry-run` — validates inputs and probes read-only endpoints (token balance,
  mailbox list, time template) but skips every write endpoint; emits a
  summary with a `dryRun: true` marker
- `--country-column COL | none` — explicit flag for auto-language mode
  (required in `--no-wizard`); `none` explicitly opts out
- Required-field matrix with dedicated error codes:
  `USAGE_CONTACT_SOURCE`, `USAGE_CONTACT_SOURCE_CONFLICT`,
  `USAGE_PITCH_FILE_REQUIRED`, `USAGE_WEBSITE_MISSING`,
  `USAGE_COUNTRY_COLUMN_MISSING`, `USAGE_COUNTRY_COLUMN_NOT_FOUND`,
  `USAGE_MAILBOX_NO_MATCH`
- Launch defaults in `--no-wizard` mode: save as draft unless `--launch` is
  explicitly passed

### M5 — token balance checks
- `token balance` — derives `{tokenTotal, tokenCost, tokenRemaining, sufficient}`
  from `GET /api/v2/oauth/me` → `data.limit.*`
- `token check [--required N]` — exits 2 (`TOKEN_INSUFFICIENT` or
  `TOKEN_EXHAUSTED`) when balance is below the requested amount
- `aiflow start` / `aiflow resume` run the same balance check pre-flight;
  `--force` skips the CLI-side check (backend `auth-gateway-svc` enforcement
  still applies where configured)
- Fail-open on `/me` errors — emits a stderr warning rather than blocking
  every launch when the /me endpoint is flaky

### Backend dependency
- New endpoint `POST /api/v1/ai/workflow/contacts/upload` (multipart file
  upload) required for `aiflow create` end-to-end. Spec in `README.md`; a
  reference implementation for `dubbo-api-svc` exists on the
  `feature/openclaw-mail-cli-260421` branch, already merged into `test`.

### Tests
- 41 unit tests covering session + client URL building + token balance
  math + wizard helpers (CSV / Sheet / pitch / mailbox filter) + non-wizard
  flag matrix + dry-run contract + pitch init
