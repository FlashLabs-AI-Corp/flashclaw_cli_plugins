# cli-anything-call-svc

Agent-friendly CLI harness for the **call-svc** voice call number management service.

```bash
cli-anything-call-svc --help
cli-anything-call-svc --json number available --country US --region 646
cli-anything-call-svc --json number buy --country US
```

See [call_svc/README.md](call_svc/README.md) for full documentation.

---

## Project Structure

```
call_svc/
├── pyproject.toml
├── README.md
└── cli_anything/
    └── call_svc/
        ├── call_svc_cli.py      # CLI entry point (Click + REPL)
        ├── core/
        │   ├── client.py        # HTTP client
        │   └── session.py       # API Key & config management
        ├── utils/
        │   ├── output.py        # JSON / human-readable output
        │   └── repl_skin.py     # Interactive REPL skin
        ├── skills/
        │   └── SKILL.md         # AI-discoverable skill definition
        └── tests/
            ├── test_core.py     # Unit + subprocess tests
            └── TEST.md          # Test plan & results
```

---

## Installation

```bash
npx clawhub install cli-anything-call-svc
```

See [call_svc/README.md](call_svc/README.md) for full installation and usage instructions.

---

## Development

```bash
cd call_svc && pip install -e .
pytest cli_anything/call_svc/tests/
```

### Publish to ClawHub

```bash
npx clawhub login

npx clawhub publish ./call_svc \
  --slug cli-anything-call-svc \
  --name "Call-Svc CLI" \
  --version 0.1.0 \
  --changelog "Initial release"
```
