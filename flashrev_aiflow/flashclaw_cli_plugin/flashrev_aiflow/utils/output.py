"""Output formatting utilities — JSON / human-readable."""

import json
import sys

import click


_JSON_MODE = False


def set_json_mode(enabled: bool):
    global _JSON_MODE
    _JSON_MODE = enabled


def is_json_mode() -> bool:
    return _JSON_MODE


def emit(data, human_formatter=None):
    """Emit data in JSON or human-readable format.

    Args:
        data: dict or list to output.
        human_formatter: optional callable(data) -> str for human mode.
    """
    if _JSON_MODE:
        click.echo(json.dumps(data, indent=2, ensure_ascii=False, default=str))
    elif human_formatter:
        click.echo(human_formatter(data))
    else:
        click.echo(json.dumps(data, indent=2, ensure_ascii=False, default=str))


def emit_error(message: str, code: str = "ERROR", details: dict = None):
    """Emit error in a structured way."""
    err = {"ok": False, "error": code, "message": message}
    if details:
        err["details"] = details
    if _JSON_MODE:
        click.echo(json.dumps(err, ensure_ascii=False), err=True)
    else:
        click.secho(f"Error: {message}", fg="red", err=True)
        if details:
            click.echo(json.dumps(details, indent=2, ensure_ascii=False), err=True)
    sys.exit(1)
