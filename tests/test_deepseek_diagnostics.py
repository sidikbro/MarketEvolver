import io
import json
import urllib.error

import pytest

from market_evolver.external.provider import DeepSeekProvider
from market_evolver.external.schemas import ExecutionStatus


class FixtureResponse:
    def __init__(self, status: int, content_type: str, body: bytes) -> None:
        self.status = status
        self.headers = {"Content-Type": content_type}
        self._body = body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def read(self, limit: int) -> bytes:
        assert limit == 1_000_001
        return self._body


@pytest.mark.unit
@pytest.mark.parametrize(
    ("status", "content_type", "body", "category", "authenticated"),
    (
        (200, "text/html", b"<html>gateway</html>", "non_json_response", None),
        (403, "text/html", b"<html>forbidden</html>", "auth_failure", False),
        (200, "application/json", b"", "non_json_response", None),
        (200, "application/json", b'{"data":[}', "malformed_json", None),
        (401, "application/json", b'{"error":"bad key"}', "auth_failure", False),
        (429, "application/json", b'{"error":"slow down"}', "rate_limit", True),
        (404, "application/json", b'{"error":"missing"}', "endpoint_failure", None),
        (503, "application/json", b'{"error":"unavailable"}', "provider_5xx", None),
    ),
)
def test_models_diagnostics_fixtures(
    status, content_type, body, category, authenticated
) -> None:
    result = DeepSeekProvider(
        api_key="super-secret-fixture-key",
        opener=lambda *args, **kwargs: FixtureResponse(status, content_type, body),
    ).validate()

    assert result.status is ExecutionStatus.FAILED_EXTERNAL
    assert result.failure_category == category
    assert result.authenticated is authenticated
    assert result.http_status == status
    assert result.content_type == content_type
    assert result.sanitized_response_preview is not None
    assert "super-secret-fixture-key" not in result.sanitized_response_preview
    assert len(result.sanitized_response_preview) <= 256


@pytest.mark.unit
def test_http_error_body_is_classified_without_losing_status() -> None:
    def forbidden(request, **kwargs):
        raise urllib.error.HTTPError(
            request.full_url,
            403,
            "Forbidden",
            {"Content-Type": "text/html"},
            io.BytesIO(b"<html>forbidden</html>"),
        )

    result = DeepSeekProvider(api_key="fixture-key", opener=forbidden).validate()
    assert result.failure_category == "auth_failure"
    assert result.http_status == 403
    assert result.authenticated is False


@pytest.mark.unit
def test_models_then_chat_success_discovers_available_model() -> None:
    requests = []

    def opener(request, **kwargs):
        requests.append(request)
        if request.get_method() == "GET":
            return FixtureResponse(
                200,
                "application/json; charset=utf-8",
                json.dumps({"data": [{"id": "available-model"}]}).encode(),
            )
        assert json.loads(request.data)["model"] == "available-model"
        return FixtureResponse(
            200,
            "application/json",
            json.dumps(
                {
                    "model": "available-model",
                    "choices": [{"message": {"content": '{"ok":true}'}}],
                    "usage": {"prompt_tokens": 7, "completion_tokens": 2},
                }
            ).encode(),
        )

    result = DeepSeekProvider(api_key="fixture-key", opener=opener).validate()
    assert [request.get_method() for request in requests] == ["GET", "POST"]
    assert requests[0].full_url == "https://api.deepseek.com/models"
    assert result.status is ExecutionStatus.PASS
    assert result.authenticated is True
    assert result.returned_model_id == "available-model"
    assert result.input_tokens == 7 and result.output_tokens == 2
    assert result.latency_ms >= 0


@pytest.mark.unit
def test_semantic_parse_failure_preserves_provider_accounting() -> None:
    def opener(request, **kwargs):
        if request.get_method() == "GET":
            return FixtureResponse(
                200,
                "application/json",
                json.dumps({"data": [{"id": "deepseek-v4-flash"}]}).encode(),
            )
        return FixtureResponse(
            200,
            "application/json",
            json.dumps(
                {
                    "id": "request-from-envelope",
                    "model": "deepseek-v4-flash",
                    "choices": [{"message": {"content": ""}}],
                    "usage": {"prompt_tokens": 113, "completion_tokens": 32},
                }
            ).encode(),
        )

    result = DeepSeekProvider(api_key="fixture-key", opener=opener).validate()
    assert result.status is ExecutionStatus.FAILED_EXTERNAL
    assert result.failure_category == "malformed_json"
    assert result.input_tokens == 113 and result.output_tokens == 32
    assert result.provider_request_id == "request-from-envelope"
    assert result.estimated_cost == "0.000025"
    assert result.raw_response_hash is not None


@pytest.mark.unit
def test_network_failure_is_distinct_and_bounded() -> None:
    attempts = 0

    def fail(*args, **kwargs):
        nonlocal attempts
        attempts += 1
        raise OSError("fixture network failure with super-secret-fixture-key")

    result = DeepSeekProvider(
        api_key="super-secret-fixture-key", opener=fail, sleeper=lambda _: None
    ).validate()
    assert attempts == 3
    assert result.failure_category == "network_failure"
    assert result.authenticated is None
    assert result.reachable is False
    assert "super-secret-fixture-key" not in (result.error_summary or "")
