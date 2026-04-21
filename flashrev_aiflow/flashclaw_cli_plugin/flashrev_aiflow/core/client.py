"""HTTP client for FlashRev AIFlow — routed via auth-gateway-svc.

Request chain:
  CLI --[X-API-Key: sk_xxx]-> auth-gateway-svc --[Bearer + X-Auth-Company]-> upstream

Upstream services:
  discover-api.flashintel.ai  (FlashRev AIFlow / user / aiflow endpoints)
  engage-api.flashintel.ai    (mailbox pool, sequence; paths start with /engage)
  mailsvc / mail-api          (mailbox listing; paths start with /mailsvc)

Only endpoints that have been verified against the frontend project
(search-website) are wired up here. For endpoints that were requested by the
PRD but do not yet exist in the frontend (Google Sheet import, blacklist CRUD,
async pitch generation job, token-pricing), the CLI returns a clear error and
points to the confirmation needed.
"""

import requests

from flashclaw_cli_plugin.flashrev_aiflow.core.session import (
    get_api_key,
    get_base_url,
    get_discover_prefix,
    get_engage_prefix,
    get_mailsvc_prefix,
    get_timeout,
)


class FlashrevAiflowClient:
    """Stateless HTTP client for FlashRev AIFlow services via auth-gateway-svc."""

    def __init__(self, base_url: str = None, api_key: str = None):
        self.base_url = (base_url or get_base_url()).rstrip("/")
        self.api_key = api_key or get_api_key()
        self.timeout = get_timeout()
        self.discover_prefix = get_discover_prefix()
        self.engage_prefix = get_engage_prefix()
        self.mailsvc_prefix = get_mailsvc_prefix()

    # ── URL builders ─────────────────────────────────────────

    def _url_discover(self, path: str) -> str:
        """Build a URL for a discover-api path. path should begin with '/'."""
        return f"{self.base_url}{self.discover_prefix}{path}"

    def _url_engage(self, path: str) -> str:
        """Build a URL for an engage-api path. Expects path like '/engage/...'."""
        return f"{self.base_url}{self.engage_prefix}{path}"

    def _url_mailsvc(self, path: str) -> str:
        """Build a URL for a mailsvc path. Expects path like '/mailsvc/...'."""
        return f"{self.base_url}{self.mailsvc_prefix}{path}"

    # ── Request helpers ──────────────────────────────────────

    def _headers(self, extra: dict = None) -> dict:
        h = {"Content-Type": "application/json"}
        if self.api_key:
            h["X-API-Key"] = self.api_key
        if extra:
            h.update(extra)
        return h

    def _handle(self, resp: requests.Response) -> dict:
        resp.raise_for_status()
        if not resp.content:
            return {}
        try:
            return resp.json()
        except ValueError:
            return {"raw": resp.text}

    # ═══════════════════════════════════════════════════════════
    # Identity (discover-api)
    # ═══════════════════════════════════════════════════════════

    def get_user_info(self, additions: str = None) -> dict:
        """GET /api/v2/oauth/me — current user / company info."""
        params = {}
        if additions:
            params["additions"] = additions
        return self._handle(
            requests.get(
                self._url_discover("/api/v2/oauth/me"),
                params=params or None,
                headers=self._headers(),
                timeout=self.timeout,
            )
        )

    def get_token_balance(self) -> dict:
        """Derive token balance from GET /api/v2/oauth/me -> data.limit.

        Returns:
            {
              "tokenTotal":     float,   # data.limit.tokenTotal
              "tokenCost":      float,   # data.limit.tokenCost (0 if missing)
              "tokenRemaining": float,   # total - cost
              "sufficient":     bool,    # remaining > 0
            }

        Raises:
            ValueError if /me response is missing data.limit.tokenTotal.
            requests exceptions bubble up from get_user_info.
        """
        me = self.get_user_info() or {}
        data = me.get("data") or {}
        limit = data.get("limit") or {}
        if "tokenTotal" not in limit:
            raise ValueError(
                "data.limit.tokenTotal missing from /api/v2/oauth/me response"
            )
        total = float(limit["tokenTotal"] or 0)
        cost = float(limit.get("tokenCost") or 0)
        remaining = total - cost
        return {
            "tokenTotal": total,
            "tokenCost": cost,
            "tokenRemaining": remaining,
            "sufficient": remaining > 0,
        }

    # ═══════════════════════════════════════════════════════════
    # Contacts upload (discover-api)
    # ═══════════════════════════════════════════════════════════
    #
    # Expected endpoint contract (see flashrev_aiflow/README.md § "Backend
    # endpoint to add"). The frontend uses a Tencent Cloud + WebSocket upload
    # chain that is not practical for a CLI to replicate; for headless use
    # the backend should expose a direct multipart endpoint that internally
    # handles cloud storage and returns the same {listId, listName} pair.

    def upload_contacts_csv(self, file_path: str, data_type: str = "People") -> dict:
        """POST /api/v1/ai/workflow/contacts/upload  (multipart/form-data)

        Args:
            file_path: local path to the CSV file.
            data_type: 'People' or 'Company'. Forwarded as a form field.

        Expected response (matches AiWorkFlowListCreateDTO.listId: Long):
            { "code": 200,
              "data": {
                  "listId":   <Long>,   # UnlockPersonGroupPO primary key
                  "listName": <String>, # original filename
              } }

        The CLI treats listId opaquely and hands it back to
        POST /api/v1/ai/workflow/create/list verbatim.
        """
        url = self._url_discover("/api/v1/ai/workflow/contacts/upload")
        # Build headers without forcing Content-Type so requests can set
        # multipart boundaries correctly.
        headers = {}
        if self.api_key:
            headers["X-API-Key"] = self.api_key

        with open(file_path, "rb") as f:
            files = {"file": (self._basename(file_path), f, "text/csv")}
            data = {"dataType": data_type}
            return self._handle(
                requests.post(
                    url,
                    files=files,
                    data=data,
                    headers=headers,
                    timeout=self.timeout,
                )
            )

    @staticmethod
    def _basename(path: str) -> str:
        import os
        return os.path.basename(path)

    # ═══════════════════════════════════════════════════════════
    # AIFlow lifecycle (discover-api)
    # ═══════════════════════════════════════════════════════════

    def create_aiflow_from_list(self, payload: dict) -> dict:
        """POST /api/v1/ai/workflow/create/list

        Expected body: {listId, listName, type: 'csv', source: 'csv'}
        Expected response: {code: 200, data: {id: flowId}}
        """
        return self._handle(
            requests.post(
                self._url_discover("/api/v1/ai/workflow/create/list"),
                json=payload,
                headers=self._headers(),
                timeout=self.timeout,
            )
        )

    def list_aiflows(self, params: dict = None) -> dict:
        """GET /api/v1/ai/workflow/agent/list — list AIFlows."""
        return self._handle(
            requests.get(
                self._url_discover("/api/v1/ai/workflow/agent/list"),
                params=params or None,
                headers=self._headers(),
                timeout=self.timeout,
            )
        )

    def get_aiflow(self, flow_id: str) -> dict:
        """GET /api/v1/ai/workflow/agent/get/flow/{flowId} — AIFlow detail."""
        return self._handle(
            requests.get(
                self._url_discover(f"/api/v1/ai/workflow/agent/get/flow/{flow_id}"),
                headers=self._headers(),
                timeout=self.timeout,
            )
        )

    def set_aiflow_status(self, flow_id: str, status: str) -> dict:
        """GET /api/v1/ai/workflow/agent/sequence/status/{flowId}/{status}
        Used for start / pause / resume. status is passed verbatim.
        """
        return self._handle(
            requests.get(
                self._url_discover(
                    f"/api/v1/ai/workflow/agent/sequence/status/{flow_id}/{status}"
                ),
                headers=self._headers(),
                timeout=self.timeout,
            )
        )

    def delete_aiflow(self, flow_id: str) -> dict:
        """GET /api/v1/ai/workflow/agent/delete/{flowId}."""
        return self._handle(
            requests.get(
                self._url_discover(f"/api/v1/ai/workflow/agent/delete/{flow_id}"),
                headers=self._headers(),
                timeout=self.timeout,
            )
        )

    def batch_delete_aiflow(self, flow_ids: list) -> dict:
        """POST /api/v1/ai/workflow/agent/delete/batch."""
        return self._handle(
            requests.post(
                self._url_discover("/api/v1/ai/workflow/agent/delete/batch"),
                json={"ids": flow_ids},
                headers=self._headers(),
                timeout=self.timeout,
            )
        )

    def rename_aiflow(self, payload: dict) -> dict:
        """POST /api/v1/ai/workflow/agent/update/name."""
        return self._handle(
            requests.post(
                self._url_discover("/api/v1/ai/workflow/agent/update/name"),
                json=payload,
                headers=self._headers(),
                timeout=self.timeout,
            )
        )

    # ═══════════════════════════════════════════════════════════
    # Pitch (discover-api)
    # ═══════════════════════════════════════════════════════════

    def get_pitch(self, params: dict) -> dict:
        """GET /api/v1/ai/workflow/agent/get/pitch."""
        return self._handle(
            requests.get(
                self._url_discover("/api/v1/ai/workflow/agent/get/pitch"),
                params=params,
                headers=self._headers(),
                timeout=self.timeout,
            )
        )

    def save_pitch(self, payload: dict) -> dict:
        """POST /api/v1/ai/workflow/agent/save/pitch."""
        return self._handle(
            requests.post(
                self._url_discover("/api/v1/ai/workflow/agent/save/pitch"),
                json=payload,
                headers=self._headers(),
                timeout=self.timeout,
            )
        )

    def test_website_connection(self, url: str) -> dict:
        """POST /api/v1/ai/workflow/agent/test/connection (timeout 20s)."""
        return self._handle(
            requests.post(
                self._url_discover("/api/v1/ai/workflow/agent/test/connection"),
                json={"url": url},
                headers=self._headers(),
                timeout=20,
            )
        )

    # ═══════════════════════════════════════════════════════════
    # Email sequence templates (discover-api)
    # ═══════════════════════════════════════════════════════════

    def get_time_template(self) -> dict:
        """GET /api/v1/ai/workflow/agent/get/time/template."""
        return self._handle(
            requests.get(
                self._url_discover("/api/v1/ai/workflow/agent/get/time/template"),
                headers=self._headers(),
                timeout=self.timeout,
            )
        )

    # ═══════════════════════════════════════════════════════════
    # Mailbox binding (discover-api)
    # ═══════════════════════════════════════════════════════════

    def get_bind_email(self) -> dict:
        """GET /api/v1/ai/workflow/agent/get/bind/email."""
        return self._handle(
            requests.get(
                self._url_discover("/api/v1/ai/workflow/agent/get/bind/email"),
                headers=self._headers(),
                timeout=self.timeout,
            )
        )

    def save_bind_email(self, payload: dict) -> dict:
        """POST /api/v1/ai/workflow/agent/save/bind/email."""
        return self._handle(
            requests.post(
                self._url_discover("/api/v1/ai/workflow/agent/save/bind/email"),
                json=payload,
                headers=self._headers(),
                timeout=self.timeout,
            )
        )

    def get_email_config(self, payload: dict) -> dict:
        """POST /api/v1/ai/workflow/agent/get/email/config

        Body is typically {workflowId}. Returns the full email-setting
        config (timeTemplateConfig, emailTrack, sequenceMailboxList,
        timeTemplateId, autoApprove, ...) that the Settings step edits.
        """
        return self._handle(
            requests.post(
                self._url_discover("/api/v1/ai/workflow/agent/get/email/config"),
                json=payload,
                headers=self._headers(),
                timeout=self.timeout,
            )
        )

    def save_email_config(self, payload: dict) -> dict:
        """POST /api/v1/ai/workflow/agent/save/email/config

        Body shape (from search-website/src/views/ai-sdr/settings.vue:324):
            {
              workflowId,
              properties: {
                timeTemplateConfig, emailTrack, sequenceMailboxList,
                timeTemplateId, ...
              },
              autoApprove
            }
        """
        return self._handle(
            requests.post(
                self._url_discover("/api/v1/ai/workflow/agent/save/email/config"),
                json=payload,
                headers=self._headers(),
                timeout=self.timeout,
            )
        )

    def has_active_email(self) -> dict:
        """GET /api/v1/ai/workflow/agent/has/active/email."""
        return self._handle(
            requests.get(
                self._url_discover("/api/v1/ai/workflow/agent/has/active/email"),
                headers=self._headers(),
                timeout=self.timeout,
            )
        )

    # ═══════════════════════════════════════════════════════════
    # Automated approval toggle (discover-api)
    # ═══════════════════════════════════════════════════════════

    def get_auto_approve_status(self, flow_id: str) -> dict:
        """GET /api/v1/ai/workflow/agent/task/get/approve/status/{flowId}."""
        return self._handle(
            requests.get(
                self._url_discover(
                    f"/api/v1/ai/workflow/agent/task/get/approve/status/{flow_id}"
                ),
                headers=self._headers(),
                timeout=self.timeout,
            )
        )

    def save_auto_approve_status(self, payload: dict) -> dict:
        """POST /api/v1/ai/workflow/agent/task/save/approve/status."""
        return self._handle(
            requests.post(
                self._url_discover(
                    "/api/v1/ai/workflow/agent/task/save/approve/status"
                ),
                json=payload,
                headers=self._headers(),
                timeout=self.timeout,
            )
        )

    # ═══════════════════════════════════════════════════════════
    # Mailbox listing (mailsvc)
    # ═══════════════════════════════════════════════════════════

    def list_mailboxes(self, params: dict = None) -> dict:
        """GET /mailsvc/mail-address/simple/v2/list — bound mailbox addresses."""
        return self._handle(
            requests.get(
                self._url_mailsvc("/mailsvc/mail-address/simple/v2/list"),
                params=params or None,
                headers=self._headers(),
                timeout=self.timeout,
            )
        )

    # ═══════════════════════════════════════════════════════════
    # Mailbox pool (engage-api)
    # ═══════════════════════════════════════════════════════════

    def get_mailbox_pool_detail(self, sequence_id: str) -> dict:
        """GET /engage/api/mailbox-pool/detail/{sequenceId}."""
        return self._handle(
            requests.get(
                self._url_engage(f"/engage/api/mailbox-pool/detail/{sequence_id}"),
                headers=self._headers(),
                timeout=self.timeout,
            )
        )
