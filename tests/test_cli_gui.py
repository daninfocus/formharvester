"""CLI wiring for the desktop GUI."""

from __future__ import annotations

from typer.testing import CliRunner

import formharvester.gui as gui_module
from formharvester.cli import cli


def test_gui_dev_flag_is_forwarded_to_launch(monkeypatch) -> None:
    runner = CliRunner()
    captured: list[bool] = []
    monkeypatch.setattr(gui_module, "launch", lambda *, dev=False: captured.append(dev))

    result = runner.invoke(cli, ["gui", "--dev"])

    assert result.exit_code == 0
    assert captured == [True]


def test_gui_hides_dev_controls_by_default(monkeypatch) -> None:
    runner = CliRunner()
    captured: list[bool] = []
    monkeypatch.setattr(gui_module, "launch", lambda *, dev=False: captured.append(dev))

    result = runner.invoke(cli, ["gui"])

    assert result.exit_code == 0
    assert captured == [False]
