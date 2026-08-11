import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from market_evolver.errors import IntegrityViolation, ValidationError
from market_evolver.live_validation import (
    BoundedHttpClient,
    HttpObservation,
    LiveStatus,
    LiveValidationHarness,
    ReplayEligibility,
    SourceContract,
    contract_fingerprint,
    project_storage,
    redact,
)

pytestmark = pytest.mark.unit
T0 = datetime(2026, 1, 1, tzinfo=UTC)


def test_contract_fingerprint_is_stable_and_detects_drift() -> None:
    first = contract_fingerprint(b'{"b":2,"a":1}', "application/json", ("a",))
    second = contract_fingerprint(b'{"a":9,"b":8}', "application/json", ("a",))
    assert first == second
    _, missing = contract_fingerprint(b'{"a":1}', "application/json", ("required",))
    assert missing == ("required",)
    with pytest.raises(IntegrityViolation):
        contract_fingerprint(b"not-json", "application/json", ())


def test_live_harness_requires_explicit_opt_in(tmp_path: Path) -> None:
    with pytest.raises(ValidationError, match="explicit operator opt-in"):
        LiveValidationHarness(tmp_path, opted_in=False)


def test_missing_user_agents_are_operator_skips_and_report_is_redacted(tmp_path: Path) -> None:
    fx = (
        b'{"exchangeRates":[{"key":"USD","currentExchangeRate":3.5,'
        b'"unit":1,"lastUpdate":"2026-01-01T00:00:00Z"}]}'
    )
    policy = b'{"currentInterest":4,"nextInterestDate":"2026-02-01T00:00:00Z"}'
    rss = b"""<rss><channel><item><title>Teva update</title><description>Bounded</description><link>https://www.bbc.com/news/x</link><pubDate>Thu, 01 Jan 2026 00:00:00 GMT</pubDate></item></channel></rss>"""

    def fetch(contract: SourceContract, user_agent: str) -> HttpObservation:
        body, media = (
            (rss, "application/rss+xml")
            if "bbc" in contract.source_id
            else (
                (policy if "policy" in contract.source_id else fx),
                "application/json",
            )
        )
        return HttpObservation(200, contract.endpoint, media, body)

    times = iter((T0, T0 + timedelta(seconds=1)))
    harness = LiveValidationHarness(
        tmp_path / "live_validation",
        opted_in=True,
        environment={},
        fetch=fetch,
        clock=lambda: next(times),
    )
    report = harness.run()
    by_source = {item.source_id: item for item in report.sources}
    assert by_source["us.sec.edgar"].status is LiveStatus.SKIPPED_BY_OPERATOR
    assert by_source["il.cbs.series.3763"].status is LiveStatus.SKIPPED_BY_OPERATOR
    assert report.status is LiveStatus.DEGRADED
    assert report.files == 3 and report.bytes == len(fx) + len(policy) + len(rss)
    assert json.loads((harness.run_root / "report.json").read_text())["status"] == "DEGRADED"
    assert "person@example.com" not in str(redact("agent person@example.com password=bad"))
    harness.cleanup()
    assert not harness.run_root.exists()


def test_schema_drift_fails_closed_after_raw_persistence(tmp_path: Path) -> None:
    def fetch(contract: SourceContract, user_agent: str) -> HttpObservation:
        return HttpObservation(200, contract.endpoint, "application/json", b'{"changed":true}')

    harness = LiveValidationHarness(tmp_path / "live_validation", opted_in=True, fetch=fetch)
    result = harness._boi_fx()
    assert result.status is LiveStatus.FAILED
    assert "required fields missing" in result.errors[0]
    assert sum(1 for path in harness.run_root.rglob("*") if path.is_file()) == 1


@pytest.mark.parametrize(
    ("response", "error"),
    (
        (HttpObservation(429, "https://example.invalid", "application/json", b"{}"), "HTTP status"),
        (
            HttpObservation(200, "https://example.invalid", "text/html", b"<html/>"),
            "content type drift",
        ),
        (
            HttpObservation(200, "https://example.invalid", "application/json", b"not-json"),
            "malformed JSON",
        ),
    ),
)
def test_http_contract_failures_are_reported(
    tmp_path: Path, response: HttpObservation, error: str
) -> None:
    harness = LiveValidationHarness(
        tmp_path / "live_validation",
        opted_in=True,
        environment={},
        fetch=lambda contract, user_agent: response,
    )
    result = harness._boi_fx()
    assert result.status is LiveStatus.FAILED
    assert error in result.errors[0]


def test_unavailable_source_is_reported_without_retry(tmp_path: Path) -> None:
    attempts = 0

    def unavailable(contract: SourceContract, user_agent: str) -> HttpObservation:
        nonlocal attempts
        attempts += 1
        raise OSError("offline")

    harness = LiveValidationHarness(
        tmp_path / "live_validation", opted_in=True, environment={}, fetch=unavailable
    )
    assert harness._boi_fx().status is LiveStatus.FAILED
    assert attempts == 1


def test_bounded_requests_and_storage_projection() -> None:
    client = BoundedHttpClient(max_total_requests=1)
    client.requests = 1
    contract = SourceContract(
        "test.source",
        "https://example.invalid/data",
        ("application/json",),
        (),
        "test/1",
        10,
        1,
        ReplayEligibility.DISABLED,
    )
    with pytest.raises(ValidationError, match="budget exhausted"):
        client.get(contract, user_agent="MarketEvolver test")
    projection = project_storage(100, 5, 30)
    assert projection.estimated_bytes == 3000
    secret = redact("postgresql://user:bad@localhost/db token=bad person@example.com")
    assert "user:bad" not in str(secret) and "person@example.com" not in str(secret)
