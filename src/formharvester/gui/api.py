"""Bridge between the pywebview window and the harvesting engine.

Every method on :class:`Api` is callable from JavaScript as
``window.pywebview.api.<name>()``. The harvest runs on a worker thread and
pushes log lines into a buffer the page drains by polling, which keeps the
engine free of any GUI imports.
"""

from __future__ import annotations

import threading
import time
import traceback
from collections import deque
from collections.abc import Callable
from typing import Any

from pydantic import ValidationError

from formharvester.cli.app import Bot
from formharvester.core import __VERSION__
from formharvester.settings import (
    CampaignProfile,
    Settings,
    config_home,
    list_profiles,
    load_profile,
    load_settings,
    save_profile,
    save_settings,
)

__all__ = ["Api"]


class _GuiBot(Bot):
    """A :class:`Bot` that reports to the GUI instead of the terminal."""

    def __init__(
        self,
        settings: Settings,
        profile: CampaignProfile,
        sink: Callable[[str], None],
        stop_event: threading.Event,
    ) -> None:
        # Set before super().__init__: the base constructor already prints.
        self._sink = sink
        self._stop_event = stop_event
        super().__init__(settings, profile)

    def bot_print(self, message: object, is_input: bool = False, figlet: bool = False) -> None:
        if figlet:
            return  # the window shows the wordmark already
        # Never honour is_input: input() would block the worker thread forever.
        self._sink(str(message))

    def check_time(self) -> None:
        """Quiet per-site timer that also honours the stop button."""
        start = time.time()
        while self.crawl:
            if self._stop_event.is_set() or time.time() - start >= self.max_time:
                self.crawl = False
                return
            time.sleep(0.5)


class Api:
    def __init__(self) -> None:
        self._lines: deque[str] = deque(maxlen=2000)
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._bot: _GuiBot | None = None

    def _emit(self, line: str) -> None:
        with self._lock:
            self._lines.append(line)

    # --- state ----------------------------------------------------------

    def get_state(self) -> dict[str, Any]:
        settings = load_settings()
        return {
            "settings": settings.model_dump(),
            "profile": load_profile(settings.active_profile).model_dump(),
            "profiles": list_profiles(),
            "home": str(config_home()),
            "version": __VERSION__,
            "running": self._is_running(),
        }

    def save_settings(self, data: dict[str, Any]) -> dict[str, Any]:
        try:
            save_settings(Settings.model_validate(data))
        except ValidationError as exc:
            return {"ok": False, "error": _first_error(exc)}
        return {"ok": True}

    def save_profile(self, data: dict[str, Any]) -> dict[str, Any]:
        try:
            profile = CampaignProfile.model_validate(data)
        except ValidationError as exc:
            return {"ok": False, "error": _first_error(exc)}
        save_profile(profile)
        return {"ok": True}

    def create_profile(self, name: str) -> dict[str, Any]:
        name = name.strip()
        if not name:
            return {"ok": False, "error": "Profile name cannot be empty."}
        if name in list_profiles():
            return {"ok": False, "error": f"Profile '{name}' already exists."}
        save_profile(CampaignProfile(name=name))
        return self.use_profile(name)

    def use_profile(self, name: str) -> dict[str, Any]:
        settings = load_settings()
        save_settings(settings.model_copy(update={"active_profile": name}))
        return {"ok": True}

    # --- run control ----------------------------------------------------

    def _is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> dict[str, Any]:
        if self._is_running():
            return {"ok": False, "error": "A harvest is already running."}

        settings = load_settings()
        profile = load_profile(settings.active_profile)
        if not profile.queries:
            return {"ok": False, "error": "This profile has no search queries yet."}

        self._stop.clear()
        with self._lock:
            self._lines.clear()
        self._thread = threading.Thread(target=self._run, args=(settings, profile), daemon=True)
        self._thread.start()
        return {"ok": True}

    def _run(self, settings: Settings, profile: CampaignProfile) -> None:
        bot = None
        try:
            bot = _GuiBot(settings, profile, self._emit, self._stop)
            self._bot = bot
            bot.run()
        except Exception:
            self._emit(traceback.format_exc())
        finally:
            if bot is not None:
                try:
                    bot.close()
                except Exception:
                    pass
            self._bot = None
            self._emit("Harvest finished.")

    def stop(self) -> dict[str, Any]:
        """Request a halt. The engine stops after the site it is on."""
        if not self._is_running():
            return {"ok": False, "error": "Nothing is running."}
        self._stop.set()
        bot = self._bot
        if bot is not None:
            bot.crawl = False
        self._emit("Stop requested, finishing the current site...")
        return {"ok": True}

    def poll(self) -> dict[str, Any]:
        with self._lock:
            lines = list(self._lines)
            self._lines.clear()
        return {"lines": lines, "running": self._is_running()}


def _first_error(exc: ValidationError) -> str:
    error = exc.errors()[0]
    location = ".".join(str(part) for part in error["loc"])
    return f"{location}: {error['msg']}" if location else error["msg"]
