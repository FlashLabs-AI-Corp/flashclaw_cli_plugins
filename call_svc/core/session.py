"""Session management — API Key storage (.env) and config (config.json).

请求链路：
  CLI  --[X-API-Key]-→  auth-gateway-svc  --[Bearer token + X-Auth-Company]-→  call-svc

Credential file:  ~/.claude/skills/call-svc-assistant/.env   (chmod 600)
Config file:      ~/.claude/skills/call-svc-assistant/config.json

Priority (high -> low): env var > .env > config.json > code default
"""

import json
import os
import stat
from pathlib import Path

CONFIG_DIR = Path.home() / ".claude" / "skills" / "call-svc-assistant"
ENV_FILE = CONFIG_DIR / ".env"
CONFIG_FILE = CONFIG_DIR / "config.json"

ENV_PRESETS = {
    "prod": {
        "base_url": "https://open-ai-api.flashlabs.ai",
    },
    "test": {
        "base_url": "https://open-ai-api-test.eape.mobi",
    },
}

CALL_SVC_ENV = os.environ.get("CALL_SVC_ENV", "prod")
_urls = ENV_PRESETS.get(CALL_SVC_ENV, ENV_PRESETS["prod"])

DEFAULTS = {
    **_urls,
    "timeout": 30,
}

ENV_VAR_MAP = {
    "CALL_SVC_API_KEY": "api_key",
    "CALL_SVC_BASE_URL": "base_url",
    "CALL_SVC_TIMEOUT": "timeout",
}


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
    os.chmod(ENV_FILE, stat.S_IRUSR | stat.S_IWUSR)  # 600


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
    env_key = os.environ.get("CALL_SVC_API_KEY")
    if env_key:
        return env_key
    return _read_env_file().get("CALL_SVC_API_KEY")


def set_api_key(api_key: str):
    """Save API key to .env file (chmod 600)."""
    env_data = _read_env_file()
    env_data["CALL_SVC_API_KEY"] = api_key
    _write_env_file(env_data)


def clear_api_key():
    """Remove API key from .env file."""
    env_data = _read_env_file()
    env_data.pop("CALL_SVC_API_KEY", None)
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
    env_prefix = f"CALL_SVC_{key.upper()}"
    if env_prefix in env_data:
        val = env_data[env_prefix]
        if key == "timeout":
            return int(val)
        return val

    config = load_config()
    return config.get(key, DEFAULTS.get(key))


def get_base_url() -> str:
    """Get the auth-gateway-svc base URL."""
    return get_config_value("base_url").rstrip("/")


def get_timeout() -> int:
    return get_config_value("timeout")
