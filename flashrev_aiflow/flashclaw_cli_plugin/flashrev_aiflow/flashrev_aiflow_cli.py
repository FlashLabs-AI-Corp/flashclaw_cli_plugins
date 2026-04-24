"""CLI entry point for flashclaw-cli-plugin-flashrev-aiflow.

Request chain:
  CLI --[X-API-Key: sk_xxx]-> auth-gateway-svc --[Bearer+X-Auth-Company]-> FlashRev upstream

Usage:
    flashclaw-cli-plugin-flashrev-aiflow [--json] COMMAND [ARGS...]

Environment variables:
    FLASHREV_AIFLOW_ENV       Switch environment preset: prod (default) | test
    FLASHREV_SVC_API_KEY      Override API Key at runtime (skip .env file).
                              Shared across all FlashRev skills that route
                              through the same auth-gateway-svc.
    FLASHREV_AIFLOW_BASE_URL  Override gateway base URL at runtime
"""

import json
import sys

import click

from flashclaw_cli_plugin.flashrev_aiflow.core.client import FlashrevAiflowClient
from flashclaw_cli_plugin.flashrev_aiflow.core.session import (
    FLASHREV_AIFLOW_ENV,
    clear_api_key,
    get_api_key,
    get_base_url,
    get_discover_prefix,
    get_engage_prefix,
    get_mailsvc_prefix,
    get_meeting_prefix,  # noqa: F401  — formatter keeps stripping this; pinned.
    load_config,
    save_config,
    set_api_key,
    unset_config_value,
)
from flashclaw_cli_plugin.flashrev_aiflow.utils.output import (
    emit,
    emit_error,
    set_json_mode,
)

def _build_client() -> FlashrevAiflowClient:
    return FlashrevAiflowClient(base_url=get_base_url(), api_key=get_api_key())


def _require_api_key():
    """Exit with a helpful message if no API key is configured."""
    key = get_api_key()
    if key:
        return key
    click.echo()
    click.secho("API Key not configured", fg="yellow")
    click.echo("  Create or copy a key at: https://info.flashlabs.ai/settings/privateApps")
    click.echo("  Then bind it locally:")
    click.echo("    flashclaw-cli-plugin-flashrev-aiflow auth login --token sk_xxx")
    click.echo()
    click.echo("  Key format starts with 'sk_', e.g. sk_aBcDeFgH...")
    click.echo()
    sys.exit(1)


def _safe_call(fn, *, code: str):
    """Run a client call and translate any exception into a structured error."""
    try:
        return fn()
    except Exception as e:  # noqa: BLE001
        emit_error(str(e), code=code)


def _check_token_balance(client, required: int = None, force: bool = False):
    """Pre-flight token check before actions that will consume tokens.

    Matches PRD section 6.3: if `tokenRemaining < required` (or <= 0 when
    `required` is None), exit with code 2. `--force` bypasses the CLI-side
    check (the backend gateway is still free to refuse).

    If the /me call itself fails (network/gateway error), emit a warning and
    proceed — we don't want a flaky /me endpoint to block every launch.
    """
    if force:
        return
    try:
        bal = client.get_token_balance()
    except Exception as e:  # noqa: BLE001
        click.echo(
            f"Warning: token balance check skipped ({e})", err=True
        )
        return
    if required is not None and bal["tokenRemaining"] < required:
        emit_error(
            f"Insufficient tokens: need {required}, "
            f"have {bal['tokenRemaining']:.0f}. "
            "Top up at https://info.flashlabs.ai/settings/credit "
            "or pass --force to bypass this CLI-side check.",
            code="TOKEN_INSUFFICIENT",
            details=bal,
        )
    if required is None and not bal["sufficient"]:
        emit_error(
            "Token balance exhausted (remaining <= 0). "
            "Top up at https://info.flashlabs.ai/settings/credit "
            "or pass --force to bypass this CLI-side check.",
            code="TOKEN_EXHAUSTED",
            details=bal,
        )


# ═══════════════════════════════════════════════════════════
# Root group
# ═══════════════════════════════════════════════════════════

@click.group(invoke_without_command=True)
@click.option("--json", "json_mode", is_flag=True, help="Output as JSON (agent-friendly).")
@click.version_option(package_name="flashclaw-cli-plugin-flashrev-aiflow")
@click.pass_context
def cli(ctx, json_mode):
    """flashclaw-cli-plugin-flashrev-aiflow — Agent-friendly CLI for FlashRev AIFlow.

    \b
    Request chain:
      CLI --[X-API-Key]-> auth-gateway-svc --[Bearer+Company]-> FlashRev upstream

    \b
    Environments (set via FLASHREV_AIFLOW_ENV):
      prod  https://open-ai-api.flashlabs.ai      (default)
      test  https://open-ai-api-test.eape.mobi
    """
    set_json_mode(json_mode)
    ctx.ensure_object(dict)
    if ctx.invoked_subcommand is None:
        _print_welcome_banner_if_unconfigured()
        click.echo(ctx.get_help())


def _print_welcome_banner_if_unconfigured():
    """First-run onboarding.

    When a user runs the bare ``flashclaw-cli-plugin-flashrev-aiflow``
    command (no subcommand) right after `pipx install ...` and has not
    yet bound an API key, print a concise "installed successfully —
    here's how to set up" banner that points at
    https://info.flashlabs.ai/settings/privateApps. Silenced as soon as
    a key is present so returning users only see the normal --help.
    """
    if get_api_key():
        return
    click.echo()
    click.secho(
        "flashclaw-cli-plugin-flashrev-aiflow installed successfully.",
        fg="green", bold=True,
    )
    click.echo()
    click.echo("Get started (3 steps):")
    click.echo(
        "  1. Open https://info.flashlabs.ai/settings/privateApps and "
        "create / copy an API key (starts with 'sk_')."
    )
    click.echo("  2. Bind it locally:")
    click.echo(
        "       flashclaw-cli-plugin-flashrev-aiflow auth login "
        "--token sk_xxx"
    )
    click.echo("  3. Verify:")
    click.echo("       flashclaw-cli-plugin-flashrev-aiflow auth whoami")
    click.echo()
    click.echo("Full command list below:")
    click.echo()


# ═══════════════════════════════════════════════════════════
# auth — API Key management
# ═══════════════════════════════════════════════════════════

@cli.group()
def auth():
    """Manage API Key for auth-gateway-svc authentication."""


@auth.command("login")
@click.option("--token", "token", default=None,
              help="API Key (sk_... format). If omitted, you will be prompted.")
def auth_login(token):
    """Save an API Key (sk_... format) to local credentials file.

    The key is stored at ~/.claude/skills/flashrev-aiflow-assistant/.env
    with file permissions 600 (POSIX). FLASHREV_SVC_API_KEY is shared with
    other FlashRev skills that go through the same auth-gateway-svc.

    \b
    Examples:
      flashclaw-cli-plugin-flashrev-aiflow auth login --token sk_aBcDeFgH...
      flashclaw-cli-plugin-flashrev-aiflow auth login
    """
    if not token:
        token = click.prompt("API Key", hide_input=True)
    if not token.startswith("sk_"):
        emit_error(
            "Invalid API Key format — must start with sk_",
            code="INVALID_KEY_FORMAT",
            details={"provided_prefix": token[:4]},
        )
    set_api_key(token)
    emit({"ok": True, "message": "API Key saved", "key_prefix": token[:10] + "****"})


@auth.command("logout")
def auth_logout():
    """Remove the saved API Key from credentials file."""
    clear_api_key()
    emit({"ok": True, "message": "API Key cleared"})


@auth.command("whoami")
def auth_whoami():
    """Validate API Key and show current account info (via GET /api/v2/oauth/me)."""
    _require_api_key()
    client = _build_client()
    result = _safe_call(lambda: client.get_user_info(), code="WHOAMI_FAILED")
    emit(result)


@auth.command("status")
def auth_status():
    """Show local API Key + gateway configuration without calling the network."""
    key = get_api_key()
    payload = {
        "configured": bool(key),
        "env": FLASHREV_AIFLOW_ENV,
        "base_url": get_base_url(),
        "discover_prefix": get_discover_prefix(),
        "engage_prefix": get_engage_prefix(),
        "mailsvc_prefix": get_mailsvc_prefix(),
        "meeting_prefix": get_meeting_prefix(),
    }
    if key:
        payload["key_prefix"] = key[:10] + "****"
    emit(payload)


# ═══════════════════════════════════════════════════════════
# config — runtime configuration
# ═══════════════════════════════════════════════════════════

@cli.group()
def config():
    """Manage CLI configuration (base_url, timeout, gateway prefixes)."""


@config.command("show")
def config_show():
    """Show current configuration and active environment."""
    cfg = load_config()
    cfg["active_env"] = FLASHREV_AIFLOW_ENV
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
    """Set a config value.

    \b
    Keys:
      base_url           Gateway base URL
      timeout            HTTP timeout seconds (int, default 300)
      discover_prefix    Gateway route prefix for discover-api (default /flashrev)
      engage_prefix      Gateway route prefix for engage-api  (default '')
      mailsvc_prefix     Gateway route prefix for mailsvc     (default '')
      meeting_prefix     Gateway route prefix for meeting-svc (default /meeting)

    \b
    Examples:
      flashclaw-cli-plugin-flashrev-aiflow config set base_url https://open-ai-api-test.eape.mobi
      flashclaw-cli-plugin-flashrev-aiflow config set timeout 60
      flashclaw-cli-plugin-flashrev-aiflow config set discover_prefix /flashrev
    """
    cfg = load_config()
    if key == "timeout":
        cfg[key] = int(value)
    else:
        cfg[key] = value
    save_config(cfg)
    emit({"ok": True, "key": key, "value": value})


@config.command("unset")
@click.argument("key")
def config_unset(key):
    """Remove a config value (revert to default on next read)."""
    unset_config_value(key)
    emit({"ok": True, "key": key, "cleared": True})


# ═══════════════════════════════════════════════════════════
# aiflow — AIFlow lifecycle
# ═══════════════════════════════════════════════════════════

@cli.group()
def aiflow():
    """Manage AIFlows (list, show, start/pause/resume, delete)."""


@aiflow.command("list")
@click.option("--type", "flow_type", default="All", show_default=True,
              help="Workflow type filter (default All).")
@click.option("--view", "view_type", default="person", show_default=True,
              help="View type (default person).")
def aiflow_list(flow_type, view_type):
    """List AIFlows (POST /api/v1/ai/workflow/type/rows)."""
    _require_api_key()
    client = _build_client()
    params = {"type": flow_type, "viewType": view_type}
    result = _safe_call(lambda: client.list_aiflows(params), code="AIFLOW_LIST_FAILED")
    emit(result)


@aiflow.command("show")
@click.argument("flow_id")
def aiflow_show(flow_id):
    """Show AIFlow detail nodes (GET /api/v1/ai/workflow/detail/nodes/{id})."""
    _require_api_key()
    client = _build_client()
    result = _safe_call(lambda: client.get_aiflow(flow_id), code="AIFLOW_SHOW_FAILED")
    emit(result)


@aiflow.command("start")
@click.argument("flow_id")
@click.option("--status", "status_value", default="ACTIVE", show_default=True,
              help="Status value sent to POST /status. "
                   "Frontend uses ACTIVE for start/resume, PAUSED for pause.")
@click.option("--required-tokens", type=int, default=None,
              help="Required token budget; exit 2 if balance is below this.")
@click.option("--force", is_flag=True,
              help="Skip CLI-side token balance check "
                   "(backend / gateway enforcement still applies).")
def aiflow_start(flow_id, status_value, required_tokens, force):
    """Start / resume an already-launched AIFlow.

    Calls: POST /api/v1/ai/workflow/status  body: {id, status: "ACTIVE"}

    For the initial DRAFT -> ACTIVE transition, use `aiflow create --launch`
    which goes through save/setting instead.

    Token pre-check: reads data.limit.{tokenTotal,tokenCost} from
    GET /api/v2/oauth/me and blocks if the balance is exhausted (or below
    --required-tokens when supplied). Use --force to bypass.
    """
    _require_api_key()
    client = _build_client()
    _check_token_balance(client, required=required_tokens, force=force)
    result = _safe_call(
        lambda: client.set_aiflow_status(flow_id, status_value),
        code="AIFLOW_START_FAILED",
    )
    emit(result)


@aiflow.command("pause")
@click.argument("flow_id")
@click.option("--status", "status_value", default="PAUSED", show_default=True,
              help="Status value sent to POST /status.")
def aiflow_pause(flow_id, status_value):
    """Pause an AIFlow.

    Calls: POST /api/v1/ai/workflow/status  body: {id, status: "PAUSED"}
    """
    _require_api_key()
    client = _build_client()
    result = _safe_call(
        lambda: client.set_aiflow_status(flow_id, status_value),
        code="AIFLOW_PAUSE_FAILED",
    )
    emit(result)


@aiflow.command("resume")
@click.argument("flow_id")
@click.option("--status", "status_value", default="ACTIVE", show_default=True,
              help="Status value sent to POST /status.")
@click.option("--required-tokens", type=int, default=None,
              help="Required token budget; exit 2 if balance is below this.")
@click.option("--force", is_flag=True,
              help="Skip CLI-side token balance check.")
def aiflow_resume(flow_id, status_value, required_tokens, force):
    """Resume a paused AIFlow.

    Calls: POST /api/v1/ai/workflow/status  body: {id, status: "ACTIVE"}
    Token pre-check applies (same contract as `aiflow start`).
    """
    _require_api_key()
    client = _build_client()
    _check_token_balance(client, required=required_tokens, force=force)
    result = _safe_call(
        lambda: client.set_aiflow_status(flow_id, status_value),
        code="AIFLOW_RESUME_FAILED",
    )
    emit(result)


@aiflow.command("delete")
@click.argument("flow_id")
@click.option("-y", "--yes", is_flag=True, help="Skip confirmation prompt.")
def aiflow_delete(flow_id, yes):
    """Delete an AIFlow (POST /api/v1/ai/workflow/delete  body: {id})."""
    _require_api_key()
    if not yes:
        click.confirm(f"Delete AIFlow '{flow_id}'?", abort=True)
    client = _build_client()
    result = _safe_call(
        lambda: client.delete_aiflow(flow_id),
        code="AIFLOW_DELETE_FAILED",
    )
    emit(result)


@aiflow.command("rename")
@click.argument("flow_id")
@click.argument("new_name")
def aiflow_rename(flow_id, new_name):
    """Rename an AIFlow (POST /api/v1/ai/workflow/agent/update/name).

    The exact request body schema is not documented in the frontend project;
    the CLI currently sends {"id": flow_id, "name": new_name}. Override by
    calling the endpoint directly if the backend expects different keys.
    """
    _require_api_key()
    client = _build_client()
    payload = {"id": flow_id, "name": new_name}
    result = _safe_call(
        lambda: client.rename_aiflow(payload),
        code="AIFLOW_RENAME_FAILED",
    )
    emit(result)


@aiflow.command("pitch-show")
@click.argument("flow_id")
def aiflow_pitch_show(flow_id):
    """Show the pitch ICP snapshot saved for a given AIFlow.

    Calls: GET /api/v1/ai/workflow/get/pitch/{flowId}

    NOTE: the backend response is the ICP / targeting DTO (activeSignals,
    icpDescription, dataCount, ...), not a literal read-back of the 6
    sections that were submitted via /save/pitch. Use `aiflow setting show`
    or dig into the DB if you need the raw pitch text.
    """
    _require_api_key()
    client = _build_client()
    result = _safe_call(
        lambda: client.get_pitch(flow_id),
        code="AIFLOW_PITCH_FAILED",
    )
    emit(result)


@aiflow.command("test-connection")
@click.argument("url")
@click.option("--language", default="en-us", show_default=True,
              help="Language code to pass to the LLM pitch generator "
                   "(e.g. en-us, ja, fr). Stored on the flow for later "
                   "use; can be 'auto' to defer to per-contact detection.")
def aiflow_test_connection(url, language):
    """Probe a company website + get an AI-generated pitch preview.

    Calls: POST /api/v1/ai/workflow/test/connection (timeout 20s)

    The response is the exact DTO that `aiflow create` forwards into
    /save/pitch — use this command to preview what the LLM would generate
    from a URL before committing to a full create.
    """
    _require_api_key()
    client = _build_client()
    result = _safe_call(
        lambda: client.test_website_connection(url, language),
        code="AIFLOW_TEST_CONNECTION_FAILED",
    )
    emit(result)


@aiflow.command("draft")
def aiflow_draft():
    """Show the current user's most recent DRAFT AIFlow (read-only).

    Calls: GET /api/v1/ai/workflow/draft

    Intentionally read-only: the CLI does NOT support resuming a draft.
    Every `aiflow create` run builds a brand-new flow — this matches the
    PRD intent ("each run is new"). Use this command only to inspect
    what's sitting around in draft state (e.g. to decide whether to
    clean up via `aiflow delete <id>` before a fresh create).
    """
    _require_api_key()
    client = _build_client()
    result = _safe_call(
        lambda: client.get_draft_workflow(),
        code="AIFLOW_DRAFT_FAILED",
    )
    emit(result)


@aiflow.command("setting-show")
@click.argument("flow_id")
def aiflow_setting_show(flow_id):
    """Show the settings / AI-reply defaults for an AIFlow.

    Calls: GET /api/v1/ai/workflow/get/setting/{flowId}

    This is the source of truth for `save/setting`'s agentPromptList,
    emailTrack, enableAgentReply, agentStrategy defaults. Frontend reads
    the same endpoint on the settings page (settings.vue:485) and the
    AIFlow create wizard uses it in the launch branch.
    """
    _require_api_key()
    client = _build_client()
    result = _safe_call(
        lambda: client.get_setting(flow_id),
        code="AIFLOW_SETTING_SHOW_FAILED",
    )
    emit(result)


# ═══════════════════════════════════════════════════════════
# Post-create edits (update pitch / prompts / settings)
# ═══════════════════════════════════════════════════════════

@aiflow.command("pitch-update")
@click.argument("flow_id")
@click.option("--url", "url", required=True,
              help="Company website URL to regenerate the pitch from (LLM "
                   "runs on /test/connection, result is written to "
                   "/save/pitch for this FLOW_ID).")
@click.option("--language", default="en-us", show_default=True,
              help="Language code forwarded to /test/connection "
                   "(e.g. en-us, ja, fr). Pass 'auto' for per-contact "
                   "detection (sets useConfigLanguage=true).")
def aiflow_pitch_update(flow_id, url, language):
    """Regenerate + overwrite the pitch of an existing AIFlow.

    \b
    Pipeline:
      1. POST /api/v1/ai/workflow/test/connection {url, language}
         -> LLM-generated ICP DTO
      2. POST /api/v1/ai/workflow/save/pitch
         -> upsert t_ai_workflow_pitch WHERE workflowId = FLOW_ID

    This replaces whatever pitch was previously saved. Use it when the
    company URL changes, or when you want to force a new LLM generation
    pass for an existing flow.
    """
    from flashclaw_cli_plugin.flashrev_aiflow import wizard

    _require_api_key()
    client = _build_client()

    test_conn_lang = language if language != "auto" else "en-us"
    click.echo(
        f"  Regenerating pitch for flow {flow_id} via test/connection "
        f"(url={url}, language={test_conn_lang}) ..."
    )
    test_resp = _safe_call(
        lambda: client.test_website_connection(url, test_conn_lang),
        code="PITCH_GENERATION_FAILED",
    )
    pitch_data = (test_resp or {}).get("data") or {}
    if not pitch_data.get("officialDescription"):
        click.echo(
            "  ! test/connection returned no officialDescription — saving "
            "anyway (pitch fields may be mostly empty).",
            err=True,
        )

    save_body = wizard.build_save_pitch_body(
        flow_id, pitch_data, url, language,
    )
    save_resp = _safe_call(
        lambda: client.save_pitch(save_body),
        code="PITCH_SAVE_FAILED",
    )
    click.echo("  Pitch overwritten.")
    emit({
        "flowId": flow_id,
        "url": save_body.get("url"),
        "language": language,
        "useConfigLanguage": save_body.get("useConfigLanguage"),
        "officialDescription": (pitch_data.get("officialDescription") or "")[:160],
        "painPoints":    len(pitch_data.get("painPoints") or []),
        "solutions":     len(pitch_data.get("solutions") or []),
        "proofPoints":   len(pitch_data.get("proofPoints") or []),
        "callToActions": len(pitch_data.get("callToActions") or []),
        "leadMagnets":   len(pitch_data.get("leadMagnets") or []),
        "saveResponse":  save_resp,
    })


@aiflow.command("prompt-show")
@click.argument("flow_id")
@click.option("--step", "step_filter", type=int, default=None,
              help="Only show one step by 1-based index (default: all).")
@click.option("--full", is_flag=True,
              help="Print the full emailContent prompt template. Default "
                   "shows just the first 200 chars per step.")
def aiflow_prompt_show(flow_id, step_filter, full):
    """Show the saved email-prompt content for each step of an AIFlow.

    \b
    Per step, reads:
      - step / delayMinutes / workflowStepId       from /get/prompt
      - emailContent (LLM prompt template)         from /get/email/prompt
        (short-circuits to the saved row when workflowStepId is supplied)

    subject / content sample previews are NOT read back — the backend
    does not expose them on a stable endpoint and the ``/get/email``
    generator is 504-prone. If you need to inspect what was saved for
    those fields, dump the full /save/prompt body the wizard sent
    (--json mode) at create time.
    """
    _require_api_key()
    client = _build_client()

    raw = _safe_call(
        lambda: client.get_workflow_prompt(flow_id),
        code="PROMPT_SHOW_FAILED",
    )
    steps = _load_prompt_steps(raw)
    if step_filter is not None:
        steps = [s for s in steps if (s.get("step") or _step_index_of(s, steps)) == step_filter]
        if not steps:
            emit_error(
                f"--step {step_filter} out of range "
                f"(flow has {len(_load_prompt_steps(raw))} step(s))",
                code="PROMPT_STEP_OUT_OF_RANGE",
            )

    out = []
    import requests as _requests
    url = client._url_discover("/api/v1/ai/workflow/get/email/prompt")
    for i, s in enumerate(steps, 1):
        step_id = s.get("workflowStepId") or s.get("id")
        entry = {
            "step":           s.get("step") or i,
            "workflowStepId": step_id,
            "delayMinutes":   s.get("delayMinutes"),
        }
        # Fetch saved emailContent via short-circuit path (workflowStepId set).
        try:
            resp = _requests.post(
                url,
                json={"workflowId": flow_id, "workflowStepId": step_id,
                      "beforStep": []},
                headers=client._headers(),
                timeout=60,
            )
            from flashclaw_cli_plugin.flashrev_aiflow import wizard
            content = wizard._parse_sse_content(resp.text)
        except Exception as e:  # noqa: BLE001
            content = ""
            entry["error"] = str(e)
        entry["emailContentLength"] = len(content)
        entry["emailContent"] = content if full else content[:200] + (
            "..." if len(content) > 200 else ""
        )
        out.append(entry)
    emit(out)


def _load_prompt_steps(raw_response):
    from flashclaw_cli_plugin.flashrev_aiflow import wizard
    return wizard.extract_prompt_steps(raw_response)


def _step_index_of(step, steps):
    """Fallback step index for rows whose `step` field is null (the
    sequence_step response sometimes omits it; index by position)."""
    try:
        return steps.index(step) + 1
    except ValueError:
        return -1


@aiflow.command("prompt-update")
@click.argument("flow_id")
@click.option("--file", "prompt_file", required=True,
              help="JSON file containing a list of prompt objects. Shape: "
                   "[{step, delayMinutes, emailSubject, emailContent, "
                   "subject, content, workflowStepId?}, ...]. "
                   "Use `aiflow prompt-show --full` + redirect to JSON as a "
                   "starting point.")
def aiflow_prompt_update(flow_id, prompt_file):
    """Replace the full step list of an AIFlow with the content of FILE.

    \b
    Calls: POST /api/v1/ai/workflow/save/prompt with the loaded array.

    WARNING: this is a REPLACE operation. The backend deletes any existing
    step row whose workflowStepId is NOT in the uploaded list (see dubbo
    AiWorkFlowServiceImpl.savePrompt line ~1577-1586). To edit one step
    without losing the others, start from a `prompt-show --full` dump and
    modify the entry you care about before uploading.

    Each prompt object accepts:
      workflowStepId    optional  existing row id (pass to UPDATE in place;
                                  omit to INSERT a new row)
      step              required  1-based position
      stepType          optional  defaults to "Email"
      delayMinutes      required  minutes after prior step (e.g. 60 / 4320 / 10080)
      emailSubject      string    LLM prompt template for subject (usually "")
      emailContent      string    LLM prompt template for body (the critical one)
      subject           string    sample subject (empty on step 1/3 by convention)
      content           string    sample body
    """
    from pathlib import Path

    _require_api_key()
    client = _build_client()

    path = Path(prompt_file).expanduser()
    if not path.exists():
        emit_error(
            f"--file not found: {path}",
            code="PROMPT_FILE_NOT_FOUND",
        )
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        emit_error(
            f"--file is not valid JSON: {e}",
            code="PROMPT_FILE_INVALID_JSON",
        )

    if not isinstance(parsed, list) or not parsed:
        emit_error(
            "--file must be a non-empty JSON array of prompt objects",
            code="PROMPT_FILE_SHAPE_ERROR",
            details={"parsedType": type(parsed).__name__},
        )

    for i, p in enumerate(parsed, 1):
        if not isinstance(p, dict):
            emit_error(
                f"--file[{i}] is not an object",
                code="PROMPT_FILE_ENTRY_NOT_OBJECT",
            )
        if "delayMinutes" not in p or not isinstance(p["delayMinutes"], int):
            emit_error(
                f"--file[{i}] missing required int `delayMinutes`",
                code="PROMPT_FILE_MISSING_DELAY",
            )

    result = _safe_call(
        lambda: client.save_prompt(flow_id, parsed),
        code="PROMPT_SAVE_FAILED",
    )
    click.echo(
        f"  Saved {len(parsed)} step(s) via /save/prompt."
    )
    emit({
        "flowId": flow_id,
        "stepsSaved": len(parsed),
        "saveResponse": result,
    })


@aiflow.command("settings-update")
@click.argument("flow_id")
@click.option("--time-template-id", "time_template_id", type=int, default=None,
              help="Override timeTemplateId. The CLI fetches the matching "
                   "entry from /engage/api/v1/time/template/list and "
                   "embeds its timeBlocks / properties as timeTemplateConfig.")
@click.option("--mailboxes", "mailbox_mode", default=None,
              help="'all-active' or a comma-separated list of mailbox ids "
                   "to bind as sequenceMailboxList.")
@click.option("--auto-approve/--no-auto-approve", "auto_approve",
              default=None,
              help="Override autoApprove. Omitted flag = keep current value.")
@click.option("--enable-agent-reply/--no-enable-agent-reply",
              "enable_agent_reply", default=None,
              help="Override enableAgentReply. Omitted flag = keep current.")
@click.option("--agent-strategy", "agent_strategy", default=None,
              type=click.Choice(
                  ["Book Meeting", "Drive Traffic",
                   "Qualify Lead", "Custom Goal"],
                  case_sensitive=False),
              help="Override agentStrategy. Omitted flag = keep current.")
def aiflow_settings_update(
    flow_id, time_template_id, mailbox_mode, auto_approve,
    enable_agent_reply, agent_strategy,
):
    """Patch launch-time settings of an AIFlow (time template, mailboxes,
    auto-approve, AI-reply toggles).

    \b
    Pipeline:
      1. GET  /api/v1/ai/workflow/get/setting/{flowId}
         -> current agentPromptList / emailTrack / enableAgentReply / ...
      2. [--time-template-id] GET /engage/api/v1/time/template/list
         -> pick the matching template to rebuild timeTemplateConfig
      3. [--mailboxes] GET /mailsvc/mail-address/simple/v2/list
         -> filter to selected mailbox ids for sequenceMailboxList
      4. POST /api/v1/ai/workflow/save/setting
         -> persist the merged body

    Flags you omit preserve the current server-side value. agentPromptList
    and emailTrack always pass through unchanged (not editable via CLI).
    """
    from flashclaw_cli_plugin.flashrev_aiflow import wizard

    if all(v is None for v in (time_template_id, mailbox_mode, auto_approve,
                               enable_agent_reply, agent_strategy)):
        emit_error(
            "At least one of --time-template-id / --mailboxes / "
            "--auto-approve / --enable-agent-reply / --agent-strategy "
            "must be provided",
            code="USAGE_NO_SETTING_UPDATE",
        )

    _require_api_key()
    client = _build_client()

    # 1) Read current setting.
    setting_resp = _safe_call(
        lambda: client.get_setting(flow_id),
        code="AIFLOW_GET_SETTING_FAILED",
    )
    setting = (setting_resp or {}).get("data") or setting_resp or {}

    # 2) Resolve time template override OR reuse the existing one.
    #    /get/setting returns `properties` at the top level of `data` (only
    #    populated for flows with a sequenceId; DRAFT flows have none).
    existing_props = setting.get("properties") or {}
    if time_template_id is not None:
        templates_resp = _safe_call(
            lambda: client.list_time_templates(),
            code="TIME_TEMPLATE_LIST_FAILED",
        )
        items = (templates_resp or {}).get("data") or []
        match = next((t for t in items if t.get("id") == time_template_id), None)
        if match is None:
            emit_error(
                f"--time-template-id {time_template_id} not found "
                "in /engage/api/v1/time/template/list",
                code="TIME_TEMPLATE_NOT_FOUND",
                details={"availableIds": [t.get("id") for t in items]},
            )
        time_template = match
    else:
        # Keep whatever the server currently has — build_save_setting_body
        # will detect existing_props.timeTemplateConfig and reuse it.
        time_template = {}

    # 3) Resolve mailbox override OR reuse existing.
    if mailbox_mode is not None:
        mailboxes_resp = _safe_call(
            lambda: client.list_mailboxes(),
            code="MAILBOXES_LIST_FAILED",
        )
        active = wizard.filter_active_mailboxes(mailboxes_resp)
        if mailbox_mode == "all-active":
            sequence_list = [
                {"addressId": wizard.mailbox_id(mb)}
                for mb in active if wizard.mailbox_id(mb)
            ]
        else:
            wanted = {p.strip() for p in mailbox_mode.split(",") if p.strip()}
            sequence_list = [
                {"addressId": wizard.mailbox_id(mb)}
                for mb in active
                if str(wizard.mailbox_id(mb)) in wanted
                or wizard.mailbox_id(mb) in wanted
            ]
            if not sequence_list:
                emit_error(
                    "--mailboxes did not match any active mailbox.",
                    code="USAGE_MAILBOX_NO_MATCH",
                    details={
                        "requested": sorted(wanted),
                        "availableIds": [
                            wizard.mailbox_id(mb) for mb in active
                            if wizard.mailbox_id(mb)
                        ],
                    },
                )
    else:
        sequence_list = existing_props.get("sequenceMailboxList") or []

    # 4) autoApprove: flag wins, else keep current.
    effective_auto_approve = (
        auto_approve if auto_approve is not None
        else bool(setting.get("autoApprove"))
    )

    # 5) Auto-patch Book Meeting meetingRouteId when the flow has AI
    #    reply enabled but no router is bound yet (commonly the case for
    #    flows created with --no-launch where the create wizard skipped
    #    the meeting-list step). Mirrors the create wizard's launch
    #    branch — fetches the user's first personal meeting router.
    meeting_router_id = None
    if setting.get("isShowAiReply"):
        agent_prompt_list = setting.get("agentPromptList") or []
        bm = next(
            (e for e in agent_prompt_list
             if e.get("strategy") == "Book Meeting"),
            None,
        )
        if bm is not None and not bm.get("meetingRouteId"):
            meetings_resp = _safe_call(
                lambda: client.list_personal_meetings(),
                code="MEETING_LIST_FAILED",
            )
            meeting_router_id = wizard.pick_first_meeting_router_id(
                meetings_resp
            )

    # 6) Assemble body (reuses the same helper the create wizard uses).
    save_body = wizard.build_save_setting_body(
        flow_id,
        time_template,
        sequence_list,
        setting,
        effective_auto_approve,
        enable_agent_reply=enable_agent_reply,
        agent_strategy=agent_strategy,
        meeting_router_id=meeting_router_id,
    )

    result = _safe_call(
        lambda: client.save_setting(save_body),
        code="AIFLOW_SETTINGS_UPDATE_FAILED",
    )
    click.echo("  Settings updated.")
    emit({
        "flowId": flow_id,
        "timeTemplateId": save_body["properties"].get("timeTemplateId"),
        "sequenceMailboxCount": len(sequence_list),
        "autoApprove": save_body.get("autoApprove"),
        "enableAgentReply": save_body.get("enableAgentReply"),
        "agentStrategy": save_body.get("agentStrategy"),
        "saveResponse": result,
    })


@aiflow.command("create")
@click.option("--no-wizard", is_flag=True,
              help="Skip the interactive wizard; drive everything via flags. "
                   "All required fields must be supplied as flags.")
@click.option("--dry-run", is_flag=True,
              help="Validate inputs and probe read-only endpoints "
                   "(token balance + mailbox list + test/connection); "
                   "skip every write endpoint (upload / create/list / "
                   "save/pitch / get/prompt / save/prompt / save/setting). "
                   "No side effects on the backend.")
@click.option("--csv", "csv_path", default=None,
              help="Path to a local CSV file (email column required).")
@click.option("--sheet", "sheet_url", default=None,
              help="Public Google Sheet URL (shared as 'Anyone with the "
                   "link -> Viewer').")
@click.option("--url", "--website", "url",
              default=None,
              help="Company website URL. Required in --no-wizard mode. "
                   "Pitch content is LLM-generated by POST /test/connection "
                   "from this URL, then written to /save/pitch — there is no "
                   "local pitch.json input any more.")
@click.option("--language", default="en-us", show_default=True,
              help="Pitch language code forwarded to /test/connection "
                   "(e.g. en-us, ja, fr). Pass 'auto' to let the backend "
                   "infer language per contact (sets useConfigLanguage=true).")
@click.option("--country-column", "country_column", default=None,
              help="CSV column name carrying the contact country/region "
                   "(or 'none' to skip). Required in --no-wizard mode when "
                   "--language=auto.")
@click.option("--regenerate-emails/--no-regenerate-emails",
              "regenerate_emails", default=True, show_default=True,
              help="Run the per-step LLM pass (POST /get/email/prompt) to "
                   "fill in the emailContent prompt template for every step "
                   "before /save/prompt. Default ON — a flow launched with "
                   "empty prompt templates cannot produce emails at send "
                   "time, so the wizard always populates them unless you "
                   "explicitly pass --no-regenerate-emails (useful for "
                   "quick scaffolding + editing via prompt-update).")
@click.option("--mailboxes", "mailbox_mode", default="all-active",
              show_default=True,
              help="'all-active' to pick every active mailbox, or a comma-"
                   "separated list of mailbox ids.")
@click.option("--auto-approve/--no-auto-approve", "auto_approve",
              default=True, show_default=True,
              help="autoApprove flag sent to /save/setting on launch.")
@click.option("--enable-agent-reply/--no-enable-agent-reply",
              "enable_agent_reply", default=None,
              help="Override enableAgentReply in the /save/setting body. "
                   "Default: inherit whatever /get/setting returned.")
@click.option("--agent-strategy", "agent_strategy", default=None,
              type=click.Choice(
                  ["Book Meeting", "Drive Traffic",
                   "Qualify Lead", "Custom Goal"],
                  case_sensitive=False),
              help="Override agentStrategy in the /save/setting body. "
                   "Default: inherit whatever /get/setting returned.")
@click.option("--launch/--no-launch", "launch_now", default=None,
              help="Launch the AIFlow after save. In --no-wizard mode, "
                   "defaults to --no-launch (save as draft) unless --launch "
                   "is passed. Launch is blocked when any step's emailContent "
                   "is empty (see --regenerate-emails, default on).")
@click.option("-y", "--yes", is_flag=True,
              help="Skip the final confirmation prompt.")
@click.option("--force", is_flag=True,
              help="Skip CLI-side token balance check before launch.")
def aiflow_create(
    no_wizard, dry_run, csv_path, sheet_url, url, language,
    country_column, regenerate_emails, mailbox_mode, auto_approve,
    enable_agent_reply, agent_strategy, launch_now, yes, force,
):
    """Create a **new** AIFlow (Strategy -> AIFlow -> Settings -> Launch).

    \b
    Pipeline (all via auth-gateway-svc):
      1. POST {discover}/contacts/upload       -> {listId, listName}
      2. POST {discover}/create/list           -> {flowId}   (NEW flow)
      3. POST {discover}/test/connection       -> LLM-generated pitch DTO
      4. POST {discover}/save/pitch            -> persist pitch
      5. POST {discover}/get/prompt            -> ensure 3 default step rows
                                                  (seed via /save/prompt if none)
      6. POST {discover}/get/email/prompt      per-step, with beforStep ctx
                                                  (default on; fills
                                                  emailContent prompt template
                                                  so the scheduler can
                                                  generate emails at send time)
      7. POST {discover}/save/prompt           -> persist step prompts
      8. [--launch]
         GET  {discover}/get/setting/{flowId}  -> agentPromptList/emailTrack defaults
         GET  {engage}/api/v1/time/template/list
                                                -> pick timeTemplateConfig
         POST {meeting}/api/v1/meeting/personal/list
                                                -> first id -> Book Meeting
         POST {discover}/save/setting          -> persist settings + DRAFT -> ACTIVE

    **Every run creates a brand-new flow** — there is no resume mode. If
    you already have a DRAFT you want to throw away, delete it first:
        aiflow draft        # inspect
        aiflow delete <id>  # clean up
    """
    _require_api_key()
    client = _build_client()
    _run_create_wizard(
        client,
        csv_path=csv_path,
        sheet_url=sheet_url,
        url=url,
        language=language,
        country_column=country_column,
        regenerate_emails=regenerate_emails,
        mailbox_mode=mailbox_mode,
        auto_approve=auto_approve,
        enable_agent_reply=enable_agent_reply,
        agent_strategy=agent_strategy,
        launch_now=launch_now,
        yes=yes,
        force=force,
        interactive=not no_wizard,
        dry_run=dry_run,
    )


def _run_create_wizard(
    client,
    *,
    csv_path=None,
    sheet_url=None,
    url=None,
    language="en-us",
    country_column=None,
    regenerate_emails=True,
    mailbox_mode="all-active",
    auto_approve=True,
    enable_agent_reply=None,
    agent_strategy=None,
    launch_now=None,
    yes=False,
    force=False,
    interactive=True,
    dry_run=False,
):
    """Drive the V2 create pipeline (see aiflow_create docstring).

    interactive=True : prompt for missing fields (wizard mode).
    interactive=False: raise USAGE_* errors for missing fields (--no-wizard).
    dry_run=True     : run only local validation + read-only probes.
    regenerate_emails=True (default): run per-step /get/email/prompt so each
                            step lands with a non-empty emailContent prompt
                            template — required for the scheduler to actually
                            produce emails at send time. Pass False only for
                            scaffolding runs where prompt-update will fill
                            the content in before launch.
    """
    from flashclaw_cli_plugin.flashrev_aiflow import wizard

    header = "Dry-run " if dry_run else ""
    click.secho(
        f"{header}Creating a NEW AIFlow (existing drafts are not reused).",
        fg="yellow",
    )

    # ── Pre-flight checks (non-interactive mode) ───────────────────
    if not interactive:
        if bool(csv_path) == bool(sheet_url):
            emit_error(
                "--no-wizard requires exactly one of --csv or --sheet",
                code="USAGE_CONTACT_SOURCE",
            )
        if not url:
            emit_error(
                "--no-wizard requires --url (company website URL; pitch "
                "content is LLM-generated from it)",
                code="USAGE_URL_REQUIRED",
            )
    # Even in wizard mode, simultaneous csv+sheet is a conflict.
    if csv_path and sheet_url:
        emit_error(
            "Specify only one of --csv or --sheet",
            code="USAGE_CONTACT_SOURCE_CONFLICT",
        )

    click.echo()
    click.secho(f"{header}Step 1 / 3 - Strategy", fg="cyan", bold=True)

    # ── 1a. Contact source ──────────────────────────────────
    if not (csv_path or sheet_url):
        # interactive-only path; non-interactive errors out above.
        source_choice = click.prompt(
            "  Contact source: [c]sv file / [s]heet url", default="c",
            show_default=True,
        ).strip().lower()
        if source_choice.startswith("s"):
            sheet_url = click.prompt("  Google Sheet URL")
        else:
            csv_path = click.prompt("  CSV path")

    local_csv = _safe_call(
        lambda: wizard.load_contacts_source(
            csv_path=csv_path, sheet_url=sheet_url,
        ),
        code="CONTACT_SOURCE_FAILED",
    )
    columns, preview_rows, total, unique_emails = _safe_call(
        lambda: wizard.preview_csv(local_csv),
        code="CSV_VALIDATION_FAILED",
    )
    click.echo(
        f"  Loaded {total} rows / {unique_emails} unique emails "
        f"from {local_csv.name}"
    )
    click.echo(f"  Columns: {columns}")
    click.echo("  Preview (first rows):")
    for row in preview_rows:
        click.echo(f"    {row}")

    # ── 1b. Country column (only when language=auto) ────────
    country_col = None
    if language == "auto":
        if country_column:
            if country_column.lower() == "none":
                country_col = None
                click.echo(
                    "  Country column: skipped "
                    "(--country-column=none; language fallback to CLI session)"
                )
            elif country_column in columns:
                country_col = country_column
                click.echo(f"  Country column: {country_col}")
            else:
                emit_error(
                    f"--country-column '{country_column}' not found in CSV. "
                    f"Available columns: {columns}",
                    code="USAGE_COUNTRY_COLUMN_NOT_FOUND",
                    details={"columns": columns},
                )
        elif interactive:
            click.echo()
            click.echo("  Language is 'auto' - picking a country/region column:")
            country_col = wizard.confirm_country_column(columns, preview_rows)
            if country_col:
                click.echo(f"  Country column: {country_col}")
            else:
                click.echo(
                    "  No country column chosen - language will fall back to "
                    "CLI session default."
                )
        else:
            emit_error(
                "--country-column is required when --language=auto in "
                "--no-wizard mode. Use 'none' to explicitly skip.",
                code="USAGE_COUNTRY_COLUMN_MISSING",
            )

    # ── 1c. URL (prompt for it in wizard mode) ──────────────
    if not url:
        if interactive:
            url = click.prompt(
                "  Company website URL (with or without https://)"
            ).strip()
        # non-interactive already errored out above

    website_normalised = url if url.startswith("http") else (
        "https://" + url.lstrip("/")
    )

    # ── 1d. Upload + create NEW AIFlow ──────────────────────
    if dry_run:
        click.echo()
        click.echo(f"  [dry-run] would upload CSV: {local_csv.name}")
        click.echo("  [dry-run] would POST /api/v1/ai/workflow/create/list")
        list_id = "<dry-run>"
        list_name = local_csv.name
        flow_id = "<dry-run>"
    else:
        click.echo()
        click.echo("  Uploading CSV ...")
        upload = _safe_call(
            lambda: client.upload_contacts_csv(str(local_csv)),
            code="CONTACTS_UPLOAD_FAILED",
        )
        up_data = (upload or {}).get("data") or {}
        list_id = up_data.get("listId")
        list_name = up_data.get("listName") or local_csv.name
        if not list_id:
            emit_error(
                "Contacts upload did not return a listId",
                code="CONTACTS_UPLOAD_NO_LIST_ID",
                details=upload,
            )
        click.echo(f"  listId  : {list_id}")
        click.echo(f"  listName: {list_name}")

        create = _safe_call(
            lambda: client.create_aiflow_from_list({
                "listId": list_id,
                "listName": list_name,
                "type": "csv",
                "source": "csv",
            }),
            code="AIFLOW_CREATE_FAILED",
        )
        create_data = (create or {}).get("data") or {}
        flow_id = create_data.get("id") or create_data.get("flowId")
        if not flow_id:
            emit_error(
                "create/list did not return an AIFlow id",
                code="AIFLOW_CREATE_NO_ID",
                details=create,
            )
        click.echo(f"  flowId  : {flow_id}  (new)")

    # ── 1e. LLM-generate pitch via test/connection ──────────
    test_conn_lang = language if language != "auto" else "en-us"
    if dry_run:
        click.echo(
            "  [dry-run] would POST /api/v1/ai/workflow/test/connection "
            f"(url={website_normalised}, language={test_conn_lang})"
        )
        pitch_data = {}
    else:
        click.echo("  Generating pitch via test/connection ...")
        test_resp = _safe_call(
            lambda: client.test_website_connection(
                website_normalised, test_conn_lang
            ),
            code="PITCH_GENERATION_FAILED",
        )
        pitch_data = (test_resp or {}).get("data") or {}
        if not pitch_data.get("officialDescription"):
            click.echo(
                "  ! test/connection returned no officialDescription — the "
                "pitch will be mostly empty. Check the URL.",
                err=True,
            )
        else:
            click.echo(
                f"  Pitch generated "
                f"(officialDescription: {pitch_data['officialDescription'][:60]}...)"
            )

    # ── 1f. Save pitch ──────────────────────────────────────
    save_pitch_body = wizard.build_save_pitch_body(
        flow_id, pitch_data, website_normalised, language,
    )
    if dry_run:
        click.echo("  [dry-run] would POST /api/v1/ai/workflow/save/pitch")
    else:
        _safe_call(
            lambda: client.save_pitch(save_pitch_body),
            code="PITCH_SAVE_FAILED",
        )
        click.echo("  Pitch saved.")

    # ── 1g. Ensure step rows exist in t_ai_workflow_prompt ─────
    # The backend's /get/prompt seeds default step rows on first call for
    # some flow types but returns [] for others (e.g. ENROLL). The frontend
    # handles this by defaulting to a 3-step pipeline in the UI; the CLI
    # mirrors that by calling /save/prompt with 3 skeleton rows when the
    # initial /get/prompt is empty. At least one step is required for the
    # scheduler to have anything to send.
    if dry_run:
        click.echo(
            "  [dry-run] would POST /api/v1/ai/workflow/get/prompt "
            "(check for existing steps)"
        )
        click.echo(
            "  [dry-run] would seed 3 default step rows via /save/prompt "
            "(1h / 3d / 7d delays) if /get/prompt returns empty"
        )
        prompt_steps = []
    else:
        prompt_resp = _safe_call(
            lambda: client.get_workflow_prompt(flow_id),
            code="WORKFLOW_PROMPT_INIT_FAILED",
        )
        prompt_steps = wizard.extract_prompt_steps(prompt_resp)
        if not prompt_steps:
            click.echo(
                "  /get/prompt returned no steps — seeding 3 default rows "
                "(1h / 3d / 7d) so the flow has a pipeline to launch against."
            )
            prompt_steps = _safe_call(
                lambda: wizard.seed_default_steps(client, flow_id),
                code="WORKFLOW_PROMPT_SEED_FAILED",
            )
        click.echo(
            f"  Steps in t_ai_workflow_prompt: {len(prompt_steps)}"
        )

    # ── 2. Prompts — LLM regenerate (default on), then save/prompt ──
    click.echo()
    click.secho(f"{header}Step 2 / 3 - Prompts", fg="cyan", bold=True)
    if regenerate_emails:
        if dry_run:
            click.echo(
                "  [dry-run] would iterate /get/email/prompt per step "
                "(SSE-parsed into emailContent prompt template)"
            )
        else:
            click.echo(
                f"  Generating email prompt templates for "
                f"{len(prompt_steps)} step(s) via /get/email/prompt (LLM) ..."
            )
            prompt_steps = wizard.regenerate_step_content(
                client, flow_id, prompt_steps,
            )
    else:
        click.secho(
            "  --no-regenerate-emails: step rows will be saved with EMPTY "
            "emailContent. The flow will be unable to produce emails at send "
            "time until you populate each step via `aiflow prompt-update "
            "FLOW_ID --file ...`.",
            fg="yellow",
        )

    incomplete = wizard.count_incomplete_prompts(prompt_steps)
    click.echo(
        f"  Step completeness  : "
        f"{len(prompt_steps) - incomplete}/{len(prompt_steps)} ready"
    )

    if not dry_run and prompt_steps:
        save_prompt_body = _safe_call(
            lambda: wizard.build_save_prompt_body(flow_id, prompt_steps),
            code="PROMPT_BODY_BUILD_FAILED",
        )
        _safe_call(
            lambda: client.save_prompt(flow_id, save_prompt_body["prompts"]),
            code="PROMPT_SAVE_FAILED",
        )
        click.echo("  Prompts persisted via /save/prompt.")
    elif dry_run:
        click.echo("  [dry-run] would POST /api/v1/ai/workflow/save/prompt")

    # ── 3. Settings ─────────────────────────────────────────
    click.echo()
    click.secho(f"{header}Step 3 / 3 - Settings", fg="cyan", bold=True)
    click.echo("  Automated Approval : " + ("ON" if auto_approve else "OFF"))

    # Pick mailboxes — read-only probe works in both modes.
    mailboxes_resp = _safe_call(
        lambda: client.list_mailboxes(),
        code="MAILBOXES_LIST_FAILED",
    )
    active = wizard.filter_active_mailboxes(mailboxes_resp)
    if mailbox_mode == "all-active":
        sequence_list = [
            {"addressId": wizard.mailbox_id(mb)}
            for mb in active if wizard.mailbox_id(mb)
        ]
        click.echo(f"  Mailboxes selected : {len(sequence_list)} (all active)")
    else:
        wanted = {p.strip() for p in mailbox_mode.split(",") if p.strip()}
        sequence_list = [
            {"addressId": wizard.mailbox_id(mb)}
            for mb in active
            if wizard.mailbox_id(mb) in wanted
        ]
        if not sequence_list:
            if interactive:
                click.echo(
                    "  No mailbox matched the --mailboxes filter; picking "
                    "interactively:"
                )
                sequence_list = wizard.select_mailboxes_interactively(active)
            else:
                emit_error(
                    "--mailboxes did not match any active mailbox.",
                    code="USAGE_MAILBOX_NO_MATCH",
                    details={
                        "requested": sorted(wanted),
                        "availableIds": [
                            wizard.mailbox_id(mb) for mb in active
                            if wizard.mailbox_id(mb)
                        ],
                    },
                )
        click.echo(f"  Mailboxes selected : {len(sequence_list)}")

    if not sequence_list and not dry_run:
        emit_error(
            "No mailbox selected; refusing to save an empty binding.",
            code="USAGE_NO_MAILBOX",
        )

    # ── Launch decision ─────────────────────────────────────
    if launch_now is None:
        if interactive:
            launch_now = click.confirm(
                "Launch this AIFlow now? (No = save as draft)", default=True
            )
        else:
            launch_now = False

    # Completeness gate — block launch when any step's emailContent is still
    # empty. With --regenerate-emails on by default, this normally only fires
    # when one or more LLM calls failed after the built-in retries; the fix
    # is to either re-run `aiflow create` or populate the failing step(s)
    # manually via `aiflow prompt-update`.
    if launch_now and not dry_run and incomplete > 0:
        recovery = (
            "Re-run `aiflow create` (the LLM sometimes flakes and a fresh "
            "run may succeed) or populate the empty step(s) manually via "
            "`aiflow prompt-update FLOW_ID --file prompts.json`. Drop "
            "--launch to leave the flow as DRAFT and edit later."
        ) if regenerate_emails else (
            "You passed --no-regenerate-emails, so all steps were saved "
            "empty. Re-run `aiflow create` without that flag, or populate "
            "step(s) via `aiflow prompt-update FLOW_ID --file prompts.json` "
            "before launching."
        )
        emit_error(
            f"{incomplete} of {len(prompt_steps)} email step(s) have empty "
            f"content; launching would produce no sends. {recovery}",
            code="AIFLOW_LAUNCH_PROMPTS_INCOMPLETE",
            details={
                "totalSteps": len(prompt_steps),
                "incompleteSteps": incomplete,
            },
        )

    if launch_now and interactive and not yes and not dry_run:
        click.confirm("Proceed with launch?", abort=True, default=True)

    if launch_now and not dry_run:
        _check_token_balance(client, required=None, force=force)

    launch_result = None
    setting_resp = {}
    time_template = None
    meeting_router_id = None

    if launch_now and not dry_run:
        # 3a. /get/setting — pull defaults (agentPromptList, emailTrack, ...)
        setting_resp = _safe_call(
            lambda: client.get_setting(flow_id),
            code="AIFLOW_GET_SETTING_FAILED",
        )
        setting_resp = (setting_resp or {}).get("data") or setting_resp or {}

        # 3b. /time/template/list — required for timeTemplateConfig
        time_template = wizard.pick_default_time_template(client)
        if time_template is None:
            emit_error(
                "No time-template available on the account — cannot populate "
                "timeTemplateConfig for launch. Create one in the web UI first.",
                code="AIFLOW_LAUNCH_NO_TIME_TEMPLATE",
            )
        click.echo(
            f"  Time template      : {time_template.get('name', '')[:60]}"
            f" (id={time_template.get('id')})"
        )

        # 3c. /meeting/personal/list — first id for Book Meeting
        if setting_resp.get("isShowAiReply"):
            meetings_resp = _safe_call(
                lambda: client.list_personal_meetings(),
                code="MEETING_LIST_FAILED",
            )
            meeting_router_id = wizard.pick_first_meeting_router_id(meetings_resp)
            if meeting_router_id is None:
                click.echo(
                    "  Warning: no personal meeting router — agentPromptList "
                    "Book Meeting entry will have an empty meetingRouteId.",
                    err=True,
                )

    # ── Assemble + send save/setting ────────────────────────
    if launch_now:
        save_body = wizard.build_save_setting_body(
            flow_id,
            time_template or {},
            sequence_list,
            setting_resp,
            auto_approve,
            enable_agent_reply=enable_agent_reply,
            agent_strategy=agent_strategy,
            meeting_router_id=meeting_router_id,
        )
        if dry_run:
            click.echo(
                "  [dry-run] would POST /api/v1/ai/workflow/save/setting "
                "(launch: persists settings AND transitions DRAFT -> ACTIVE)"
            )
        else:
            launch_result = _safe_call(
                lambda: client.save_setting(save_body),
                code="AIFLOW_LAUNCH_FAILED",
            )
            click.echo("  Settings saved + flow launched.")
    else:
        click.echo(
            "  Flow left as DRAFT (no save/setting call). Re-run with "
            "--launch next time, or use `aiflow settings-update` to launch "
            "this flow after editing."
        )

    # ── Summary ─────────────────────────────────────────────
    click.echo()
    click.secho(f"{header}Summary", fg="cyan", bold=True)

    balance = None
    try:
        balance = client.get_token_balance()
    except Exception as e:  # noqa: BLE001
        click.echo(f"  Warning: token balance probe failed ({e})", err=True)

    summary = {
        "dryRun": dry_run,
        "flowId": flow_id,
        "contacts": total,
        "uniqueEmails": unique_emails,
        "url": website_normalised,
        "language": language,
        "countryColumn": country_col,
        "stepsTotal": len(prompt_steps),
        "stepsIncomplete": incomplete,
        "regenerateEmails": regenerate_emails,
        "mailboxesSelected": len(sequence_list),
        "autoApprove": bool(auto_approve),
        "launched": bool(launch_now) and not dry_run,
        "meetingRouterId": meeting_router_id,
    }
    if balance is not None:
        summary["tokenRemaining"] = balance["tokenRemaining"]
        summary["tokenSufficient"] = balance["sufficient"]
    emit(summary)

    if dry_run:
        click.echo()
        click.echo(
            "Dry-run complete. No side effects. Remove --dry-run to "
            "create the AIFlow."
        )
        return

    if launch_now:
        click.secho(f"Launched: {flow_id}", fg="green")
        if launch_result is not None:
            emit(launch_result)
    else:
        click.echo(
            f"Saved as DRAFT (flowId={flow_id}). Activate later with "
            "`aiflow settings-update {flow_id} --enable-agent-reply` "
            "or re-run `aiflow create --launch`."
        )


# ═══════════════════════════════════════════════════════════
# mailboxes
# ═══════════════════════════════════════════════════════════

@cli.group()
def mailboxes():
    """Mailbox pool operations."""


@mailboxes.command("list")
@click.option("--status", default=None,
              help="Pass-through filter forwarded as ?status=...")
@click.option("--warmup", default=None,
              help="Pass-through filter forwarded as ?warmup=...")
def mailboxes_list(status, warmup):
    """List bound mailboxes.

    Calls: GET /mailsvc/mail-address/simple/v2/list
    """
    _require_api_key()
    client = _build_client()
    params = {}
    if status:
        params["status"] = status
    if warmup:
        params["warmup"] = warmup
    result = _safe_call(
        lambda: client.list_mailboxes(params),
        code="MAILBOXES_LIST_FAILED",
    )
    emit(result)


@mailboxes.command("bind-list")
@click.argument("flow_id")
def mailboxes_bind_list(flow_id):
    """Show the mailbox pool bound to an AIFlow.

    Calls: GET /api/v1/ai/workflow/get/bind/email/{flowId}
    """
    _require_api_key()
    client = _build_client()
    result = _safe_call(
        lambda: client.get_bind_email(flow_id),
        code="MAILBOXES_BIND_LIST_FAILED",
    )
    emit(result)


@mailboxes.command("unbind-list")
@click.argument("flow_id")
def mailboxes_unbind_list(flow_id):
    """Show the mailboxes an AIFlow is actively using (currently-active set).

    Calls: GET /api/v1/ai/workflow/get/unbind/email/{flowId}
    """
    _require_api_key()
    client = _build_client()
    result = _safe_call(
        lambda: client.get_unbind_email(flow_id),
        code="MAILBOXES_UNBIND_LIST_FAILED",
    )
    emit(result)


@mailboxes.command("has-active")
def mailboxes_has_active():
    """Check whether the current account has any active mailbox.

    Calls: GET /api/v1/ai/workflow/has/active/email
    """
    _require_api_key()
    client = _build_client()
    result = _safe_call(
        lambda: client.has_active_email(),
        code="MAILBOXES_HAS_ACTIVE_FAILED",
    )
    emit(result)


# ═══════════════════════════════════════════════════════════
# meetings — meeting-svc personal routers
# ═══════════════════════════════════════════════════════════

@cli.group()
def meetings():
    """Meeting routers (meeting-svc) — personal meeting listing.

    The wizard's launch branch picks ``meetings[0].id`` as the
    ``meetingRouteId`` for the Book Meeting agent-reply strategy;
    this group lets you inspect that list directly.
    """


@meetings.command("list")
@click.option("--name", "meet_name", default="",
              help="Filter by meeting name (LIKE match, case-sensitive).")
@click.option("--type", "meet_type", default="",
              help="Filter by meetingEventType (exact match).")
def meetings_list(meet_name, meet_type):
    """List personal meeting routers.

    Calls: POST /meeting/api/v1/meeting/personal/list
    """
    _require_api_key()
    client = _build_client()
    result = _safe_call(
        lambda: client.list_personal_meetings(meet_name, meet_type),
        code="MEETINGS_LIST_FAILED",
    )
    emit(result)


# ═══════════════════════════════════════════════════════════
# token — balance query + pre-launch budget check
# ═══════════════════════════════════════════════════════════

@cli.group()
def token():
    """Token balance query and pre-launch budget checks.

    Balance is derived from data.limit.{tokenTotal, tokenCost} in the
    response of GET /api/v2/oauth/me.
    """


@token.command("balance")
def token_balance():
    """Show current token balance (tokenTotal - tokenCost).

    \b
    Example output (JSON mode):
      {
        "tokenTotal":     11580283.0,
        "tokenCost":      7291284.0,
        "tokenRemaining": 4288999.0,
        "sufficient":     true
      }
    """
    _require_api_key()
    client = _build_client()
    result = _safe_call(
        lambda: client.get_token_balance(),
        code="TOKEN_BALANCE_FAILED",
    )
    emit(result)


@token.command("check")
@click.option("--required", type=int, default=None,
              help="Required token count. Omit to check remaining > 0.")
def token_check(required):
    """Exit with code 2 if the balance is below --required.

    Designed for CI / scripts: `flashclaw-cli-plugin-flashrev-aiflow token check
    --required 11000` exits 2 (TOKEN_INSUFFICIENT) and prints a structured
    error to stderr when the balance is too low.
    """
    _require_api_key()
    client = _build_client()
    bal = _safe_call(
        lambda: client.get_token_balance(),
        code="TOKEN_BALANCE_FAILED",
    )
    if required is not None and bal["tokenRemaining"] < required:
        emit_error(
            f"Insufficient tokens: need {required}, "
            f"have {bal['tokenRemaining']:.0f}. "
            "Top up at https://info.flashlabs.ai/settings/credit.",
            code="TOKEN_INSUFFICIENT",
            details=bal,
        )
    if required is None and not bal["sufficient"]:
        emit_error(
            "Token balance exhausted (remaining <= 0). "
            "Top up at https://info.flashlabs.ai/settings/credit.",
            code="TOKEN_EXHAUSTED",
            details=bal,
        )
    emit(bal)


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
    except Exception as e:  # noqa: BLE001
        emit({"ok": False, "base_url": url, "error": str(e)})


def main():
    cli()


if __name__ == "__main__":
    main()
