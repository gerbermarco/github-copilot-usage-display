import io
from unittest.mock import patch
from urllib.error import HTTPError, URLError

import pytest

from copilot_usage_meter import __version__
from copilot_usage_meter.config import AppConfig
from copilot_usage_meter.github_client import GITHUB_API_BASE_URL, GitHubApiError, GitHubClient, USER_AGENT


class _FakeResponse:
    def __init__(self, payload: bytes) -> None:
        self._payload = payload

    def read(self) -> bytes:
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False


def _build_config(**overrides) -> AppConfig:
    values = {
        "github_token": "test-token",
        "copilot_license": None,
        "copilot_monthly_quota": None,
        "refresh_seconds": 10,
        "output_mode": "both",
        "eink_driver_module": "auto",
        "eink_rotation": 0,
        "api_version": "2026-03-10",
        "request_timeout_seconds": 15.0,
        "max_retries": 2,
        "retry_backoff_seconds": 1.5,
    }
    values.update(overrides)
    return AppConfig(**values)


def test_build_url_filters_none_query_values() -> None:
    client = GitHubClient(_build_config())

    url = client._build_url(
        "/users/octocat/settings/billing/premium_request/usage",
        {"year": 2026, "month": None, "product": "Copilot"},
    )

    assert url == (
        f"{GITHUB_API_BASE_URL}/users/octocat/settings/billing/premium_request/usage"
        "?year=2026&product=Copilot"
    )

def test_get_authenticated_username_sends_expected_headers() -> None:
    client = GitHubClient(_build_config())
    captured: dict[str, object] = {}

    def fake_urlopen(request, timeout):
        captured["request"] = request
        captured["timeout"] = timeout
        return _FakeResponse(b'{"login": "octocat"}')

    with patch("copilot_usage_meter.github_client.urlopen", side_effect=fake_urlopen):
        username = client.get_authenticated_username()

    request = captured["request"]
    assert hasattr(request, "header_items")
    headers = {key.lower(): value for key, value in request.header_items()}
    assert username == "octocat"
    assert headers["authorization"] == "Bearer test-token"
    assert headers["x-github-api-version"] == "2026-03-10"
    assert headers["user-agent"] == USER_AGENT
    assert USER_AGENT == f"copilot-usage-meter/{__version__}"
    assert captured["timeout"] == 15.0

def test_retries_retryable_http_errors_before_succeeding() -> None:
    client = GitHubClient(_build_config(max_retries=1, retry_backoff_seconds=2.0))
    attempts = iter(
        [
            HTTPError(
                url=f"{GITHUB_API_BASE_URL}/user",
                code=503,
                msg="Service Unavailable",
                hdrs=None,
                fp=io.BytesIO(b'{"message": "Try later"}'),
            ),
            _FakeResponse(b'{"login": "octocat"}'),
        ]
    )

    def fake_urlopen(request, timeout):
        del request, timeout
        next_item = next(attempts)
        if isinstance(next_item, Exception):
            raise next_item
        return next_item

    with (
        patch("copilot_usage_meter.github_client.urlopen", side_effect=fake_urlopen),
        patch("copilot_usage_meter.github_client.time.sleep") as sleep,
    ):
        username = client.get_authenticated_username()

    assert username == "octocat"
    sleep.assert_called_once_with(2.0)

def test_raises_network_error_after_retry_limit() -> None:
    client = GitHubClient(_build_config(max_retries=1, retry_backoff_seconds=2.0))

    with (
        patch(
            "copilot_usage_meter.github_client.urlopen",
            side_effect=URLError("offline"),
        ),
        patch("copilot_usage_meter.github_client.time.sleep") as sleep,
    ):
        with pytest.raises(GitHubApiError) as raised:
            client.get_authenticated_username()

    assert "Network error while calling GitHub API" in str(raised.value)
    sleep.assert_called_once_with(2.0)

def test_raises_parse_error_for_invalid_json() -> None:
    client = GitHubClient(_build_config())

    with patch(
        "copilot_usage_meter.github_client.urlopen",
        return_value=_FakeResponse(b"not-json"),
    ):
        with pytest.raises(GitHubApiError) as raised:
            client.get_authenticated_username()

    assert "Failed to parse JSON response" in str(raised.value)

def test_formats_http_error_message_from_response_body() -> None:
    client = GitHubClient(_build_config(max_retries=0))
    error = HTTPError(
        url=f"{GITHUB_API_BASE_URL}/user",
        code=404,
        msg="Not Found",
        hdrs=None,
        fp=io.BytesIO(
            b'{"message": "Not Found", "documentation_url": "https://docs.github.com/rest"}'
        ),
    )

    with patch("copilot_usage_meter.github_client.urlopen", side_effect=error):
        with pytest.raises(GitHubApiError) as raised:
            client.get_authenticated_username()

    assert raised.value.status_code == 404
    assert "GitHub API request failed: Not Found" in str(raised.value)
    assert "docs: https://docs.github.com/rest" in str(raised.value)