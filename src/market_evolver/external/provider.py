from __future__ import annotations

import hashlib
import json
import os
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from decimal import Decimal

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
            return ProviderValidationResult(
                self.profile.profile_id,
                ExecutionStatus.BLOCKED_PROVIDER,
                False,
                False,
                False,
                False,
                0,
                0,
                0,
                None,
                None,
                None,
                (),
                "DEEPSEEK_API_KEY is absent",
                now,
            )
        started = time.monotonic()
        body = {
            "model": self.model_id,
            "messages": [{"role": "user", "content": 'Return exactly {"ok":true} as JSON.'}],
            "temperature": 0,
            "max_tokens": 16,
            "response_format": {"type": "json_object"},
        }
        try:
            raw, request_id = self._request(body)
            document = json.loads(raw)
            content = json.loads(document["choices"][0]["message"]["content"])
            usage = document.get("usage", {})
            returned_model = document.get("model")
            response_metadata = tuple(
                (key, str(document[key]))
                for key in ("id", "system_fingerprint", "object")
                if document.get(key) is not None
            )
            structured = content == {"ok": True}
            status = ExecutionStatus.PASS if structured else ExecutionStatus.FAILED_EXTERNAL
            return ProviderValidationResult(
                self.profile.profile_id,
                status,
                True,
                True,
                True,
                structured,
                int(usage.get("prompt_tokens", 0)),
                int(usage.get("completion_tokens", 0)),
                round((time.monotonic() - started) * 1000),
                f"sha256:{hashlib.sha256(raw).hexdigest()}",
                request_id,
                returned_model if isinstance(returned_model, str) else None,
                response_metadata,
                None if structured else "provider did not return required structured response",
                self._clock(),
            )
        except (IntegrityViolation, KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
            return ProviderValidationResult(
                self.profile.profile_id,
                ExecutionStatus.FAILED_EXTERNAL,
                False,
                False,
                False,
                False,
                0,
                0,
                round((time.monotonic() - started) * 1000),
                None,
                None,
                None,
                (),
                type(exc).__name__,
                self._clock(),
            )

    def _request(self, body: dict[str, object]) -> tuple[bytes, str | None]:
        request = urllib.request.Request(
            self.profile.endpoint,
            data=json.dumps(body).encode(),
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
        )
        last_error: BaseException | None = None
        for attempt in range(self.profile.retry_attempts):
            try:
                response = self._opener(request, timeout=self.profile.timeout_seconds)
                with response:  # type: ignore[attr-defined]
                    raw = response.read(1_000_001)  # type: ignore[attr-defined]
                    request_id = response.headers.get("x-request-id")  # type: ignore[attr-defined]
                if len(raw) > 1_000_000:
                    raise IntegrityViolation("DeepSeek response exceeds size limit")
                if request_id is None:
                    try:
                        envelope = json.loads(raw)
                        value = envelope.get("id") if isinstance(envelope, dict) else None
                        request_id = value if isinstance(value, str) else None
                    except json.JSONDecodeError:
                        pass
                return raw, request_id
            except (OSError, TimeoutError, urllib.error.HTTPError) as exc:
                last_error = exc
                if attempt + 1 < self.profile.retry_attempts:
                    self._sleeper(self.profile.retry_backoff_seconds * (2**attempt))
        raise IntegrityViolation("DeepSeek request failed after bounded retries") from last_error


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
