# flashrev_aiflow — Test Plan

## Scope

| Area | Covered |
|------|---------|
| `core.session` | API Key round-trip (set/get/clear), `FLASHREV_SVC_API_KEY` env var priority over `.env`, config round-trip, `unset_config_value`, prefix getter defaults (`/flashrev`, `''`, `''`) |
| `core.client` URL building | `_url_discover` prepends the configured prefix; `_url_engage` and `_url_mailsvc` keep the native path prefix (no extra prefix) |
| `core.client` headers | `X-API-Key` injected; `Content-Type: application/json` set |
| `core.client` endpoints | `list_aiflows` hits the discover path; `get_user_info` hits `/api/v2/oauth/me`; `list_mailboxes` stays on `/mailsvc/...` and is NOT double-prefixed; `test_website_connection` uses the 20s timeout contract |

## Running

```bash
cd flashrev_aiflow
pip install -e .
pytest flashclaw_cli_plugin/flashrev_aiflow/tests/ -v
```

## Out of scope for this release

- CLI subprocess tests (requires the binary to be on PATH after `pip install -e .`)
- Live gateway integration tests (requires a valid `sk_` key and a running auth-gateway-svc)
- `aiflow create` end-to-end — blocked on request-body schema confirmation (see `flashrev_aiflow_cli.py::aiflow_create`)
