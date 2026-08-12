"""Command-line entry point for actions-log-parser."""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Sequence

from .github import GitHubApiError, GitHubClient
from .parser import analyze_run


def build_parser() -> argparse.ArgumentParser:
    """Create and return the command-line argument parser."""

    parser = argparse.ArgumentParser(
        prog="actions-log-parser",
        description="Extract structured failure details from a GitHub Actions workflow run.",
    )
    parser.add_argument("run_url", help="GitHub Actions run URL")
    parser.add_argument(
        "--token",
        default=os.environ.get("GITHUB_TOKEN"),
        help="GitHub token (defaults to GITHUB_TOKEN; recommended for private repos/rate limits)",
    )
    parser.add_argument("--output", "-o", help="Write JSON to this path instead of stdout")
    parser.add_argument("--compact", action="store_true", help="Emit compact JSON")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the CLI and return a process exit code."""

    args = build_parser().parse_args(argv)
    try:
        report = analyze_run(args.run_url, GitHubClient(token=args.token))
    except (ValueError, GitHubApiError) as error:
        print(json.dumps({"error": str(error)}), file=sys.stderr)
        return 2

    rendered = json.dumps(report, indent=None if args.compact else 2, ensure_ascii=False)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as output:
            output.write(rendered + "\n")
    else:
        print(rendered)
    return 1 if report["failures"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
