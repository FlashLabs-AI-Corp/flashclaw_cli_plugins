"""Session management — API Key storage (.env) and config (config.json).

Request chain:
  CLI  --[X-API-Key]->  auth-gateway-svc  --[Bearer + X-Auth-Company]->  FlashRev services
                                               |-- discover-api  (no path prefix, routed via discover_prefix)
                                               |-- engage-api    (path prefix /engage)
                                               |-- mailsvc       (path prefix /mailsvc)
                                               |-- meeting-svc   (routed via meeting_prefix, default /meeting)

Credential file:  ~/.claude/skills/flashrev-aiflow-assistant/.env      (chmod 600)
Config file:      ~/.claude/skills/flashrev-aiflow-assistant/config.json

Priority (high -> low): env var > .env > config.json > code default

API Key env var is FLASHREV_SVC_API_KEY, shared across all FlashRev skills that
route through the same auth-gateway-svc.
"""

import json
import os
import stat
from pathlib import Path

CONFIG_DIR = Path.home() / ".claude" / "skills" / "flashrev-aiflow-assistant"
ENV_FILE = CONFIG_DIR / ".env"
CONFIG_FILE = CONFIG_DIR / "config.json"

# auth-gateway-svc base URLs per environment. FlashRev services are NOT called
# directly; requests go through the gateway which swaps X-API-Key for a
# Bearer token and forwards to the upstream service (discover / engage / mailsvc).
ENV_PRESETS = {
    "prod": {
        "base_url": "https://open-ai-api.flashlabs.ai",
    },
    "test": {
        "base_url": "https://open-ai-api-test.eape.mobi",
    },
}

FLASHREV_AIFLOW_ENV = os.environ.get("FLASHREV_AIFLOW_ENV", "prod")
_urls = ENV_PRESETS.get(FLASHREV_AIFLOW_ENV, ENV_PRESETS["prod"])

# Gateway routing prefixes.
#   discover_prefix — prepended to every discover-api path. Discover's own
#                     paths have no natural prefix (they start with /api/v1,
#                     /api/v2), so we add one here to let auth-gateway-svc
#                     route the request. MUST match the prefix configured
#                     in auth-gateway-svc/config-*.yaml under proxy.routes.
#   engage_prefix   — usually empty because engage-api paths already begin
#                     with /engage/...
#   mailsvc_prefix  — usually empty because mailsvc paths already begin
#                     with /mailsvc/...
DEFAULTS = {
    **_urls,
    "timeout": 300,
    "discover_prefix": "/flashrev",
    "engage_prefix": "",
    "mailsvc_prefix": "",
    "meeting_prefix": "/meeting-svc",
}

ENV_VAR_MAP = {
    "FLASHREV_SVC_API_KEY": "api_key",
    "FLASHREV_AIFLOW_BASE_URL": "base_url",
    "FLASHREV_AIFLOW_TIMEOUT": "timeout",
    "FLASHREV_AIFLOW_DISCOVER_PREFIX": "discover_prefix",
    "FLASHREV_AIFLOW_ENGAGE_PREFIX": "engage_prefix",
    "FLASHREV_AIFLOW_MAILSVC_PREFIX": "mailsvc_prefix",
    "FLASHREV_AIFLOW_MEETING_PREFIX": "meeting_prefix",
}

# Name of the env var we read the API key from. Kept as a constant so that
# callers (and tests) don't hardcode the string.
API_KEY_ENV_VAR = "FLASHREV_SVC_API_KEY"


def _ensure_config_dir():
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)


def _read_env_file() -> dict:
    """Read key=value pairs from .env file."""
    result = {}
    if ENV_FILE.exists():
        with open(ENV_FILE, "r") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    key, value = line.split("=", 1)
                    result[key.strip()] = value.strip()
    return result


def _write_env_file(data: dict):
    """Write key=value pairs to .env file with chmod 600."""
    _ensure_config_dir()
    with open(ENV_FILE, "w") as f:
        for key, value in data.items():
            f.write(f"{key}={value}\n")
    try:
        os.chmod(ENV_FILE, stat.S_IRUSR | stat.S_IWUSR)  # 600 (POSIX only)
    except (OSError, NotImplementedError):
        # Windows doesn't map chmod cleanly; skip silently.
        pass


def load_config() -> dict:
    """Load config.json, returning defaults if not present."""
    _ensure_config_dir()
    if CONFIG_FILE.exists():
        with open(CONFIG_FILE, "r") as f:
            stored = json.load(f)
        merged = dict(DEFAULTS)
        merged.update(stored)
        return merged
    return dict(DEFAULTS)


def save_config(config: dict):
    """Persist config.json."""
    _ensure_config_dir()
    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=2)


def get_api_key() -> str | None:
    """Get API key following priority: env var > .env > None."""
    env_key = os.environ.get(API_KEY_ENV_VAR)
    if env_key:
        return env_key
    return _read_env_file().get(API_KEY_ENV_VAR)


def set_api_key(api_key: str):
    """Save API key to .env file (chmod 600 on POSIX)."""
    env_data = _read_env_file()
    env_data[API_KEY_ENV_VAR] = api_key
    _write_env_file(env_data)


def clear_api_key():
    """Remove API key from .env file."""
    env_data = _read_env_file()
    env_data.pop(API_KEY_ENV_VAR, None)
    _write_env_file(env_data)


def get_config_value(key: str):
    """Get a config value following priority: env var > .env > config.json > default."""
    for env_var, config_key in ENV_VAR_MAP.items():
        if config_key == key:
            env_val = os.environ.get(env_var)
            if env_val is not None:
                if key == "timeout":
                    return int(env_val)
                return env_val

    env_data = _read_env_file()
    env_prefix = f"FLASHREV_AIFLOW_{key.upper()}"
    if env_prefix in env_data:
        val = env_data[env_prefix]
        if key == "timeout":
            return int(val)
        return val

    config = load_config()
    return config.get(key, DEFAULTS.get(key))


def unset_config_value(key: str):
    """Remove a key from config.json (revert to default on next read)."""
    _ensure_config_dir()
    if not CONFIG_FILE.exists():
        return
    with open(CONFIG_FILE, "r") as f:
        stored = json.load(f)
    stored.pop(key, None)
    with open(CONFIG_FILE, "w") as f:
        json.dump(stored, f, indent=2)


def get_base_url() -> str:
    """Get the auth-gateway-svc base URL."""
    return get_config_value("base_url").rstrip("/")


def get_timeout() -> int:
    return get_config_value("timeout")


def get_discover_prefix() -> str:
    """Gateway prefix for discover-api routes. Default '/flashrev'."""
    val = get_config_value("discover_prefix") or ""
    return val.rstrip("/")


def get_engage_prefix() -> str:
    """Gateway prefix for engage-api routes. Default '' (paths already start with /engage)."""
    val = get_config_value("engage_prefix") or ""
    return val.rstrip("/")


def get_mailsvc_prefix() -> str:
    """Gateway prefix for mailsvc routes. Default '' (paths already start with /mailsvc)."""
    val = get_config_value("mailsvc_prefix") or ""
    return val.rstrip("/")


def get_meeting_prefix() -> str:
    """Gateway prefix for meeting-svc routes. Default '/meeting-svc'.

    The auth-gateway-svc route ``/meeting-svc`` targets the bare meeting-svc
    domain (``https://meeting-api-test.eape.mobi`` on test/dev,
    ``https://meeting-api.flashintel.ai`` on prod). After gateway
    TrimPrefix, the full path (including the native ``/meeting/...``
    segment that meeting-svc itself serves) is kept in the CLI client,
    mirroring how ``/flashrev`` is wired against the bare discover-api
    domain.
    """
    val = get_config_value("meeting_prefix") or ""
    return val.rstrip("/")
