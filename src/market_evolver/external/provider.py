from __future__ import annotations

import hashlib
import json
import os
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, cast

from market_evolver.errors import IntegrityViolation
from market_evolver.external.schemas import (
    EndpointClass,
    ExecutionStatus,
    ProviderExecutionProfile,
    ProviderValidationResult,
    UsageAccounting,
)
from market_evolver.research.providers import parse_claims, render_prompt
from market_evolver.research.schemas import ProviderCall, ResearchContext, ResearchTask

DEEPSEEK_PROFILE = ProviderExecutionProfile(
    "deepseek",
    "DeepSeek",
    "deepseek-v4-flash",
    EndpointClass.OPENAI_COMPATIBLE_CHAT,
    "https://api.deepseek.com/chat/completions",
    0.0,
    512,
    30,
    3,
    0.5,
    True,
    "0.14",
    "0.28",
    datetime(2026, 8, 13, tzinfo=UTC),
    "v028-deepseek-v4-flash-v1; 2026-08-13 cache-miss input and output USD pricing",
)

_PREVIEW_LIMIT = 256


@dataclass(frozen=True, slots=True)
class _HttpResponse:
    status: int
    content_type: str | None
    body: bytes
    request_id: str | None


class _NetworkFailure(Exception):
    pass


class DeepSeekProvider:
    provider_id = "deepseek"

    def __init__(
        self,
        profile: ProviderExecutionProfile = DEEPSEEK_PROFILE,
        *,
        api_key: str | None = None,
        opener: Callable[..., object] = urllib.request.urlopen,
        sleeper: Callable[[float], None] = time.sleep,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.profile = profile
        self.model_id = profile.model_id
        self._api_key = api_key if api_key is not None else os.environ.get("DEEPSEEK_API_KEY")
        self._opener = opener
        self._sleeper = sleeper
        self._clock = clock

    def invoke(
        self,
        task: ResearchTask,
        context: ResearchContext,
        *,
        prompt_version: str,
        settings: Mapping[str, str],
    ) -> ProviderCall:
        if not self._api_key:
            raise IntegrityViolation("DeepSeek credential is absent")
        requested = self._clock()
        body = {
            "model": self.model_id,
            "messages": [{"role": "user", "content": render_prompt(task, context, prompt_version)}],
            "temperature": self.profile.temperature,
            "max_tokens": self.profile.max_tokens,
            "response_format": {"type": "json_object"},
        }
        raw, request_id = self._request(body)
        try:
            document = json.loads(raw)
            content = document["choices"][0]["message"]["content"]
            usage = document.get("usage", {})
        except (json.JSONDecodeError, KeyError, IndexError, TypeError) as exc:
            raise IntegrityViolation("malformed DeepSeek response envelope") from exc
        if not isinstance(content, str) or not isinstance(usage, dict):
            raise IntegrityViolation("malformed DeepSeek structured output")
        try:
            structured = json.loads(content)
            claims_document = structured["claims"] if isinstance(structured, dict) else structured
            claims_json = json.dumps(claims_document)
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            raise IntegrityViolation("malformed DeepSeek claims document") from exc
        responded = self._clock()
        token_usage = {
            "input_tokens": int(usage.get("prompt_tokens", 0)),
            "output_tokens": int(usage.get("completion_tokens", 0)),
        }
        if request_id:
            token_usage["provider_request_id_present"] = 1
        return ProviderCall(
            self.provider_id,
            self.model_id,
            requested,
            responded,
            tuple(sorted(settings.items())),
            prompt_version,
            tuple(sorted(token_usage.items())),
            f"sha256:{hashlib.sha256(raw).hexdigest()}",
            parse_claims(claims_json, self.model_id, prompt_version, responded),
        )

    def validate(self) -> ProviderValidationResult:
        now = self._clock()
        if not self._api_key:
            return self._validation_result(
                status=ExecutionStatus.BLOCKED_PROVIDER,
                authenticated=None,
                error_summary="DEEPSEEK_API_KEY is absent",
                failure_category="auth_failure",
                validated_at=now,
            )
        started = time.monotonic()
        try:
            models_response = self._http_request(self._models_endpoint(), method="GET")
        except _NetworkFailure as exc:
            return self._failed_validation(
                started, "network_failure", None, f"network failure: {exc}"
            )
        models_failure = self._response_failure(models_response)
        if models_failure is not None:
            category, authenticated, summary = models_failure
            return self._failed_validation(
                started, category, authenticated, summary, models_response
            )
        try:
            models_document = json.loads(models_response.body)
        except json.JSONDecodeError:
            category = "malformed_json"
            return self._failed_validation(
                started,
                category,
                None,
                f"{category.replace('_', ' ')} from /models",
                models_response,
            )
        model_ids = self._model_ids(models_document)
        if not model_ids:
            return self._failed_validation(
                started,
                "malformed_json",
                None,
                "/models JSON contains no usable model IDs",
                models_response,
            )
        model_id = self._select_model(model_ids)
        body = {
            "model": model_id,
            "messages": [{"role": "user", "content": 'Return exactly {"ok":true} as JSON.'}],
            "temperature": 0,
            "max_tokens": 128,
            "response_format": {"type": "json_object"},
        }
        try:
            chat_response = self._http_request(self.profile.endpoint, method="POST", body=body)
        except _NetworkFailure as exc:
            return self._failed_validation(
                started, "network_failure", True, f"network failure: {exc}"
            )
        chat_failure = self._response_failure(chat_response)
        if chat_failure is not None:
            category, authenticated, summary = chat_failure
            return self._failed_validation(
                started,
                category,
                authenticated,
                summary,
                chat_response,
                model_id=model_id,
                model_available=True,
            )
        try:
            document = json.loads(chat_response.body)
        except json.JSONDecodeError:
            category = "malformed_json"
            return self._failed_validation(
                started,
                category,
                True,
                f"{category.replace('_', ' ')} from chat",
                chat_response,
                model_id=model_id,
                model_available=True,
            )
        usage = document.get("usage", {}) if isinstance(document, dict) else {}
        input_tokens = int(usage.get("prompt_tokens", 0)) if isinstance(usage, dict) else 0
        output_tokens = int(usage.get("completion_tokens", 0)) if isinstance(usage, dict) else 0
        returned_model = document.get("model") if isinstance(document, dict) else None
        response_metadata = tuple(
            (key, str(document[key]))
            for key in ("id", "system_fingerprint", "object")
            if isinstance(document, dict) and document.get(key) is not None
        )
        envelope_request_id = (
            chat_response.request_id
            or (str(document["id"]) if isinstance(document, dict) and document.get("id") else None)
        )
        try:
            content = json.loads(document["choices"][0]["message"]["content"])
            structured = content == {"ok": True}
            status = ExecutionStatus.PASS if structured else ExecutionStatus.FAILED_EXTERNAL
            return self._validation_result(
                status=status,
                authenticated=True,
                reachable=True,
                model_available=True,
                structured_response=structured,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                latency_ms=round((time.monotonic() - started) * 1000),
                raw_response_hash=f"sha256:{hashlib.sha256(chat_response.body).hexdigest()}",
                provider_request_id=envelope_request_id,
                returned_model_id=returned_model if isinstance(returned_model, str) else model_id,
                response_metadata=response_metadata + (("requested_model", model_id),),
                error_summary=None if structured else "provider did not return required structured response",
                validated_at=self._clock(),
                failure_category=None if structured else "malformed_json",
                response=chat_response,
            )
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            return self._failed_validation(
                started,
                "malformed_json",
                True,
                f"malformed chat response envelope: {type(exc).__name__}",
                chat_response,
                model_id=model_id,
                model_available=True,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                raw_response_hash=f"sha256:{hashlib.sha256(chat_response.body).hexdigest()}",
                provider_request_id=envelope_request_id,
                returned_model_id=(
                    returned_model if isinstance(returned_model, str) else model_id
                ),
                response_metadata=response_metadata + (("requested_model", model_id),),
            )

    def _models_endpoint(self) -> str:
        return self.profile.endpoint.split("/chat/completions", 1)[0] + "/models"

    @staticmethod
    def _model_ids(document: object) -> tuple[str, ...]:
        if not isinstance(document, dict) or not isinstance(document.get("data"), list):
            return ()
        return tuple(
            sorted(
                item["id"]
                for item in document["data"]
                if isinstance(item, dict) and isinstance(item.get("id"), str) and item["id"]
            )
        )

    def _select_model(self, model_ids: tuple[str, ...]) -> str:
        for candidate in (self.model_id, "deepseek-chat"):
            if candidate in model_ids:
                return candidate
        return model_ids[0]

    def _response_failure(
        self, response: _HttpResponse
    ) -> tuple[str, bool | None, str] | None:
        if response.status == 401 or response.status == 403:
            return "auth_failure", False, f"authentication rejected with HTTP {response.status}"
        if response.status == 429:
            return "rate_limit", True, "provider rate limit (HTTP 429)"
        if response.status >= 500:
            return "provider_5xx", None, f"provider server failure (HTTP {response.status})"
        if response.status < 200 or response.status >= 300:
            return "endpoint_failure", None, f"endpoint failure (HTTP {response.status})"
        content_type = (response.content_type or "").lower()
        if "json" not in content_type:
            return "non_json_response", None, "provider returned a non-JSON Content-Type"
        if not response.body.strip():
            return "non_json_response", None, "provider returned an empty JSON response"
        return None

    def _failed_validation(
        self,
        started: float,
        category: str,
        authenticated: bool | None,
        summary: str,
        response: _HttpResponse | None = None,
        *,
        model_id: str | None = None,
        model_available: bool = False,
        input_tokens: int = 0,
        output_tokens: int = 0,
        raw_response_hash: str | None = None,
        provider_request_id: str | None = None,
        returned_model_id: str | None = None,
        response_metadata: tuple[tuple[str, str], ...] = (),
    ) -> ProviderValidationResult:
        return self._validation_result(
            status=ExecutionStatus.FAILED_EXTERNAL,
            authenticated=authenticated,
            reachable=response is not None,
            model_available=model_available,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            raw_response_hash=raw_response_hash,
            provider_request_id=provider_request_id,
            returned_model_id=returned_model_id or model_id,
            response_metadata=response_metadata,
            latency_ms=round((time.monotonic() - started) * 1000),
            error_summary=summary,
            validated_at=self._clock(),
            failure_category=category,
            response=response,
        )

    def _validation_result(
        self,
        *,
        status: ExecutionStatus,
        authenticated: bool | None,
        validated_at: datetime,
        reachable: bool = False,
        model_available: bool = False,
        structured_response: bool = False,
        input_tokens: int = 0,
        output_tokens: int = 0,
        latency_ms: int = 0,
        raw_response_hash: str | None = None,
        provider_request_id: str | None = None,
        returned_model_id: str | None = None,
        response_metadata: tuple[tuple[str, str], ...] = (),
        error_summary: str | None = None,
        failure_category: str | None = None,
        response: _HttpResponse | None = None,
    ) -> ProviderValidationResult:
        accounting = usage_accounting(
            input_tokens, output_tokens, 1 if input_tokens or output_tokens else 0, latency_ms,
            self.profile,
        )
        return ProviderValidationResult(
            self.profile.profile_id,
            status,
            authenticated,
            reachable,
            model_available,
            structured_response,
            input_tokens,
            output_tokens,
            latency_ms,
            raw_response_hash,
            provider_request_id,
            returned_model_id,
            response_metadata,
            error_summary,
            validated_at,
            failure_category,
            response.status if response else None,
            response.content_type if response else None,
            self._sanitized_preview(response.body) if response else None,
            accounting.estimated_cost,
        )

    def _sanitized_preview(self, body: bytes) -> str:
        preview = " ".join(body.decode("utf-8", errors="replace").split())
        if self._api_key:
            preview = preview.replace(self._api_key, "[REDACTED]")
        # Defensive redaction for common credential-shaped response diagnostics.
        import re

        preview = re.sub(r"(?i)bearer\s+[a-z0-9._~+/=-]+", "Bearer [REDACTED]", preview)
        preview = re.sub(
            r'(?i)("?(?:authorization|api[_-]?key)"?\s*[:=]\s*")([^"]+)',
            r'\1[REDACTED]',
            preview,
        )
        return preview[:_PREVIEW_LIMIT]

    def _http_request(
        self, url: str, *, method: str, body: dict[str, object] | None = None
    ) -> _HttpResponse:
        request = urllib.request.Request(
            url,
            data=json.dumps(body).encode() if body is not None else None,
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
            method=method,
        )
        last_error: BaseException | None = None
        for attempt in range(self.profile.retry_attempts):
            try:
                try:
                    response = self._opener(request, timeout=self.profile.timeout_seconds)
                except urllib.error.HTTPError as exc:
                    response = exc
                response_any = cast(Any, response)
                with response:  # type: ignore[attr-defined]
                    raw = response.read(1_000_001)  # type: ignore[attr-defined]
                    headers = response.headers  # type: ignore[attr-defined]
                    status_value = getattr(response, "status", None)
                    status = int(
                        status_value if status_value is not None else response_any.getcode()
                    )
                    request_id = headers.get("x-request-id")
                    content_type = headers.get("Content-Type")
                if len(raw) > 1_000_000:
                    raise _NetworkFailure("DeepSeek response exceeds size limit")
                return _HttpResponse(status, content_type, raw, request_id)
            except (OSError, TimeoutError) as exc:
                last_error = exc
                if attempt + 1 < self.profile.retry_attempts:
                    self._sleeper(self.profile.retry_backoff_seconds * (2**attempt))
        raise _NetworkFailure(type(last_error).__name__ if last_error else "unknown network error")

    def _request(self, body: dict[str, object]) -> tuple[bytes, str | None]:
        try:
            response = self._http_request(self.profile.endpoint, method="POST", body=body)
        except _NetworkFailure as exc:
            raise IntegrityViolation("DeepSeek request failed after bounded retries") from exc
        if not 200 <= response.status < 300:
            raise IntegrityViolation(f"DeepSeek request failed with HTTP {response.status}")
        return response.body, response.request_id


def usage_accounting(
    input_tokens: int,
    output_tokens: int,
    calls: int,
    latency_ms: int,
    profile: ProviderExecutionProfile,
) -> UsageAccounting:
    estimated: str | None = None
    if profile.input_price_per_million_tokens and profile.output_price_per_million_tokens:
        cost = (
            Decimal(input_tokens) * Decimal(profile.input_price_per_million_tokens)
            + Decimal(output_tokens) * Decimal(profile.output_price_per_million_tokens)
        ) / Decimal(1_000_000)
        estimated = str(cost.quantize(Decimal("0.000001")))
    return UsageAccounting(input_tokens, output_tokens, calls, latency_ms, estimated)
