# flashclaw-cli-plugin-call-svc

Agent-friendly CLI harness for the **call-svc** voice call service.

Request chain:
```
CLI  --[X-API-Key: sk_xxx]-->  auth-gateway-svc  --[Bearer + X-Auth-Company]-->  call-svc
```

`companyId` / `userId` are extracted from the API Key by the gateway and injected automatically — the client does not need to pass them.

---

## Installation

### Option 1: Install via ClawHub (for end users)

**Prerequisites:** Python 3.10+, OpenClaw installed.

**Step 1 — Install the skill**

```bash
npx clawhub install flashclaw-cli-plugin-call-svc
```

**Step 2 — Configure API Key**

Generate an API Key in the FlashRev console → Settings → Private Apps (format: `sk_` prefix), then:

```bash
flashclaw-cli-plugin-call-svc auth set-key sk_aBcDeFgHiJkLmNoPqRsTuVwXyZ01234
```

The key is stored at `~/.claude/skills/call-svc-assistant/.env` with permissions 600.

**Step 3 — Verify connectivity**

```bash
flashclaw-cli-plugin-call-svc --json health
```

A response of `"ok": true` confirms the skill is ready to use in OpenClaw.

---

**(Optional) Switch to test environment**

Edit `~/.openclaw/openclaw.json`, add to `skills.entries`:

```json
{
  "flashclaw-cli-plugin-call-svc": {
    "env": {
      "CALL_SVC_ENV": "test"
    }
  }
}
```

OpenClaw will inject this environment variable automatically, routing the skill to the test gateway.

---

### Option 2: Install from source (for developers)

```bash
cd call_svc
pip install -e .
```

---

## Configuration

```bash
# 1. Save API Key (generate in FlashRev console → Settings → Private Apps)
flashclaw-cli-plugin-call-svc auth set-key sk_aBcDeFgHiJkLmNoPqRsTuVwXyZ01234

# 2. Confirm configuration
flashclaw-cli-plugin-call-svc --json auth status

# 3. Check gateway connectivity
flashclaw-cli-plugin-call-svc --json health
```

### Environments

Switch via `CALL_SVC_ENV` environment variable (default: `prod`):

| CALL_SVC_ENV | Gateway |
|-------------|---------|
| `prod` (default) | auth-gateway-svc production |
| `test` | auth-gateway-svc test |

```bash
# Switch to test environment
CALL_SVC_ENV=test flashclaw-cli-plugin-call-svc --json health
CALL_SVC_ENV=test flashclaw-cli-plugin-call-svc --json number available
```

---

## Usage

### Check connectivity

```bash
flashclaw-cli-plugin-call-svc health
flashclaw-cli-plugin-call-svc --json health
```

### List purchased phone numbers

```bash
flashclaw-cli-plugin-call-svc --json number list
```

**Response schema:**
```json
{
  "code": 0,
  "data": [
    {
      "companyId": 123,
      "phoneNumber": "19498665342",
      "phoneNumberFormat": "+19498665342"
    }
  ]
}
```

### Query available phone numbers

```bash
# All US numbers
flashclaw-cli-plugin-call-svc --json number available

# Filter by country and area code
flashclaw-cli-plugin-call-svc --json number available --country US --region 646

# Paginate
flashclaw-cli-plugin-call-svc --json number available --country CA --page 2 --page-size 10
```

**Response schema:**
```json
{
  "code": 0,
  "data": {
    "list": [
      {
        "country": "US",
        "msisdn": "+12125551234",
        "msisdnFormat": "(212) 555-1234",
        "cost": "1.00",
        "type": "local",
        "features": ["VOICE", "SMS"]
      }
    ],
    "count": 42,
    "page": 1,
    "pageSize": 20
  }
}
```

### Purchase a phone number

```bash
# Auto-assign a US number
flashclaw-cli-plugin-call-svc --json number buy --country US

# Buy in a specific area code
flashclaw-cli-plugin-call-svc --json number buy --country US --region 646

# Buy a specific number (E.164)
flashclaw-cli-plugin-call-svc --json number buy --msisdn +12125551234
```

**Response schema:**
```json
{
  "code": 0,
  "data": {
    "msisdn": "+12125551234",
    "countryCode": "us",
    "buyStatus": 1,
    "features": ["VOICE", "SMS"],
    "hasError": false,
    "phoneFormat": "(212) 555-1234"
  }
}
```

`buyStatus` values: `0` = buying · `1` = success · `2` = failed · `3` = unknown

### Initiate a voice call (legacy)

> **Note:** This endpoint is a legacy shim and returns `true` as a placeholder.

```bash
# Basic call
flashclaw-cli-plugin-call-svc call voice --from +12125551234 --to +8613800138000

# With TTS
flashclaw-cli-plugin-call-svc --json call voice \
  --from +12125551234 --to +8613800138000 \
  --speak-type TTS \
  --tts '{"language":"en-US","style":0,"text":"Hello, this is a test call."}'

# With audio stream URL and recording
flashclaw-cli-plugin-call-svc --json call voice \
  --from +12125551234 --to +8613800138000 \
  --speak-type STREAM \
  --voice-url https://example.com/audio.mp3 \
  --record
```

---

## Architecture

```
flashclaw_cli_plugin/call_svc/
├── call_svc_cli.py      # Click CLI entry point
├── pyproject.toml       # Package & script configuration
├── core/
│   ├── client.py        # HTTP client for call-svc REST API
│   └── session.py       # Session/config persistence + env presets
├── utils/
│   └── output.py        # JSON/human dual-mode output formatting
├── skills/
│   └── SKILL.md         # AI-discoverable skill definition
└── tests/
    └── test_core.py     # Unit + subprocess tests
```

---

## Development

```bash
# Install in editable mode
pip install -e .

# Run tests
pytest call_svc/tests/

# Test against a specific environment (set base URL first)
flashclaw-cli-plugin-call-svc config set base_url <call-svc-base-url>
flashclaw-cli-plugin-call-svc --json health
flashclaw-cli-plugin-call-svc --json number available
```
