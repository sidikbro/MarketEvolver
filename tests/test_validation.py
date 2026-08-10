from pathlib import Path

from market_evolver.validation import ValidationCheck, validate_system


def test_validation_fails_when_required_postgres_is_unavailable(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        "market_evolver.validation._run",
        lambda name, command, root, environment=None: ValidationCheck(
            name, "PASS", "mock", "passed"
        ),
    )
    monkeypatch.setattr(
        "market_evolver.validation._postgres_ready", lambda url: (False, "connection refused")
    )
    report = validate_system(tmp_path)
    assert report.status == "FAIL"
    assert {"postgres", "migrations"} <= set(report.failures)


def test_validation_rejects_critical_postgres_skips(monkeypatch, tmp_path: Path) -> None:
    def run(name, command, root, environment=None):
        return ValidationCheck(name, "PASS", "mock", "1 skipped")

    monkeypatch.setattr("market_evolver.validation._run", run)
    monkeypatch.setattr("market_evolver.validation._postgres_ready", lambda url: (True, "db"))
    monkeypatch.setattr(
        "market_evolver.validation._migration_check",
        lambda url, root, environment: ValidationCheck("migrations", "PASS", "mock", "head=0019"),
    )
    report = validate_system(tmp_path)
    assert report.status == "FAIL" and "postgres" in report.failures


def test_validation_pass_requires_every_critical_suite(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        "market_evolver.validation._run",
        lambda name, command, root, environment=None: ValidationCheck(
            name, "PASS", "mock", "all passed"
        ),
    )
    monkeypatch.setattr("market_evolver.validation._postgres_ready", lambda url: (True, "db"))
    monkeypatch.setattr(
        "market_evolver.validation._migration_check",
        lambda url, root, environment: ValidationCheck("migrations", "PASS", "mock", "head=0019"),
    )
    report = validate_system(tmp_path)
    assert report.status == "PASS" and report.failures == () and report.skips == ()
