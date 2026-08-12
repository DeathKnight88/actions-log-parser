"""Minimal GitHub Actions API client using only the Python standard library."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any


class GitHubApiError(RuntimeError):
    """Raised when GitHub returns an unsuccessful API response."""


@dataclass(frozen=True)
class GitHubClient:
    """Fetch run metadata, jobs, and the log archive from GitHub."""

    token: str | None = None
    api_base: str = "https://api.github.com"
    timeout: float = 30.0

    def _request(self, url: str, accept: str = "application/vnd.github+json") -> bytes:
        headers = {
            "Accept": accept,
            "User-Agent": "actions-log-parser/0.1",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        request = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return response.read()
        except urllib.error.HTTPError as error:
            detail = error.read().decode("utf-8", errors="replace")
            try:
                message = json.loads(detail).get("message", detail)
            except json.JSONDecodeError:
                message = detail
            raise GitHubApiError(f"GitHub API returned HTTP {error.code}: {message}") from error
        except urllib.error.URLError as error:
            raise GitHubApiError(f"Could not reach GitHub API: {error.reason}") from error

    def fetch_run(self, owner: str, repo: str, run_id: int) -> dict[str, Any]:
        """Return metadata for one workflow run."""

        url = f"{self.api_base}/repos/{owner}/{repo}/actions/runs/{run_id}"
        return json.loads(self._request(url))

    def fetch_jobs(self, owner: str, repo: str, run_id: int) -> list[dict[str, Any]]:
        """Return every job for a workflow run, following pagination."""

        jobs: list[dict[str, Any]] = []
        page = 1
        while True:
            url = (
                f"{self.api_base}/repos/{owner}/{repo}/actions/runs/{run_id}/jobs"
                f"?filter=all&per_page=100&page={page}"
            )
            payload = json.loads(self._request(url))
            batch = payload.get("jobs", [])
            if not isinstance(batch, list):
                raise GitHubApiError("GitHub jobs response did not contain a jobs array")
            jobs.extend(batch)
            if len(batch) < 100:
                break
            page += 1
        return jobs

    def download_logs(self, owner: str, repo: str, run_id: int) -> bytes:
        """Download the workflow run's ZIP log archive."""

        url = f"{self.api_base}/repos/{owner}/{repo}/actions/runs/{run_id}/logs"
        return self._request(url, accept="application/vnd.github+json")
