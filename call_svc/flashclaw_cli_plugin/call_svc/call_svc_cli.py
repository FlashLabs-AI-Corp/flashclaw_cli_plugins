"""CLI entry point for flashclaw-cli-plugin-call-svc.

Request chain:
  CLI --[X-API-Key: sk_xxx]-→ auth-gateway-svc --[Bearer+Company]-→ call-svc

Usage:
    flashclaw-cli-plugin-call-svc [--json] COMMAND [ARGS...]
    flashclaw-cli-plugin-call-svc          # no args → interactive REPL

Environment variables:
    CALL_SVC_ENV      Switch environment preset: prod (default) | test
    CALL_SVC_API_KEY  Override API Key at runtime (skip .env file)
    CALL_SVC_BASE_URL Override gateway base URL at runtime
"""

import json
import shlex
import sys

import click

from flashclaw_cli_plugin.call_svc.core.client import CallSvcClient
from flashclaw_cli_plugin.call_svc.core.session import (
    CALL_SVC_ENV,
    ENV_PRESETS,
    clear_api_key,
    get_api_key,
    get_base_url,
    load_config,
    save_config,
    set_api_key,
)
from flashclaw_cli_plugin.call_svc.utils.output import emit, emit_error, set_json_mode


def _build_client() -> CallSvcClient:
    return CallSvcClient(base_url=get_base_url(), api_key=get_api_key())


def _require_api_key() -> str:
    """Return API key or guide user to create one, then exit."""
    key = get_api_key()
    if key:
        return key
    if not key:
        click.echo()
        click.secho("⚠ API Key not configured", fg="yellow")
        click.echo("  Run: flashclaw-cli-plugin-call-svc auth set-key <your-api-key>")
        click.echo()
        click.echo("  Generate an API Key in the FlashRev console → Settings → Private Apps.")
        click.echo("  Key format starts with sk_, e.g.: sk_aBcDeFgH...")
        click.echo()
        sys.exit(1)


# ═══════════════════════════════════════════════════════════
# Root group
# ═══════════════════════════════════════════════════════════

@click.group(invoke_without_command=True)
@click.option("--json", "json_mode", is_flag=True, help="Output as JSON (agent-friendly).")
@click.version_option(package_name="flashclaw-cli-plugin-call-svc")
@click.pass_context
def cli(ctx, json_mode):
    """flashclaw-cli-plugin-call-svc — Agent-friendly CLI for call-svc (via auth-gateway-svc).

    \b
    Request chain:
      CLI --[X-API-Key]-→ auth-gateway-svc --[Bearer+Company]-→ call-svc

    \b
    Environments (set via CALL_SVC_ENV):
      prod  https://open-ai-api.flashlabs.ai      (default)
      test  https://open-ai-api-test.eape.mobi

    Run without arguments to enter the interactive REPL.
    """
    set_json_mode(json_mode)
    ctx.ensure_object(dict)
    if ctx.invoked_subcommand is None:
        ctx.invoke(repl)


# ═══════════════════════════════════════════════════════════
# repl — interactive session
# ═══════════════════════════════════════════════════════════

_REPL_HELP = {
    "auth set-key KEY":       "Save API Key",
    "auth status":            "Show API Key status",
    "auth clear":             "Remove API Key",
    "config show":            "Show configuration",
    "config set KEY VALUE":   "Set a config value",
    "number list":            "List purchased numbers",
    "number available":       "Query available numbers",
    "number buy":             "Purchase a number",
    "call voice":             "Initiate a voice call",
    "health":                 "Check gateway connectivity",
    "quit":                   "Exit the REPL",
}


@cli.command()
def repl():
    """Start an interactive REPL session."""
    from flashclaw_cli_plugin.call_svc.utils.repl_skin import ReplSkin

    skin = ReplSkin("call-svc", version="0.1.0")
    skin.print_banner()
    pt_session = skin.create_prompt_session()

    while True:
        try:
            line = skin.get_input(pt_session)
        except (EOFError, KeyboardInterrupt):
            skin.print_goodbye()
            break

        if not line:
            continue

        cmd_lower = line.lower().strip()
        if cmd_lower in ("quit", "exit", "q"):
            skin.print_goodbye()
            break

        if cmd_lower in ("help", "?", "h"):
            skin.help(_REPL_HELP)
            continue

        try:
            args = shlex.split(line)
            cli.main(args, standalone_mode=False, obj={})
        except SystemExit:
            pass
        except click.exceptions.UsageError as e:
            skin.error(str(e))
        except click.exceptions.Exit:
            pass
        except Exception as e:
            skin.error(str(e))


# ═══════════════════════════════════════════════════════════
# auth — API Key management
# ═══════════════════════════════════════════════════════════

@cli.group()
def auth():
    """Manage API Key for auth-gateway-svc authentication."""


@auth.command("set-key")
@click.argument("api_key")
def auth_set_key(api_key):
    """Save an API Key (sk_... format) to local credentials file.

    The key is stored in ~/.claude/skills/call-svc-assistant/.env with
    file permissions 600 (owner read/write only).

    \b
    Example:
      flashclaw-cli-plugin-call-svc auth set-key sk_aBcDeFgHiJkLmNoPqRsTuVwXyZ01234
    """
    if not api_key.startswith("sk_"):
        emit_error(
            "Invalid API Key format — must start with sk_",
            code="INVALID_KEY_FORMAT",
            details={"provided_prefix": api_key[:4]},
        )
    set_api_key(api_key)
    emit({"ok": True, "message": "API Key saved", "key_prefix": api_key[:10] + "****"})


@auth.command("status")
def auth_status():
    """Show current API Key configuration status."""
    key = get_api_key()
    env = CALL_SVC_ENV
    base_url = get_base_url()
    if key:
        emit({
            "configured": True,
            "key_prefix": key[:10] + "****",
            "env": env,
            "base_url": base_url,
        })
    else:
        emit({"configured": False, "message": "No API Key configured", "env": env})


@auth.command("clear")
def auth_clear():
    """Remove the saved API Key from credentials file."""
    clear_api_key()
    emit({"ok": True, "message": "API Key cleared"})


# ═══════════════════════════════════════════════════════════
# config — runtime configuration
# ═══════════════════════════════════════════════════════════

@cli.group()
def config():
    """Manage CLI configuration (base_url, timeout)."""


@config.command("show")
def config_show():
    """Show current configuration and active environment."""
    cfg = load_config()
    cfg["active_env"] = CALL_SVC_ENV
    cfg["base_url"] = get_base_url()
    api_key = get_api_key()
    cfg["api_key_configured"] = bool(api_key)
    if api_key:
        cfg["api_key_prefix"] = api_key[:10] + "****"
    emit(cfg)


@config.command("set")
@click.argument("key")
@click.argument("value")
def config_set(key, value):
    """Set a config value (base_url, timeout).

    \b
    Keys:
      base_url   Override the gateway base URL
      timeout    HTTP timeout in seconds (default 30)

    \b
    Examples:
      flashclaw-cli-plugin-call-svc config set base_url https://open-ai-api-test.eape.mobi
      flashclaw-cli-plugin-call-svc config set timeout 60
    """
    cfg = load_config()
    if key == "timeout":
        cfg[key] = int(value)
    else:
        cfg[key] = value
    save_config(cfg)
    emit({"ok": True, "key": key, "value": value})


# ═══════════════════════════════════════════════════════════
# number — phone number lifecycle management
# ═══════════════════════════════════════════════════════════

@cli.group()
def number():
    """Manage phone numbers (query, buy, list purchased)."""


@number.command("list")
def number_list():
    """List phone numbers already purchased by the current company.

    \b
    Examples:
      flashclaw-cli-plugin-call-svc number list
      flashclaw-cli-plugin-call-svc --json number list
    """
    _require_api_key()
    client = _build_client()
    try:
        result = client.purchased_numbers()
        emit(result)
    except Exception as e:
        emit_error(str(e), code="LIST_NUMBERS_FAILED")


@number.command("available")
@click.option("--country", "country_code", default="us", show_default=True,
              help="ISO 3166-1 alpha-2 country code, e.g. US, CA, GB.")
@click.option("--region", "region_code", default=None,
              help="Area code filter, e.g. 646. Omit for all regions.")
@click.option("--page", default=1, show_default=True, type=int,
              help="Page number (starts at 1).")
@click.option("--page-size", default=20, show_default=True, type=int,
              help="Results per page (max 100).")
def number_available(country_code, region_code, page, page_size):
    """Query phone numbers available for purchase.

    \b
    Examples:
      flashclaw-cli-plugin-call-svc number available
      flashclaw-cli-plugin-call-svc number available --country US --region 646
      flashclaw-cli-plugin-call-svc --json number available --country CA --page-size 10
    """
    _require_api_key()
    client = _build_client()
    try:
        result = client.available_numbers(
            country_code=country_code,
            region_code=region_code,
            page=page,
            page_size=page_size,
        )
        emit(result)
    except Exception as e:
        emit_error(str(e), code="AVAILABLE_NUMBERS_FAILED")


@number.command("buy")
@click.option("--country", "country_code", default="us", show_default=True,
              help="ISO 3166-1 alpha-2 country code.")
@click.option("--region", default=None,
              help="Area code preference, e.g. 646.")
@click.option("--msisdn", default=None,
              help="Specific E.164 number to purchase, e.g. +12125551234. "
                   "Omit to auto-assign.")
@click.option("--bundle-id", "bundle_id", default=None, type=int,
              help="Bundle regulatory record ID.")
@click.option("--address-id", "address_id", default=None, type=int,
              help="Address regulatory record ID.")
def number_buy(country_code, region, msisdn, bundle_id, address_id):
    """Purchase a phone number and bind it to the current company.

    \b
    buyStatus in response: 0=buying 1=success 2=failed 3=unknown

    \b
    Examples:
      flashclaw-cli-plugin-call-svc number buy --country US
      flashclaw-cli-plugin-call-svc number buy --country US --region 646
      flashclaw-cli-plugin-call-svc --json number buy --msisdn +12125551234
    """
    _require_api_key()
    client = _build_client()
    payload = {"countryCode": country_code}
    if region:
        payload["region"] = region
    if msisdn:
        payload["msisdn"] = msisdn
    if bundle_id is not None:
        payload["twilioBundleId"] = bundle_id
    if address_id is not None:
        payload["twilioAddressId"] = address_id

    try:
        result = client.buy_number(payload)
        emit(result)
    except Exception as e:
        emit_error(str(e), code="BUY_NUMBER_FAILED")


# ═══════════════════════════════════════════════════════════
# call — voice call operations
# ═══════════════════════════════════════════════════════════

@cli.group()
def call():
    """Voice call operations."""


@call.command("voice")
@click.option("--from", "from_number", required=True,
              help="Caller E.164 number, e.g. +12125551234.")
@click.option("--to", "to_number", required=True,
              help="Callee E.164 number, e.g. +8613800138000.")
@click.option("--voice-url", default=None,
              help="Audio file URL (required when speak-type is STREAM).")
@click.option("--speak-type", default=None, type=click.Choice(["STREAM", "TTS"]),
              help="Voice delivery type: STREAM uses voiceUrl, TTS uses --tts.")
@click.option("--tts", "tts_json", default=None,
              help='TTS config as JSON, e.g. \'{"language":"en-US","style":0,"text":"Hello"}\'')
@click.option("--record/--no-record", default=False,
              help="Whether to record the call.")
@click.option("--contact-id", type=int, default=None,
              help="CRM contact ID.")
@click.option("--business-id", default=None,
              help="Business / sequence ID.")
def call_voice(from_number, to_number, voice_url, speak_type, tts_json,
               record, contact_id, business_id):
    """Initiate a voice call (legacy shim, returns true as a placeholder).

    \b
    Examples:
      flashclaw-cli-plugin-call-svc call voice --from +12125551234 --to +8613800138000
      flashclaw-cli-plugin-call-svc --json call voice --from +1111 --to +2222 \\
          --speak-type TTS --tts '{"language":"en-US","style":0,"text":"Hi there"}'
    """
    _require_api_key()
    client = _build_client()
    payload = {
        "fromNumber": from_number,
        "toNumber": to_number,
    }
    if voice_url:
        payload["voiceUrl"] = voice_url
    if speak_type:
        payload["speakType"] = speak_type
    if tts_json:
        try:
            payload["tts"] = json.loads(tts_json)
        except json.JSONDecodeError:
            emit_error("Invalid JSON in --tts", code="INVALID_JSON")
    if record:
        payload["recordVoice"] = record
    if contact_id is not None:
        payload["contactId"] = contact_id
    if business_id:
        payload["businessId"] = business_id

    try:
        result = client.voice_call(payload)
        emit(result)
    except Exception as e:
        emit_error(str(e), code="VOICE_CALL_FAILED")


# ═══════════════════════════════════════════════════════════
# health — quick connectivity check
# ═══════════════════════════════════════════════════════════

@cli.command()
def health():
    """Check connectivity to auth-gateway-svc.

    Performs a lightweight GET to the gateway base URL to verify reachability.
    Does NOT require an API Key.
    """
    import requests as req

    url = get_base_url()
    try:
        r = req.get(url, timeout=5)
        emit({"ok": True, "base_url": url, "status_code": r.status_code})
    except Exception as e:
        emit({"ok": False, "base_url": url, "error": str(e)})


def main():
    cli()


if __name__ == "__main__":
    main()
