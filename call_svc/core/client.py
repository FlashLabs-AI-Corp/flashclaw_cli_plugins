"""HTTP client for call-svc — routed via auth-gateway-svc.

请求链路：
  CLI  --[X-API-Key: sk_xxx]-→  auth-gateway-svc  --[Bearer + X-Auth-Company]-→  call-svc
"""

import requests

from flashclaw_cli_plugin.call_svc.core.session import get_api_key, get_base_url, get_timeout

# Gateway route prefix for call-svc
_PREFIX = "/callsvc"


class CallSvcClient:
    """Stateless HTTP client for call-svc, routed through auth-gateway-svc."""

    def __init__(self, base_url: str = None, api_key: str = None):
        self.base_url = (base_url or get_base_url()).rstrip("/")
        self.api_key = api_key or get_api_key()
        self.timeout = get_timeout()

    def _headers(self) -> dict:
        h = {"Content-Type": "application/json"}
        if self.api_key:
            h["X-API-Key"] = self.api_key
        return h

    def _url(self, path: str) -> str:
        return f"{self.base_url}{_PREFIX}{path}"

    def _handle(self, resp: requests.Response) -> dict:
        resp.raise_for_status()
        return resp.json()

    # ── Number management ────────────────────────────────────

    def available_numbers(
        self,
        country_code: str = "us",
        region_code: str = None,
        page: int = 1,
        page_size: int = 20,
    ) -> dict:
        """Query local numbers available for purchase."""
        params = {
            "countryCode": country_code,
            "page": page,
            "pageSize": page_size,
        }
        if region_code:
            params["regionCode"] = region_code

        return self._handle(
            requests.get(
                self._url("/api/v1/call-number/available-numbers"),
                params=params,
                headers=self._headers(),
                timeout=self.timeout,
            )
        )

    def purchased_numbers(self) -> dict:
        """Query phone numbers already purchased by the current company."""
        return self._handle(
            requests.get(
                self._url("/api/v1/call-number/purchased-numbers"),
                headers=self._headers(),
                timeout=self.timeout,
            )
        )

    def buy_number(self, payload: dict) -> dict:
        """Purchase a phone number and bind it to the current company."""
        return self._handle(
            requests.post(
                self._url("/api/v1/call-number/buy"),
                json=payload,
                headers=self._headers(),
                timeout=self.timeout,
            )
        )

    def voice_call(self, payload: dict) -> dict:
        """Initiate a voice call (legacy shim)."""
        return self._handle(
            requests.post(
                self._url("/api/v1/call-number/voice-call"),
                json=payload,
                headers=self._headers(),
                timeout=self.timeout,
            )
        )
