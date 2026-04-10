"""Base Ark API HTTP client."""

from __future__ import annotations

from typing import Any

import httpx

from changdu.errors import AuthError, NetworkError, RequestError, ServerError


class ArkClient:
    def __init__(self, *, api_key: str, base_url: str, timeout_s: int = 120) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.timeout_s = timeout_s

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}

    def post(self, endpoint: str, payload: dict[str, Any]) -> tuple[dict[str, Any], str | None]:
        return self._request("POST", endpoint, json=payload)

    def get(self, endpoint: str) -> tuple[dict[str, Any], str | None]:
        return self._request("GET", endpoint)

    def _request(self, method: str, endpoint: str, **kwargs: Any) -> tuple[dict[str, Any], str | None]:
        url = f"{self.base_url}{endpoint}"
        try:
            with httpx.Client(timeout=self.timeout_s) as client:
                response = client.request(method, url, headers=self._headers(), **kwargs)
        except httpx.RequestError as exc:
            raise NetworkError(f"Network error while calling Ark: {exc}") from exc

        request_id = response.headers.get("x-tt-logid") or response.headers.get("x-request-id")
        message = self._extract_error_message(response)
        if response.status_code in (401, 403):
            raise AuthError(message or "Authentication failed for Ark API.", request_id=request_id)
        if 400 <= response.status_code < 500:
            raise RequestError(message or f"Request rejected: HTTP {response.status_code}.", request_id=request_id)
        if response.status_code >= 500:
            raise ServerError(message or f"Ark server error: HTTP {response.status_code}.", request_id=request_id)

        try:
            return response.json(), request_id
        except ValueError as exc:
            raise ServerError("Ark response is not valid JSON.", request_id=request_id) from exc

    @staticmethod
    def _extract_error_message(response: httpx.Response) -> str:
        try:
            payload = response.json()
        except ValueError:
            return response.text[:500]
        if isinstance(payload, dict):
            error = payload.get("error")
            if isinstance(error, dict):
                return str(error.get("message") or error.get("code") or "")
            return str(payload.get("message") or payload.get("msg") or "")
        return ""
