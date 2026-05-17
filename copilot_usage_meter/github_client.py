from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from . import __version__
from .config import AppConfig

RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}
GITHUB_API_BASE_URL = "https://api.github.com"
USER_AGENT = f"copilot-usage-meter/{__version__}"


@dataclass
class GitHubApiError(Exception):
    message: str
    status_code: Optional[int] = None
    response_body: str = ""

    def __str__(self) -> str:
        if self.status_code is None:
            return self.message
        return f"{self.message} (status={self.status_code})"


class GitHubClient:
    def __init__(self, config: AppConfig) -> None:
        self._config = config

    def _build_url(self, path: str, query: Optional[Dict[str, Any]] = None) -> str:
        url = f"{GITHUB_API_BASE_URL.rstrip('/')}/{path.lstrip('/')}"
        if query:
            filtered = {k: v for k, v in query.items() if v is not None}
            if filtered:
                url = f"{url}?{urlencode(filtered)}"
        return url

    def _sleep_before_retry(self, attempt: int) -> None:
        delay = self._config.retry_backoff_seconds * (2**attempt)
        if delay > 0:
            time.sleep(delay)

    def _request_json(self, method: str, path: str, query: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        url = self._build_url(path, query)
        last_error: Optional[Exception] = None

        for attempt in range(self._config.max_retries + 1):
            request = Request(
                url=url,
                method=method,
                headers={
                    "Accept": "application/vnd.github+json",
                    "Authorization": f"Bearer {self._config.github_token}",
                    "X-GitHub-Api-Version": self._config.api_version,
                    "User-Agent": USER_AGENT,
                },
            )

            try:
                with urlopen(request, timeout=self._config.request_timeout_seconds) as response:
                    payload = response.read()
                if not payload:
                    return {}
                return json.loads(payload.decode("utf-8"))
            except HTTPError as exc:
                body = exc.read().decode("utf-8", errors="replace")
                last_error = GitHubApiError(
                    message=self._format_http_error_message(body),
                    status_code=exc.code,
                    response_body=body,
                )
                if exc.code in RETRYABLE_STATUS_CODES and attempt < self._config.max_retries:
                    self._sleep_before_retry(attempt)
                    continue
                raise last_error
            except URLError as exc:
                last_error = GitHubApiError(f"Network error while calling GitHub API: {exc.reason}")
                if attempt < self._config.max_retries:
                    self._sleep_before_retry(attempt)
                    continue
                raise last_error
            except json.JSONDecodeError as exc:
                raise GitHubApiError(f"Failed to parse JSON response from GitHub API: {exc}") from exc

        if isinstance(last_error, Exception):
            raise last_error
        raise GitHubApiError("Unknown GitHub API error")

    @staticmethod
    def _format_http_error_message(body: str) -> str:
        base = "GitHub API request failed"
        if not body:
            return base

        try:
            parsed = json.loads(body)
        except json.JSONDecodeError:
            return base

        parts = []
        message = parsed.get("message")
        if isinstance(message, str) and message.strip():
            parts.append(message.strip())

        documentation_url = parsed.get("documentation_url")
        if isinstance(documentation_url, str) and documentation_url.strip():
            parts.append(f"docs: {documentation_url.strip()}")

        if not parts:
            return base
        return f"{base}: {' | '.join(parts)}"

    def get_authenticated_username(self) -> str:
        payload = self._request_json("GET", "/user")
        login = payload.get("login")
        if not isinstance(login, str) or not login.strip():
            raise GitHubApiError("Unable to resolve authenticated username from /user response")
        return login

    def get_user_premium_request_usage(
        self,
        username: str,
        year: Optional[int] = None,
        month: Optional[int] = None,
        day: Optional[int] = None,
        product: Optional[str] = "Copilot",
    ) -> Dict[str, Any]:
        return self._request_json(
            "GET",
            f"/users/{username}/settings/billing/premium_request/usage",
            query={
                "year": year,
                "month": month,
                "day": day,
                "product": product,
            },
        )

    def get_user_usage_summary(
        self,
        username: str,
        year: Optional[int] = None,
        month: Optional[int] = None,
        day: Optional[int] = None,
        product: Optional[str] = "Copilot",
    ) -> Dict[str, Any]:
        return self._request_json(
            "GET",
            f"/users/{username}/settings/billing/usage/summary",
            query={
                "year": year,
                "month": month,
                "day": day,
                "product": product,
            },
        )
