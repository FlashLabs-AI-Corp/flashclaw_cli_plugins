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
