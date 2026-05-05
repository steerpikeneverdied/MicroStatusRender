from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from urllib import error, request


class MicrostatusApiError(Exception):
    pass


@dataclass(frozen=True)
class MicrostatusClientConfig:
    api_base: str
    display_id: str
    display_name: str
    location: str | None = None
    auth_token: str | None = None
    timeout_seconds: float = 5.0


class MicrostatusApiClient:
    def __init__(self, config: MicrostatusClientConfig):
        self.config = config

    def register_display(
        self,
        *,
        capabilities: dict[str, Any],
        metadata: dict[str, Any],
    ) -> dict[str, Any]:
        return self._request_json(
            "POST",
            "/microstatus/displays/register",
            {
                "display_id": self.config.display_id,
                "display_name": self.config.display_name,
                "location": self.config.location,
                "status": "online",
                "capabilities": capabilities,
                "metadata": metadata,
            },
        )

    def heartbeat(
        self,
        *,
        capabilities: dict[str, Any],
        metadata: dict[str, Any],
        status: str = "online",
    ) -> dict[str, Any]:
        return self._request_json(
            "POST",
            f"/microstatus/displays/{self.config.display_id}/heartbeat",
            {
                "display_name": self.config.display_name,
                "location": self.config.location,
                "status": status,
                "capabilities": capabilities,
                "metadata": metadata,
            },
        )

    def fetch_render_body(self) -> str:
        return self._request_text(
            "GET",
            f"/microstatus/displays/{self.config.display_id}/render/plain",
            accept="text/plain",
        )

    def _request_json(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        url = f"{self.config.api_base.rstrip('/')}{path}"
        headers = {"Accept": "application/json"}
        data = None
        if self.config.auth_token:
            headers["Authorization"] = f"Bearer {self.config.auth_token}"
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"

        req = request.Request(url=url, data=data, headers=headers, method=method.upper())
        try:
            with request.urlopen(req, timeout=self.config.timeout_seconds) as response:
                raw_body = response.read().decode("utf-8")
        except error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace").strip()
            raise MicrostatusApiError(detail or f"{exc.code} {exc.reason}") from exc
        except error.URLError as exc:
            raise MicrostatusApiError(str(exc.reason) or "Failed to contact Microstatus API.") from exc
        except OSError as exc:
            raise MicrostatusApiError(str(exc) or "Microstatus API request failed.") from exc

        if not raw_body.strip():
            return {}
        try:
            parsed = json.loads(raw_body)
        except json.JSONDecodeError as exc:
            raise MicrostatusApiError("Microstatus API returned invalid JSON.") from exc
        if not isinstance(parsed, dict):
            raise MicrostatusApiError("Microstatus API returned an unexpected payload shape.")
        return parsed

    def _request_text(
        self,
        method: str,
        path: str,
        *,
        accept: str = "text/plain",
    ) -> str:
        url = f"{self.config.api_base.rstrip('/')}{path}"
        headers = {"Accept": accept}
        if self.config.auth_token:
            headers["Authorization"] = f"Bearer {self.config.auth_token}"

        req = request.Request(url=url, headers=headers, method=method.upper())
        try:
            with request.urlopen(req, timeout=self.config.timeout_seconds) as response:
                return response.read().decode("utf-8")
        except error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace").strip()
            raise MicrostatusApiError(detail or f"{exc.code} {exc.reason}") from exc
        except error.URLError as exc:
            raise MicrostatusApiError(str(exc.reason) or "Failed to contact Microstatus API.") from exc
        except OSError as exc:
            raise MicrostatusApiError(str(exc) or "Microstatus API request failed.") from exc
