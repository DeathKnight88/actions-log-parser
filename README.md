# actions-log-parser

Turn a GitHub Actions workflow run URL into a structured JSON failure report for CI triage.

The CLI identifies the failed job and step, extracts the primary error plus nearby stack/context lines, and assigns a suggested fix category. It recognizes pytest/Jest failures, TypeScript and compilation errors, lint diagnostics, and general runtime errors.

## Installation

Requires Python 3.10 or newer.

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install .
```

For development and verification:

```bash
python -m pip install -e . pytest pylint
pytest
pylint src/actions_log_parser
```

## Usage

For a public repository:

```bash
actions-log-parser https://github.com/OWNER/REPO/actions/runs/RUN_ID
```

Use `GITHUB_TOKEN` for private repositories and to avoid GitHub's low unauthenticated API rate limit:

```bash
GITHUB_TOKEN=github_pat_xxx actions-log-parser \
  https://github.com/OWNER/REPO/actions/runs/RUN_ID \
  --output failure.json
```

Options:

```text
--token TOKEN     Explicit GitHub token; defaults to GITHUB_TOKEN
--output, -o PATH Write JSON to a file
--compact         Emit compact JSON
```

The process exits with `0` for a successful run, `1` when failures were found, and `2` for invalid input or API errors.

## Example output

```json
{
  "repository": "acme/widget",
  "run_id": 42,
  "run_url": "https://github.com/acme/widget/actions/runs/42",
  "workflow": "CI",
  "status": "completed",
  "conclusion": "failure",
  "failures": [
    {
      "job_name": "tests",
      "failing_step": "Run pytest",
      "error_message": "FAILED tests/test_api.py::test_health - AssertionError",
      "stack_trace": [
        "FAILED tests/test_api.py::test_health - AssertionError",
        "assert 500 == 200"
      ],
      "suggested_fix_category": "inspect-test-assertion-or-fixture",
      "job_url": "https://github.com/acme/widget/actions/runs/42/job/7"
    }
  ],
  "summary": "Detected 1 failed job(s)"
}
```

## How it works

1. Validates and parses the GitHub Actions run URL.
2. Reads run and job metadata from GitHub's REST API.
3. Downloads the run log ZIP only when failed jobs exist.
4. Matches logs to jobs, classifies failure signatures, and extracts concise context.
5. Emits stable, UTF-8 JSON suitable for automated CI triage.

No token is stored, printed, or added to the output. Network and GitHub errors are emitted as JSON on stderr.

## License

MIT
