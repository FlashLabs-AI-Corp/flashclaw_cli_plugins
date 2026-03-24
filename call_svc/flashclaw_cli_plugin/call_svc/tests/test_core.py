"""Unit tests for call-svc CLI core modules — no external dependencies."""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from flashclaw_cli_plugin.call_svc.core.session import (
    get_api_key,
    set_api_key,
    clear_api_key,
    get_base_url,
)
from flashclaw_cli_plugin.call_svc.core.client import CallSvcClient
from flashclaw_cli_plugin.call_svc.utils.output import set_json_mode, is_json_mode

# Gateway base URL used by the CLI
_GATEWAY_PROD = "https://open-ai-api.flashlabs.ai"
_GATEWAY_TEST = "https://open-ai-api-test.eape.mobi"


def _resolve_cli(name="flashclaw-cli-plugin-call-svc"):
    """Resolve installed CLI command; falls back to python -m for dev.

    Set env CLI_ANYTHING_FORCE_INSTALLED=1 to require the installed command.
    """
    force = os.environ.get("CLI_ANYTHING_FORCE_INSTALLED", "").strip() == "1"
    path = shutil.which(name)
    if path:
        print(f"[_resolve_cli] Using installed command: {path}")
        return [path]
    if force:
        raise RuntimeError(
            f"{name} not found in PATH. Install with: pip install -e ."
        )
    module = "flashclaw_cli_plugin.call_svc.call_svc_cli"
    print(f"[_resolve_cli] Falling back to: {sys.executable} -m {module}")
    return [sys.executable, "-m", module]


class TestSession(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.patcher_dir = patch(
            "flashclaw_cli_plugin.call_svc.core.session.CONFIG_DIR",
            new=__import__("pathlib").Path(self.tmpdir),
        )
        self.patcher_env = patch(
            "flashclaw_cli_plugin.call_svc.core.session.ENV_FILE",
            new=__import__("pathlib").Path(self.tmpdir) / ".env",
        )
        self.patcher_cfg = patch(
            "flashclaw_cli_plugin.call_svc.core.session.CONFIG_FILE",
            new=__import__("pathlib").Path(self.tmpdir) / "config.json",
        )
        self.patcher_dir.start()
        self.patcher_env.start()
        self.patcher_cfg.start()

    def tearDown(self):
        patch.stopall()
        shutil.rmtree(self.tmpdir)

    def test_default_base_url_prod(self):
        with patch.dict(os.environ, {"CALL_SVC_ENV": "prod"}, clear=False):
            url = get_base_url()
        self.assertIn("eape.mobi", url)
        self.assertNotIn("test", url)

    def test_default_base_url_test_env(self):
        test_url = "https://open-ai-api-test.eape.mobi"
        with patch.dict(os.environ, {"CALL_SVC_BASE_URL": test_url}, clear=False):
            url = get_base_url()
        self.assertIn("test", url)
        self.assertIn("eape.mobi", url)

    def test_api_key_round_trip(self):
        set_api_key("sk_testkey1234")
        self.assertEqual(get_api_key(), "sk_testkey1234")

    def test_clear_api_key(self):
        set_api_key("sk_testkey1234")
        clear_api_key()
        self.assertIsNone(get_api_key())

    def test_env_var_overrides_file(self):
        set_api_key("sk_from_file")
        with patch.dict(os.environ, {"CALL_SVC_API_KEY": "sk_from_env"}, clear=False):
            self.assertEqual(get_api_key(), "sk_from_env")


class TestClient(unittest.TestCase):
    def test_url_contains_callsvc_prefix(self):
        """All URLs must include /callsvc prefix for gateway routing."""
        c = CallSvcClient(base_url=_GATEWAY_TEST, api_key="sk_test")
        url = c._url("/api/v1/call-number/available-numbers")
        self.assertEqual(
            url,
            f"{_GATEWAY_TEST}/callsvc/api/v1/call-number/available-numbers",
        )

    def test_x_api_key_header_set(self):
        """X-API-Key header must be used (not Authorization Bearer)."""
        c = CallSvcClient(base_url=_GATEWAY_TEST, api_key="sk_testkey")
        headers = c._headers()
        self.assertIn("X-API-Key", headers)
        self.assertEqual(headers["X-API-Key"], "sk_testkey")
        self.assertNotIn("Authorization", headers)

    def test_base_url_trailing_slash_stripped(self):
        c = CallSvcClient(base_url=_GATEWAY_PROD + "/", api_key="sk_x")
        self.assertFalse(c.base_url.endswith("/"))

    @patch("flashclaw_cli_plugin.call_svc.core.client.requests.get")
    def test_available_numbers_calls_gateway_path(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "code": 0,
            "data": {"list": [], "count": 0, "page": 1, "pageSize": 20},
        }
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        c = CallSvcClient(base_url=_GATEWAY_TEST, api_key="sk_test")
        result = c.available_numbers(country_code="us")
        self.assertEqual(result["code"], 0)

        called_url = mock_get.call_args[0][0]
        self.assertIn("/callsvc/api/v1/call-number/available-numbers", called_url)

        called_headers = mock_get.call_args.kwargs.get("headers", {})
        self.assertIn("X-API-Key", called_headers)

    @patch("flashclaw_cli_plugin.call_svc.core.client.requests.get")
    def test_purchased_numbers_calls_gateway_path(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "code": 0,
            "data": [{"companyId": 1, "phoneNumber": "19498665342",
                      "phoneNumberFormat": "+19498665342"}],
        }
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        c = CallSvcClient(base_url=_GATEWAY_TEST, api_key="sk_test")
        result = c.purchased_numbers()
        self.assertEqual(result["code"], 0)

        called_url = mock_get.call_args[0][0]
        self.assertIn("/callsvc/api/v1/call-number/purchased-numbers", called_url)

    @patch("flashclaw_cli_plugin.call_svc.core.client.requests.post")
    def test_buy_number_calls_gateway_path(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "code": 0,
            "data": {"msisdn": "+12125551234", "buyStatus": 1, "hasError": False},
        }
        mock_resp.raise_for_status = MagicMock()
        mock_post.return_value = mock_resp

        c = CallSvcClient(base_url=_GATEWAY_TEST, api_key="sk_test")
        result = c.buy_number({"countryCode": "us"})
        self.assertEqual(result["code"], 0)

        called_url = mock_post.call_args[0][0]
        self.assertIn("/callsvc/api/v1/call-number/buy", called_url)

    @patch("flashclaw_cli_plugin.call_svc.core.client.requests.post")
    def test_voice_call(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"code": 0, "data": True}
        mock_resp.raise_for_status = MagicMock()
        mock_post.return_value = mock_resp

        c = CallSvcClient(base_url=_GATEWAY_TEST, api_key="sk_test")
        result = c.voice_call({"fromNumber": "+12125551234", "toNumber": "+8613800138000"})
        self.assertEqual(result["code"], 0)

        called_url = mock_post.call_args[0][0]
        self.assertIn("/callsvc/api/v1/call-number/voice-call", called_url)


class TestOutputMode(unittest.TestCase):
    def test_json_mode_toggle(self):
        set_json_mode(True)
        self.assertTrue(is_json_mode())
        set_json_mode(False)
        self.assertFalse(is_json_mode())


class TestCLISubprocess(unittest.TestCase):
    """Test the installed CLI command via subprocess."""

    CLI_BASE = _resolve_cli()

    def _run(self, args, check=False):
        return subprocess.run(
            self.CLI_BASE + args,
            capture_output=True, text=True, timeout=15,
        )

    def test_help(self):
        result = self._run(["--help"])
        self.assertEqual(result.returncode, 0)
        self.assertIn("Agent-friendly CLI", result.stdout)

    def test_config_show_json(self):
        result = self._run(["--json", "config", "show"])
        self.assertEqual(result.returncode, 0)
        data = json.loads(result.stdout)
        self.assertIn("base_url", data)

    def test_health_json(self):
        result = self._run(["--json", "health"])
        self.assertEqual(result.returncode, 0)
        data = json.loads(result.stdout)
        self.assertIn("base_url", data)

    def test_auth_status_json(self):
        result = self._run(["--json", "auth", "status"])
        self.assertEqual(result.returncode, 0)
        data = json.loads(result.stdout)
        self.assertIn("configured", data)

    def test_number_help(self):
        result = self._run(["number", "--help"])
        self.assertEqual(result.returncode, 0)
        self.assertIn("list", result.stdout)
        self.assertIn("available", result.stdout)
        self.assertIn("buy", result.stdout)


if __name__ == "__main__":
    unittest.main()
