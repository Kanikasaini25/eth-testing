"""Signed Delta REST helper with retries, 429 backoff, and timeout handling."""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from typing import Any
from urllib.parse import urlencode

import requests

from src.config import HTTP_MAX_RETRIES
from src.errors import DeltaAPIError, RateLimitError


def generate_signature(secret: str, message: str) -> str:
    return hmac.new(secret.encode("utf-8"), message.encode("utf-8"), hashlib.sha256).hexdigest()


class DeltaHttp:
    def __init__(self, base_url: str, api_key: str = "", api_secret: str = "") -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.api_secret = api_secret
        self.session = requests.Session()

    def _sign(self, method: str, path: str, query: str, body: str) -> dict[str, str]:
        timestamp = str(int(time.time()))
        query_string = query if not query or query.startswith("?") else f"?{query}"
        payload = body or ""
        signature_data = method.upper() + timestamp + path + query_string + payload
        return {
            "api-key": self.api_key,
            "timestamp": timestamp,
            "signature": generate_signature(self.api_secret, signature_data),
            "User-Agent": "bb-rsi-mean-reversion",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
        signed: bool = False,
        timeout: int = 15,
    ) -> Any:
        query = f"?{urlencode(params)}" if params else ""
        body = json.dumps(json_body, separators=(",", ":")) if json_body is not None else ""
        url = f"{self.base_url}{path}{query}"
        last_error: Exception | None = None

        for attempt in range(HTTP_MAX_RETRIES):
            headers = {"User-Agent": "bb-rsi-mean-reversion", "Accept": "application/json"}
            if signed:
                if not self.api_key or not self.api_secret:
                    raise DeltaAPIError("Signed request requires DELTA_API_KEY and DELTA_API_SECRET")
                headers = self._sign(method, path, query, body)
            try:
                response = self.session.request(
                    method=method.upper(),
                    url=url,
                    headers=headers,
                    data=body if body else None,
                    timeout=timeout,
                )
            except (requests.Timeout, requests.ConnectionError) as exc:
                last_error = exc
                time.sleep(min(2 ** attempt, 16))
                continue

            if response.status_code == 429:
                retry_after = float(response.headers.get("Retry-After", 2 ** attempt))
                time.sleep(min(max(retry_after, 1.0), 30.0))
                last_error = RateLimitError(response.text)
                continue

            if response.status_code >= 500:
                last_error = DeltaAPIError(f"HTTP {response.status_code}: {response.text}")
                time.sleep(min(2 ** attempt, 16))
                continue

            if response.status_code >= 400:
                raise DeltaAPIError(f"HTTP {response.status_code}: {response.text}")

            payload = response.json()
            if isinstance(payload, dict) and payload.get("success") is False:
                raise DeltaAPIError(str(payload.get("error") or payload))
            return payload.get("result", payload) if isinstance(payload, dict) else payload

        raise DeltaAPIError(f"Delta request failed after retries: {last_error}")
