"""Parse GitHub Actions run metadata and logs into a concise failure report."""

from __future__ import annotations

import io
import re
import zipfile
from typing import Any
from urllib.parse import urlparse

from .github import GitHubClient

RUN_URL = re.compile(r"^/([^/]+)/([^/]+)/actions/runs/(\d+)(?:/.*)?$")
TIMESTAMP = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z\s?")
ANSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")

PATTERNS: list[tuple[str, tuple[re.Pattern[str], ...]]] = [
    (
        "test_failure",
        (
            re.compile(r"(?:^|\s)(?:FAILED|FAIL)\s+", re.IGNORECASE),
            re.compile(r"AssertionError|Tests?:\s+\d+\s+failed", re.IGNORECASE),
            re.compile(r"Expected:.*Received:", re.IGNORECASE),
        ),
    ),
    (
        "build_error",
        (
            re.compile(r"error\s+TS\d+", re.IGNORECASE),
            re.compile(r"(?:SyntaxError|Compilation failed|Build failed)", re.IGNORECASE),
            re.compile(r"(?:fatal error|undefined reference|cannot find symbol)", re.IGNORECASE),
        ),
    ),
    (
        "lint_error",
        (
            re.compile(r"(?:^|\s)[A-Z]\d{3,4}(?:\s|:)", re.IGNORECASE),
            re.compile(r"(?:eslint|pylint|ruff|flake8).*(?:error|failed)", re.IGNORECASE),
            re.compile(r"\d+:\d+\s+(?:error|warning)\s+", re.IGNORECASE),
        ),
    ),
]


def parse_run_url(run_url: str) -> tuple[str, str, int]:
    """Extract owner, repository, and numeric run id from a GitHub Actions URL."""

    parsed = urlparse(run_url)
    if parsed.scheme != "https" or parsed.netloc.lower() not in {"github.com", "www.github.com"}:
        raise ValueError("Expected an HTTPS github.com Actions run URL")
    match = RUN_URL.match(parsed.path.rstrip("/"))
    if not match:
        raise ValueError("URL must look like https://github.com/OWNER/REPO/actions/runs/RUN_ID")
    owner, repo, run_id = match.groups()
    return owner, repo, int(run_id)


def clean_line(line: str) -> str:
    """Remove timestamps, ANSI control sequences, and Actions command prefixes."""

    cleaned = ANSI.sub("", line.rstrip("\r\n"))
    cleaned = TIMESTAMP.sub("", cleaned)
    return cleaned.replace("##[error]", "").replace("##[warning]", "").strip()


def classify_failure(lines: list[str]) -> tuple[str, int]:
    """Return the best failure category and the first matching line index."""

    for category, patterns in PATTERNS:
        for index, line in enumerate(lines):
            if any(pattern.search(line) for pattern in patterns):
                return category, index
    for index, line in enumerate(lines):
        if "##[error]" in line.lower() or re.search(r"\berror\b", line, re.IGNORECASE):
            return "runtime_error", index
    return "unknown", max(len(lines) - 1, 0)


def extract_error(lines: list[str], index: int) -> tuple[str, list[str]]:
    """Extract a primary error and nearby stack/context lines."""

    if not lines:
        return "No error text was present in the downloaded logs", []
    primary = clean_line(lines[index]) or "Failure reported without an error message"
    start = max(index - 2, 0)
    end = min(index + 9, len(lines))
    context = [clean_line(line) for line in lines[start:end]]
    context = [line for line in context if line]
    return primary, context


def suggested_fix(category: str) -> str:
    """Map a detected failure class to a concise remediation category."""

    return {
        "test_failure": "inspect-test-assertion-or-fixture",
        "build_error": "fix-compilation-or-dependency",
        "lint_error": "apply-lint-rule-or-formatting-fix",
        "runtime_error": "inspect-runtime-exception",
        "unknown": "manual-log-review",
    }[category]


def unpack_logs(archive: bytes) -> dict[str, list[str]]:
    """Return UTF-8-decoded text files from a GitHub Actions ZIP archive."""

    try:
        with zipfile.ZipFile(io.BytesIO(archive)) as bundle:
            return {
                name: bundle.read(name).decode("utf-8", errors="replace").splitlines()
                for name in bundle.namelist()
                if not name.endswith("/")
            }
    except zipfile.BadZipFile as error:
        raise ValueError("GitHub returned an invalid workflow log archive") from error


def _job_log(job: dict[str, Any], logs: dict[str, list[str]]) -> list[str]:
    name = str(job.get("name", "")).lower()
    candidates = [lines for path, lines in logs.items() if name and name in path.lower()]
    if candidates:
        return max(candidates, key=len)
    all_lines: list[str] = []
    for lines in logs.values():
        all_lines.extend(lines)
    return all_lines


def _failing_step(job: dict[str, Any]) -> str:
    for step in job.get("steps", []):
        if step.get("conclusion") == "failure":
            return str(step.get("name") or "Unknown step")
    return str(job.get("name") or "Unknown job")


def _failure_record(job: dict[str, Any], logs: dict[str, list[str]]) -> dict[str, Any]:
    """Build one structured failure record from a failed job and its log lines."""

    lines = _job_log(job, logs)
    category, index = classify_failure(lines)
    error_message, stack_trace = extract_error(lines, index)
    return {
        "job_name": job.get("name"),
        "failing_step": _failing_step(job),
        "error_message": error_message,
        "stack_trace": stack_trace,
        "suggested_fix_category": suggested_fix(category),
        "job_url": job.get("html_url"),
    }


def analyze_run(run_url: str, client: GitHubClient) -> dict[str, Any]:
    """Fetch and analyze a workflow run, returning a JSON-serializable report."""

    owner, repo, run_id = parse_run_url(run_url)
    run = client.fetch_run(owner, repo, run_id)
    jobs = client.fetch_jobs(owner, repo, run_id)
    failed_jobs = [job for job in jobs if job.get("conclusion") == "failure"]

    result: dict[str, Any] = {
        "repository": f"{owner}/{repo}",
        "run_id": run_id,
        "run_url": run_url,
        "workflow": run.get("name"),
        "status": run.get("status"),
        "conclusion": run.get("conclusion"),
        "failures": [],
    }
    if not failed_jobs:
        result["summary"] = "No failed jobs found"
        return result

    logs = unpack_logs(client.download_logs(owner, repo, run_id))
    for job in failed_jobs:
        result["failures"].append(_failure_record(job, logs))
    result["summary"] = f"Detected {len(result['failures'])} failed job(s)"
    return result
