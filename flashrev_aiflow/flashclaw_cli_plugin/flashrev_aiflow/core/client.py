"""HTTP client for FlashRev AIFlow — routed via auth-gateway-svc.

Request chain:
  CLI --[X-API-Key: sk_xxx]-> auth-gateway-svc --[Bearer + X-Auth-Company]-> upstream

The CLI only talks to auth-gateway-svc. The gateway dispatches to the
correct upstream service based on the path prefix:

  {discover_prefix}   (default "/flashrev")    user/company, AIFlow CRUD, pitch, templates
  /engage             (prefix already in path)  mailbox pool detail, sequence
  /mailsvc            (prefix already in path)  bound mailbox listing
  {meeting_prefix}    (default "/meeting-svc") meeting routers (personal list)

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
    get_meeting_prefix,
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
        self.meeting_prefix = get_meeting_prefix()

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

    def _url_meeting(self, path: str) -> str:
        """Build a URL for a meeting-svc path. path should begin with '/'."""
        return f"{self.base_url}{self.meeting_prefix}{path}"

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

    def get_pitch(self, flow_id) -> dict:
        """GET /api/v1/ai/workflow/get/pitch/{workflowId}."""
        return self._handle(
            requests.get(
                self._url_discover(f"/api/v1/ai/workflow/get/pitch/{flow_id}"),
                headers=self._headers(),
                timeout=self.timeout,
            )
        )

    def save_pitch(self, payload: dict) -> dict:
        """POST /api/v1/ai/workflow/save/pitch — upsert t_ai_workflow_pitch.

        Body is the ICP-shaped DTO returned by :meth:`test_website_connection`
        with ``workflowId`` / ``url`` / ``language`` / ``useConfigLanguage``
        filled in. Backend persists fields as-is (no defaults, no validation
        beyond workflow-ownership). See dubbo-api-svc AiWorkFlowServiceImpl
        ``savePitch`` (line ~1115).
        """
        return self._handle(
            requests.post(
                self._url_discover("/api/v1/ai/workflow/save/pitch"),
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

    def test_website_connection(self, url: str, language: str = "en-us") -> dict:
        """POST /api/v1/ai/workflow/test/connection — LLM-generate pitch from URL.

        Body: ``{"url": <url>, "language": <lang>}``. Returns an
        ``AiWorkFlowPitchDTO`` shape with ``officialDescription`` + 5 list
        sections (``painPoints`` / ``solutions`` / ``proofPoints`` /
        ``callToActions`` / ``leadMagnets``) auto-generated by the remote AI
        service. Has NO side effects (no DB writes); the response is the
        direct input for :meth:`save_pitch` once a ``workflowId`` exists.

        Uses the shared ``self.timeout`` (default 300s, override via
        ``FLASHREV_AIFLOW_TIMEOUT``). The upstream has to fetch the target
        site (cold-cache fetches like tongchengir.com / ctrip.com routinely
        take 20-30s) and then run an LLM pass on top — the previous 20s
        cap was hit by any first-time URL even when the gateway / dubbo
        path itself was healthy.
        """
        return self._handle(
            requests.post(
                self._url_discover("/api/v1/ai/workflow/test/connection"),
                json={"url": url, "language": language},
                headers=self._headers(),
                timeout=self.timeout,
            )
        )

    # ═══════════════════════════════════════════════════════════
    # Email sequence templates (engage-api)
    # ═══════════════════════════════════════════════════════════

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

    def get_bind_email(self, flow_id) -> dict:
        """GET /api/v1/ai/workflow/get/bind/email/{workflowId} — mailbox pool
        bound to the given AIFlow."""
        return self._handle(
            requests.get(
                self._url_discover(f"/api/v1/ai/workflow/get/bind/email/{flow_id}"),
                headers=self._headers(),
                timeout=self.timeout,
            )
        )

    def get_unbind_email(self, flow_id) -> dict:
        """GET /api/v1/ai/workflow/get/unbind/email/{workflowId} — mailboxes
        still actively used by the given AIFlow (the ones that would be
        unbound if the flow were torn down)."""
        return self._handle(
            requests.get(
                self._url_discover(f"/api/v1/ai/workflow/get/unbind/email/{flow_id}"),
                headers=self._headers(),
                timeout=self.timeout,
            )
        )

    def save_setting(self, payload: dict) -> dict:
        """POST /api/v1/ai/workflow/save/setting — persist email settings AND
        transition the flow from DRAFT to ACTIVE.

        This is what the frontend's "Launch AIFlow" button on
        /flow/steps/settings hits
        (search-website/src/views/ai-sdr/settings.vue:358 calling
        ai-sdr/index.ts::saveSetting at line 290-297).

        An attempt to launch via GET /sequence/status/{flowId}/ACTIVE
        returns ``{code:200, data:false}`` and does not actually flip the
        state machine; this endpoint is the real launch path.

        Body shape, optionally plus AI-reply fields when enabled:
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
        """GET /api/v1/ai/workflow/has/active/email — company has at least one
        actively-bound mailbox (global, not per-flow)."""
        return self._handle(
            requests.get(
                self._url_discover("/api/v1/ai/workflow/has/active/email"),
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
    # Email prompt generation (discover-api)
    # ═══════════════════════════════════════════════════════════

    def get_email_prompt(
        self,
        workflow_id,
        workflow_step_id=None,
        before_step: list = None,
    ) -> dict:
        """POST /api/v1/ai/workflow/get/email/prompt — per-step LLM prompt.

        Backend is SSE-streamed; requests collects the full body before
        returning, so the default ``_handle`` works (falls back to
        ``{"raw": text}`` if content-type is event-stream).

        Body:
            {
              "workflowId":     <Long>,
              "workflowStepId": <Long>,           # optional; short-circuits
                                                  # to saved emailContent
              "beforStep":      [                 # prior-step context
                 {"emailSubject": ..., "emailContent": ...}, ...
              ]
            }

        The frontend (typing-effect.vue:211-228) builds ``beforStep`` from
        the preceding pipeline entries. CLI does the same when iterating
        step by step.
        """
        body = {"workflowId": workflow_id, "beforStep": before_step or []}
        if workflow_step_id is not None:
            body["workflowStepId"] = workflow_step_id
        return self._handle(
            requests.post(
                self._url_discover("/api/v1/ai/workflow/get/email/prompt"),
                json=body,
                headers=self._headers(),
                timeout=self.timeout,
            )
        )

    def get_email(self, payload: dict) -> dict:
        """POST /api/v1/ai/workflow/get/email — LLM-generate sample subject+body.

        Costs 1 token on token-metered accounts (dubbo equityService). Frontend
        calls this after ``/get/email/prompt`` finishes streaming to fill in
        the editable ``subject``/``content`` preview pair.

        Returns ``{step, subject, content}``.
        """
        return self._handle(
            requests.post(
                self._url_discover("/api/v1/ai/workflow/get/email"),
                json=payload,
                headers=self._headers(),
                timeout=self.timeout,
            )
        )

    def save_prompt(self, workflow_id, prompts: list) -> dict:
        """POST /api/v1/ai/workflow/save/prompt — persist per-step prompts.

        Body:
            {
              "workflowId": <Long>,
              "prompts": [
                {
                  "workflowStepId": <Long>,     # required by backend
                  "step":           1,
                  "stepType":       "email",
                  "delayMinutes":   0|60|1440|10080|...,
                  "emailSubject":   "...",       # LLM prompt template
                  "emailContent":   "...",       # LLM prompt template
                  "subject":        "...",       # sample subject
                  "content":        "..."        # sample body
                }, ...
              ]
            }

        IMPORTANT: backend saves empty fields as empty strings — it does NOT
        auto-fill defaults. See dubbo-api-svc AiWorkFlowServiceImpl ``savePrompt``
        (line ~1560). The CLI wizard generates defaults via
        :meth:`get_email_prompt` / :meth:`get_email` when the user opts in
        (``--regenerate-emails``).
        """
        return self._handle(
            requests.post(
                self._url_discover("/api/v1/ai/workflow/save/prompt"),
                json={"workflowId": workflow_id, "prompts": prompts},
                headers=self._headers(),
                timeout=self.timeout,
            )
        )

    # ═══════════════════════════════════════════════════════════
    # Setting read (discover-api)
    # ═══════════════════════════════════════════════════════════

    def get_setting(self, workflow_id) -> dict:
        """GET /api/v1/ai/workflow/get/setting/{workflowId}.

        Response keys (dubbo-api-svc AiWorkFlowServiceImpl line ~1264):
          - isShowAiReply    bool, true for flows created after 2026-02-07
          - autoApprove      bool?, from t_ai_workflow
          - enableAgentReply bool?, from t_ai_workflow
          - agentStrategy    str?,  from t_ai_workflow
          - agentPromptList  list,  from t_ai_workflow_agent_prompt
                             (falls back to default prompts row with
                             workflowId=0 when no per-flow entries exist)
          - setting?         {properties: {timeTemplateConfig,
                               timeTemplateId, sequenceMailboxList,
                               emailTrack}}  — only populated for flows
                               that already have a sequenceId (ACTIVE /
                               PAUSED). DRAFT flows return no `setting`.

        This is the **source of truth** for the ``save/setting`` body
        (agentPromptList, emailTrack, defaults are all read from here).
        """
        return self._handle(
            requests.get(
                self._url_discover(
                    f"/api/v1/ai/workflow/get/setting/{workflow_id}"
                ),
                headers=self._headers(),
                timeout=self.timeout,
            )
        )

    # ═══════════════════════════════════════════════════════════
    # Draft workflow lookup (discover-api)
    # ═══════════════════════════════════════════════════════════

    def get_draft_workflow(self) -> dict:
        """GET /api/v1/ai/workflow/draft — the current user's most recent DRAFT.

        Returns a single ``AiWorkFlowDTO`` (``{id, type, companyId, userId}``)
        or an empty object when the user has no draft. Used by the web UI's
        "Resume Draft" banner; CLI exposes it read-only via ``aiflow draft``
        (no resume support — each ``aiflow create`` builds a fresh flow).
        """
        return self._handle(
            requests.get(
                self._url_discover("/api/v1/ai/workflow/draft"),
                headers=self._headers(),
                timeout=self.timeout,
            )
        )

    # ═══════════════════════════════════════════════════════════
    # Meeting routers (meeting-svc)
    # ═══════════════════════════════════════════════════════════

    def list_personal_meetings(
        self, meet_name: str = "", meet_type: str = ""
    ) -> dict:
        """POST /meeting/api/v1/meeting/personal/list.

        The full path ``/meeting/api/v1/meeting/personal/list`` is kept in
        the client (not split between gateway prefix + suffix) so that
        auth-gateway-svc's ``/meeting-svc`` route can point at a bare
        upstream domain (``https://meeting-api{-test}.<host>``) and stay
        symmetric with ``/flashrev``.

        Body (both optional filters): ``{"meetName": "...", "meetType": "..."}``
        Returns ``{code, data: [MeetingProfileVO, ...]}`` where each item has
        ``{id, meetingName, meetingType, meetingDuration, meetingUrl,
        memberList, ownerId, ...}``.

        First item's ``id`` is used as ``agentPromptList[0].meetingRouteId``
        for the Book Meeting strategy (mirrors search-website
        ai-sdr/v2/components/ai-reply.vue:192-194).
        """
        return self._handle(
            requests.post(
                self._url_meeting("/meeting/api/v1/meeting/personal/list"),
                json={"meetName": meet_name, "meetType": meet_type},
                headers=self._headers(),
                timeout=self.timeout,
            )
        )
