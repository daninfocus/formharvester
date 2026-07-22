"""Desktop interface for FormHarvester.

A pywebview window rendering the same console aesthetic as formharvester.com,
backed by :class:`~formharvester.gui.api.Api`.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from formharvester.settings import migrate_legacy_config

__all__ = ["launch"]

WEB_ROOT = Path(__file__).parent / "web"


def launch(on_ready: Callable[[], None] | None = None) -> None:
    """Open the FormHarvester window (blocks until it is closed).

    ``on_ready`` runs once the window is up. The frozen build uses it to close
    the splash screen.
    """
    try:
        import webview
    except ImportError as exc:  # pragma: no cover - depends on install extras
        raise SystemExit("The GUI needs pywebview. Install it with:\n\n    pip install 'formharvester[gui]'\n") from exc

    from formharvester.gui.api import Api

    migrate_legacy_config()

    webview.create_window(
        "FormHarvester",
        str(WEB_ROOT / "index.html"),
        js_api=Api(),
        width=1000,
        height=620,
        min_size=(780, 520),
        background_color="#08090c",
    )
    webview.start(on_ready)
