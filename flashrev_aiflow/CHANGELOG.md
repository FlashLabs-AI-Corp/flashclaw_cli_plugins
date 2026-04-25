# Changelog — flashclaw-cli-plugin-flashrev-aiflow

All notable changes to this module are recorded here. The format loosely
follows [Keep a Changelog](https://keepachangelog.com/). Versions follow
[SemVer](https://semver.org/); until the first `1.0.0` release,
command-level breaking changes are acceptable within `0.x` versions.

## Unreleased

_(nothing yet)_

---

## 0.4.0 — 2026-04-25

**Breaking change.** `aiflow create --no-launch` is now FORBIDDEN.

In 0.3.3 the `--no-launch` path was discouraged (yellow WARNING +
`creationComplete: false` in the summary) but still allowed —
agents and scripts kept reaching for it and ending up with orphan
DRAFTs (workflow row exists but with no sequenceId on the engage
service, no bound mailbox, no time template, no meetingRouteId; the
scheduler cannot send anything against such a flow). 0.4.0 closes the
hole entirely: the `--no-launch` flag is rejected at the entry of
`aiflow create` with `AIFLOW_NO_LAUNCH_FORBIDDEN` (exit code 1), BEFORE
any side-effect call (no CSV upload, no `create/list`, no pitch fetch,
nothing). The flag-shape stays registered with Click only so the error
is helpful instead of Click's generic "no such option".

### Migration
The error message and updated docs both point at the canonical
replacement workflow:

- **Goal: create a flow but don't send right now** —
  `aiflow create ...` (always launches) then `aiflow pause FLOW_ID` to
  flip ACTIVE → PAUSED. The flow is fully built (sequenceId, mailbox,
  time template all bound) and the scheduler is held off. This is the
  state `--no-launch` was trying to produce, but without leaving an
  unbuilt orphan.

- **Goal: edit prompts / settings before sending** —
  `aiflow create ...` → `aiflow pause FLOW_ID` →
  `aiflow prompt-update FLOW_ID --file ...` /
  `aiflow settings-update FLOW_ID ...` →
  `aiflow resume FLOW_ID` (PAUSED → ACTIVE).

### Changed
- `--launch/--no-launch` Click option help text rewritten: `--launch`
  is documented as a no-op (default behaviour); `--no-launch` is
  documented as FORBIDDEN with the migration recipe inline.
- `SKILL.md` `aiflow create` description leads with "`--no-launch` is
  FORBIDDEN" and the create → pause migration. The args list drops
  `--launch/--no-launch`. Examples drop `--launch` (now redundant) and
  add an `aiflow create ... && aiflow pause $FLOW_ID` example for the
  build-but-don't-send case.
- `README.md` options table flags `--launch` as a no-op and `--no-launch`
  as FORBIDDEN with `AIFLOW_NO_LAUNCH_FORBIDDEN`. Pipeline section
  drops the "(when `--launch`)" qualifier on step 8 — launch is always
  mandatory now.

### Tests
- `test_no_launch_marks_creation_incomplete_with_next_step` (the
  0.3.3 happy-path test for `--no-launch`) renamed to
  `test_explicit_no_launch_is_rejected`. New assertions: exit code
  != 0; output contains `AIFLOW_NO_LAUNCH_FORBIDDEN`; none of the
  upload / create / save endpoints were called (the guard fires
  before any network hit); migration message contains all of
  `aiflow pause`, `aiflow prompt-update`, `aiflow settings-update`,
  `aiflow resume`.
- `test_default_create_triggers_regenerate_emails` no longer relies
  on `--no-launch` to short-circuit the launch path — it now mocks
  the full M3 set (`get_setting` / `list_time_templates` /
  `list_personal_meetings` / `save_setting`) so the wizard runs end
  to end.
- 88 passing.

### Not changed (deliberately)
The interactive wizard's `Launch this AIFlow now? (No = save as
draft)` confirm prompt is untouched in 0.4.0. It was authored before
the milestone-based DoD was enforced, and answering "No" still ends
up in the same orphan-DRAFT state `--no-launch` produced. This is
known and tracked separately — the focus of 0.4.0 is sealing the
flag-driven path that automation / agents take.

---

## 0.3.3 — 2026-04-25

Definition-of-done is now enforced and surfaced. `aiflow create` is
documented and instrumented as THREE required milestones: M1 — file
upload + `create/list` (yields listId + flowId); M2 — pitch parsing
(`test/connection` → `save/pitch`) + email prompt templates persisted
(`get/email/prompt` → `save/prompt`); M3 — pick mailbox + time template
+ meetingRouteId + `POST /save/setting` (DRAFT → ACTIVE). Missing any
milestone means the AIFlow is NOT successfully created.

### Added
- `_emit_creation_failure_banner` in the create wizard. On any pipeline
  failure (network error, validation error, user abort) the CLI now
  prints a prominent red `AIFLOW NOT CREATED` callout listing the
  failed milestone, the M1/M2/M3 checklist with [x]/[ ] markers, the
  partial state (listId / flowId), and concrete recovery commands
  (`aiflow settings-update <id>` to resume, `aiflow delete <id>` to
  discard the orphan DRAFT). Previously, mid-pipeline failures only
  produced a single red `Error: ...` line, leaving users to figure out
  whether a workflow row had been created and what state it was in.
- `creationComplete`, `completedMilestones`, `missing`, and `nextStep`
  fields in the `aiflow create` summary JSON. `creationComplete` is
  the authoritative success signal (true only when M3-settings entered
  `completedMilestones`); downstream agents and scripts should branch
  on it rather than on `flowId` existence.
- JSON-mode addendum: a structured `{creationComplete, failedMilestone,
  completedMilestones, partialState, recovery}` block is emitted on
  failure so agents can react without parsing the human banner.

### Changed
- `--no-launch` exit messaging promoted from a plain `Flow left as
  DRAFT` line to a yellow `WARNING:` callout that explicitly states
  the workflow has no sequenceId, no bound mailbox, no time template,
  and the scheduler cannot send emails until settings-update fires.
- `SKILL.md` `aiflow create` description rewritten around the
  three-milestone definition of done. Agents are explicitly told to
  read `creationComplete` + `completedMilestones`, not to assume
  `flowId` alone means success.

### Tests
- Added `test_pipeline_failure_emits_aiflow_not_created_banner` —
  M1 succeeds, M2 aborts at `test/connection`; asserts banner text,
  the M1=[x] / M2=[ ] / M3=[ ] checklist, the orphan flowId surfaces
  in the `aiflow delete` recovery hint, and `failedMilestone` JSON
  field is correct.
- Added `test_pipeline_failure_at_m3_save_setting_emits_banner` —
  M1+M2 succeed, M3 fails at `save_setting`; asserts the banner
  reflects the M3 failure even though everything upstream worked.
- Extended `test_default_create_triggers_save_setting` to also assert
  `creationComplete: true`, `missing: []`, `nextStep: null` on the
  happy path.
- Added `test_no_launch_marks_creation_incomplete_with_next_step` —
  the deliberate `--no-launch` skip path must report
  `creationComplete: false` + a non-empty `missing` array + a recovery
  hint pointing at `aiflow settings-update`.
- 88 passing (was 85).

---

## 0.3.2 — 2026-04-25

### Fixed
- `test_website_connection` (`POST /api/v1/ai/workflow/test/connection`)
  no longer hard-codes a 20s read timeout. It now uses the shared
  `self.timeout` (default 300s, configurable via the existing
  `FLASHREV_AIFLOW_TIMEOUT` env var). The previous 20s cap was hit
  whenever the upstream had to do a cold-cache fetch of the target site
  (e.g. `tongchengir.com`, `ctrip.com` — both routinely take 20-30s
  before the LLM pass even starts), causing `aiflow create` to abort
  client-side after the workflow row was created but before pitch /
  prompts / save-setting could run. Confirmed against the gateway in
  test env: a `curl` to `/test/connection` for the same URL returns in
  21s, well within the new 5min ceiling.

### Tests
- `test_test_website_connection_uses_20s_timeout` renamed to
  `test_test_website_connection_uses_shared_timeout`. The assertion
  now pins the timeout to `self.client.timeout` and adds a `>= 180`
  floor so future regressions that drop the default below 3min are
  caught (85 passing).

---

## 0.3.1 — 2026-04-24

### Fixed
- `aiflow create --no-wizard` now defaults to launching the flow
  (`launch_now=True`), so `/api/v1/ai/workflow/save/setting` is fired as
  part of every create. Previously the `--no-wizard` branch defaulted to
  `launch_now=False`, which produced flows without a sequence binding on
  the engage service, no mailbox bound, no time template, and no way for
  the scheduler to actually send emails — even though every other step
  in the create pipeline (pitch / prompts / step seed / regenerate) ran
  normally. Mirrors the frontend's "Launch AIFlow" button being the
  natural endpoint of the create wizard. Pass `--no-launch` explicitly
  when you intend to populate prompts later via `aiflow prompt-update`
  before launching.

### Tests
- Added `test_default_create_triggers_save_setting` pinning the new
  default-on launch behaviour for the headless `--no-wizard` path
  (85 passing, was 84).

---

## 0.3.0 — 2026-04-24

Major rewrite to match the real `search-website` frontend flow: pitch
content is now LLM-generated from a URL, email prompt templates are
always populated before launch, and four post-create edit commands let
operators iterate on a flow without recreating it from scratch.

### Added — create pipeline (V2)
- `--url URL` / `--language LANG` — pitch content is now generated by
  `POST /api/v1/ai/workflow/test/connection {url, language}` and written
  to `/save/pitch` with the flow's `workflowId`. No more local
  pitch.json input. `--language auto` sets `useConfigLanguage=true`.
- Automatic 3-step skeleton seed (1h / 3d / 7d delays) when
  `POST /get/prompt` returns an empty list for a fresh flow, via
  `wizard.seed_default_steps` → `/save/prompt` with empty rows → re-query.
  Backs the frontend's hard-coded 3-step default pipeline.
- **`--regenerate-emails` is on by default** — every `aiflow create` run
  now calls `POST /get/email/prompt` per step (SSE-parsed) to fill the
  `emailContent` prompt template, so the scheduler has something real
  to feed the LLM at send time. Pass `--no-regenerate-emails` to skip
  (scaffolding only; launch will be blocked until populated via
  `aiflow prompt-update`).
- Launch-time completeness gate (`AIFLOW_LAUNCH_PROMPTS_INCOMPLETE`)
  blocks `--launch` when any step's `emailContent` is still empty.
- `--enable-agent-reply/--no-enable-agent-reply` and `--agent-strategy`
  overrides for the `/save/setting` body (inherits from `/get/setting`
  when not passed).
- Auto-patch `agentPromptList[Book Meeting].meetingRouteId` on launch by
  picking `[0].id` from `POST /meeting-svc/api/v1/meeting/personal/list`,
  mirroring search-website `ai-sdr/v2/components/ai-reply.vue:192-194`.
- 3-attempt retry + 2s backoff in `wizard.regenerate_step_content` for
  the flaky ai-sdr/Cloudflare chain on test env.

### Added — post-create edit commands
- `aiflow pitch-update FLOW_ID --url URL [--language]` — rerun
  `/test/connection` and overwrite the saved pitch.
- `aiflow prompt-show FLOW_ID [--step N] [--full]` — dump the saved
  `emailContent` per step (uses `/get/email/prompt`'s short-circuit
  path with `workflowStepId`).
- `aiflow prompt-update FLOW_ID --file prompts.json` — REPLACE the
  step list via `/save/prompt` (warning: deletes any existing step not
  in the uploaded list).
- `aiflow settings-update FLOW_ID [--time-template-id N] [--mailboxes MODE]
  [--auto-approve] [--enable-agent-reply] [--agent-strategy S]` —
  fetch `/get/setting`, merge the passed flags onto the returned body
  (keeps `agentPromptList` / `emailTrack` passthrough), POST
  `/save/setting`. Auto-patches Book Meeting `meetingRouteId` when
  `isShowAiReply=True` and no router is bound yet.

### Added — read-only commands
- `aiflow draft` — `GET /api/v1/ai/workflow/draft` (shows the user's
  most recent DRAFT; read-only, no resume).
- `aiflow setting-show FLOW_ID` — `GET /api/v1/ai/workflow/get/setting/{id}`.
- `meetings list [--name N] [--type T]` — meeting-svc personal routers,
  new top-level command group.

### Added — gateway + session
- `meeting_prefix` config key with default `/meeting-svc` (reuses the
  existing auth-gateway-svc route).
- `FLASHREV_AIFLOW_MEETING_PREFIX` env override.
- `auth status` JSON payload now includes `meeting_prefix`.

### Added — onboarding + prompt copy
- First-run welcome banner. Running the bare
  `flashclaw-cli-plugin-flashrev-aiflow` command (no subcommand) after
  `pipx install` prints a green "installed successfully" message plus a
  3-step onboarding checklist that points at
  https://info.flashlabs.ai/settings/privateApps for API key creation,
  shows the exact `auth login` command, and ends with `auth whoami` as
  a verification step. Banner auto-suppresses once a key is bound.
- Missing API key prompt now points to
  https://info.flashlabs.ai/settings/privateApps for key creation.
- Insufficient / exhausted token balance prompts point to
  https://info.flashlabs.ai/settings/credit for top-up.
- All user-facing text standardized to English (CSV column heuristics
  like `邮箱 / 国家` stay bilingual since they match user CSV data,
  not CLI prompts).

### Changed — BREAKING
- `aiflow create` accepts `--url` (with `--website` as alias) instead
  of `--pitch-file` + `--website`. Pitch is now always LLM-generated;
  the local JSON-pitch path is gone.
- `aiflow pitch show` → `aiflow pitch-show` (flat command, no group).
- `aiflow create` default behaviour: LLM prompt templates are generated
  automatically (`--regenerate-emails=True`); previous opt-in flag
  semantics are inverted.
- `/save/pitch` client path: was `/api/v1/ai/workflow/agent/save/pitch`,
  now `/api/v1/ai/workflow/save/pitch` (drops the redundant `/agent/`).
- `test_website_connection(url)` now requires a `language` argument;
  the DTO body is `{url, language}` rather than `{url}`.
- auth-gateway-svc `/meeting-svc` route target was stripped of its
  trailing `/meeting` — the CLI now carries the full
  `/meeting/api/v1/meeting/personal/list` path to mirror `/flashrev`.
  (Paired commit in `auth-gateway-svc`.)
- Client `save_prompt(workflow_id, prompts)` signature, replacing the
  old `save_workflow_prompt(payload)` (removed).

### Removed
- `aiflow pitch init` command (and `_pitch_scaffold`) — pitch is now
  LLM-driven from `--url`; the local JSON scaffold served a workflow
  that no longer exists.
- `aiflow template` command.
- Client methods that have no CLI binding or hit obsolete paths:
  `get_time_template`, `save_workflow_prompt`, `save_bind_email`,
  `get_email_config`, `save_email_config`, `get_auto_approve_status`,
  `save_auto_approve_status`, `batch_delete_aiflow`,
  `get_mailbox_pool_detail`.

### Fixed
- Cap CLI-supplied `emailContent` (and the other three TEXT-mapped
  prompt fields) at 2/3 of the MySQL TEXT column limit
  (43,690 bytes — `_EMAIL_CONTENT_BYTE_LIMIT` in `wizard.py`). LLM
  templates regenerated by `--regenerate-emails` were occasionally
  exceeding the column ceiling, which the backend reported as
  HTTP 200 + body `{code: 400, msg: "Data truncation: Data too long
  for column 'email_content'"}`; the CLI's `_handle` only checks the
  HTTP status, so the failure was slipping through silently as a
  "successful" save with empty content on read-back. The truncation
  is byte-aware (handles utf-8 multi-byte boundaries via
  `decode("utf-8", errors="ignore")`) and emits a stderr warning
  per truncated step so operators can see the cap fire. Applied at
  the source in `regenerate_step_content` and defensively in
  `build_save_prompt_body` so `aiflow prompt-update --file` is
  protected too.
- `/get/email/prompt` short-circuit: `regenerate_step_content` no
  longer passes `workflowStepId` on the request. The backend
  short-circuits to the saved (empty) row whenever it sees a matching
  id, which was suppressing the LLM path for freshly-seeded rows.
- SSE parser (`wizard._parse_sse_content`) strips the backend's
  `</content>` stream terminator so downstream consumers see a clean
  prompt template.
- `/get/setting` response shape: `properties` lives at the top level of
  `data`, not under `data.setting.properties` as an older doc suggested;
  `build_save_setting_body` + `settings-update` now read the correct
  path and preserve `emailTrack` / `timeTemplateConfig` on partial
  updates.
- `timeTemplateConfig` precedence: when the CLI supplies a concrete
  template (e.g. `--time-template-id`), it now overrides the
  already-persisted one instead of silently reusing the existing.
- `get_meeting_prefix` import kept pinned with an explicit `# noqa:
  F401` comment; the shared formatter was stripping it repeatedly.
- 502/504 transient upstream failures during the regenerate pass now
  retry 3 times with 2s backoff before giving up on a step.

### Tests
- 84 passing (was 41). New coverage: V2 endpoints (`test_connection`
  with language, `save_pitch` path fix, `get_email_prompt` body shape,
  `get_setting` / `draft` / `list_personal_meetings` paths, meeting
  prefix routing), `_parse_sse_content` + `seed_default_steps` +
  `patch_meeting_route_id` + `pick_first_meeting_router_id`,
  `build_save_setting_body` (DRAFT / flag overrides / agent block
  visibility), all four edit commands (pitch-update / prompt-show /
  prompt-update / settings-update), launch-completeness gate, the
  first-run welcome banner (shown-when-unconfigured + suppressed-when-bound),
  and the email-content byte-limit cap (passes-through under limit,
  truncates over limit, safe at multi-byte UTF-8 boundaries,
  applied at build_save_prompt_body).

### Docs
- `README.md` rewritten: V2 pipeline table, `--no-wizard` required-field
  matrix, launch-gate semantics, `--no-regenerate-emails` opt-out.
- `skills/SKILL.md` command manifest synced (27 commands across 6 groups).

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
