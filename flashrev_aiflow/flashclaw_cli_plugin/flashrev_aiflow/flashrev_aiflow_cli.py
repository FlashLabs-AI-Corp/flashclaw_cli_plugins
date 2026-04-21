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

# Endpoints listed in the PRD but NOT present in the search-website frontend.
# Implementations are blocked until the user confirms the right project /
# endpoint; the CLI reports this clearly instead of silently failing.
_NOT_CONFIRMED_MSG = (
    "Endpoint not verified in the search-website frontend yet. "
    "Please confirm the owning project and the real API path before this "
    "command can be wired up."
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
    click.echo("  Run: flashclaw-cli-plugin-flashrev-aiflow auth login --token <your-api-key>")
    click.echo()
    click.echo("  Generate an API Key in the FlashRev console -> Settings -> Private Apps.")
    click.echo("  Key format starts with sk_, e.g.: sk_aBcDeFgH...")
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
            f"have {bal['tokenRemaining']:.0f}. Use --force to bypass.",
            code="TOKEN_INSUFFICIENT",
            details=bal,
        )
    if required is None and not bal["sufficient"]:
        emit_error(
            "Token balance exhausted (remaining <= 0). "
            "Use --force to bypass the CLI-side check.",
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
        click.echo(ctx.get_help())


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
@click.option("--status", "status", default=None,
              help="Filter by status (pass-through to backend).")
@click.option("--page", default=None, type=int, help="Page number (1-indexed).")
@click.option("--page-size", "page_size", default=None, type=int,
              help="Results per page.")
def aiflow_list(status, page, page_size):
    """List AIFlows (GET /api/v1/ai/workflow/agent/list)."""
    _require_api_key()
    client = _build_client()
    params = {}
    if status:
        params["status"] = status
    if page is not None:
        params["page"] = page
    if page_size is not None:
        params["pageSize"] = page_size
    result = _safe_call(lambda: client.list_aiflows(params), code="AIFLOW_LIST_FAILED")
    emit(result)


@aiflow.command("show")
@click.argument("flow_id")
def aiflow_show(flow_id):
    """Show a single AIFlow (GET /api/v1/ai/workflow/agent/get/flow/{id})."""
    _require_api_key()
    client = _build_client()
    result = _safe_call(lambda: client.get_aiflow(flow_id), code="AIFLOW_SHOW_FAILED")
    emit(result)


@aiflow.command("start")
@click.argument("flow_id")
@click.option("--status", "status_value", default="ACTIVE", show_default=True,
              help="Status token sent to /sequence/status/{id}/{status}. "
                   "Frontend uses ACTIVE for launch/resume (see "
                   "search-website/src/views/ai-flow/components/columns/"
                   "ai-status-cell.vue).")
@click.option("--required-tokens", type=int, default=None,
              help="Required token budget; exit 2 if balance is below this.")
@click.option("--force", is_flag=True,
              help="Skip CLI-side token balance check "
                   "(backend / gateway enforcement still applies).")
def aiflow_start(flow_id, status_value, required_tokens, force):
    """Start / launch an AIFlow.

    Calls: GET /api/v1/ai/workflow/agent/sequence/status/{flowId}/{status}

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
              help="Status token sent to /sequence/status/{id}/{status}. "
                   "Frontend uses PAUSED (flow-header.vue:120).")
def aiflow_pause(flow_id, status_value):
    """Pause an AIFlow."""
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
              help="Status token sent to /sequence/status/{id}/{status}. "
                   "Frontend uses ACTIVE to resume (same as launch).")
@click.option("--required-tokens", type=int, default=None,
              help="Required token budget; exit 2 if balance is below this.")
@click.option("--force", is_flag=True,
              help="Skip CLI-side token balance check.")
def aiflow_resume(flow_id, status_value, required_tokens, force):
    """Resume a paused AIFlow.

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
    """Delete an AIFlow (GET /api/v1/ai/workflow/agent/delete/{id})."""
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


@aiflow.group("pitch")
def aiflow_pitch():
    """Pitch content for an AIFlow.

    \b
    Subcommands:
      show FLOW_ID      Fetch the saved 6-section pitch for an AIFlow.
      init [--out PATH] Emit a local pitch.json scaffold to edit + pass
                        to `aiflow create --pitch-file`.
    """


@aiflow_pitch.command("show")
@click.argument("flow_id")
def aiflow_pitch_show(flow_id):
    """Show the 6-section pitch saved for a given AIFlow.

    Calls: GET /api/v1/ai/workflow/agent/get/pitch?flowId=...
    """
    _require_api_key()
    client = _build_client()
    result = _safe_call(
        lambda: client.get_pitch({"flowId": flow_id}),
        code="AIFLOW_PITCH_FAILED",
    )
    emit(result)


@aiflow_pitch.command("init")
@click.option("--out", "out_path", default="pitch.json", show_default=True,
              help="Output file path.")
@click.option("--force", is_flag=True,
              help="Overwrite the file if it already exists.")
def aiflow_pitch_init(out_path, force):
    """Emit a pitch.json scaffold (no network call).

    Writes a ready-to-edit JSON file with the 6 required pitch sections
    (officialDescription + painPoints / solutions / proofPoints /
    callToActions / leadMagnets) plus optional url and language fields.

    \b
    Example:
      flashclaw-cli-plugin-flashrev-aiflow aiflow pitch init --out ./my-pitch.json
      # edit ./my-pitch.json
      flashclaw-cli-plugin-flashrev-aiflow aiflow create --no-wizard \\
          --csv ./contacts.csv --pitch-file ./my-pitch.json \\
          --country-column country --dry-run
    """
    from pathlib import Path

    path = Path(out_path).expanduser()
    if path.exists() and not force:
        emit_error(
            f"Refusing to overwrite existing file: {path}. "
            "Use --force to overwrite.",
            code="PITCH_INIT_FILE_EXISTS",
            details={"path": str(path.resolve())},
        )
    scaffold = _pitch_scaffold()
    path.write_text(
        json.dumps(scaffold, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    emit({
        "ok": True,
        "path": str(path.resolve()),
        "sections": list(scaffold.keys()),
    })


def _pitch_scaffold() -> dict:
    """Default pitch JSON scaffold. Kept in sync with examples/pitch.example.json."""
    return {
        "officialDescription": (
            "One-sentence value proposition describing what your company does "
            "and why it matters to buyers."
        ),
        "painPoints": [
            "First specific pain your customers feel (keep each bullet short and concrete)",
            "Second pain point",
        ],
        "solutions": [
            "How your product solves the first pain",
            "How it solves the second",
        ],
        "proofPoints": [
            "Customer testimonial or case-study one-liner",
            "Notable metric you have achieved (e.g. 30% lift, 2x ROI)",
        ],
        "callToActions": [
            "Book a 15-minute demo",
            "Download the one-page ROI brief",
        ],
        "leadMagnets": [
            "Free audit of the prospect's current setup",
            "Template / checklist / ROI calculator",
        ],
        "url": "acme.com",
        "language": "en",
    }


@aiflow.command("test-connection")
@click.argument("url")
def aiflow_test_connection(url):
    """Test whether a company website URL is reachable for pitch generation.

    Calls: POST /api/v1/ai/workflow/agent/test/connection  (timeout 20s)
    """
    _require_api_key()
    client = _build_client()
    result = _safe_call(
        lambda: client.test_website_connection(url),
        code="AIFLOW_TEST_CONNECTION_FAILED",
    )
    emit(result)


@aiflow.command("template")
def aiflow_template():
    """Show the default email-sequence time template.

    Calls: GET /api/v1/ai/workflow/agent/get/time/template
    """
    _require_api_key()
    client = _build_client()
    result = _safe_call(
        lambda: client.get_time_template(),
        code="AIFLOW_TEMPLATE_FAILED",
    )
    emit(result)


@aiflow.command("create")
@click.option("--no-wizard", is_flag=True,
              help="Skip the interactive wizard; drive everything via flags. "
                   "All required fields must be supplied as flags.")
@click.option("--dry-run", is_flag=True,
              help="Validate inputs and probe read-only endpoints "
                   "(token balance + mailbox list); skip all write operations "
                   "(upload / create / save_pitch / save_email_config / launch). "
                   "No side effects on the backend.")
@click.option("--csv", "csv_path", default=None,
              help="Path to a local CSV file (email column required).")
@click.option("--sheet", "sheet_url", default=None,
              help="Public Google Sheet URL (shared as 'Anyone with the "
                   "link -> Viewer').")
@click.option("--website", default=None,
              help="Company website URL (for the pitch). May be omitted if "
                   "the --pitch-file contains a top-level 'url' field.")
@click.option("--pitch-file", "pitch_file", default=None,
              help="JSON file with the 6-section pitch payload. Required in "
                   "--no-wizard mode (interactive editor is disabled there).")
@click.option("--language", default="auto", show_default=True,
              help="Pitch language; 'auto' lets the backend infer per contact.")
@click.option("--country-column", "country_column", default=None,
              help="CSV column name carrying the contact country/region "
                   "(or 'none' to skip). Required in --no-wizard mode when "
                   "--language=auto.")
@click.option("--email-rounds", "email_rounds", default=2, type=int,
              show_default=True, help="Emails per contact (1-5).")
@click.option("--mailboxes", "mailbox_mode", default="all-active",
              show_default=True,
              help="'all-active' to pick every active mailbox, or a comma-"
                   "separated list of mailbox ids.")
@click.option("--auto-approve/--no-auto-approve", "auto_approve",
              default=True, show_default=True,
              help="autoApprove flag on the saved email config.")
@click.option("--launch/--no-launch", "launch_now", default=None,
              help="Launch the AIFlow after save. In --no-wizard mode, "
                   "defaults to --no-launch (save as draft) unless --launch "
                   "is passed.")
@click.option("-y", "--yes", is_flag=True,
              help="Skip the final confirmation prompt.")
@click.option("--force", is_flag=True,
              help="Skip CLI-side token balance check before launch.")
def aiflow_create(
    no_wizard, dry_run, csv_path, sheet_url, website, pitch_file, language,
    country_column, email_rounds, mailbox_mode, auto_approve, launch_now,
    yes, force,
):
    """Create a new AIFlow (Strategy -> AIFlow -> Settings -> Launch).

    Pipeline (all via auth-gateway-svc /flashrev):

      1. POST /api/v1/ai/workflow/contacts/upload    -> {listId, listName}
      2. POST /api/v1/ai/workflow/create/list        -> {flowId}
      3. POST /api/v1/ai/workflow/save/pitch         -> save 6-section pitch
      4. GET  /api/v1/ai/workflow/agent/get/time/template (preview only)
      5. POST /api/v1/ai/workflow/agent/get/email/config  (load current)
      6. POST /api/v1/ai/workflow/agent/save/email/config (save with edits)
      7. GET  /api/v1/ai/workflow/agent/sequence/status/{flowId}/ACTIVE  (launch)

    Wizard mode (default) prompts for missing fields. --no-wizard makes every
    missing field an error (CI/script-friendly). --dry-run validates inputs
    and probes read-only endpoints without making any write calls.
    """
    _require_api_key()
    client = _build_client()
    _run_create_wizard(
        client,
        csv_path=csv_path,
        sheet_url=sheet_url,
        website=website,
        pitch_file=pitch_file,
        language=language,
        country_column=country_column,
        email_rounds=email_rounds,
        mailbox_mode=mailbox_mode,
        auto_approve=auto_approve,
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
    website=None,
    pitch_file=None,
    language="auto",
    country_column=None,
    email_rounds=2,
    mailbox_mode="all-active",
    auto_approve=True,
    launch_now=None,
    yes=False,
    force=False,
    interactive=True,
    dry_run=False,
):
    """Drive the Strategy -> AIFlow -> Settings -> Launch pipeline.

    interactive=True : prompt for missing fields (wizard mode).
    interactive=False: raise USAGE_* errors for missing fields (--no-wizard).
    dry_run=True     : perform local validation + read-only probes only; skip
                       every write endpoint (upload / create / save_pitch /
                       save_email_config / launch).
    """
    from flashclaw_cli_plugin.flashrev_aiflow import wizard

    header = "Dry-run " if dry_run else ""

    # ── Pre-flight checks (non-interactive mode) ───────────────────
    if not interactive:
        if bool(csv_path) == bool(sheet_url):
            emit_error(
                "--no-wizard requires exactly one of --csv or --sheet",
                code="USAGE_CONTACT_SOURCE",
            )
        if not pitch_file:
            emit_error(
                "--no-wizard requires --pitch-file (the interactive pitch "
                "editor is disabled in this mode)",
                code="USAGE_PITCH_FILE_REQUIRED",
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

    # ── 1c. Pitch + website (resolve URL first, allowing pitch file to supply it) ─
    pitch_payload = None
    if pitch_file:
        pitch_payload = _safe_call(
            lambda: wizard.load_pitch_file(pitch_file),
            code="PITCH_FILE_INVALID",
        )

    if not website and pitch_payload and pitch_payload.get("url"):
        website = pitch_payload["url"]

    if not website:
        if interactive:
            website = click.prompt(
                "  Company website URL (with or without https://)"
            ).strip()
        else:
            emit_error(
                "--website is required (or include a top-level 'url' in "
                "--pitch-file)",
                code="USAGE_WEBSITE_MISSING",
            )

    website_normalised = website if website.startswith("http") else (
        "https://" + website.lstrip("/")
    )

    if pitch_payload is None:
        # Interactive-only path; non-interactive mode errored out above.
        click.echo(
            "  No --pitch-file given. Opening $EDITOR for 6-section pitch ..."
        )
        pitch_payload = wizard.edit_pitch_interactively()

    # ── 1d. Upload + create AIFlow ──────────────────────────
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
        click.echo(f"  flowId  : {flow_id}")

    # ── 1e. Save pitch ──────────────────────────────────────
    save_pitch_body = {
        **pitch_payload,
        "workflowId": flow_id,
        "url": website_normalised,
        "language": language,
        "useConfigLanguage": (language == "auto"),
    }
    if dry_run:
        click.echo("  [dry-run] would POST /api/v1/ai/workflow/save/pitch "
                   "(6 sections validated)")
    else:
        _safe_call(
            lambda: client.save_pitch(save_pitch_body),
            code="PITCH_SAVE_FAILED",
        )
        click.echo("  Pitch saved.")

    # ── 2. AIFlow — default email-sequence template (read-only) ────
    click.echo()
    click.secho(f"{header}Step 2 / 3 - AIFlow", fg="cyan", bold=True)
    click.echo(f"  Emails per contact: {email_rounds}")
    click.echo(
        "  (Default email sequence template shown as preview; not "
        "editable in V1.)"
    )
    template = _safe_call(
        lambda: client.get_time_template(),
        code="TIME_TEMPLATE_FAILED",
    )
    tpl_summary = (template or {}).get("data")
    if tpl_summary is not None:
        click.echo(f"  Template: {_short_repr(tpl_summary)}")

    # ── 3. Settings ─────────────────────────────────────────
    click.echo()
    click.secho(f"{header}Step 3 / 3 - Settings", fg="cyan", bold=True)
    click.echo("  Automated Approval : " + ("ON" if auto_approve else "OFF"))
    click.echo(
        "  Schedule           : Mon-Fri 10:00-17:00 UTC-5 (fixed in V1)"
    )

    # Load current email config so we can preserve timeTemplateConfig /
    # emailTrack / timeTemplateId and only edit mailbox list + autoApprove.
    # Dry-run skips this (no flowId yet) and saves with empty props.
    if dry_run:
        props = {}
    else:
        email_cfg = _safe_call(
            lambda: client.get_email_config({"workflowId": flow_id}),
            code="EMAIL_CONFIG_LOAD_FAILED",
        )
        cfg_data = (email_cfg or {}).get("data") or {}
        props = cfg_data.get("properties") or {}

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

    new_props = dict(props)
    new_props["sequenceMailboxList"] = sequence_list

    save_body = {
        "workflowId": flow_id,
        "properties": new_props,
        "autoApprove": bool(auto_approve),
    }
    if dry_run:
        click.echo(
            "  [dry-run] would POST /api/v1/ai/workflow/agent/save/email/config"
        )
    else:
        _safe_call(
            lambda: client.save_email_config(save_body),
            code="EMAIL_CONFIG_SAVE_FAILED",
        )
        click.echo("  Settings saved.")

    # ── Summary ─────────────────────────────────────────────
    click.echo()
    click.secho(f"{header}Summary", fg="cyan", bold=True)

    # Token balance probe (read-only, useful in dry-run too).
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
        "website": website_normalised,
        "language": language,
        "countryColumn": country_col,
        "emailRounds": email_rounds,
        "mailboxesSelected": len(sequence_list),
        "autoApprove": bool(auto_approve),
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

    # ── Launch branch ───────────────────────────────────────
    if launch_now is None:
        if interactive:
            launch_now = click.confirm(
                "Launch this AIFlow now? (No = save as draft)", default=True
            )
        else:
            # Non-wizard default: save as draft unless --launch was explicit.
            launch_now = False

    if not launch_now:
        click.echo("Saved as draft. Launch later with:")
        click.echo(
            f"  flashclaw-cli-plugin-flashrev-aiflow aiflow start {flow_id}"
        )
        return

    if interactive and not yes:
        click.confirm("Proceed with launch?", abort=True, default=True)

    _check_token_balance(client, required=None, force=force)
    launch = _safe_call(
        lambda: client.set_aiflow_status(flow_id, "ACTIVE"),
        code="AIFLOW_LAUNCH_FAILED",
    )
    click.secho(f"Launched: {flow_id}", fg="green")
    emit(launch)


def _short_repr(obj) -> str:
    """Compact one-line repr for wizard-time summaries (avoid huge JSON blobs)."""
    try:
        s = json.dumps(obj, ensure_ascii=False)
    except Exception:  # noqa: BLE001
        s = str(obj)
    return s if len(s) <= 240 else s[:237] + "..."


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
def mailboxes_bind_list():
    """Show mailboxes currently bound to the AIFlow account.

    Calls: GET /api/v1/ai/workflow/agent/get/bind/email
    """
    _require_api_key()
    client = _build_client()
    result = _safe_call(
        lambda: client.get_bind_email(),
        code="MAILBOXES_BIND_LIST_FAILED",
    )
    emit(result)


@mailboxes.command("has-active")
def mailboxes_has_active():
    """Check whether the current account has any active mailbox.

    Calls: GET /api/v1/ai/workflow/agent/has/active/email
    """
    _require_api_key()
    client = _build_client()
    result = _safe_call(
        lambda: client.has_active_email(),
        code="MAILBOXES_HAS_ACTIVE_FAILED",
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
            f"have {bal['tokenRemaining']:.0f}",
            code="TOKEN_INSUFFICIENT",
            details=bal,
        )
    if required is None and not bal["sufficient"]:
        emit_error(
            "Token balance exhausted (remaining <= 0)",
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
