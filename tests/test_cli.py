"""CLI behavior tests using mocked analysis responses."""

from __future__ import annotations

import json

from actions_log_parser import cli


def test_cli_outputs_json(monkeypatch, capsys) -> None:  # type: ignore[no-untyped-def]
    """The CLI emits the structured report to stdout."""

    monkeypatch.setattr(
        cli,
        "analyze_run",
        lambda _url, _client: {"failures": [], "summary": "No failed jobs found"},
    )
    assert cli.main(["https://github.com/acme/widget/actions/runs/42"]) == 0
    assert json.loads(capsys.readouterr().out)["summary"] == "No failed jobs found"


def test_cli_reports_input_errors(monkeypatch, capsys) -> None:  # type: ignore[no-untyped-def]
    """Input/API errors become machine-readable stderr with exit code 2."""

    monkeypatch.setattr(cli, "analyze_run", lambda _url, _client: (_ for _ in ()).throw(ValueError("bad URL")))
    assert cli.main(["bad"]) == 2
    assert json.loads(capsys.readouterr().err) == {"error": "bad URL"}
