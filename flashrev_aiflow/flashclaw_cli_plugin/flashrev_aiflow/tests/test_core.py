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
        url = self.client._url_discover("/api/v1/ai/workflow/type/rows")
        self.assertEqual(
            url,
            "https://gateway.example.com/flashrev/api/v1/ai/workflow/type/rows",
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

    @patch("flashclaw_cli_plugin.flashrev_aiflow.core.client.requests.post")
    def test_list_aiflows_posts_to_type_rows(self, mock_post):
        mock_post.return_value = self._mock_response({"code": 200, "data": []})

        self.client.list_aiflows({"type": "All", "viewType": "person"})

        called_url = mock_post.call_args[0][0]
        self.assertIn("/flashrev/api/v1/ai/workflow/type/rows", called_url)
        body = mock_post.call_args[1]["json"]
        self.assertEqual(body["type"], "All")
        self.assertEqual(body["viewType"], "person")

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
    def test_test_website_connection_uses_shared_timeout(self, mock_post):
        mock_post.return_value = self._mock_response({"code": 200})

        self.client.test_website_connection("https://acme.com")

        # Now uses the shared self.timeout (default 300s) so cold-cache
        # site fetches don't hit a hard 20s cap. Must be >= 180s to
        # satisfy the 3-minute floor.
        self.assertEqual(mock_post.call_args[1]["timeout"], self.client.timeout)
        self.assertGreaterEqual(self.client.timeout, 180)
        self.assertEqual(
            mock_post.call_args[1]["json"],
            {"url": "https://acme.com", "language": "en-us"},
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

    def test_filter_active_mailboxes_handles_int_status(self):
        """mailsvc test-env returns status as an int (1=active, 0=inactive).
        Regression guard for the 2026-04-23 wire-up crash where .upper()
        was called on an int and blew up the create wizard."""
        from flashclaw_cli_plugin.flashrev_aiflow import wizard

        resp = {
            "code": 200,
            "data": [
                {"id": 1, "status": 1, "mailAddressEnum": "SUCCESS"},
                {"id": 2, "status": 0, "mailAddressEnum": "FAILED"},
            ],
        }
        actives = wizard.filter_active_mailboxes(resp)
        self.assertEqual([m["id"] for m in actives], [1])

    def test_filter_active_mailboxes_uses_mailAddressEnum_fallback(self):
        from flashclaw_cli_plugin.flashrev_aiflow import wizard

        resp = {"code": 200, "data": [
            {"id": 7, "mailAddressEnum": "SUCCESS"},  # no status at all
        ]}
        actives = wizard.filter_active_mailboxes(resp)
        self.assertEqual([m["id"] for m in actives], [7])

    def test_mailbox_id_picks_address_id_first(self):
        from flashclaw_cli_plugin.flashrev_aiflow import wizard

        self.assertEqual(
            wizard.mailbox_id({"addressId": "A", "id": "B"}), "A"
        )
        self.assertEqual(wizard.mailbox_id({"id": "B"}), "B")
        self.assertIsNone(wizard.mailbox_id({}))

    def test_mailbox_id_preserves_int_type(self):
        """save/email/config expects addressId as a JSON number, not string.
        Regression guard: mailbox_id MUST NOT str-convert the value."""
        from flashclaw_cli_plugin.flashrev_aiflow import wizard

        result = wizard.mailbox_id({"id": 1479})
        self.assertEqual(result, 1479)
        self.assertIsInstance(result, int)
        self.assertNotIsInstance(result, str)


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

    @patch("flashclaw_cli_plugin.flashrev_aiflow.core.client.requests.get")
    def test_get_pitch_uses_path_param(self, mock_get):
        mock_get.return_value = self._mock_response({"code": 200, "data": {}})

        self.client.get_pitch("abc123")

        called_url = mock_get.call_args[0][0]
        self.assertIn(
            "/flashrev/api/v1/ai/workflow/get/pitch/abc123", called_url
        )

    @patch("flashclaw_cli_plugin.flashrev_aiflow.core.client.requests.get")
    def test_get_bind_email_uses_path_param(self, mock_get):
        mock_get.return_value = self._mock_response({"code": 200, "data": []})

        self.client.get_bind_email("f1")

        called_url = mock_get.call_args[0][0]
        self.assertIn(
            "/flashrev/api/v1/ai/workflow/get/bind/email/f1", called_url
        )

    @patch("flashclaw_cli_plugin.flashrev_aiflow.core.client.requests.get")
    def test_get_unbind_email_uses_path_param(self, mock_get):
        mock_get.return_value = self._mock_response({"code": 200, "data": []})

        self.client.get_unbind_email("f2")

        called_url = mock_get.call_args[0][0]
        self.assertIn(
            "/flashrev/api/v1/ai/workflow/get/unbind/email/f2", called_url
        )

    @patch("flashclaw_cli_plugin.flashrev_aiflow.core.client.requests.get")
    def test_has_active_email_no_agent_segment(self, mock_get):
        mock_get.return_value = self._mock_response({"code": 200, "data": True})

        self.client.has_active_email()

        called_url = mock_get.call_args[0][0]
        self.assertIn(
            "/flashrev/api/v1/ai/workflow/has/active/email", called_url
        )
        # Regression guard: the old /agent/ segment must be gone.
        self.assertNotIn("/agent/has/active/email", called_url)

    @patch("flashclaw_cli_plugin.flashrev_aiflow.core.client.requests.post")
    def test_test_connection_no_agent_segment(self, mock_post):
        mock_post.return_value = self._mock_response({"code": 200})

        self.client.test_website_connection("https://acme.com")

        called_url = mock_post.call_args[0][0]
        self.assertIn(
            "/flashrev/api/v1/ai/workflow/test/connection", called_url
        )
        self.assertNotIn("/agent/test/connection", called_url)


class TestV2ClientEndpoints(unittest.TestCase):
    """New V2 endpoints added to client.py (URL-driven pitch + full launch)."""

    def setUp(self):
        from flashclaw_cli_plugin.flashrev_aiflow.core.client import (
            FlashrevAiflowClient,
        )
        self.client = FlashrevAiflowClient(
            base_url="https://gateway.example.com", api_key="sk_test",
        )
        self.client.discover_prefix = "/flashrev"
        self.client.engage_prefix = ""
        self.client.mailsvc_prefix = ""
        self.client.meeting_prefix = "/meeting-svc"

    def _mock_response(self, payload):
        r = MagicMock()
        r.raise_for_status = MagicMock()
        r.json.return_value = payload
        r.content = json.dumps(payload).encode()
        return r

    @patch("flashclaw_cli_plugin.flashrev_aiflow.core.client.requests.post")
    def test_test_website_connection_sends_language(self, mock_post):
        mock_post.return_value = self._mock_response({"code": 200, "data": {}})
        self.client.test_website_connection("https://baidu.com", "en-us")
        body = mock_post.call_args[1]["json"]
        self.assertEqual(body, {"url": "https://baidu.com", "language": "en-us"})
        self.assertEqual(mock_post.call_args[1]["timeout"], self.client.timeout)

    @patch("flashclaw_cli_plugin.flashrev_aiflow.core.client.requests.post")
    def test_save_pitch_path_no_agent_segment(self, mock_post):
        mock_post.return_value = self._mock_response({"code": 200})
        self.client.save_pitch({"workflowId": 1})
        called_url = mock_post.call_args[0][0]
        self.assertIn("/flashrev/api/v1/ai/workflow/save/pitch", called_url)
        self.assertNotIn("/agent/save/pitch", called_url)

    @patch("flashclaw_cli_plugin.flashrev_aiflow.core.client.requests.post")
    def test_get_email_prompt_defaults_empty_beforstep(self, mock_post):
        mock_post.return_value = self._mock_response({"code": 200})
        self.client.get_email_prompt(1114)
        body = mock_post.call_args[1]["json"]
        self.assertEqual(body["workflowId"], 1114)
        self.assertEqual(body["beforStep"], [])
        self.assertNotIn("workflowStepId", body)

    @patch("flashclaw_cli_plugin.flashrev_aiflow.core.client.requests.post")
    def test_get_email_prompt_forwards_step_context(self, mock_post):
        mock_post.return_value = self._mock_response({"code": 200})
        self.client.get_email_prompt(
            1114, workflow_step_id=99,
            before_step=[{"emailSubject": "s", "emailContent": "c"}],
        )
        body = mock_post.call_args[1]["json"]
        self.assertEqual(body["workflowStepId"], 99)
        self.assertEqual(len(body["beforStep"]), 1)

    @patch("flashclaw_cli_plugin.flashrev_aiflow.core.client.requests.post")
    def test_save_prompt_shape(self, mock_post):
        mock_post.return_value = self._mock_response(True)
        self.client.save_prompt(1114, [{"workflowStepId": 1, "step": 1}])
        body = mock_post.call_args[1]["json"]
        self.assertEqual(body["workflowId"], 1114)
        self.assertEqual(body["prompts"][0]["step"], 1)
        called_url = mock_post.call_args[0][0]
        self.assertIn("/flashrev/api/v1/ai/workflow/save/prompt", called_url)

    @patch("flashclaw_cli_plugin.flashrev_aiflow.core.client.requests.get")
    def test_get_setting_path(self, mock_get):
        mock_get.return_value = self._mock_response({"code": 200, "data": {}})
        self.client.get_setting(1114)
        called_url = mock_get.call_args[0][0]
        self.assertIn("/flashrev/api/v1/ai/workflow/get/setting/1114", called_url)

    @patch("flashclaw_cli_plugin.flashrev_aiflow.core.client.requests.get")
    def test_get_draft_workflow_path(self, mock_get):
        mock_get.return_value = self._mock_response({"code": 200, "data": {}})
        self.client.get_draft_workflow()
        called_url = mock_get.call_args[0][0]
        self.assertIn("/flashrev/api/v1/ai/workflow/draft", called_url)

    @patch("flashclaw_cli_plugin.flashrev_aiflow.core.client.requests.post")
    def test_list_personal_meetings_uses_meeting_prefix(self, mock_post):
        mock_post.return_value = self._mock_response({"code": 200, "data": []})
        self.client.list_personal_meetings("foo", "bar")
        called_url = mock_post.call_args[0][0]
        # Full path: gateway prefix /meeting-svc + native /meeting/... path.
        # Gateway targets the bare meeting-svc domain, so the /meeting/
        # segment is kept on the CLI side (mirrors /flashrev's setup).
        self.assertIn(
            "/meeting-svc/meeting/api/v1/meeting/personal/list", called_url
        )
        self.assertNotIn("/flashrev/", called_url)
        body = mock_post.call_args[1]["json"]
        self.assertEqual(body, {"meetName": "foo", "meetType": "bar"})


class TestWizardV2Helpers(unittest.TestCase):
    """V2 wizard helpers: pitch body, prompt body, settings assembly."""

    def test_build_save_pitch_body_spreads_icp_and_overrides(self):
        from flashclaw_cli_plugin.flashrev_aiflow import wizard
        icp = {
            "officialDescription": "desc",
            "painPoints": ["p1", "p2"],
            "url": "",  # should be overridden
            "language": "",  # should be overridden
        }
        body = wizard.build_save_pitch_body(1114, icp, "baidu.com", "en-us")
        self.assertEqual(body["workflowId"], 1114)
        self.assertEqual(body["url"], "https://baidu.com")  # https:// added
        self.assertEqual(body["language"], "en-us")
        self.assertFalse(body["useConfigLanguage"])
        self.assertEqual(body["officialDescription"], "desc")
        self.assertEqual(body["painPoints"], ["p1", "p2"])

    def test_build_save_pitch_body_auto_language_sets_useConfigLanguage(self):
        from flashclaw_cli_plugin.flashrev_aiflow import wizard
        body = wizard.build_save_pitch_body(
            1, {"officialDescription": "d"}, "https://acme.com", "auto",
        )
        self.assertTrue(body["useConfigLanguage"])
        self.assertEqual(body["language"], "auto")

    def test_prompt_step_completeness(self):
        """Complete = emailContent (prompt template) non-empty; subject /
        content / emailSubject can stay blank (mirrors frontend save/prompt
        sample body where step 1 and step 3 ship with everything empty but
        step 2 has a full emailContent)."""
        from flashclaw_cli_plugin.flashrev_aiflow import wizard
        self.assertTrue(wizard.prompt_step_is_complete(
            {"emailContent": "You are a cold email copywriter..."}
        ))
        # emailContent missing -> incomplete, even if emailSubject is set.
        self.assertFalse(wizard.prompt_step_is_complete(
            {"emailSubject": "s", "emailContent": ""}
        ))
        # Whitespace-only emailContent counts as empty.
        self.assertFalse(wizard.prompt_step_is_complete(
            {"emailContent": "   "}
        ))
        self.assertFalse(wizard.prompt_step_is_complete({}))

    def test_count_incomplete_prompts(self):
        from flashclaw_cli_plugin.flashrev_aiflow import wizard
        steps = [
            {"emailContent": "template-a"},
            {"emailContent": ""},                 # incomplete
            {"emailContent": "template-c"},
        ]
        self.assertEqual(wizard.count_incomplete_prompts(steps), 1)

    def test_parse_sse_content_concatenates_content_events(self):
        """SSE parser pulls data from type=content events and concatenates."""
        from flashclaw_cli_plugin.flashrev_aiflow import wizard
        raw = (
            '{"type":"content","data":""}\n'
            '{"type":"content","data":"You are "}\n'
            '{"type":"content","data":"a cold email "}\n'
            '{"type":"content","data":"copywriter."}\n'
            '{"type":"done"}\n'
            ':keepalive-comment-line\n'
        )
        self.assertEqual(
            wizard._parse_sse_content(raw),
            "You are a cold email copywriter.",
        )

    def test_parse_sse_content_tolerates_data_prefix(self):
        from flashclaw_cli_plugin.flashrev_aiflow import wizard
        raw = (
            'data: {"type":"content","data":"hello"}\n'
            'data: {"type":"content","data":" world"}\n'
        )
        self.assertEqual(
            wizard._parse_sse_content(raw),
            "hello world",
        )

    def test_truncate_to_byte_limit_is_noop_under_limit(self):
        from flashclaw_cli_plugin.flashrev_aiflow import wizard
        text = "hello world"
        self.assertEqual(wizard._truncate_to_byte_limit(text), text)

    def test_truncate_to_byte_limit_clips_over_limit_ascii(self):
        """ASCII = 1 byte/char; verify the cap kicks in at the byte
        threshold (43,690 bytes by default)."""
        from flashclaw_cli_plugin.flashrev_aiflow import wizard
        # 50 KB of ASCII chars = 50_000 bytes, well over the 43_690 cap.
        long_text = "a" * 50_000
        out = wizard._truncate_to_byte_limit(long_text)
        self.assertEqual(len(out.encode("utf-8")),
                         wizard._EMAIL_CONTENT_BYTE_LIMIT)

    def test_truncate_to_byte_limit_explicit_max_bytes(self):
        from flashclaw_cli_plugin.flashrev_aiflow import wizard
        out = wizard._truncate_to_byte_limit("abcdef", max_bytes=3)
        self.assertEqual(out, "abc")

    def test_truncate_to_byte_limit_safe_on_multibyte_boundary(self):
        """A truncation boundary that splits a multi-byte UTF-8 char must
        not produce invalid bytes (use errors='ignore' on decode)."""
        from flashclaw_cli_plugin.flashrev_aiflow import wizard
        # "中" is 3 bytes in utf-8. Cap at 4 bytes — first char fits (3),
        # second's leading byte (1 of 3) must be dropped.
        out = wizard._truncate_to_byte_limit("中中中", max_bytes=4)
        self.assertEqual(out, "中")
        # Ensure the result is valid utf-8 with no replacement chars.
        out.encode("utf-8")  # must not raise

    def test_build_save_prompt_body_caps_emailContent(self):
        """User-supplied (or LLM-generated) emailContent is truncated to
        the TEXT column limit when building the /save/prompt body."""
        from flashclaw_cli_plugin.flashrev_aiflow import wizard
        oversized = "x" * (wizard._EMAIL_CONTENT_BYTE_LIMIT + 5_000)
        body = wizard.build_save_prompt_body(1, [
            {"workflowStepId": 1, "step": 1, "delayMinutes": 60,
             "emailContent": oversized},
        ])
        self.assertEqual(
            len(body["prompts"][0]["emailContent"].encode("utf-8")),
            wizard._EMAIL_CONTENT_BYTE_LIMIT,
        )

    def test_parse_sse_content_strips_trailing_terminator(self):
        """Backend emits ``</content>`` as the stream close marker — the
        parser must strip it so callers get a clean prompt template."""
        from flashclaw_cli_plugin.flashrev_aiflow import wizard
        raw = (
            '{"type":"content","data":"EC1"}\n'
            '{"type":"content","data":"</content>"}\n'
        )
        self.assertEqual(wizard._parse_sse_content(raw), "EC1")

    def test_seed_default_steps_posts_three_skeleton_rows(self):
        """seed_default_steps ships 3 empty rows (1h/3d/7d) to /save/prompt
        then re-queries /get/prompt to fetch the new step IDs."""
        from flashclaw_cli_plugin.flashrev_aiflow import wizard
        from unittest.mock import MagicMock
        client = MagicMock()
        # Re-query after save returns the seeded rows with IDs.
        client.get_workflow_prompt.return_value = [
            {"id": 100, "step": 1, "delayMinutes": 60},
            {"id": 101, "step": 2, "delayMinutes": 4320},
            {"id": 102, "step": 3, "delayMinutes": 10080},
        ]
        result = wizard.seed_default_steps(client, 1117)

        client.save_prompt.assert_called_once()
        args, _ = client.save_prompt.call_args
        workflow_id, prompts = args
        self.assertEqual(workflow_id, 1117)
        self.assertEqual(len(prompts), 3)
        self.assertEqual([p["delayMinutes"] for p in prompts],
                         [60, 4320, 10080])
        # Skeleton rows must have no workflowStepId (backend auto-assigns).
        for p in prompts:
            self.assertNotIn("workflowStepId", p)
            self.assertEqual(p["emailContent"], "")
        # Re-query must have run and returned the 3 rows with IDs.
        self.assertEqual(len(result), 3)
        self.assertEqual(result[0]["id"], 100)

    def test_build_save_prompt_body_requires_step_id(self):
        from flashclaw_cli_plugin.flashrev_aiflow import wizard
        with self.assertRaises(click.UsageError):
            wizard.build_save_prompt_body(1, [{"step": 1}])  # no id

    def test_build_save_prompt_body_maps_fields(self):
        from flashclaw_cli_plugin.flashrev_aiflow import wizard
        body = wizard.build_save_prompt_body(1114, [
            {"workflowStepId": 10, "step": 1, "emailSubject": "es",
             "emailContent": "ec", "subject": "s", "content": "c",
             "delayMinutes": 60},
            {"id": 11, "step": 2, "exampleSubject": "xs",
             "exampleContent": "xc"},  # example* -> subject/content fallback
        ])
        self.assertEqual(body["workflowId"], 1114)
        p1, p2 = body["prompts"]
        self.assertEqual(p1["workflowStepId"], 10)
        self.assertEqual(p1["delayMinutes"], 60)
        self.assertEqual(p2["workflowStepId"], 11)
        # default delay for step 2 (index 1) is 4320 (3 days)
        self.assertEqual(p2["delayMinutes"], 4320)
        # example* mapped to subject/content
        self.assertEqual(p2["subject"], "xs")
        self.assertEqual(p2["content"], "xc")

    def test_patch_meeting_route_id_only_on_book_meeting(self):
        from flashclaw_cli_plugin.flashrev_aiflow import wizard
        lst = [
            {"strategy": "Book Meeting", "meetingRouteId": 0, "prompt": "a"},
            {"strategy": "Drive Traffic", "meetingRouteId": 0, "prompt": "b"},
        ]
        patched = wizard.patch_meeting_route_id(lst, 483)
        self.assertEqual(patched[0]["meetingRouteId"], 483)
        self.assertEqual(patched[1]["meetingRouteId"], 0)  # untouched

    def test_pick_first_meeting_router_id(self):
        from flashclaw_cli_plugin.flashrev_aiflow import wizard
        self.assertEqual(
            wizard.pick_first_meeting_router_id(
                {"code": 200, "data": [{"id": 7}, {"id": 8}]}
            ),
            7,
        )
        self.assertIsNone(
            wizard.pick_first_meeting_router_id({"code": 200, "data": []})
        )
        self.assertIsNone(wizard.pick_first_meeting_router_id({}))

    def test_build_save_setting_body_draft_flow(self):
        """Fresh DRAFT flow: /get/setting has no .setting.properties block,
        so the wizard falls back to hardcoded defaults + picked template."""
        from flashclaw_cli_plugin.flashrev_aiflow import wizard
        template = {
            "id": 135487,
            "name": "my-template",
            "properties": {"foo": "bar"},
            "timeBlocks": [{"startTime": "10:00", "endTime": "17:00"}],
        }
        setting = {
            "isShowAiReply": True,
            "autoApprove": None,
            "enableAgentReply": None,
            "agentStrategy": None,
            "agentPromptList": [
                {"strategy": "Book Meeting", "prompt": "bm"},
                {"strategy": "Drive Traffic", "prompt": "dt"},
            ],
        }
        body = wizard.build_save_setting_body(
            1114, template, [{"addressId": 1479}], setting,
            True, meeting_router_id=483,
        )
        self.assertEqual(body["workflowId"], 1114)
        self.assertTrue(body["autoApprove"])
        props = body["properties"]
        self.assertEqual(props["timeTemplateId"], 135487)
        self.assertEqual(props["timeTemplateConfig"]["name"], "my-template")
        self.assertEqual(props["sequenceMailboxList"], [{"addressId": 1479}])
        # emailTrack falls back to hardcoded default
        self.assertIn("unsubscribeTemplate", props["emailTrack"])
        # agent block present because isShowAiReply is True
        self.assertEqual(len(body["agentPromptList"]), 2)
        self.assertEqual(body["agentPromptList"][0]["meetingRouteId"], 483)

    def test_build_save_setting_body_hides_agent_block_pre_2026_02_07(self):
        from flashclaw_cli_plugin.flashrev_aiflow import wizard
        body = wizard.build_save_setting_body(
            1, {}, [], {"isShowAiReply": False}, True,
        )
        # agent block is NOT in the body when isShowAiReply is False
        self.assertNotIn("agentPromptList", body)
        self.assertNotIn("enableAgentReply", body)

    def test_build_save_setting_body_flag_override_beats_server(self):
        from flashclaw_cli_plugin.flashrev_aiflow import wizard
        body = wizard.build_save_setting_body(
            1, {}, [],
            {"isShowAiReply": True, "enableAgentReply": False,
             "agentStrategy": "Qualify Lead", "agentPromptList": []},
            True,
            enable_agent_reply=True,
            agent_strategy="Custom Goal",
        )
        self.assertTrue(body["enableAgentReply"])
        self.assertEqual(body["agentStrategy"], "Custom Goal")


class TestCreateNoWizardV2(unittest.TestCase):
    """V2 `aiflow create --no-wizard` flag matrix + dry-run contract.

    Pipeline under test:
      upload_contacts_csv -> create_aiflow_from_list -> test_website_connection
      -> save_pitch -> get_workflow_prompt -> [regenerate_emails] -> save_prompt
      -> [launch] get_setting + pick_default_time_template + list_personal_meetings
                  -> save_setting
    """

    def setUp(self):
        from click.testing import CliRunner
        from flashclaw_cli_plugin.flashrev_aiflow import flashrev_aiflow_cli

        self.runner = CliRunner()
        self.cli = flashrev_aiflow_cli.cli

        self.key_patch = patch(
            "flashclaw_cli_plugin.flashrev_aiflow."
            "flashrev_aiflow_cli.get_api_key",
            return_value="sk_test",
        )
        self.key_patch.start()

        self.client_stub = MagicMock()
        self.client_stub.list_mailboxes.return_value = {
            "code": 200,
            "data": [
                {"id": "m1", "address": "a@x.com", "status": "ACTIVE"},
                {"id": "m2", "address": "b@x.com", "status": "ACTIVE"},
            ],
        }
        self.client_stub.get_token_balance.return_value = {
            "tokenTotal": 100.0, "tokenCost": 10.0,
            "tokenRemaining": 90.0, "sufficient": True,
        }
        self.build_patch = patch(
            "flashclaw_cli_plugin.flashrev_aiflow."
            "flashrev_aiflow_cli._build_client",
            return_value=self.client_stub,
        )
        self.build_patch.start()

        self.tmpdir = tempfile.mkdtemp()
        self.csv_path = Path(self.tmpdir) / "contacts.csv"
        self.csv_path.write_text(
            "name,email,country\nAlice,a@b.com,US\nBob,b@c.com,CA\n",
            encoding="utf-8",
        )

    def tearDown(self):
        patch.stopall()
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _invoke(self, *args):
        return self.runner.invoke(
            self.cli, ["--json", "aiflow", "create", *args],
            catch_exceptions=False,
        )

    # ── flag matrix ─────────────────────────────────────────

    def test_errors_when_neither_csv_nor_sheet(self):
        result = self._invoke(
            "--no-wizard", "--url", "acme.com", "--country-column", "none",
        )
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("USAGE_CONTACT_SOURCE", result.output)

    def test_errors_when_url_missing(self):
        result = self._invoke(
            "--no-wizard", "--csv", str(self.csv_path),
            "--country-column", "none",
        )
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("USAGE_URL_REQUIRED", result.output)

    def test_errors_when_country_column_missing_for_auto(self):
        result = self._invoke(
            "--no-wizard", "--csv", str(self.csv_path),
            "--url", "acme.com", "--language", "auto", "--dry-run",
        )
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("USAGE_COUNTRY_COLUMN_MISSING", result.output)

    def test_country_column_not_required_for_fixed_language(self):
        # language=en-us (the new default) => country-column is optional
        result = self._invoke(
            "--no-wizard", "--csv", str(self.csv_path),
            "--url", "acme.com", "--dry-run",
        )
        self.assertEqual(result.exit_code, 0, msg=result.output)

    def test_mailboxes_filter_no_match_in_no_wizard(self):
        result = self._invoke(
            "--no-wizard", "--csv", str(self.csv_path),
            "--url", "acme.com", "--language", "en-us",
            "--mailboxes", "nonexistent_id", "--dry-run",
        )
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("USAGE_MAILBOX_NO_MATCH", result.output)

    # ── dry-run contract ────────────────────────────────────

    def test_dry_run_skips_all_write_endpoints(self):
        result = self._invoke(
            "--no-wizard", "--csv", str(self.csv_path),
            "--url", "acme.com", "--language", "en-us", "--dry-run",
        )
        self.assertEqual(result.exit_code, 0, msg=result.output)
        # All write endpoints must be skipped
        self.client_stub.upload_contacts_csv.assert_not_called()
        self.client_stub.create_aiflow_from_list.assert_not_called()
        self.client_stub.test_website_connection.assert_not_called()
        self.client_stub.save_pitch.assert_not_called()
        self.client_stub.get_workflow_prompt.assert_not_called()
        self.client_stub.save_prompt.assert_not_called()
        self.client_stub.save_setting.assert_not_called()
        self.client_stub.list_personal_meetings.assert_not_called()
        # Read-only probes fired
        self.client_stub.list_mailboxes.assert_called_once()
        self.client_stub.get_token_balance.assert_called_once()
        self.assertIn("Dry-run complete", result.output)

    # ── prompt completeness gate ────────────────────────────

    def test_launch_blocked_with_no_regenerate_emails_flag(self):
        """When user explicitly passes --no-regenerate-emails, step rows
        stay empty; --launch must be blocked by the completeness gate
        with AIFLOW_LAUNCH_PROMPTS_INCOMPLETE."""
        self.client_stub.upload_contacts_csv.return_value = {
            "code": 200, "data": {"listId": 1, "listName": "c.csv"},
        }
        self.client_stub.create_aiflow_from_list.return_value = {
            "code": 200, "data": {"id": 999},
        }
        self.client_stub.test_website_connection.return_value = {
            "code": 200,
            "data": {"officialDescription": "desc", "painPoints": []},
        }
        self.client_stub.save_pitch.return_value = {"code": 200}
        # 1st /get/prompt call returns [] -> wizard triggers seed_default_steps;
        # 2nd (re-query inside seed_default_steps) returns 3 empty rows
        # simulating the just-seeded skeleton.
        self.client_stub.get_workflow_prompt.side_effect = [
            [],
            [
                {"id": 10, "workflowStepId": 10, "step": 1,
                 "delayMinutes": 60, "emailSubject": "", "emailContent": ""},
                {"id": 11, "workflowStepId": 11, "step": 2,
                 "delayMinutes": 4320, "emailSubject": "", "emailContent": ""},
                {"id": 12, "workflowStepId": 12, "step": 3,
                 "delayMinutes": 10080, "emailSubject": "", "emailContent": ""},
            ],
        ]
        self.client_stub.save_prompt.return_value = {"code": 200, "data": True}

        result = self._invoke(
            "--no-wizard", "--csv", str(self.csv_path),
            "--url", "acme.com", "--language", "en-us",
            "--no-regenerate-emails",      # explicit opt-out
            "--launch", "-y",
        )
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("AIFLOW_LAUNCH_PROMPTS_INCOMPLETE", result.output)
        # save_setting must NOT have been called — launch was blocked
        self.client_stub.save_setting.assert_not_called()
        # Gate message should mention prompt-update as the recovery path.
        self.assertIn("prompt-update", result.output)

    def test_default_create_triggers_save_setting(self):
        """Without an explicit --launch / --no-launch flag, --no-wizard
        mode must default to launching the flow (i.e. firing save/setting)
        — otherwise the flow has no sequence bound and the scheduler can't
        send anything. Mirror the frontend's "Launch AIFlow" button being
        the natural endpoint of the create wizard."""
        # Wire just enough stubs for the launch branch to complete.
        self.client_stub.upload_contacts_csv.return_value = {
            "code": 200, "data": {"listId": 1, "listName": "c.csv"},
        }
        self.client_stub.create_aiflow_from_list.return_value = {
            "code": 200, "data": {"id": 999},
        }
        self.client_stub.test_website_connection.return_value = {
            "code": 200, "data": {"officialDescription": "d"},
        }
        self.client_stub.save_pitch.return_value = {"code": 200}
        # Empty initial /get/prompt then 3 seeded rows on re-query (post seed).
        self.client_stub.get_workflow_prompt.side_effect = [
            [],
            [
                {"id": 10, "workflowStepId": 10, "step": 1,
                 "delayMinutes": 60, "emailContent": "filled"},
                {"id": 11, "workflowStepId": 11, "step": 2,
                 "delayMinutes": 4320, "emailContent": "filled"},
                {"id": 12, "workflowStepId": 12, "step": 3,
                 "delayMinutes": 10080, "emailContent": "filled"},
            ],
        ]
        self.client_stub.save_prompt.return_value = {"code": 200, "data": True}
        self.client_stub.get_setting.return_value = {
            "isShowAiReply": False, "autoApprove": False,
            "agentPromptList": [],
        }
        self.client_stub.list_time_templates.return_value = {
            "code": 200, "data": [{"id": 1, "name": "tpl",
                                   "properties": {}, "timeBlocks": []}],
        }
        self.client_stub.list_personal_meetings.return_value = {
            "code": 200, "data": [],
        }
        self.client_stub.save_setting.return_value = {"code": 200, "data": True}

        result = self._invoke(
            "--no-wizard", "--csv", str(self.csv_path),
            "--url", "acme.com", "--language", "en-us",
            # NO --launch / --no-launch flag — relies on default-on
            "--no-regenerate-emails",  # short-circuit LLM, content already "filled"
            "-y",
        )
        # save_setting MUST have been called — that's the whole point.
        self.assertTrue(
            self.client_stub.save_setting.called,
            msg=f"save/setting was NOT called — flow stayed DRAFT.\n{result.output}",
        )
        # Summary JSON must mark this run as a deliverable AIFlow.
        # Downstream agents are told (via SKILL.md) to branch on
        # creationComplete, so a regression here breaks contract.
        self.assertIn('"creationComplete": true', result.output)
        self.assertIn('"missing": []', result.output)
        self.assertIn('"nextStep": null', result.output)

    def test_no_launch_marks_creation_incomplete_with_next_step(self):
        """The --no-launch escape hatch leaves the flow in a non-deliverable
        state. The Summary JSON must reflect that with creationComplete=false
        + a non-empty missing array + a nextStep recovery hint, so downstream
        scripts and agents don't mistake the flowId for a working flow."""
        self.client_stub.upload_contacts_csv.return_value = {
            "code": 200, "data": {"listId": 1, "listName": "c.csv"},
        }
        self.client_stub.create_aiflow_from_list.return_value = {
            "code": 200, "data": {"id": 999},
        }
        self.client_stub.test_website_connection.return_value = {
            "code": 200, "data": {"officialDescription": "d"},
        }
        self.client_stub.save_pitch.return_value = {"code": 200}
        self.client_stub.get_workflow_prompt.side_effect = [
            [],
            [
                {"id": 10, "workflowStepId": 10, "step": 1,
                 "delayMinutes": 60, "emailContent": "filled"},
                {"id": 11, "workflowStepId": 11, "step": 2,
                 "delayMinutes": 4320, "emailContent": "filled"},
                {"id": 12, "workflowStepId": 12, "step": 3,
                 "delayMinutes": 10080, "emailContent": "filled"},
            ],
        ]
        self.client_stub.save_prompt.return_value = {"code": 200, "data": True}

        result = self._invoke(
            "--no-wizard", "--csv", str(self.csv_path),
            "--url", "acme.com", "--language", "en-us",
            "--no-regenerate-emails",
            "--no-launch",
            "-y",
        )
        self.assertEqual(result.exit_code, 0, msg=result.output)
        # save_setting must NOT have been called on this branch.
        self.client_stub.save_setting.assert_not_called()
        # Summary JSON: creation is NOT complete + caller is told what's
        # missing + given a concrete recovery command.
        self.assertIn('"creationComplete": false', result.output)
        self.assertIn('"save/setting', result.output)
        self.assertIn('aiflow settings-update', result.output)
        # Yellow WARNING text in plain stdout (color codes stripped by
        # CliRunner in some setups, so just check the keyword).
        self.assertIn("WARNING", result.output)

    def test_pipeline_failure_emits_aiflow_not_created_banner(self):
        """Any failure mid-pipeline must surface as a prominent banner,
        not just a one-line red error. Definition of done = M1 + M2 + M3
        all complete; failure in any one leaves an orphan DRAFT and the
        user must be told explicitly."""
        # M1 succeeds: CSV uploads, flow row created.
        self.client_stub.upload_contacts_csv.return_value = {
            "code": 200, "data": {"listId": 42, "listName": "c.csv"},
        }
        self.client_stub.create_aiflow_from_list.return_value = {
            "code": 200, "data": {"id": 9001},
        }
        # M2 aborts at /test/connection — simulates the cold-cache LLM
        # outage that motivated the 0.3.2 timeout fix.
        self.client_stub.test_website_connection.side_effect = Exception(
            "Read timed out — upstream LLM unavailable"
        )

        result = self._invoke(
            "--no-wizard", "--csv", str(self.csv_path),
            "--url", "acme.com", "--language", "en-us",
            "--no-regenerate-emails",
            "-y",
        )
        self.assertNotEqual(result.exit_code, 0)
        # Banner content (stderr + stdout get merged in CliRunner output).
        self.assertIn("AIFLOW NOT CREATED", result.output)
        self.assertIn("M2", result.output)  # failed milestone
        self.assertIn("9001", result.output)  # orphan flowId surfaced
        self.assertIn("aiflow delete 9001", result.output)  # recovery hint
        # M1 was completed before M2 aborted — banner must reflect that.
        self.assertIn("[x] M1", result.output)
        self.assertIn("[ ] M2", result.output)
        self.assertIn("[ ] M3", result.output)
        # JSON-mode addendum: structured failure block.
        self.assertIn('"creationComplete": false', result.output)
        self.assertIn('"failedMilestone": "M2-pitch-prompts"', result.output)
        # save_setting must NOT have been called.
        self.client_stub.save_setting.assert_not_called()

    def test_pipeline_failure_at_m3_save_setting_emits_banner(self):
        """When everything else succeeds but /save/setting itself fails,
        the banner must still fire — flowId exists, prompts persisted,
        but the AIFlow has no sequence binding so it's an orphan DRAFT."""
        self.client_stub.upload_contacts_csv.return_value = {
            "code": 200, "data": {"listId": 1, "listName": "c.csv"},
        }
        self.client_stub.create_aiflow_from_list.return_value = {
            "code": 200, "data": {"id": 7777},
        }
        self.client_stub.test_website_connection.return_value = {
            "code": 200, "data": {"officialDescription": "d"},
        }
        self.client_stub.save_pitch.return_value = {"code": 200}
        self.client_stub.get_workflow_prompt.side_effect = [
            [],
            [
                {"id": 10, "workflowStepId": 10, "step": 1,
                 "delayMinutes": 60, "emailContent": "filled"},
                {"id": 11, "workflowStepId": 11, "step": 2,
                 "delayMinutes": 4320, "emailContent": "filled"},
                {"id": 12, "workflowStepId": 12, "step": 3,
                 "delayMinutes": 10080, "emailContent": "filled"},
            ],
        ]
        self.client_stub.save_prompt.return_value = {"code": 200, "data": True}
        self.client_stub.get_setting.return_value = {
            "isShowAiReply": False, "autoApprove": False,
            "agentPromptList": [],
        }
        self.client_stub.list_time_templates.return_value = {
            "code": 200, "data": [{"id": 1, "name": "tpl",
                                   "properties": {}, "timeBlocks": []}],
        }
        self.client_stub.list_personal_meetings.return_value = {
            "code": 200, "data": [],
        }
        # M3's last call fails — pretend the engage service rejected
        # the launch.
        self.client_stub.save_setting.side_effect = Exception(
            "engage-api 500 — sequence binding refused"
        )

        result = self._invoke(
            "--no-wizard", "--csv", str(self.csv_path),
            "--url", "acme.com", "--language", "en-us",
            "--no-regenerate-emails",
            "-y",
        )
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("AIFLOW NOT CREATED", result.output)
        self.assertIn("M3", result.output)
        self.assertIn("7777", result.output)
        # M1 + M2 ticked, M3 not.
        self.assertIn("[x] M1", result.output)
        self.assertIn("[x] M2", result.output)
        self.assertIn("[ ] M3", result.output)
        self.assertIn('"failedMilestone": "M3-settings"', result.output)

    def test_default_create_triggers_regenerate_emails(self):
        """The default --regenerate-emails=True path must hit
        /get/email/prompt per seeded step. We don't run a real network
        call here — just assert the wizard announces the regenerate
        pass (proof the flag is default-on)."""
        self.client_stub.upload_contacts_csv.return_value = {
            "code": 200, "data": {"listId": 1, "listName": "c.csv"},
        }
        self.client_stub.create_aiflow_from_list.return_value = {
            "code": 200, "data": {"id": 999},
        }
        self.client_stub.test_website_connection.return_value = {
            "code": 200, "data": {"officialDescription": "d"},
        }
        self.client_stub.save_pitch.return_value = {"code": 200}
        self.client_stub.get_workflow_prompt.return_value = []
        # Stub save_prompt so seed_default_steps can run without real HTTP.
        self.client_stub.save_prompt.return_value = {"code": 200}

        # --no-launch so we don't need to mock /get/setting, meetings etc.
        result = self._invoke(
            "--no-wizard", "--csv", str(self.csv_path),
            "--url", "acme.com", "--language", "en-us",
            "--no-launch",
        )
        # Regardless of whether the LLM calls succeed on the stub, the
        # wizard should announce "Generating email prompt templates"
        # (the default-on regenerate path). A `--no-regenerate-emails`
        # run would show the yellow warning instead.
        self.assertIn("Generating email prompt templates", result.output)
        self.assertNotIn("--no-regenerate-emails: step rows will be saved",
                         result.output)


class TestAiflowEditCommands(unittest.TestCase):
    """pitch-update / prompt-show / prompt-update / settings-update."""

    def setUp(self):
        from click.testing import CliRunner
        from flashclaw_cli_plugin.flashrev_aiflow import flashrev_aiflow_cli

        self.runner = CliRunner()
        self.cli = flashrev_aiflow_cli.cli

        self.key_patch = patch(
            "flashclaw_cli_plugin.flashrev_aiflow."
            "flashrev_aiflow_cli.get_api_key",
            return_value="sk_test",
        )
        self.key_patch.start()

        self.client_stub = MagicMock()
        self.build_patch = patch(
            "flashclaw_cli_plugin.flashrev_aiflow."
            "flashrev_aiflow_cli._build_client",
            return_value=self.client_stub,
        )
        self.build_patch.start()

        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        patch.stopall()
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    # ── pitch-update ────────────────────────────────────────

    def test_pitch_update_calls_test_connection_then_save_pitch(self):
        self.client_stub.test_website_connection.return_value = {
            "code": 200,
            "data": {
                "officialDescription": "Acme Corp description",
                "painPoints": ["p1", "p2"],
                "solutions": ["s1"],
                "proofPoints": [],
                "callToActions": ["CTA"],
                "leadMagnets": [],
            },
        }
        self.client_stub.save_pitch.return_value = {"code": 200}

        result = self.runner.invoke(
            self.cli,
            ["--json", "aiflow", "pitch-update", "9001",
             "--url", "acme.com", "--language", "en-us"],
            catch_exceptions=False,
        )

        self.assertEqual(result.exit_code, 0, msg=result.output)
        self.client_stub.test_website_connection.assert_called_once_with(
            "acme.com", "en-us",
        )
        # save_pitch body must carry the workflowId + normalised https URL.
        save_args = self.client_stub.save_pitch.call_args[0][0]
        self.assertEqual(save_args["workflowId"], "9001")
        self.assertEqual(save_args["url"], "https://acme.com")
        self.assertEqual(save_args["language"], "en-us")
        self.assertFalse(save_args["useConfigLanguage"])
        self.assertEqual(save_args["officialDescription"], "Acme Corp description")

    def test_pitch_update_auto_language_sets_use_config_language(self):
        self.client_stub.test_website_connection.return_value = {
            "code": 200, "data": {"officialDescription": "x"}
        }
        self.client_stub.save_pitch.return_value = {"code": 200}

        result = self.runner.invoke(
            self.cli,
            ["--json", "aiflow", "pitch-update", "9001",
             "--url", "acme.com", "--language", "auto"],
            catch_exceptions=False,
        )
        self.assertEqual(result.exit_code, 0, msg=result.output)
        # test/connection still hits a concrete language (auto -> en-us).
        self.client_stub.test_website_connection.assert_called_once_with(
            "acme.com", "en-us",
        )
        save_args = self.client_stub.save_pitch.call_args[0][0]
        self.assertTrue(save_args["useConfigLanguage"])
        self.assertEqual(save_args["language"], "auto")

    # ── prompt-update ───────────────────────────────────────

    def test_prompt_update_errors_on_missing_file(self):
        result = self.runner.invoke(
            self.cli,
            ["--json", "aiflow", "prompt-update", "9001",
             "--file", "/nonexistent/prompts.json"],
            catch_exceptions=False,
        )
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("PROMPT_FILE_NOT_FOUND", result.output)

    def test_prompt_update_errors_on_bad_json(self):
        bad = Path(self.tmpdir) / "bad.json"
        bad.write_text("not json at all", encoding="utf-8")
        result = self.runner.invoke(
            self.cli,
            ["--json", "aiflow", "prompt-update", "9001",
             "--file", str(bad)],
            catch_exceptions=False,
        )
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("PROMPT_FILE_INVALID_JSON", result.output)

    def test_prompt_update_errors_on_empty_array(self):
        empty = Path(self.tmpdir) / "empty.json"
        empty.write_text("[]", encoding="utf-8")
        result = self.runner.invoke(
            self.cli,
            ["--json", "aiflow", "prompt-update", "9001",
             "--file", str(empty)],
            catch_exceptions=False,
        )
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("PROMPT_FILE_SHAPE_ERROR", result.output)

    def test_prompt_update_errors_on_missing_delay_minutes(self):
        broken = Path(self.tmpdir) / "broken.json"
        broken.write_text('[{"step": 1}]', encoding="utf-8")
        result = self.runner.invoke(
            self.cli,
            ["--json", "aiflow", "prompt-update", "9001",
             "--file", str(broken)],
            catch_exceptions=False,
        )
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("PROMPT_FILE_MISSING_DELAY", result.output)

    def test_prompt_update_forwards_array_to_save_prompt(self):
        self.client_stub.save_prompt.return_value = {"code": 200, "data": True}
        prompts = [
            {"step": 1, "delayMinutes": 60, "emailContent": "template-a",
             "emailSubject": "", "subject": "", "content": ""},
            {"step": 2, "delayMinutes": 4320, "emailContent": "template-b",
             "emailSubject": "", "subject": "", "content": ""},
        ]
        path = Path(self.tmpdir) / "p.json"
        path.write_text(json.dumps(prompts), encoding="utf-8")

        result = self.runner.invoke(
            self.cli,
            ["--json", "aiflow", "prompt-update", "9001",
             "--file", str(path)],
            catch_exceptions=False,
        )
        self.assertEqual(result.exit_code, 0, msg=result.output)
        self.client_stub.save_prompt.assert_called_once()
        flow_id_arg, prompts_arg = self.client_stub.save_prompt.call_args[0]
        self.assertEqual(flow_id_arg, "9001")
        self.assertEqual(len(prompts_arg), 2)
        self.assertEqual(prompts_arg[0]["emailContent"], "template-a")

    # ── settings-update ─────────────────────────────────────

    def test_settings_update_errors_when_no_flag(self):
        result = self.runner.invoke(
            self.cli,
            ["--json", "aiflow", "settings-update", "9001"],
            catch_exceptions=False,
        )
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("USAGE_NO_SETTING_UPDATE", result.output)

    def test_settings_update_mailboxes_all_active(self):
        # /get/setting snapshot — emailTrack + agentPromptList passthrough.
        self.client_stub.get_setting.return_value = {
            "isShowAiReply": True,
            "autoApprove": True,
            "enableAgentReply": False,
            "agentStrategy": "",
            "agentPromptList": [{"strategy": "Book Meeting", "prompt": "bm"}],
            "properties": {
                "timeTemplateConfig": {"name": "existing"},
                "timeTemplateId": 135,
                "emailTrack": {"trackOpen": True},
                "sequenceMailboxList": [{"addressId": 999}],
            },
        }
        self.client_stub.list_mailboxes.return_value = {
            "code": 200,
            "data": [
                {"id": 1479, "address": "a@x.com", "status": "ACTIVE"},
                {"id": 1480, "address": "b@x.com", "status": "ACTIVE"},
            ],
        }
        self.client_stub.save_setting.return_value = {
            "code": 200, "data": True,
        }

        result = self.runner.invoke(
            self.cli,
            ["--json", "aiflow", "settings-update", "9001",
             "--mailboxes", "all-active"],
            catch_exceptions=False,
        )
        self.assertEqual(result.exit_code, 0, msg=result.output)
        self.client_stub.list_time_templates.assert_not_called()
        save_body = self.client_stub.save_setting.call_args[0][0]
        mailbox_list = save_body["properties"]["sequenceMailboxList"]
        self.assertEqual({m["addressId"] for m in mailbox_list}, {1479, 1480})
        # emailTrack passthrough preserved.
        self.assertEqual(
            save_body["properties"]["emailTrack"], {"trackOpen": True}
        )
        # timeTemplateConfig preserved since --time-template-id not passed.
        self.assertEqual(
            save_body["properties"]["timeTemplateConfig"]["name"], "existing"
        )

    def test_settings_update_time_template_id_override(self):
        self.client_stub.get_setting.return_value = {
            "isShowAiReply": False,
            "autoApprove": False,
            "properties": {
                "timeTemplateConfig": {"name": "old"},
                "timeTemplateId": 100,
                "sequenceMailboxList": [{"addressId": 1}],
            },
        }
        self.client_stub.list_time_templates.return_value = {
            "code": 200,
            "data": [
                {"id": 200, "name": "new-tpl",
                 "properties": {"notSendOnUsHolidaysEnabled": 1},
                 "timeBlocks": [{"startTime": "09:00"}]},
            ],
        }
        self.client_stub.save_setting.return_value = {"code": 200, "data": True}

        result = self.runner.invoke(
            self.cli,
            ["--json", "aiflow", "settings-update", "9001",
             "--time-template-id", "200"],
            catch_exceptions=False,
        )
        self.assertEqual(result.exit_code, 0, msg=result.output)
        save_body = self.client_stub.save_setting.call_args[0][0]
        self.assertEqual(save_body["properties"]["timeTemplateId"], 200)
        self.assertEqual(
            save_body["properties"]["timeTemplateConfig"]["name"], "new-tpl"
        )

    def test_settings_update_time_template_id_not_found(self):
        self.client_stub.get_setting.return_value = {"setting": {}}
        self.client_stub.list_time_templates.return_value = {
            "code": 200,
            "data": [{"id": 100, "name": "x"}],
        }
        result = self.runner.invoke(
            self.cli,
            ["--json", "aiflow", "settings-update", "9001",
             "--time-template-id", "999"],
            catch_exceptions=False,
        )
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("TIME_TEMPLATE_NOT_FOUND", result.output)
        self.client_stub.save_setting.assert_not_called()

    def test_settings_update_auto_approve_flag(self):
        self.client_stub.get_setting.return_value = {
            "isShowAiReply": True,
            "autoApprove": True,  # current
            "enableAgentReply": False,
            "agentStrategy": "Book Meeting",
            "agentPromptList": [],
            "properties": {
                "sequenceMailboxList": [{"addressId": 1}],
                "timeTemplateConfig": {"name": "t"},
                "timeTemplateId": 1,
            },
        }
        self.client_stub.save_setting.return_value = {"code": 200}

        result = self.runner.invoke(
            self.cli,
            ["--json", "aiflow", "settings-update", "9001",
             "--no-auto-approve"],
            catch_exceptions=False,
        )
        self.assertEqual(result.exit_code, 0, msg=result.output)
        save_body = self.client_stub.save_setting.call_args[0][0]
        self.assertFalse(save_body["autoApprove"])
        # Other flags preserved from /get/setting.
        self.assertEqual(save_body["agentStrategy"], "Book Meeting")


class TestWelcomeBanner(unittest.TestCase):
    """First-run onboarding banner on bare CLI invocation."""

    def setUp(self):
        from click.testing import CliRunner
        from flashclaw_cli_plugin.flashrev_aiflow import flashrev_aiflow_cli

        self.runner = CliRunner()
        self.cli = flashrev_aiflow_cli.cli
        self.key_patch_path = (
            "flashclaw_cli_plugin.flashrev_aiflow."
            "flashrev_aiflow_cli.get_api_key"
        )

    def test_banner_shown_when_no_api_key(self):
        with patch(self.key_patch_path, return_value=None):
            result = self.runner.invoke(self.cli, [], catch_exceptions=False)
        self.assertEqual(result.exit_code, 0)
        # Success signal + exact privateApps URL + login command snippet.
        self.assertIn(
            "flashclaw-cli-plugin-flashrev-aiflow installed successfully.",
            result.output,
        )
        self.assertIn(
            "https://info.flashlabs.ai/settings/privateApps", result.output,
        )
        self.assertIn("auth login --token sk_xxx", result.output)
        # Help text still follows (banner does not suppress --help).
        self.assertIn("Usage:", result.output)

    def test_banner_suppressed_when_key_configured(self):
        with patch(self.key_patch_path, return_value="sk_fake_already_bound"):
            result = self.runner.invoke(self.cli, [], catch_exceptions=False)
        self.assertEqual(result.exit_code, 0)
        # No onboarding banner for returning users.
        self.assertNotIn("installed successfully", result.output)
        self.assertNotIn(
            "https://info.flashlabs.ai/settings/privateApps", result.output,
        )
        # Normal --help is still emitted.
        self.assertIn("Usage:", result.output)


if __name__ == "__main__":
    unittest.main()
