"""HTTP client for FlashRev AIFlow — routed via auth-gateway-svc.

Request chain:
  CLI --[X-API-Key: sk_xxx]-> auth-gateway-svc --[Bearer + X-Auth-Company]-> upstream

The CLI only talks to auth-gateway-svc. The gateway dispatches to the
correct upstream service based on the path prefix:

  {discover_prefix}   (default "/flashrev")    user/company, AIFlow CRUD, pitch, templates
  /engage             (prefix already in path)  mailbox pool detail, sequence
  /mailsvc            (prefix already in path)  bound mailbox listing

Which upstream owns each prefix is configured on the gateway side
(proxy.routes in auth-gateway-svc config); this client does not and
does not need to know the upstream URLs.

Only endpoints that have been verified against the frontend project
(search-website) are wired up here. For endpoints that were requested
by the PRD but not found in the frontend (Google Sheet import,
blacklist CRUD, async pitch generation job, token-pricing), the CLI
returns a clear error and points to the confirmation needed.
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
        """POST /api/v1/ai/workflow/type/rows — list AIFlows.

        Backend writes to HttpServletResponse (stream); requests still
        collects the full body before returning, so resp.json() or the
        _handle fallback works.

        Default body: {type: "All", viewType: "person"}.
        Extra keys from *params* (e.g. type override) are merged in.
        """
        body = {"type": "All", "viewType": "person"}
        if params:
            body.update(params)
        return self._handle(
            requests.post(
                self._url_discover("/api/v1/ai/workflow/type/rows"),
                json=body,
                headers=self._headers(),
                timeout=self.timeout,
            )
        )

    def get_aiflow(self, flow_id) -> dict:
        """GET /api/v1/ai/workflow/detail/nodes/{workflowId} — AIFlow detail.

        Returns a list of workflow nodes (each with id, name, sort,
        openUrl, configuration JSON string, scenario).
        """
        return self._handle(
            requests.get(
                self._url_discover(f"/api/v1/ai/workflow/detail/nodes/{flow_id}"),
                headers=self._headers(),
                timeout=self.timeout,
            )
        )

    def set_aiflow_status(self, flow_id, status: str) -> dict:
        """POST /api/v1/ai/workflow/status — change AIFlow status.

        Body: {id: <Long>, status: "ACTIVE" | "PAUSED"}
        Used for start / pause / resume on already-launched flows.
        For the initial DRAFT -> ACTIVE transition use save_setting().
        """
        return self._handle(
            requests.post(
                self._url_discover("/api/v1/ai/workflow/status"),
                json={"id": flow_id, "status": status},
                headers=self._headers(),
                timeout=self.timeout,
            )
        )

    def delete_aiflow(self, flow_id) -> dict:
        """POST /api/v1/ai/workflow/delete — delete a single AIFlow.

        Body: {id: <Long>}
        """
        return self._handle(
            requests.post(
                self._url_discover("/api/v1/ai/workflow/delete"),
                json={"id": flow_id},
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

    def get_workflow_prompt(self, workflow_id) -> dict:
        """POST /api/v1/ai/workflow/get/prompt (SSE-style streaming response).

        The first call on a newly-created flow has an important
        **side effect**: the backend reads the flow's ICP targeting +
        pitch + header variables and auto-generates default email
        prompts (``emailSubject`` / ``emailContent`` LLM prompts +
        sample ``subject`` / ``content``) for each step, then persists
        them to ``t_ai_workflow_prompt``. Subsequent calls just return
        the stored rows.

        The CLI invokes this in the create pipeline purely for the
        side effect: without it, ``save/setting`` launches a flow whose
        ``t_ai_workflow_prompt`` is empty, and the schedule runner may
        find no prompts to feed the LLM when the send window opens.

        The response body is a JSON array of step dicts; requests.post
        still returns once the server has written the full body, so
        ``resp.json()`` works (with ``_handle``'s ``{"raw": text}``
        fallback for any odd content type).
        """
        return self._handle(
            requests.post(
                self._url_discover("/api/v1/ai/workflow/get/prompt"),
                json={"workflowId": workflow_id},
                headers=self._headers(),
                timeout=self.timeout,
            )
        )

    def save_workflow_prompt(self, payload: dict) -> dict:
        """POST /api/v1/ai/workflow/save/prompt — persist edited step prompts.

        Body shape (from search-website/src/views/ai-sdr/workflow.vue:462):
            {
              workflowId: Long,
              prompts: [
                {
                  id?, workflowStepId?,              # for edits; omit on new
                  step: Integer,                     # 1..20
                  stepType: "Email",
                  delayMinutes: Integer,             # 0 / 1440=1d / 10080=1w
                  emailSubject: String,              # LLM prompt, {{var}} ok
                  emailContent: String,              # LLM prompt, {{var}} ok
                  subject?: String,                  # generated sample (opt)
                  content?: String,                  # generated sample (opt)
                }, ...
              ]
            }

        Not currently invoked by any CLI command — included for the future
        ``aiflow workflow save`` command. For the default-prompts case
        (create + launch), :meth:`get_workflow_prompt` is enough since
        the backend auto-generates + persists defaults on first call.
        """
        return self._handle(
            requests.post(
                self._url_discover("/api/v1/ai/workflow/save/prompt"),
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

    def list_time_templates(self, params: dict = None) -> dict:
        """GET /engage/api/v1/time/template/list — list available send-time templates.

        The save/setting endpoint requires a non-null ``timeTemplateConfig``
        (``get_time_template`` returns empty for fresh draft flows), so the
        wizard picks a template from this listing when launching. Each item
        in ``data`` has ``{id, name, properties, timeBlocks, busSource}``.
        """
        return self._handle(
            requests.get(
                self._url_engage("/engage/api/v1/time/template/list"),
                params=params or None,
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

        Persists email-setting config while leaving the flow in DRAFT.
        Use this for `aiflow create --no-launch`. For launch-on-create,
        use :meth:`save_setting` instead — save_email_config alone does
        NOT transition the flow to ACTIVE.

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

    def save_setting(self, payload: dict) -> dict:
        """POST /api/v1/ai/workflow/save/setting  (note: no /agent/ segment)

        Launch-the-flow endpoint. This is what the frontend's
        "Launch AIFlow" button on /flow/steps/settings hits
        (search-website/src/views/ai-sdr/settings.vue:358 calling
        ai-sdr/index.ts::saveSetting at line 290-297).

        Distinguishes itself from :meth:`save_email_config` in two ways:
            1. Different URL path -- /save/setting, NOT /agent/save/email/config.
            2. Side effect -- both persists the settings body AND transitions
               the flow from DRAFT to ACTIVE.

        An attempt to launch via GET /sequence/status/{flowId}/ACTIVE
        returns ``{code:200, data:false}`` and does not actually flip the
        state machine; this endpoint is the real launch path.

        Body shape is the same as save_email_config's, optionally plus
        AI-reply fields when enabled:
            {
              workflowId,
              properties: { timeTemplateConfig, emailTrack,
                            sequenceMailboxList, timeTemplateId, ... },
              autoApprove,
              # optional (only when isShowAiReply is on in the frontend):
              agentPromptList, enableAgentReply, agentStrategy
            }
        """
        return self._handle(
            requests.post(
                self._url_discover("/api/v1/ai/workflow/save/setting"),
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
