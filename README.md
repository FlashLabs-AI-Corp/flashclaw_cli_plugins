# flashclaw-cli-plugin-call-svc

Agent-friendly CLI harness for the **call-svc** voice call number management service, routed via **auth-gateway-svc**.

```
CLI --[X-API-Key: sk_xxx]-> auth-gateway-svc --[Bearer + X-Auth-Company]-> call-svc
```

The CLI only sends an API Key; `companyId` / `userId` are extracted by the gateway and injected into the upstream request.

See [`call_svc/README.md`](call_svc/README.md) for full documentation.

---

## Project layout

```
call_svc/
├── pyproject.toml
├── README.md
└── flashclaw_cli_plugin/
    └── call_svc/
        ├── call_svc_cli.py       # Click CLI entry point (+ REPL)
        ├── core/
        │   ├── client.py         # HTTP client, gateway routing
        │   └── session.py        # API Key + config persistence
        ├── utils/
        │   ├── output.py         # JSON / human-readable output
        │   └── repl_skin.py      # Interactive REPL skin
        ├── skills/
        │   └── SKILL.md          # AI-discoverable skill definition
        └── tests/
            ├── test_core.py      # Unit + subprocess tests
            └── TEST.md           # Test plan & results
```

---

## Install

End users (via ClawHub):

```bash
npx clawhub install flashclaw-cli-plugin-call-svc
flashclaw-cli-plugin-call-svc auth set-key sk_aBcDeFgH...
flashclaw-cli-plugin-call-svc --json health
```

From source:

```bash
cd call_svc
pip install -e .
```

See [`call_svc/README.md`](call_svc/README.md) for API Key provisioning, environment switching, and full command reference.

---

## Commands at a glance

| Group   | Commands                                  |
|---------|-------------------------------------------|
| `auth`  | `set-key`, `status`, `clear`              |
| `config`| `show`, `set`                             |
| `number`| `list`, `available`, `buy`                |
| `call`  | `voice`                                   |
| —       | `health`, `repl`                          |

All commands accept `--json` for agent-friendly structured output.

---

## Development

```bash
cd call_svc
pip install -e .
pytest flashclaw_cli_plugin/call_svc/tests/
```

### Publish to ClawHub

```bash
npx clawhub login

npx clawhub publish ./call_svc \
  --slug flashclaw-cli-plugin-call-svc \
  --name "Call-Svc CLI" \
  --version 0.1.0 \
  --changelog "Initial release"
```
