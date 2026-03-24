---
name: flashclaw-cli-plugin-call-svc
description: Agent-friendly CLI for call-svc voice call number management, routed via auth-gateway-svc
version: 0.1.0
commands:
  - name: auth set-key
    description: Save API Key (sk_... format) to local credentials file
    args: API_KEY
    examples:
      - auth set-key sk_aBcDeFgHiJkLmNoPqRsTuVwXyZ01234
  - name: auth status
    description: Show current API Key configuration status
  - name: auth clear
    description: Remove the saved API Key
  - name: config show
    description: Show current configuration (base_url, env, api_key_configured)
  - name: config set
    description: Set a config value (base_url, timeout)
    args: KEY VALUE
    examples:
      - config set base_url https://open-ai-api-test.eape.mobi
      - config set timeout 60
  - name: number list
    description: List phone numbers already purchased by the current company
    examples:
      - number list
  - name: number available
    description: Query phone numbers available for purchase
    args: --country CODE --region AREA_CODE --page N --page-size N
    examples:
      - number available
      - number available --country US --region 646
      - number available --country CA --page-size 10
  - name: number buy
    description: Purchase a phone number and bind it to the current company
    args: --country CODE --region AREA_CODE --msisdn E164 --bundle-id N --address-id N
    examples:
      - number buy --country US
      - number buy --country US --region 646
      - number buy --msisdn +12125551234
  - name: call voice
    description: Initiate a voice call (legacy shim)
    args: --from E164 --to E164 --voice-url URL --speak-type STREAM|TTS --tts JSON --record --contact-id N --business-id ID
    examples:
      - call voice --from +12125551234 --to +8613800138000
      - call voice --from +1111 --to +2222 --speak-type TTS --tts '{"language":"en-US","style":0,"text":"Hi there"}'
  - name: health
    description: Check connectivity to auth-gateway-svc (no API Key required)
---

# flashclaw-cli-plugin-call-svc

Agent-friendly CLI for the **call-svc** voice call service, routed via **auth-gateway-svc**.

请求链路：
```
CLI --[X-API-Key: sk_xxx]-→ auth-gateway-svc --[Bearer+X-Auth-Company]-→ call-svc
```

## Quick start

```bash
# Install
cd call_svc && pip install -e .

# Save API Key (obtained from FlashRev console → Settings → Private Apps)
flashclaw-cli-plugin-call-svc auth set-key sk_aBcDeFgHiJkLmNoPqRsTuVwXyZ01234

# Check gateway connectivity
flashclaw-cli-plugin-call-svc --json health

# Query available numbers
flashclaw-cli-plugin-call-svc --json number available --country US --region 646
```

## Environments

Switch via `CALL_SVC_ENV` environment variable (default: `prod`):

```bash
CALL_SVC_ENV=test flashclaw-cli-plugin-call-svc --json health
CALL_SVC_ENV=test flashclaw-cli-plugin-call-svc --json number available
```

## JSON mode

All commands support `--json` for structured agent output:

```bash
flashclaw-cli-plugin-call-svc --json number available --country US
flashclaw-cli-plugin-call-svc --json number buy --country US --region 646
```

## Command groups

- **auth** — API Key management (set-key, status, clear)
- **config** — Gateway base URL and timeout settings
- **number** — Phone number lifecycle (list, available, buy)
- **call** — Voice call operations
- **health** — Gateway connectivity check
