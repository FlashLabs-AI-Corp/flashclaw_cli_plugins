"""Unit tests for flashrev_aiflow core modules.

Covered:
  - session: API Key + config round-trip, env var priority, unset_config_value
  - client:  URL building for discover / engage / mailsvc, X-API-Key header
             injection, core endpoint wiring (mocked requests)
"""

import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import click


class TestSession(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.patcher_dir = patch(
            "flashclaw_cli_plugin.flashrev_aiflow.core.session.CONFIG_DIR",
            new=Path(self.tmpdir),
        )
        self.patcher_env = patch(
            "flashclaw_cli_plugin.flashrev_aiflow.core.session.ENV_FILE",
            new=Path(self.tmpdir) / ".env",
        )
        self.patcher_cfg = patch(
            "flashclaw_cli_plugin.flashrev_aiflow.core.session.CONFIG_FILE",
            new=Path(self.tmpdir) / "config.json",
        )
        self.patcher_dir.start()
        self.patcher_env.start()
        self.patcher_cfg.start()

    def tearDown(self):
        patch.stopall()
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_api_key_round_trip(self):
        from flashclaw_cli_plugin.flashrev_aiflow.core.session import (
            clear_api_key,
            get_api_key,
            set_api_key,
        )

        set_api_key("sk_testkey_1234")
        self.assertEqual(get_api_key(), "sk_testkey_1234")
        clear_api_key()
        self.assertIsNone(get_api_key())

    def test_env_var_priority_over_dotenv(self):
        from flashclaw_cli_plugin.flashrev_aiflow.core.session import (
            get_api_key,
            set_api_key,
        )

        set_api_key("sk_from_dotenv")
        with patch.dict("os.environ", {"FLASHREV_SVC_API_KEY": "sk_from_env"}):
            self.assertEqual(get_api_key(), "sk_from_env")

    def test_config_round_trip_and_unset(self):
        from flashclaw_cli_plugin.flashrev_aiflow.core.session import (
            load_config,
            save_config,
            unset_config_value,
        )

        cfg = load_config()
        cfg["timeout"] = 42
        cfg["discover_prefix"] = "/custom"
        save_config(cfg)

        cfg2 = load_config()
        self.assertEqual(cfg2["timeout"], 42)
        self.assertEqual(cfg2["discover_prefix"], "/custom")

        unset_config_value("discover_prefix")
        cfg3 = load_config()
        self.assertEqual(cfg3["discover_prefix"], "/flashrev")  # default
        self.assertEqual(cfg3["timeout"], 42)  # unchanged

    def test_prefix_getters_defaults(self):
        from flashclaw_cli_plugin.flashrev_aiflow.core.session import (
            get_discover_prefix,
            get_engage_prefix,
            get_mailsvc_prefix,
        )

        self.assertEqual(get_discover_prefix(), "/flashrev")
        self.assertEqual(get_engage_prefix(), "")
        self.assertEqual(get_mailsvc_prefix(), "")


class TestClientUrlBuilding(unittest.TestCase):
    def setUp(self):
        from flashclaw_cli_plugin.flashrev_aiflow.core.client import (
            FlashrevAiflowClient,
        )

        self.client = FlashrevAiflowClient(
            base_url="https://gateway.example.com",
            api_key="sk_test",
        )
        # Force known prefixes regardless of local config.
        self.client.discover_prefix = "/flashrev"
        self.client.engage_prefix = ""
        self.client.mailsvc_prefix = ""

    def test_discover_url_prepends_prefix(self):
        url = self.client._url_discover("/api/v1/ai/workflow/agent/list")
        self.assertEqual(
            url,
            "https://gateway.example.com/flashrev/api/v1/ai/workflow/agent/list",
        )

    def test_engage_url_keeps_native_prefix(self):
        url = self.client._url_engage("/engage/api/mailbox-pool/detail/abc")
        self.assertEqual(
            url,
            "https://gateway.example.com/engage/api/mailbox-pool/detail/abc",
        )

    def test_mailsvc_url_keeps_native_prefix(self):
        url = self.client._url_mailsvc("/mailsvc/mail-address/simple/v2/list")
        self.assertEqual(
            url,
            "https://gateway.example.com/mailsvc/mail-address/simple/v2/list",
        )

    def test_headers_include_x_api_key(self):
        headers = self.client._headers()
        self.assertEqual(headers["X-API-Key"], "sk_test")
        self.assertEqual(headers["Content-Type"], "application/json")


class TestClientEndpoints(unittest.TestCase):
    def setUp(self):
        from flashclaw_cli_plugin.flashrev_aiflow.core.client import (
            FlashrevAiflowClient,
        )

        self.client = FlashrevAiflowClient(
            base_url="https://gateway.example.com",
            api_key="sk_test",
        )
        self.client.discover_prefix = "/flashrev"
        self.client.engage_prefix = ""
        self.client.mailsvc_prefix = ""

    def _mock_response(self, payload):
        r = MagicMock()
        r.raise_for_status = MagicMock()
        r.json.return_value = payload
        r.content = json.dumps(payload).encode()
        return r

    @patch("flashclaw_cli_plugin.flashrev_aiflow.core.client.requests.get")
    def test_list_aiflows_calls_expected_url(self, mock_get):
        mock_get.return_value = self._mock_response({"code": 200, "data": []})

        self.client.list_aiflows({"status": "running"})

        called_url = mock_get.call_args[0][0]
        self.assertIn("/flashrev/api/v1/ai/workflow/agent/list", called_url)
        self.assertEqual(
            mock_get.call_args[1]["params"], {"status": "running"}
        )

    @patch("flashclaw_cli_plugin.flashrev_aiflow.core.client.requests.get")
    def test_whoami_hits_me_endpoint(self, mock_get):
        mock_get.return_value = self._mock_response(
            {"code": 200, "data": {"email": "a@b.c"}}
        )

        result = self.client.get_user_info()

        self.assertEqual(result["data"]["email"], "a@b.c")
        called_url = mock_get.call_args[0][0]
        self.assertIn("/flashrev/api/v2/oauth/me", called_url)

    @patch("flashclaw_cli_plugin.flashrev_aiflow.core.client.requests.get")
    def test_list_mailboxes_uses_mailsvc_path(self, mock_get):
        mock_get.return_value = self._mock_response({"code": 200, "data": []})

        self.client.list_mailboxes()

        called_url = mock_get.call_args[0][0]
        self.assertIn("/mailsvc/mail-address/simple/v2/list", called_url)
        # Must NOT be prefixed with /flashrev (that's only for discover).
        self.assertNotIn("/flashrev/mailsvc", called_url)

    @patch("flashclaw_cli_plugin.flashrev_aiflow.core.client.requests.post")
    def test_test_website_connection_uses_20s_timeout(self, mock_post):
        mock_post.return_value = self._mock_response({"code": 200})

        self.client.test_website_connection("https://acme.com")

        self.assertEqual(mock_post.call_args[1]["timeout"], 20)
        self.assertEqual(
            mock_post.call_args[1]["json"], {"url": "https://acme.com"}
        )


class TestTokenBalance(unittest.TestCase):
    def setUp(self):
        from flashclaw_cli_plugin.flashrev_aiflow.core.client import (
            FlashrevAiflowClient,
        )

        self.client = FlashrevAiflowClient(
            base_url="https://gateway.example.com",
            api_key="sk_test",
        )
        self.client.discover_prefix = "/flashrev"

    def _mock_response(self, payload):
        r = MagicMock()
        r.raise_for_status = MagicMock()
        r.json.return_value = payload
        r.content = json.dumps(payload).encode()
        return r

    @patch("flashclaw_cli_plugin.flashrev_aiflow.core.client.requests.get")
    def test_get_token_balance_computes_remaining(self, mock_get):
        mock_get.return_value = self._mock_response({
            "code": 200,
            "data": {
                "limit": {"tokenTotal": 11580283, "tokenCost": 7291284}
            },
        })

        bal = self.client.get_token_balance()

        self.assertEqual(bal["tokenTotal"], 11580283.0)
        self.assertEqual(bal["tokenCost"], 7291284.0)
        self.assertEqual(bal["tokenRemaining"], 4288999.0)
        self.assertTrue(bal["sufficient"])

    @patch("flashclaw_cli_plugin.flashrev_aiflow.core.client.requests.get")
    def test_get_token_balance_handles_missing_cost_as_zero(self, mock_get):
        mock_get.return_value = self._mock_response({
            "code": 200,
            "data": {"limit": {"tokenTotal": 1000}},
        })

        bal = self.client.get_token_balance()

        self.assertEqual(bal["tokenCost"], 0.0)
        self.assertEqual(bal["tokenRemaining"], 1000.0)
        self.assertTrue(bal["sufficient"])

    @patch("flashclaw_cli_plugin.flashrev_aiflow.core.client.requests.get")
    def test_get_token_balance_marks_exhausted(self, mock_get):
        mock_get.return_value = self._mock_response({
            "code": 200,
            "data": {"limit": {"tokenTotal": 100, "tokenCost": 100}},
        })

        bal = self.client.get_token_balance()

        self.assertEqual(bal["tokenRemaining"], 0.0)
        self.assertFalse(bal["sufficient"])

    @patch("flashclaw_cli_plugin.flashrev_aiflow.core.client.requests.get")
    def test_get_token_balance_raises_on_missing_limit_total(self, mock_get):
        mock_get.return_value = self._mock_response({
            "code": 200, "data": {"limit": {}},
        })

        with self.assertRaises(ValueError):
            self.client.get_token_balance()


class TestWizardHelpers(unittest.TestCase):
    """Wizard logic: CSV parsing, heuristics, pitch schema, mailbox filtering."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _write_csv(self, name, content_bytes):
        p = Path(self.tmpdir) / name
        p.write_bytes(content_bytes)
        return p

    def test_preview_csv_parses_utf8_bom_and_dedupes_emails(self):
        from flashclaw_cli_plugin.flashrev_aiflow import wizard

        # utf-8-sig BOM in front of the header row.
        content = (
            "\ufeffname,email,country\n"
            "Alice,a@b.com,US\n"
            "Bob,b@c.com,CA\n"
            "Alice dup,a@b.com,US\n"
        ).encode("utf-8")
        p = self._write_csv("contacts.csv", content)

        columns, rows, total, unique = wizard.preview_csv(p)

        self.assertEqual(columns, ["name", "email", "country"])
        self.assertEqual(total, 3)
        self.assertEqual(unique, 2)  # a@b.com counted once
        self.assertEqual(len(rows), 3)

    def test_preview_csv_rejects_missing_email_column(self):
        from flashclaw_cli_plugin.flashrev_aiflow import wizard

        p = self._write_csv("bad.csv", b"name,country\nAlice,US\n")

        with self.assertRaises(click.UsageError):
            wizard.preview_csv(p)

    def test_detect_country_column_prefers_exact_match(self):
        from flashclaw_cli_plugin.flashrev_aiflow import wizard

        self.assertEqual(
            wizard.detect_country_column(["name", "country", "city"]),
            "country",
        )
        self.assertEqual(
            wizard.detect_country_column(["姓名", "邮箱", "国家"]),
            "国家",
        )
        self.assertEqual(
            wizard.detect_country_column(["name", "region_code"]),
            "region_code",
        )
        self.assertIsNone(
            wizard.detect_country_column(["name", "email", "age"])
        )

    def test_validate_pitch_schema_round_trip(self):
        from flashclaw_cli_plugin.flashrev_aiflow import wizard

        good = {
            "officialDescription": "A short value prop.",
            "painPoints": ["p1", "p2"],
            "solutions": ["s1"],
            "proofPoints": [],
            "callToActions": ["book a demo"],
            "leadMagnets": [],
        }
        out = wizard.validate_pitch_schema(good)
        self.assertEqual(out["officialDescription"], "A short value prop.")
        self.assertEqual(out["painPoints"], ["p1", "p2"])

    def test_validate_pitch_schema_rejects_bad_list_type(self):
        from flashclaw_cli_plugin.flashrev_aiflow import wizard

        with self.assertRaises(click.UsageError):
            wizard.validate_pitch_schema({"painPoints": "not-a-list"})

    def test_parse_google_sheet_url_extracts_id_and_gid(self):
        from flashclaw_cli_plugin.flashrev_aiflow import wizard

        url = (
            "https://docs.google.com/spreadsheets/d/AbCd123/edit#gid=7890"
        )
        sid, gid = wizard._parse_google_sheet_url(url)
        self.assertEqual(sid, "AbCd123")
        self.assertEqual(gid, "7890")

    def test_filter_active_mailboxes_keeps_active_only(self):
        from flashclaw_cli_plugin.flashrev_aiflow import wizard

        resp = {
            "code": 200,
            "data": [
                {"id": "m1", "address": "a@x.com", "status": "ACTIVE"},
                {"id": "m2", "address": "b@x.com", "status": "INACTIVE"},
                {"id": "m3", "address": "c@x.com"},  # missing status -> kept
            ],
        }
        actives = wizard.filter_active_mailboxes(resp)
        ids = [m["id"] for m in actives]
        self.assertIn("m1", ids)
        self.assertIn("m3", ids)
        self.assertNotIn("m2", ids)

    def test_mailbox_id_picks_address_id_first(self):
        from flashclaw_cli_plugin.flashrev_aiflow import wizard

        self.assertEqual(
            wizard.mailbox_id({"addressId": "A", "id": "B"}), "A"
        )
        self.assertEqual(wizard.mailbox_id({"id": "B"}), "B")
        self.assertIsNone(wizard.mailbox_id({}))


class TestNewClientEndpoints(unittest.TestCase):
    def setUp(self):
        from flashclaw_cli_plugin.flashrev_aiflow.core.client import (
            FlashrevAiflowClient,
        )

        self.client = FlashrevAiflowClient(
            base_url="https://gateway.example.com",
            api_key="sk_test",
        )
        self.client.discover_prefix = "/flashrev"

    def _mock_response(self, payload):
        r = MagicMock()
        r.raise_for_status = MagicMock()
        r.json.return_value = payload
        r.content = json.dumps(payload).encode()
        return r

    @patch("flashclaw_cli_plugin.flashrev_aiflow.core.client.requests.post")
    def test_upload_contacts_csv_posts_multipart(self, mock_post):
        tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".csv", delete=False, encoding="utf-8"
        )
        tmp.write("email\na@b.com\n")
        tmp.close()
        try:
            # Backend contract: listId is a Long (JSON number), not a string.
            # The CLI treats it opaquely, so the test exercises that.
            mock_post.return_value = self._mock_response({
                "code": 200,
                "data": {"listId": 12345, "listName": "x.csv"},
            })

            out = self.client.upload_contacts_csv(tmp.name)

            self.assertEqual(out["data"]["listId"], 12345)
            called_url = mock_post.call_args[0][0]
            self.assertIn(
                "/flashrev/api/v1/ai/workflow/contacts/upload",
                called_url,
            )
            # Multipart path: requests receives `files=` and `data=`.
            self.assertIn("files", mock_post.call_args[1])
            self.assertEqual(
                mock_post.call_args[1]["data"], {"dataType": "People"}
            )
            # Content-Type must not be forced (requests sets the boundary).
            self.assertNotIn(
                "Content-Type", mock_post.call_args[1]["headers"]
            )
        finally:
            Path(tmp.name).unlink(missing_ok=True)

    @patch("flashclaw_cli_plugin.flashrev_aiflow.core.client.requests.post")
    def test_create_aiflow_from_list_posts_expected_body(self, mock_post):
        mock_post.return_value = self._mock_response({
            "code": 200, "data": {"id": "af_abc"},
        })

        out = self.client.create_aiflow_from_list({
            "listId": 12345,  # Long, per AiWorkFlowListCreateDTO.listId
            "listName": "y.csv",
            "type": "csv", "source": "csv",
        })

        self.assertEqual(out["data"]["id"], "af_abc")
        called_url = mock_post.call_args[0][0]
        self.assertIn("/flashrev/api/v1/ai/workflow/create/list", called_url)
        body = mock_post.call_args[1]["json"]
        self.assertEqual(body["type"], "csv")
        self.assertEqual(body["source"], "csv")

    @patch("flashclaw_cli_plugin.flashrev_aiflow.core.client.requests.post")
    def test_email_config_endpoints(self, mock_post):
        mock_post.return_value = self._mock_response({"code": 200})

        self.client.get_email_config({"workflowId": "f1"})
        self.assertIn(
            "/flashrev/api/v1/ai/workflow/agent/get/email/config",
            mock_post.call_args[0][0],
        )

        self.client.save_email_config({
            "workflowId": "f1", "properties": {}, "autoApprove": True,
        })
        self.assertIn(
            "/flashrev/api/v1/ai/workflow/agent/save/email/config",
            mock_post.call_args[0][0],
        )


class TestCreateNoWizard(unittest.TestCase):
    """Flag-matrix + dry-run contract for `aiflow create --no-wizard`."""

    def setUp(self):
        from click.testing import CliRunner

        from flashclaw_cli_plugin.flashrev_aiflow import flashrev_aiflow_cli

        self.runner = CliRunner()
        self.cli = flashrev_aiflow_cli.cli

        # Every invocation needs an API key; patch the session getter.
        self.key_patch = patch(
            "flashclaw_cli_plugin.flashrev_aiflow."
            "flashrev_aiflow_cli.get_api_key",
            return_value="sk_test",
        )
        self.key_patch.start()

        # Point the client factory at a stub so no real HTTP ever fires.
        self.client_stub = MagicMock()
        self.client_stub.list_mailboxes.return_value = {
            "code": 200,
            "data": [
                {"id": "m1", "address": "a@x.com", "status": "ACTIVE"},
                {"id": "m2", "address": "b@x.com", "status": "ACTIVE"},
            ],
        }
        self.client_stub.get_time_template.return_value = {
            "code": 200, "data": {"emails": []},
        }
        self.client_stub.get_token_balance.return_value = {
            "tokenTotal": 100.0,
            "tokenCost": 10.0,
            "tokenRemaining": 90.0,
            "sufficient": True,
        }
        self.build_patch = patch(
            "flashclaw_cli_plugin.flashrev_aiflow."
            "flashrev_aiflow_cli._build_client",
            return_value=self.client_stub,
        )
        self.build_patch.start()

        # Write a valid CSV + pitch file for the happy-path dry-run.
        self.tmpdir = tempfile.mkdtemp()
        self.csv_path = Path(self.tmpdir) / "contacts.csv"
        self.csv_path.write_text(
            "name,email,country\nAlice,a@b.com,US\nBob,b@c.com,CA\n",
            encoding="utf-8",
        )
        self.pitch_path = Path(self.tmpdir) / "pitch.json"
        self.pitch_path.write_text(
            json.dumps({
                "officialDescription": "A short value prop.",
                "painPoints": ["p1"],
                "solutions": ["s1"],
                "proofPoints": [],
                "callToActions": ["Book a demo"],
                "leadMagnets": [],
                "url": "acme.com",
            }),
            encoding="utf-8",
        )

    def tearDown(self):
        patch.stopall()
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _invoke(self, *args):
        # --json makes emit_error emit the structured {"error": CODE, ...}
        # blob so tests can assert on the code, not the English message.
        return self.runner.invoke(
            self.cli,
            ["--json", "aiflow", "create", *args],
            catch_exceptions=False,
        )

    # ── missing required flags ──────────────────────────────

    def test_no_wizard_errors_when_neither_csv_nor_sheet(self):
        result = self._invoke(
            "--no-wizard", "--pitch-file", str(self.pitch_path),
            "--website", "acme.com",
        )
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("USAGE_CONTACT_SOURCE", result.output)

    def test_no_wizard_errors_when_both_csv_and_sheet(self):
        result = self._invoke(
            "--no-wizard",
            "--csv", str(self.csv_path),
            "--sheet", "https://docs.google.com/spreadsheets/d/x/edit",
            "--pitch-file", str(self.pitch_path),
            "--website", "acme.com",
        )
        self.assertNotEqual(result.exit_code, 0)
        # Either the non-wizard exclusive check or the conflict check fires;
        # both are acceptable (both use USAGE_CONTACT_SOURCE* codes).
        self.assertIn("USAGE_CONTACT_SOURCE", result.output)

    def test_no_wizard_errors_when_pitch_file_missing(self):
        result = self._invoke(
            "--no-wizard",
            "--csv", str(self.csv_path),
            "--website", "acme.com",
        )
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("USAGE_PITCH_FILE_REQUIRED",
                      result.output)

    def test_no_wizard_errors_when_country_column_missing_for_auto(self):
        # language defaults to 'auto' so country-column is required.
        result = self._invoke(
            "--no-wizard",
            "--csv", str(self.csv_path),
            "--pitch-file", str(self.pitch_path),
            "--website", "acme.com",
            "--dry-run",
        )
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("USAGE_COUNTRY_COLUMN_MISSING",
                      result.output)

    def test_no_wizard_errors_when_country_column_not_in_csv(self):
        result = self._invoke(
            "--no-wizard",
            "--csv", str(self.csv_path),
            "--pitch-file", str(self.pitch_path),
            "--website", "acme.com",
            "--country-column", "not_a_real_column",
            "--dry-run",
        )
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("USAGE_COUNTRY_COLUMN_NOT_FOUND",
                      result.output)

    def test_no_wizard_errors_when_mailboxes_filter_matches_nothing(self):
        result = self._invoke(
            "--no-wizard",
            "--csv", str(self.csv_path),
            "--pitch-file", str(self.pitch_path),
            "--website", "acme.com",
            "--country-column", "country",
            "--mailboxes", "nonexistent_id",
            "--dry-run",
        )
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("USAGE_MAILBOX_NO_MATCH",
                      result.output)

    # ── dry-run contract ────────────────────────────────────

    def test_dry_run_does_not_call_write_endpoints(self):
        result = self._invoke(
            "--no-wizard",
            "--csv", str(self.csv_path),
            "--pitch-file", str(self.pitch_path),
            "--website", "acme.com",
            "--country-column", "country",
            "--dry-run",
        )
        self.assertEqual(result.exit_code, 0, msg=result.output)
        # None of the write endpoints must have fired.
        self.client_stub.upload_contacts_csv.assert_not_called()
        self.client_stub.create_aiflow_from_list.assert_not_called()
        self.client_stub.save_pitch.assert_not_called()
        self.client_stub.save_email_config.assert_not_called()
        self.client_stub.set_aiflow_status.assert_not_called()
        # Read-only probes that the summary depends on did fire.
        self.client_stub.list_mailboxes.assert_called_once()
        self.client_stub.get_token_balance.assert_called_once()
        # Summary mentions dry-run.
        self.assertIn("Dry-run complete", result.output)

    def test_dry_run_accepts_url_from_pitch_file(self):
        # Drop --website; pitch file carries 'url': 'acme.com'.
        result = self._invoke(
            "--no-wizard",
            "--csv", str(self.csv_path),
            "--pitch-file", str(self.pitch_path),
            "--country-column", "country",
            "--dry-run",
        )
        self.assertEqual(result.exit_code, 0, msg=result.output)
        self.assertIn("https://acme.com", result.output)

    def test_dry_run_errors_when_url_missing_everywhere(self):
        bare_pitch = Path(self.tmpdir) / "pitch_no_url.json"
        bare_pitch.write_text(
            json.dumps({
                "officialDescription": "v",
                "painPoints": [], "solutions": [],
                "proofPoints": [], "callToActions": [], "leadMagnets": [],
            }),
            encoding="utf-8",
        )
        result = self._invoke(
            "--no-wizard",
            "--csv", str(self.csv_path),
            "--pitch-file", str(bare_pitch),
            "--country-column", "country",
            "--dry-run",
        )
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("USAGE_WEBSITE_MISSING",
                      result.output)


class TestPitchInit(unittest.TestCase):
    """`aiflow pitch init` writes a valid pitch.json scaffold (no network)."""

    def setUp(self):
        from click.testing import CliRunner
        from flashclaw_cli_plugin.flashrev_aiflow import flashrev_aiflow_cli

        self.runner = CliRunner()
        self.cli = flashrev_aiflow_cli.cli
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_init_writes_scaffold_with_all_required_sections(self):
        out = Path(self.tmpdir) / "pitch.json"
        result = self.runner.invoke(
            self.cli,
            ["aiflow", "pitch", "init", "--out", str(out)],
            catch_exceptions=False,
        )

        self.assertEqual(result.exit_code, 0, msg=result.output)
        self.assertTrue(out.exists())
        data = json.loads(out.read_text(encoding="utf-8"))
        # 6 required pitch sections (per PitchStrategySection.vue) must be present.
        for key in (
            "officialDescription",
            "painPoints",
            "solutions",
            "proofPoints",
            "callToActions",
            "leadMagnets",
        ):
            self.assertIn(key, data)
        # Optional convenience fields that let --website be omitted.
        self.assertIn("url", data)
        self.assertIn("language", data)

    def test_init_refuses_overwrite_without_force(self):
        out = Path(self.tmpdir) / "pitch.json"
        out.write_text("already here", encoding="utf-8")

        result = self.runner.invoke(
            self.cli,
            ["--json", "aiflow", "pitch", "init", "--out", str(out)],
            catch_exceptions=False,
        )

        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("PITCH_INIT_FILE_EXISTS", result.output)
        # File must remain untouched.
        self.assertEqual(out.read_text(encoding="utf-8"), "already here")

    def test_init_overwrites_with_force(self):
        out = Path(self.tmpdir) / "pitch.json"
        out.write_text("stale", encoding="utf-8")

        result = self.runner.invoke(
            self.cli,
            ["aiflow", "pitch", "init", "--out", str(out), "--force"],
            catch_exceptions=False,
        )

        self.assertEqual(result.exit_code, 0, msg=result.output)
        data = json.loads(out.read_text(encoding="utf-8"))
        self.assertIn("officialDescription", data)

    def test_init_scaffold_validates_against_wizard_schema(self):
        """The scaffold must pass wizard.validate_pitch_schema unchanged so
        users can `aiflow pitch init` then hand the file straight to
        `aiflow create --pitch-file` with zero edits if they only want a
        smoke-test dry-run.
        """
        from flashclaw_cli_plugin.flashrev_aiflow.flashrev_aiflow_cli import (
            _pitch_scaffold,
        )
        from flashclaw_cli_plugin.flashrev_aiflow import wizard

        scaffold = _pitch_scaffold()
        validated = wizard.validate_pitch_schema(scaffold)
        self.assertEqual(
            validated["officialDescription"], scaffold["officialDescription"]
        )
        self.assertEqual(validated["painPoints"], scaffold["painPoints"])
        # url should pass through (validate_pitch_schema retains it now).
        self.assertEqual(validated.get("url"), "acme.com")


class TestPitchShowBackwardCompat(unittest.TestCase):
    """Ensure `aiflow pitch` is now a group that still exposes the old show path."""

    def test_pitch_is_a_group_with_show_and_init(self):
        from flashclaw_cli_plugin.flashrev_aiflow import flashrev_aiflow_cli

        pitch_group = flashrev_aiflow_cli.aiflow.commands["pitch"]
        self.assertTrue(
            hasattr(pitch_group, "commands"),
            msg="aiflow pitch must be a group so that init + show can coexist",
        )
        self.assertIn("show", pitch_group.commands)
        self.assertIn("init", pitch_group.commands)
        # show still accepts a positional FLOW_ID.
        show_cmd = pitch_group.commands["show"]
        self.assertIn("flow_id", [p.name for p in show_cmd.params])


if __name__ == "__main__":
    unittest.main()
