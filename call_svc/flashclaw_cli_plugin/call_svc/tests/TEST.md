# Test Documentation — flashclaw-cli-plugin-call-svc

## Test Inventory

| File | Tests | Coverage |
|------|-------|---------|
| `test_core.py` | 15 unit + subprocess tests | Session, Client, OutputMode, CLI subprocess |

---

## Unit Test Plan

### `TestSession` (5 tests)
Tests `core/session.py` API Key and config management.

| Test | What it covers |
|------|---------------|
| `test_default_base_url_prod` | `CALL_SVC_ENV=prod` → gateway prod URL |
| `test_default_base_url_test_env` | `CALL_SVC_ENV=test` → gateway test URL |
| `test_api_key_round_trip` | `set_api_key` → `get_api_key` returns same value |
| `test_clear_api_key` | After `clear_api_key`, `get_api_key` returns None |
| `test_env_var_overrides_file` | `CALL_SVC_API_KEY` env var overrides .env file |

### `TestClient` (6 tests)
Tests `core/client.py` HTTP client with mocked `requests`.

| Test | What it covers |
|------|---------------|
| `test_url_contains_callsvc_prefix` | All URLs include `/callsvc` gateway prefix |
| `test_x_api_key_header_set` | `X-API-Key` header used, no `Authorization` header |
| `test_base_url_trailing_slash_stripped` | Trailing slash removed from base URL |
| `test_available_numbers_calls_gateway_path` | GET to correct gateway path, X-API-Key present |
| `test_purchased_numbers_calls_gateway_path` | GET purchased-numbers to correct gateway path |
| `test_buy_number_calls_gateway_path` | POST to correct buy gateway path |
| `test_voice_call` | POST to correct voice-call gateway path |

### `TestOutputMode` (1 test)
Tests `utils/output.py` JSON mode toggle.

### `TestCLISubprocess` (5 tests)
Tests the installed `flashclaw-cli-plugin-call-svc` command via subprocess.

| Test | What it covers |
|------|---------------|
| `test_help` | `--help` exits 0, contains expected text |
| `test_config_show_json` | `--json config show` returns valid JSON with `base_url` |
| `test_health_json` | `--json health` returns valid JSON with `base_url` |
| `test_auth_status_json` | `--json auth status` returns valid JSON with `configured` |
| `test_number_help` | `number --help` lists all subcommands |

---

## Running Tests

```bash
# Install in editable mode first
cd call_svc && pip install -e .

# Run all tests
pytest flashclaw_cli_plugin/call_svc/tests/ -v -s

# Run against installed command only (CI mode)
CLI_ANYTHING_FORCE_INSTALLED=1 pytest flashclaw_cli_plugin/call_svc/tests/ -v -s
```

---

## Test Results

```
============================= test session starts =============================
platform win32 -- Python 3.11.9, pytest-9.0.2
collected 18 items

TestSession::test_api_key_round_trip                              PASSED
TestSession::test_clear_api_key                                   PASSED
TestSession::test_default_base_url_prod                           PASSED
TestSession::test_default_base_url_test_env                       PASSED
TestSession::test_env_var_overrides_file                          PASSED
TestClient::test_available_numbers_calls_gateway_path             PASSED
TestClient::test_base_url_trailing_slash_stripped                 PASSED
TestClient::test_buy_number_calls_gateway_path                    PASSED
TestClient::test_purchased_numbers_calls_gateway_path             PASSED
TestClient::test_url_contains_callsvc_prefix                      PASSED
TestClient::test_voice_call                                       PASSED
TestClient::test_x_api_key_header_set                             PASSED
TestOutputMode::test_json_mode_toggle                             PASSED
TestCLISubprocess::test_auth_status_json                          PASSED
TestCLISubprocess::test_config_show_json                          PASSED
TestCLISubprocess::test_health_json                               PASSED
TestCLISubprocess::test_help                                      PASSED
TestCLISubprocess::test_number_help                               PASSED

============================== 18 passed in 1.32s ==============================
```

**Summary:** 18 tests, 18 passed, 0 failed. Execution time: 1.32s.
