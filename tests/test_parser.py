"""Unit tests for workflow URL and failure parsing."""

from __future__ import annotations

import io
import json
import zipfile
from typing import Any

import pytest

from actions_log_parser.parser import analyze_run, classify_failure, parse_run_url


class MockClient:
    """Small GitHub client test double with deterministic API responses."""

    def __init__(self, run: dict[str, Any], jobs: list[dict[str, Any]], logs: dict[str, str]):
        self.run = run
        self.jobs = jobs
        self.logs = logs

    def fetch_run(self, owner: str, repo: str, run_id: int) -> dict[str, Any]:
        """Return mocked run metadata."""

        assert (owner, repo, run_id) == ("acme", "widget", 42)
        return self.run

    def fetch_jobs(self, owner: str, repo: str, run_id: int) -> list[dict[str, Any]]:
        """Return mocked jobs."""

        assert (owner, repo, run_id) == ("acme", "widget", 42)
        return self.jobs

    def download_logs(self, owner: str, repo: str, run_id: int) -> bytes:
        """Return a mocked ZIP log archive."""

        assert (owner, repo, run_id) == ("acme", "widget", 42)
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            for name, body in self.logs.items():
                archive.writestr(name, body)
        return buffer.getvalue()


def job(name: str = "tests", step: str = "Run tests") -> dict[str, Any]:
    """Build a failed GitHub job fixture."""

    return {
        "name": name,
        "conclusion": "failure",
        "html_url": "https://github.com/acme/widget/actions/runs/42/job/7",
        "steps": [{"name": step, "conclusion": "failure"}],
    }


def report(log_text: str, name: str = "tests", step: str = "Run tests") -> dict[str, Any]:
    """Analyze one failed mocked job."""

    client = MockClient(
        {"name": "CI", "status": "completed", "conclusion": "failure"},
        [job(name, step)],
        {f"{name}.txt": log_text},
    )
    return analyze_run("https://github.com/acme/widget/actions/runs/42", client)  # type: ignore[arg-type]


def test_parse_valid_run_url() -> None:
    """A canonical run URL exposes owner, repo, and run id."""

    assert parse_run_url("https://github.com/acme/widget/actions/runs/42") == (
        "acme",
        "widget",
        42,
    )


@pytest.mark.parametrize(
    "url",
    ["http://github.com/acme/widget/actions/runs/42", "https://example.com/a/b/actions/runs/1"],
)
def test_rejects_invalid_run_url(url: str) -> None:
    """Only canonical HTTPS GitHub URLs are accepted."""

    with pytest.raises(ValueError):
        parse_run_url(url)


def test_pytest_failure() -> None:
    """Pytest assertions are classified as test failures."""

    result = report("collecting...\nFAILED tests/test_api.py::test_health - AssertionError\nassert 500 == 200")
    failure = result["failures"][0]
    assert failure["failing_step"] == "Run tests"
    assert failure["suggested_fix_category"] == "inspect-test-assertion-or-fixture"
    assert "FAILED tests/test_api.py" in failure["error_message"]


def test_jest_failure() -> None:
    """Jest expected/received output is classified as a test failure."""

    result = report("FAIL src/sum.test.ts\nExpected: 4 Received: 5\n at Object.<anonymous>")
    assert result["failures"][0]["suggested_fix_category"] == "inspect-test-assertion-or-fixture"


def test_typescript_build_error() -> None:
    """TypeScript compiler errors are classified as build errors."""

    result = report("src/index.ts(8,3): error TS2322: Type 'string' is not assignable", "build", "tsc")
    assert result["failures"][0]["suggested_fix_category"] == "fix-compilation-or-dependency"


def test_lint_error() -> None:
    """ESLint diagnostics are classified as lint errors."""

    result = report("src/app.js\n  4:8  error  'thing' is never used  no-unused-vars", "lint", "eslint")
    assert result["failures"][0]["suggested_fix_category"] == "apply-lint-rule-or-formatting-fix"


def test_success_run_does_not_download_logs() -> None:
    """A successful run returns an empty failure list without requiring logs."""

    client = MockClient(
        {"name": "CI", "status": "completed", "conclusion": "success"},
        [{"name": "tests", "conclusion": "success", "steps": []}],
        {},
    )
    result = analyze_run("https://github.com/acme/widget/actions/runs/42", client)  # type: ignore[arg-type]
    assert result["failures"] == []
    assert result["summary"] == "No failed jobs found"


def test_report_is_json_serializable() -> None:
    """The complete public result can always be emitted as JSON."""

    result = report("##[error]Unexpected runtime error\nTraceback (most recent call last):")
    assert json.loads(json.dumps(result))["repository"] == "acme/widget"


def test_multiple_failed_jobs() -> None:
    """Each failed job gets an independent structured failure record."""

    client = MockClient(
        {"name": "CI", "status": "completed", "conclusion": "failure"},
        [job("tests", "pytest"), job("build", "tsc")],
        {
            "tests.txt": "FAILED tests/test_api.py::test_x - AssertionError",
            "build.txt": "src/index.ts: error TS2304: Cannot find name 'x'",
        },
    )
    result = analyze_run("https://github.com/acme/widget/actions/runs/42", client)  # type: ignore[arg-type]
    assert [item["suggested_fix_category"] for item in result["failures"]] == [
        "inspect-test-assertion-or-fixture",
        "fix-compilation-or-dependency",
    ]


def test_classification_fallback() -> None:
    """Unknown text has a stable manual-review fallback."""

    assert classify_failure(["process stopped unexpectedly"])[0] == "unknown"
