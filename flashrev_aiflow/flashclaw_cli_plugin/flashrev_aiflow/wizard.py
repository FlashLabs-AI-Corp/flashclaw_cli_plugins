"""Interactive wizard helpers for `aiflow create`.

The wizard drives a headless equivalent of the FlashRev web UI's 3-step
AIFlow creation flow (Strategy -> AIFlow -> Settings), using the real
endpoints observed in the search-website frontend:

  Strategy  POST /api/v1/ai/workflow/contacts/upload   (new direct-multipart endpoint; see README)
            POST /api/v1/ai/workflow/create/list       {listId, listName, type:'csv', source:'csv'}
            POST /api/v1/ai/workflow/save/pitch        {workflowId, url, language, ...6 sections}
  AIFlow    GET  /api/v1/ai/workflow/agent/get/time/template   (read-only preview of the default sequence)
  Settings  POST /api/v1/ai/workflow/agent/get/email/config    (load current config)
            POST /api/v1/ai/workflow/agent/save/email/config   (save with user edits to mailboxes/autoApprove)
  Launch    GET  /api/v1/ai/workflow/agent/sequence/status/{flowId}/ACTIVE

Only functions here (no Click commands) — keeps the wizard reusable from
tests and from the non-wizard dispatch path (M4).
"""

from __future__ import annotations

import csv
import json
import re
import tempfile
import urllib.parse
from pathlib import Path
from typing import Iterable, Optional

import click
import requests

# Heuristics used to match columns in contact CSVs.
_EMAIL_COLUMN_HINTS = ("email", "mail", "e-mail", "邮箱", "邮件")
_COUNTRY_COLUMN_HINTS = (
    "country", "region", "location", "nation", "地区", "国家", "地域"
)

# Required fields on a pitch JSON. url is not required here because the CLI
# accepts it separately (command flag or wizard prompt).
_PITCH_TEXT_FIELD = "officialDescription"
_PITCH_LIST_FIELDS = (
    "painPoints",
    "solutions",
    "proofPoints",
    "callToActions",
    "leadMagnets",
)


# ═══════════════════════════════════════════════════════════
# CSV + Sheet loading
# ═══════════════════════════════════════════════════════════

def load_contacts_source(
    csv_path: Optional[str] = None,
    sheet_url: Optional[str] = None,
) -> Path:
    """Return a local Path to a CSV file, fetching the Google Sheet if given.

    Exactly one of csv_path / sheet_url must be provided.
    """
    if bool(csv_path) == bool(sheet_url):
        raise click.UsageError(
            "Provide exactly one of: a local CSV path, or a Google Sheet URL."
        )
    if csv_path:
        p = Path(csv_path).expanduser().resolve()
        if not p.exists() or not p.is_file():
            raise click.UsageError(f"CSV file not found: {p}")
        return p
    return fetch_google_sheet_as_csv(sheet_url)


def fetch_google_sheet_as_csv(sheet_url: str) -> Path:
    """Download a public Google Sheet as CSV to a named temp file.

    Requires the sheet to be shared via 'Anyone with the link -> Viewer'.
    Uses the sheet's public /export?format=csv endpoint; no OAuth.
    """
    sheet_id, gid = _parse_google_sheet_url(sheet_url)
    export = (
        f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv"
    )
    if gid:
        export += f"&gid={gid}"

    resp = requests.get(export, timeout=30, allow_redirects=True)
    if resp.status_code != 200:
        raise click.UsageError(
            "Failed to download Google Sheet as CSV "
            f"(HTTP {resp.status_code}). Ensure the sheet is shared as "
            "'Anyone with the link -> Viewer'."
        )
    if b"<html" in resp.content[:200].lower():
        raise click.UsageError(
            "Google Sheet is not publicly accessible. Change sharing to "
            "'Anyone with the link -> Viewer' and retry."
        )

    tmp = tempfile.NamedTemporaryFile(
        prefix="flashrev_sheet_", suffix=".csv", delete=False
    )
    tmp.write(resp.content)
    tmp.close()
    return Path(tmp.name)


def _parse_google_sheet_url(url: str) -> tuple[str, Optional[str]]:
    """Extract (sheetId, gid) from a Google Sheet URL."""
    m = re.search(r"/spreadsheets/d/([A-Za-z0-9_-]+)", url)
    if not m:
        raise click.UsageError(
            f"Unrecognized Google Sheet URL: {url}. Expected form: "
            "https://docs.google.com/spreadsheets/d/<id>/..."
        )
    sheet_id = m.group(1)
    gid = None
    parsed = urllib.parse.urlparse(url)
    frag = urllib.parse.parse_qs(parsed.fragment) if parsed.fragment else {}
    qs = urllib.parse.parse_qs(parsed.query) if parsed.query else {}
    if "gid" in frag:
        gid = frag["gid"][0]
    elif "gid" in qs:
        gid = qs["gid"][0]
    return sheet_id, gid


# ═══════════════════════════════════════════════════════════
# CSV validation + heuristics
# ═══════════════════════════════════════════════════════════

def preview_csv(
    path: Path, n: int = 5
) -> tuple[list[str], list[dict], int, int]:
    """Read the CSV and return (columns, first_n_rows, total_rows, unique_emails).

    Uses utf-8-sig to transparently strip the BOM.
    Raises click.UsageError on missing email column or empty file.
    """
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        columns = list(reader.fieldnames or [])
        if not columns:
            raise click.UsageError(
                f"CSV is empty or has no header row: {path}"
            )
        email_col = _detect_email_column(columns)
        if not email_col:
            raise click.UsageError(
                "CSV must contain an email column "
                "(case-insensitive, accepted names: "
                f"{', '.join(_EMAIL_COLUMN_HINTS)}). "
                f"Got columns: {columns}"
            )
        rows = []
        seen_emails = set()
        total = 0
        for row in reader:
            total += 1
            if total <= n:
                rows.append(row)
            email = (row.get(email_col) or "").strip().lower()
            if email:
                seen_emails.add(email)
    return columns, rows, total, len(seen_emails)


def _detect_email_column(columns: Iterable[str]) -> Optional[str]:
    for col in columns:
        lc = (col or "").strip().lower()
        if lc in _EMAIL_COLUMN_HINTS:
            return col
    # Fall back to a substring match.
    for col in columns:
        lc = (col or "").strip().lower()
        if any(h in lc for h in _EMAIL_COLUMN_HINTS):
            return col
    return None


def detect_country_column(columns: Iterable[str]) -> Optional[str]:
    """Heuristic: match English + Chinese country/region column names."""
    for col in columns:
        lc = (col or "").strip().lower()
        if lc in _COUNTRY_COLUMN_HINTS:
            return col
    for col in columns:
        lc = (col or "").strip().lower()
        if any(h in lc for h in _COUNTRY_COLUMN_HINTS):
            return col
    return None


def confirm_country_column(
    columns: list[str], rows: list[dict]
) -> Optional[str]:
    """Prompt the user to accept the heuristic match, pick another, or skip.

    Returns the chosen column name, or None if the user opts out of country
    inference (language will fall back to the CLI session language).
    """
    candidate = detect_country_column(columns)

    if candidate:
        samples = [
            (row.get(candidate) or "").strip()
            for row in rows[:3]
            if (row.get(candidate) or "").strip()
        ]
        click.echo(
            f"  Detected country column: '{candidate}' "
            f"(samples: {samples or 'no data'})"
        )
        choice = click.prompt(
            "  [a]ccept / [s]elect another / [n]one",
            default="a",
            show_default=True,
        ).strip().lower()
        if choice.startswith("a"):
            return candidate
        if choice.startswith("n"):
            return None
        # fall through to manual selection
    else:
        click.echo("  No obvious country/region column detected.")

    click.echo("  Available columns:")
    for i, col in enumerate(columns, 1):
        click.echo(f"    {i}. {col}")
    click.echo("    0. none (skip country inference)")
    idx = click.prompt(
        "  Pick a column number", type=int, default=0, show_default=True
    )
    if idx == 0 or idx < 0 or idx > len(columns):
        return None
    return columns[idx - 1]


# ═══════════════════════════════════════════════════════════
# Pitch handling
# ═══════════════════════════════════════════════════════════

def load_pitch_file(path: str) -> dict:
    """Read and validate a pitch JSON file.

    Expected schema (from search-website PitchStrategySection.vue:205-215):
        {
          "officialDescription": "Value Proposition paragraph",
          "painPoints":   ["..."],
          "solutions":    ["..."],
          "proofPoints":  ["..."],
          "callToActions":["..."],
          "leadMagnets":  ["..."]
        }

    The top-level 'url' / 'language' / 'useConfigLanguage' / 'workflowId'
    are supplied by the wizard and do NOT need to be in the file.
    """
    p = Path(path).expanduser().resolve()
    if not p.exists():
        raise click.UsageError(f"Pitch file not found: {p}")
    try:
        data = json.loads(p.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as e:
        raise click.UsageError(f"Pitch file is not valid JSON: {e}")
    return validate_pitch_schema(data)


def validate_pitch_schema(data: dict) -> dict:
    """Ensure required fields exist with the right types.

    Missing sections are allowed (will just be sent as empty) but types that
    don't match raise a clear error.
    """
    if not isinstance(data, dict):
        raise click.UsageError(
            "Pitch payload must be a JSON object, got "
            f"{type(data).__name__}"
        )
    cleaned = {}
    if _PITCH_TEXT_FIELD in data:
        if not isinstance(data[_PITCH_TEXT_FIELD], str):
            raise click.UsageError(
                f"'{_PITCH_TEXT_FIELD}' must be a string"
            )
        cleaned[_PITCH_TEXT_FIELD] = data[_PITCH_TEXT_FIELD]
    for field in _PITCH_LIST_FIELDS:
        if field in data:
            val = data[field]
            if not isinstance(val, list) or not all(
                isinstance(x, str) for x in val
            ):
                raise click.UsageError(
                    f"'{field}' must be a list of strings"
                )
            cleaned[field] = val
    # Carry through any extra scalar fields the caller might have stashed
    # (e.g. 'url', 'language', 'useConfigLanguage'). workflowId is always
    # supplied by the wizard from the create/list response.
    for k, v in data.items():
        if k not in cleaned and k != "workflowId":
            cleaned[k] = v
    return cleaned


def edit_pitch_interactively(initial: Optional[dict] = None) -> dict:
    """Open $EDITOR on a JSON scaffold; re-open on parse failure.

    initial: current pitch payload (if any) to seed the editor with.
    """
    scaffold = dict(initial or {})
    scaffold.setdefault(_PITCH_TEXT_FIELD, "")
    for f in _PITCH_LIST_FIELDS:
        scaffold.setdefault(f, [])

    header = (
        "// Edit the pitch and save to continue.\n"
        "// officialDescription   -> Value Proposition\n"
        "// painPoints[]          -> Pain Points\n"
        "// solutions[]           -> Solutions\n"
        "// proofPoints[]         -> Proof Points\n"
        "// callToActions[]       -> CTAs\n"
        "// leadMagnets[]         -> Lead Magnets\n"
    )
    text = header + json.dumps(scaffold, indent=2, ensure_ascii=False)

    while True:
        edited = click.edit(text, extension=".json")
        if edited is None:
            raise click.Abort()
        # Strip banner comment lines before parsing.
        body = "\n".join(
            line for line in edited.splitlines() if not line.lstrip().startswith("//")
        )
        try:
            parsed = json.loads(body)
            return validate_pitch_schema(parsed)
        except (json.JSONDecodeError, click.UsageError) as e:
            click.echo(f"  Pitch JSON is invalid: {e}", err=True)
            if not click.confirm("  Re-open editor?", default=True):
                raise click.Abort()
            text = edited


# ═══════════════════════════════════════════════════════════
# Mailbox selection
# ═══════════════════════════════════════════════════════════

def filter_active_mailboxes(mailboxes_response: dict) -> list[dict]:
    """Extract mailbox items from the mailsvc response and keep Active only.

    The mailsvc response shape is typically:
        { code: 200, data: [ {id, address, status, mailAddressEnum, ...}, ... ] }
    Tolerates data being either a list or {items: [...]}.

    Status representations seen in the wild:
      * int ``status == 1`` means active (mailsvc convention on test + prod)
      * string ``"ACTIVE"`` / ``"ENABLED"``
      * string ``mailAddressEnum == "SUCCESS"`` — mailsvc health flag
      * absent — treated as active (conservative: avoids silently dropping
        items when a new backend schema adds a field we do not yet know)
    """
    data = (mailboxes_response or {}).get("data")
    items = data if isinstance(data, list) else (data or {}).get("items", [])

    active_string_values = {"ACTIVE", "ENABLED", "SUCCESS"}
    actives = []
    for item in items or []:
        raw_status = item.get("status")
        raw_enum = item.get("mailAddressEnum") or item.get("state")

        is_active = False
        # bool is a subclass of int in Python; exclude it so True/False don't
        # accidentally satisfy the int branch.
        if isinstance(raw_status, int) and not isinstance(raw_status, bool):
            is_active = raw_status == 1
        elif isinstance(raw_status, str) \
                and raw_status.upper() in active_string_values:
            is_active = True

        if not is_active and isinstance(raw_enum, str) \
                and raw_enum.upper() in active_string_values:
            is_active = True

        # No recognised signal at all -> include (conservative default).
        if raw_status is None and raw_enum is None:
            is_active = True

        if is_active:
            actives.append(item)
    return actives


def pick_default_time_template(client) -> Optional[dict]:
    """Fetch /engage/api/v1/time/template/list and pick a usable template.

    The save/setting (launch) endpoint rejects requests whose
    ``properties.timeTemplateConfig`` is null or empty with ``400 Unknown
    error``. For a fresh draft flow, ``get_email_config`` returns
    ``timeTemplateConfig: null``, so on launch we fetch the account's
    template library and embed one.

    Preference order:
      1. Entries tagged ``busSource == 'ai_workflow'`` (what the web wizard
         saves templates as).
      2. Any template.
      3. None if the account has none -- caller must fall back to a
         hard-coded minimal template or surface an error.
    """
    try:
        resp = client.list_time_templates()
    except Exception:  # noqa: BLE001
        return None
    items = (resp or {}).get("data") or []
    for t in items:
        if t.get("busSource") == "ai_workflow":
            return t
    return items[0] if items else None


def build_time_template_config(template: dict) -> dict:
    """Shape a time-template record into the ``timeTemplateConfig`` key
    expected inside ``save_setting``'s ``properties`` payload.

    Matches the subset the frontend sends from
    search-website/src/views/ai-sdr/settings.vue:324-340 -- ``name``,
    ``properties``, ``timeBlocks``. Ignores the outer ``id`` / ``busSource``
    fields (those aren't part of the nested config; ``id`` is passed
    separately as the sibling ``timeTemplateId`` key).
    """
    return {
        "name": template.get("name", ""),
        "properties": template.get("properties") or {},
        "timeBlocks": template.get("timeBlocks") or [],
    }


def mailbox_id(mailbox: dict):
    """Return the id field of a mailbox record, preserving its native type.

    mailsvc returns ``id`` as an int (e.g. 1479). Do NOT str-convert: the
    downstream save/email/config endpoint expects ``addressId`` as a JSON
    number, matching what the frontend sends (search-website
    src/views/ai-sdr/settings.vue:318-320 reads ``item.id`` raw).
    """
    for k in ("addressId", "id", "mailAddressId", "mailboxId"):
        v = mailbox.get(k)
        if v is not None:
            return v
    return None


def select_mailboxes_interactively(
    active_mailboxes: list[dict],
) -> list[dict]:
    """Prompt the user to pick mailboxes; default is all active.

    Returns the subset the user selected, formatted for
    save_email_config's sequenceMailboxList: [{"addressId": "..."}].
    """
    if not active_mailboxes:
        raise click.UsageError(
            "No active mailboxes available. Bind at least one mailbox "
            "before creating an AIFlow."
        )

    click.echo(f"  Active mailboxes ({len(active_mailboxes)}):")
    for i, mb in enumerate(active_mailboxes, 1):
        addr = mb.get("address") or mb.get("email") or "(no address)"
        warm = mb.get("warmUp") or mb.get("warmup") or "-"
        click.echo(f"    {i}. {addr}   warmUp={warm}")

    raw = click.prompt(
        "  Select mailboxes: [a]ll / comma-separated numbers (e.g. 1,3,5)",
        default="a",
        show_default=True,
    ).strip().lower()

    if raw in ("a", "all", ""):
        selected = active_mailboxes
    else:
        idxs = set()
        for part in raw.split(","):
            part = part.strip()
            if part.isdigit():
                n = int(part)
                if 1 <= n <= len(active_mailboxes):
                    idxs.add(n - 1)
        if not idxs:
            raise click.UsageError("No valid mailbox numbers selected.")
        selected = [active_mailboxes[i] for i in sorted(idxs)]

    return [
        {"addressId": mailbox_id(mb)}
        for mb in selected
        if mailbox_id(mb) is not None
    ]


# ═══════════════════════════════════════════════════════════
# V2 pitch flow — test/connection -> save/pitch
# ═══════════════════════════════════════════════════════════

def build_save_pitch_body(
    workflow_id,
    test_connection_data: dict,
    url: str,
    language: str,
) -> dict:
    """Shape the payload for ``POST /save/pitch`` from a ``test/connection``
    response.

    Mirrors search-website/src/views/ai-sdr/pitch.vue:490-499:
      - spreads the ICP DTO returned by test/connection (officialDescription,
        painPoints, solutions, proofPoints, callToActions, leadMagnets,
        benchmarkBrands, ...)
      - injects workflowId, url (prefixed with https:// if missing), and
        language from the wizard context
      - sets useConfigLanguage=True when language == 'auto' so the backend
        per-contact language detection kicks in
      - leaves all other ICP fields untouched (backend persists as-is; see
        dubbo-api-svc AiWorkFlowServiceImpl.savePitch ~line 1115)
    """
    body = dict(test_connection_data or {})
    normalised_url = url if url.startswith("http") else "https://" + url.lstrip("/")
    body["workflowId"] = workflow_id
    body["url"] = normalised_url
    body["language"] = language
    body["useConfigLanguage"] = (language == "auto")
    return body


# ═══════════════════════════════════════════════════════════
# V2 prompt flow — get/workflow/prompt -> [regenerate] -> save/prompt
# ═══════════════════════════════════════════════════════════

# Default step cadence used when the backend's /get/prompt response doesn't
# carry delayMinutes (mirrors the 3-step default the frontend seeds in
# search-website/src/views/ai-sdr/workflow.vue:383-389).
_DEFAULT_DELAY_MINUTES = [60, 4320, 10080]  # 1h, 3d, 7d


# t_ai_workflow_prompt.email_content is a MySQL TEXT column (65,535 bytes
# hard cap). Cap CLI-supplied content at 2/3 of that to leave headroom for
# any later edits / extensions and to avoid the silent BatchUpdateException
# truncation we observed when long LLM templates pushed past the limit.
# Counts BYTES (not chars) because TEXT's limit is byte-based and any
# non-ASCII char in the prompt expands to 2-4 utf-8 bytes.
_TEXT_COLUMN_HARD_CAP_BYTES = 65_535
_EMAIL_CONTENT_BYTE_LIMIT = _TEXT_COLUMN_HARD_CAP_BYTES * 2 // 3  # 43,690


def _truncate_to_byte_limit(
    text: str, max_bytes: int = _EMAIL_CONTENT_BYTE_LIMIT,
) -> str:
    """Return ``text`` clipped so its UTF-8 representation fits within
    ``max_bytes``. A no-op when the text is already short enough.

    Truncation drops any partial multi-byte character at the cut point
    via ``decode("utf-8", errors="ignore")`` so the result is always
    valid UTF-8.
    """
    if text is None:
        return text
    encoded = text.encode("utf-8")
    if len(encoded) <= max_bytes:
        return text
    return encoded[:max_bytes].decode("utf-8", errors="ignore")


def extract_prompt_steps(get_prompt_response: dict) -> list[dict]:
    """Normalise the `/get/prompt` response into a flat list of step dicts.

    The endpoint returns one of two shapes depending on backend version:
      A) ``{"code":200, "data":[{step,...}, ...]}``
      B) a bare list ``[{step,...}, ...]``
    We accept both and return the inner list, sorted by ``step``.
    """
    if isinstance(get_prompt_response, list):
        steps = get_prompt_response
    else:
        steps = (get_prompt_response or {}).get("data") or []
        if not isinstance(steps, list):
            steps = []
    return sorted(steps, key=lambda s: s.get("step") or 0)


def prompt_step_is_complete(step: dict) -> bool:
    """A step is "complete" when its ``emailContent`` (the LLM prompt
    template) is non-empty. The scheduler generates per-contact emails at
    send time by feeding ``emailContent`` + contact data into the AI
    service; as long as this template is present, the step can produce
    emails even if ``emailSubject`` / ``subject`` / ``content`` stay empty
    (mirrors the frontend sample save/prompt body which ships step 1/3
    with all those fields blank but step 2 with a full emailContent).
    """
    return bool((step.get("emailContent") or "").strip())


def count_incomplete_prompts(steps: list[dict]) -> int:
    """How many steps still need LLM generation before launch is safe."""
    return sum(1 for s in steps if not prompt_step_is_complete(s))


def build_save_prompt_body(
    workflow_id,
    steps: list[dict],
) -> dict:
    """Shape ``/save/prompt`` body from a steps list (as produced by
    :func:`extract_prompt_steps`, possibly after regeneration).

    Backend requires ``workflowStepId`` on every prompt (dubbo-api-svc
    AiWorkFlowServiceImpl line 1570-1572) — if any step is missing it we
    raise :class:`click.UsageError` rather than silently sending garbage.

    ``delayMinutes`` is taken from the step if present, otherwise the Nth
    entry of :data:`_DEFAULT_DELAY_MINUTES` (1h / 3d / 7d).
    """
    prompts = []
    for i, s in enumerate(steps):
        step_id = s.get("workflowStepId") or s.get("id")
        if step_id is None:
            raise click.UsageError(
                f"step {s.get('step') or i+1} has no workflowStepId; the "
                "wizard must call /get/prompt first to seed default rows."
            )
        delay = s.get("delayMinutes")
        if delay is None:
            delay = _DEFAULT_DELAY_MINUTES[i] if i < len(_DEFAULT_DELAY_MINUTES) else 10080
        # Defensive cap on every string field that maps to a TEXT column
        # in t_ai_workflow_prompt — protects user-supplied content from
        # `aiflow prompt-update --file` as well as the regenerate path.
        prompts.append({
            "workflowStepId": step_id,
            "step": s.get("step") or (i + 1),
            "stepType": s.get("stepType") or "email",
            "delayMinutes": delay,
            "emailSubject": _truncate_to_byte_limit(
                s.get("emailSubject") or ""
            ),
            "emailContent": _truncate_to_byte_limit(
                s.get("emailContent") or ""
            ),
            "subject": _truncate_to_byte_limit(
                s.get("subject") or s.get("exampleSubject") or ""
            ),
            "content": _truncate_to_byte_limit(
                s.get("content") or s.get("exampleContent") or ""
            ),
        })
    return {"workflowId": workflow_id, "prompts": prompts}


def _parse_sse_content(raw: str) -> str:
    """Concatenate ``data`` fields of ``type=content`` events from an SSE stream.

    Handles the Server-Sent Events shape that
    ``/api/v1/ai/workflow/get/email/prompt`` returns: one JSON event per
    line, each like ``{"type":"content","data":"...chunk..."}``. Events
    whose ``type`` is not ``content`` (done / error / etc.) are skipped.
    Malformed lines are silently ignored so a stray keepalive comment
    doesn't kill the whole parse.

    The backend emits ``</content>`` as a stream terminator (wrapped in
    its own content event) — it is stripped from the result so callers
    get the clean prompt template.
    """
    out = []
    for line in (raw or "").split("\n"):
        line = line.strip()
        if not line or line.startswith(":"):
            continue
        # The server emits bare JSON per line — no ``data: `` SSE prefix —
        # but strip one if present just in case.
        if line.startswith("data:"):
            line = line[len("data:"):].strip()
        try:
            import json
            ev = json.loads(line)
        except Exception:  # noqa: BLE001
            continue
        if ev.get("type") == "content":
            out.append(ev.get("data", ""))
    text = "".join(out)
    # Strip the backend's stream terminator if it leaked through.
    for terminator in ("</content>", "<content>"):
        if text.endswith(terminator):
            text = text[: -len(terminator)]
    return text


# Default delay cadence mirrored from search-website/src/views/ai-sdr/workflow.vue:
# 3 steps at 1h / 3d / 7d. Used when /get/prompt returns an empty list —
# the CLI seeds three skeleton rows so /save/prompt has something to
# anchor on, and so the launch-time completeness check has something to
# report against.
_SEED_DEFAULT_STEPS = [
    {"step": 1, "stepType": "Email", "delayMinutes": 60},
    {"step": 2, "stepType": "Email", "delayMinutes": 4320},
    {"step": 3, "stepType": "Email", "delayMinutes": 10080},
]


def seed_default_steps(client, workflow_id) -> list[dict]:
    """Seed 3 skeleton step rows in ``t_ai_workflow_prompt`` for a flow that
    has none.

    Backend ``/get/prompt`` returns an empty list for freshly-created flows
    whose type does not auto-generate default prompts (e.g. ENROLL). The
    frontend handles this by defaulting to a 3-step pipeline (1h / 3d / 7d)
    in the UI and sending a ``/save/prompt`` request with empty content —
    the backend accepts rows without ``workflowStepId`` (it auto-generates
    PKs for new rows) so this is a supported path.

    After save, the method re-queries ``/get/prompt`` to fetch the newly
    assigned workflowStepIds and returns the resulting steps list,
    ready for a subsequent regenerate pass.
    """
    prompts = [
        {
            **skel,
            "emailSubject": "",
            "emailContent": "",
            "subject": "",
            "content": "",
        }
        for skel in _SEED_DEFAULT_STEPS
    ]
    client.save_prompt(workflow_id, prompts)
    # Re-query so we have the new step IDs for the regenerate pass.
    return extract_prompt_steps(client.get_workflow_prompt(workflow_id))


def regenerate_step_content(
    client,
    workflow_id,
    steps: list[dict],
    timeout: int = 120,
) -> list[dict]:
    """Per-step LLM fill (``--regenerate-emails``): parse SSE from
    ``/get/email/prompt`` into ``emailContent``.

    For each step:
      POST /get/email/prompt with beforStep carrying the prior steps'
      ``emailSubject`` / ``emailContent`` history (mirrors
      search-website/src/views/ai-sdr/components/typing-effect.vue:211-218).

    The response is a text/event-stream: one JSON event per line. Events
    of ``type=content`` are concatenated into the final ``emailContent``
    prompt template. That template is what the scheduler later feeds
    (together with per-contact data) into the AI service to produce the
    actual email at send time.

    ``/get/email`` (the sample subject+content preview) is intentionally
    NOT called here — the upstream ai-sdr service routinely exceeds the
    Cloudflare 90s edge timeout and returns HTML 504 responses, which
    breaks --regenerate-emails for the whole run. The sample fields
    (``subject`` / ``content``) are left blank; the frontend's own launch
    flow ships them blank too for step 1 / step 3 of the default 3-step
    pipeline, so this is consistent with the web UI behaviour.

    IMPORTANT: this call **deliberately omits ``workflowStepId``** from
    the request body. Dubbo's ``/get/email/prompt`` short-circuits when
    ``workflowStepId`` is provided AND the row already exists — it
    returns the saved ``emailContent`` verbatim (even if empty), skipping
    the LLM path. Since regenerate is meant to *replace* empty seed rows
    with fresh LLM content, we must force the generation path by leaving
    the step id out. The id is still kept on the step dict internally so
    the subsequent ``/save/prompt`` can UPDATE the correct row.

    Mutates copies of the step dicts; returns the updated list. Per-step
    failures are logged to stderr and that step's emailContent is left
    as-is (empty if fresh seed), so one flaky step doesn't abort the pass.
    """
    import time
    import requests as _requests

    url = client._url_discover("/api/v1/ai/workflow/get/email/prompt")
    max_attempts = 3
    updated = []
    before_step = []
    for s in steps:
        new_s = dict(s)
        step_label = new_s.get("step") or (len(updated) + 1)

        # Retry transient upstream failures (502/503/504, connection errors).
        # The ai-sdr-svc + Cloudflare edge chain is flaky on test env; one
        # retry per step catches the common intermittent failures without
        # ballooning runtime.
        last_err = None
        prompt_text = ""
        for attempt in range(1, max_attempts + 1):
            try:
                # NB: no ``workflowStepId`` — see docstring "IMPORTANT" note.
                body = {"workflowId": workflow_id, "beforStep": before_step}
                resp = _requests.post(
                    url, json=body, headers=client._headers(), timeout=timeout,
                )
                resp.raise_for_status()
                prompt_text = _parse_sse_content(resp.text)
                if prompt_text:
                    # Cap to the t_ai_workflow_prompt.email_content TEXT
                    # column ceiling (with headroom). Without this, long
                    # LLM templates trigger MySQL "Data truncation: Data
                    # too long for column 'email_content'" — backend
                    # returns it as HTTP 200 + body code 400, which is
                    # easy to miss in the wizard log.
                    original_len = len(prompt_text.encode("utf-8"))
                    prompt_text = _truncate_to_byte_limit(prompt_text)
                    if len(prompt_text.encode("utf-8")) < original_len:
                        click.echo(
                            f"  ~ step {step_label}: emailContent truncated "
                            f"from {original_len} to "
                            f"{len(prompt_text.encode('utf-8'))} bytes "
                            f"to fit MySQL TEXT column limit.",
                            err=True,
                        )
                    break
                # Empty response — treat as failure and retry.
                last_err = "empty SSE stream"
            except Exception as e:  # noqa: BLE001
                last_err = str(e)
            if attempt < max_attempts:
                click.echo(
                    f"  ~ step {step_label} attempt {attempt} failed "
                    f"({last_err}); retrying ...",
                    err=True,
                )
                time.sleep(2)

        if prompt_text:
            new_s["emailContent"] = prompt_text
        else:
            click.echo(
                f"  ! step {step_label}: /get/email/prompt failed after "
                f"{max_attempts} attempts — {last_err}",
                err=True,
            )

        updated.append(new_s)
        before_step.append({
            "emailSubject": new_s.get("emailSubject") or "",
            "emailContent": new_s.get("emailContent") or "",
        })
    return updated


# ═══════════════════════════════════════════════════════════
# V2 save/setting body assembly
# ═══════════════════════════════════════════════════════════

def _pick_default_time_block_config() -> dict:
    """Fallback timeTemplateConfig.properties when /get/setting returns an
    empty flow. Matches settings.vue:324-340 hardcoded defaults.
    """
    return {
        "notSendOnUsHolidaysEnabled": 1,
        "useProspectTimezoneEnabled": 1,
        "useDefaultTimezoneEnabled": 1,
        "defaultTimezone": {"id": 106, "timezoneId": "", "displayName": ""},
    }


def _default_email_track() -> dict:
    """Hardcoded emailTrack baseline when /get/setting doesn't supply one.
    Matches settings.vue:285-290 default ref value.
    """
    return {
        "emailUnsubscribe": False,
        "mailSettingTemplateId": None,
        "trackLinkClick": False,
        "trackOpen": False,
        "trackType": "",
        "unsubscribeTemplate": (
            "Don't want to get emails like this? "
            "<%Unsubscribe from our emails%>"
        ),
    }


def patch_meeting_route_id(
    agent_prompt_list: list[dict],
    meeting_router_id,
) -> list[dict]:
    """Inject ``meetingRouteId`` into the Book Meeting entry of an
    agentPromptList (mirrors ai-reply.vue:175+192-194).

    Returns a new list (shallow-copies mutated entry only). Leaves Drive
    Traffic / Qualify Lead / Custom Goal untouched. No-op when the list
    has no Book Meeting entry.
    """
    if not agent_prompt_list or meeting_router_id is None:
        return agent_prompt_list or []
    out = []
    for entry in agent_prompt_list:
        if entry.get("strategy") == "Book Meeting":
            patched = dict(entry)
            patched["meetingRouteId"] = meeting_router_id
            out.append(patched)
        else:
            out.append(entry)
    return out


def build_save_setting_body(
    workflow_id,
    time_template: dict,
    mailbox_list: list[dict],
    setting_response: dict,
    auto_approve: bool,
    *,
    enable_agent_reply: Optional[bool] = None,
    agent_strategy: Optional[str] = None,
    meeting_router_id=None,
) -> dict:
    """Assemble the full ``/save/setting`` body from its inputs.

    Mirrors search-website/src/views/ai-sdr/settings.vue:317-356.

    Sources:
      * ``time_template`` — picked via :func:`pick_default_time_template`
        (``/engage/api/v1/time/template/list``)
      * ``mailbox_list`` — ``[{"addressId": ...}, ...]`` from the mailbox
        selection wizard step
      * ``setting_response`` — JSON from ``/get/setting/{flow_id}``; supplies
        ``agentPromptList``, ``emailTrack``, ``enableAgentReply``,
        ``agentStrategy``, ``isShowAiReply``. For a DRAFT flow it may have
        most of these fields missing / null — we fall back to hardcoded
        defaults to match the frontend's initial ref values.
      * ``meeting_router_id`` — first item id from
        ``/meeting/api/v1/meeting/personal/list``; patched into
        ``agentPromptList[Book Meeting].meetingRouteId``.

    ``enable_agent_reply`` / ``agent_strategy`` overrides let the CLI --flag
    take precedence over what /get/setting returned.
    """
    setting = setting_response or {}

    # /get/setting returns ``properties`` at the top level of ``data`` (not
    # nested under ``setting.properties`` as an older doc suggested). The
    # field is only populated for flows that already have a sequenceId
    # (post-launch); DRAFT flows have no properties block.
    existing_props = setting.get("properties") or {}

    # timeTemplateConfig precedence:
    #  1. If the caller supplied a concrete time_template (non-empty with an
    #     id), use it — this is the CLI "override" path
    #     (aiflow settings-update --time-template-id N).
    #  2. Otherwise, if the flow already has one persisted (ACTIVE/PAUSED
    #     flows after a prior save/setting), reuse it.
    #  3. Otherwise build a fresh config from the picked template + the
    #     hardcoded frontend defaults (fresh-DRAFT create path).
    provided_template = bool((time_template or {}).get("id"))
    if provided_template:
        time_template_config = {
            "name": time_template.get("name", ""),
            "properties": time_template.get("properties")
                          or _pick_default_time_block_config(),
            "timeBlocks": time_template.get("timeBlocks") or [],
        }
        time_template_id = time_template.get("id")
    elif existing_props.get("timeTemplateConfig"):
        time_template_config = existing_props["timeTemplateConfig"]
        time_template_id = existing_props.get("timeTemplateId")
    else:
        time_template_config = {
            "name": (time_template or {}).get("name", ""),
            "properties": (time_template or {}).get("properties")
                          or _pick_default_time_block_config(),
            "timeBlocks": (time_template or {}).get("timeBlocks") or [],
        }
        time_template_id = (time_template or {}).get("id")

    email_track = existing_props.get("emailTrack") or _default_email_track()

    properties = {
        "timeTemplateConfig": time_template_config,
        "emailTrack": email_track,
        "sequenceMailboxList": mailbox_list,
        "timeTemplateId": time_template_id,
    }

    body = {
        "workflowId": workflow_id,
        "properties": properties,
        "autoApprove": bool(auto_approve),
    }

    # Agent-reply block: only included when the backend says the UI would
    # show the AI reply controls (isShowAiReply True for flows created
    # after 2026-02-07). Mirrors settings.vue:348-352.
    if setting.get("isShowAiReply"):
        agent_prompt_list = setting.get("agentPromptList") or []
        if meeting_router_id is not None:
            agent_prompt_list = patch_meeting_route_id(
                agent_prompt_list, meeting_router_id
            )
        body["agentPromptList"] = agent_prompt_list
        body["enableAgentReply"] = (
            enable_agent_reply
            if enable_agent_reply is not None
            else bool(setting.get("enableAgentReply"))
        )
        body["agentStrategy"] = (
            agent_strategy
            if agent_strategy is not None
            else (setting.get("agentStrategy") or "")
        )

    return body


def pick_first_meeting_router_id(meetings_response: dict):
    """Return the ``id`` of the first meeting router in a personal list
    response, or ``None`` if the account has no meeting routers yet.

    Mirrors ai-reply.vue:192-194:
        if MEETING_ROUTERS.length && !selectedRouter:
            selectedRouter = MEETING_ROUTERS[0].id
    """
    items = (meetings_response or {}).get("data") or []
    if not items:
        return None
    return items[0].get("id")
