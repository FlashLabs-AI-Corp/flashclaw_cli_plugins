# flashclaw-cli-plugins

Monorepo for the **flashclaw-cli-plugin-*** family of agent-friendly CLIs.
Each plugin is an independently installable PyPI / ClawHub package that
routes through **auth-gateway-svc**.

```
CLI --[X-API-Key: sk_xxx]-> auth-gateway-svc --[Bearer + X-Auth-Company]-> upstream
```

The CLI only sends an API key; `companyId` / `userId` are extracted by the
gateway and injected into the upstream request. Plugins never call upstream
services directly.

## Plugins

| Module | PyPI name | Purpose |
|---|---|---|
| [`call_svc/`](call_svc/) | `flashclaw-cli-plugin-call-svc` | call-svc voice-call number lifecycle |
| [`flashrev_aiflow/`](flashrev_aiflow/) | `flashclaw-cli-plugin-flashrev-aiflow` | FlashRev AIFlow email-outreach automation |

Each plugin has its own `README.md`, `pyproject.toml`, `SKILL.md`, tests,
and (where present) `CHANGELOG.md`.

## Install (end users)

Plugins install independently — pick whichever subset you need:

```bash
npx clawhub install flashclaw-cli-plugin-call-svc
npx clawhub install flashclaw-cli-plugin-flashrev-aiflow
```

See each module's README for its own config + first-run steps.

## Shared API key

All plugins read the API key from the **`FLASHREV_SVC_API_KEY`** env var
or `~/.claude/skills/<slug>-assistant/.env`. Setting the key once works
across the family — no need to log in per plugin.

## Package layout (namespace package)

Plugins share the `flashclaw_cli_plugin.*` Python import prefix via
**PEP 420 namespace packages**. Each plugin contributes one sub-package:

```
call_svc/flashclaw_cli_plugin/call_svc/                → from flashclaw_cli_plugin.call_svc import X
flashrev_aiflow/flashclaw_cli_plugin/flashrev_aiflow/  → from flashclaw_cli_plugin.flashrev_aiflow import X
```

Rationale documented in
[`call_svc/flashclaw_cli_plugin/NAMESPACE.md`](call_svc/flashclaw_cli_plugin/NAMESPACE.md) /
[`flashrev_aiflow/flashclaw_cli_plugin/NAMESPACE.md`](flashrev_aiflow/flashclaw_cli_plugin/NAMESPACE.md).

## Development

```bash
# Pick a plugin, install editable, run its tests
cd call_svc && pip install -e . && pytest flashclaw_cli_plugin/call_svc/tests/
cd flashrev_aiflow && pip install -e . && pytest flashclaw_cli_plugin/flashrev_aiflow/tests/
```

New plugins: copy the structure of an existing module, rename both the
`<module>/` directory at the repo root and the inner
`flashclaw_cli_plugin/<module>/` directory, then update `pyproject.toml`'s
`name` / `[project.scripts]` / `[tool.setuptools.package-data]` entries.
