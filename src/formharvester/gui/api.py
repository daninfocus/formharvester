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
from formharvester.health import check_captcha_health, check_llm_health
from formharvester.leads import LeadRepository
from formharvester.llm import GeneratedFormContent, ReviewCallback
from formharvester.settings import (
    CampaignProfile,
    Settings,
    config_home,
    data_dir,
    list_profiles,
    load_profile,
    load_settings,
    save_profile,
    save_settings,
)
from formharvester.settings import (
    delete_profile as remove_profile,
)

__all__ = ["Api"]

_UNDECIDED = object()


class _GuiBot(Bot):
    """A :class:`Bot` that reports to the GUI instead of the terminal."""

    def __init__(
        self,
        settings: Settings,
        profile: CampaignProfile,
        sink: Callable[[str], None],
        stop_event: threading.Event,
        review_callback: ReviewCallback,
    ) -> None:
        # Set before super().__init__: the base constructor already prints.
        self._sink = sink
        self._stop_event = stop_event
        super().__init__(settings, profile, review_callback=review_callback)

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
        self._review: dict[str, str] | None = None
        self._review_event: threading.Event | None = None
        self._review_decision: object = _UNDECIDED
        self._health_lock = threading.Lock()
        self._health_thread: threading.Thread | None = None
        self._health_checked_at = 0.0
        self._health: dict[str, dict[str, str]] = {
            "llm": {"name": "LLM", "state": "checking", "detail": "checking..."},
            "captcha": {"name": "CAPTCHA", "state": "checking", "detail": "checking..."},
        }

    def _emit(self, line: str) -> None:
        with self._lock:
            self._lines.append(line)

    # --- external service health ---------------------------------------

    def get_health(self) -> dict[str, dict[str, str]]:
        """Return cached health and refresh it in the background when stale."""
        with self._health_lock:
            stale = time.monotonic() - self._health_checked_at >= 30
            running = self._health_thread is not None and self._health_thread.is_alive()
            if stale and not running:
                self._health = {
                    "llm": {"name": "LLM", "state": "checking", "detail": "checking..."},
                    "captcha": {"name": "CAPTCHA", "state": "checking", "detail": "checking..."},
                }
                self._health_thread = threading.Thread(target=self._refresh_health, daemon=True)
                self._health_thread.start()
            return {name: dict(value) for name, value in self._health.items()}

    def _refresh_health(self) -> None:
        try:
            settings = load_settings()
            result = {
                "llm": check_llm_health(settings.llm),
                "captcha": check_captcha_health(settings.captcha),
            }
        except Exception as exc:
            result = {
                "llm": {"name": "LLM", "state": "warning", "detail": f"check failed: {exc}"},
                "captcha": {"name": "CAPTCHA", "state": "warning", "detail": "check failed"},
            }
        with self._health_lock:
            self._health = result
            self._health_checked_at = time.monotonic()

    def _invalidate_health(self) -> None:
        with self._health_lock:
            self._health_checked_at = 0

    # --- state ----------------------------------------------------------

    def get_state(self) -> dict[str, Any]:
        settings = load_settings()
        with LeadRepository(data_dir()) as leads:
            lead_metrics = leads.metrics(settings.active_profile)
        return {
            "settings": settings.model_dump(),
            "profile": load_profile(settings.active_profile).model_dump(),
            "profiles": list_profiles(),
            "home": str(config_home()),
            "version": __VERSION__,
            "running": self._is_running(),
            "review": self._review_snapshot(),
            "lead_metrics": lead_metrics,
            "health": self.get_health(),
        }

    def get_leads(self, status: str | None = None) -> dict[str, Any]:
        campaign = load_settings().active_profile
        with LeadRepository(data_dir()) as leads:
            records = leads.list_leads(campaign=campaign, status=status, limit=250)
            return {
                "leads": [record.to_dict() for record in records],
                "metrics": leads.metrics(campaign),
            }

    def get_lead_audit(self, record_id: str) -> dict[str, Any]:
        with LeadRepository(data_dir()) as leads:
            return {"ok": True, "events": leads.audit(record_id)}

    def suppress_lead(self, record_id: str) -> dict[str, Any]:
        with LeadRepository(data_dir()) as leads:
            try:
                record = leads.suppress(record_id)
            except LookupError as exc:
                return {"ok": False, "error": str(exc)}
            return {"ok": True, "lead": record.to_dict()}

    def unsuppress_lead(self, record_id: str) -> dict[str, Any]:
        with LeadRepository(data_dir()) as leads:
            try:
                record = leads.unsuppress(record_id)
            except LookupError as exc:
                return {"ok": False, "error": str(exc)}
            return {"ok": True, "lead": record.to_dict()}

    def export_leads(self) -> dict[str, Any]:
        campaign = load_settings().active_profile
        destination = data_dir() / f"{campaign}_leads.csv"
        with LeadRepository(data_dir()) as leads:
            path = leads.export_csv(destination, campaign=campaign)
        return {"ok": True, "path": str(path)}

    def save_settings(self, data: dict[str, Any]) -> dict[str, Any]:
        try:
            save_settings(Settings.model_validate(data))
        except ValidationError as exc:
            return {"ok": False, "error": _first_error(exc)}
        self._invalidate_health()
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
        name_error = _profile_name_error(name)
        if name_error:
            return {"ok": False, "error": name_error}
        if name in list_profiles():
            return {"ok": False, "error": f"Campaign '{name}' already exists."}
        save_profile(CampaignProfile(name=name))
        return self.use_profile(name)

    def rename_profile(self, old_name: str, new_name: str) -> dict[str, Any]:
        if self._is_running():
            return {"ok": False, "error": "Stop the harvest before renaming a campaign."}

        old_name = old_name.strip()
        new_name = new_name.strip()
        name_error = _profile_name_error(new_name)
        if name_error:
            return {"ok": False, "error": name_error}
        profiles = list_profiles()
        if old_name not in profiles:
            return {"ok": False, "error": f"Campaign '{old_name}' was not found."}
        if new_name in profiles:
            return {"ok": False, "error": f"Campaign '{new_name}' already exists."}
        if old_name == new_name:
            return {"ok": False, "error": "Enter a different campaign name."}

        profile = load_profile(old_name)
        save_profile(profile.model_copy(update={"name": new_name}))
        if not remove_profile(old_name):
            remove_profile(new_name)
            return {"ok": False, "error": f"Could not remove the old campaign file for '{old_name}'."}

        settings = load_settings()
        if settings.active_profile == old_name:
            save_settings(settings.model_copy(update={"active_profile": new_name}))
        return {"ok": True}

    def delete_profile(self, name: str) -> dict[str, Any]:
        if self._is_running():
            return {"ok": False, "error": "Stop the harvest before deleting a campaign."}

        name = name.strip()
        profiles = list_profiles()
        if name not in profiles:
            return {"ok": False, "error": f"Campaign '{name}' was not found."}
        if len(profiles) <= 1:
            return {"ok": False, "error": "Keep at least one campaign configured."}
        if not remove_profile(name):
            return {"ok": False, "error": f"Could not delete campaign '{name}'."}

        settings = load_settings()
        if settings.active_profile == name:
            next_name = next(profile for profile in profiles if profile != name)
            save_settings(settings.model_copy(update={"active_profile": next_name}))
        return {"ok": True}

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
            return {"ok": False, "error": "The selected campaign has no search queries yet."}
        if settings.engine.send_form and settings.llm.enabled and not settings.llm.api_key_for_provider().strip():
            return {
                "ok": False,
                "error": f"LLM is enabled, but no {settings.llm.provider} API key is configured in Settings.",
            }

        self._stop.clear()
        with self._lock:
            self._lines.clear()
        self._thread = threading.Thread(target=self._run, args=(settings, profile), daemon=True)
        self._thread.start()
        return {"ok": True}

    def _run(self, settings: Settings, profile: CampaignProfile) -> None:
        bot = None
        try:
            bot = _GuiBot(
                settings,
                profile,
                self._emit,
                self._stop,
                review_callback=lambda url, content: self._request_review(url, content, self._stop),
            )
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
            self._resolve_review(None)
            self._emit("Harvest finished.")

    def stop(self) -> dict[str, Any]:
        """Request a halt. The engine stops after the site it is on."""
        if not self._is_running():
            return {"ok": False, "error": "Nothing is running."}
        self._stop.set()
        bot = self._bot
        if bot is not None:
            bot.crawl = False
        self._resolve_review(None)
        self._emit("Stop requested, finishing the current site...")
        return {"ok": True}

    # --- manual LLM review ---------------------------------------------

    def _review_snapshot(self) -> dict[str, str] | None:
        with self._lock:
            return dict(self._review) if self._review is not None else None

    def _request_review(
        self,
        url: str,
        content: GeneratedFormContent,
        stop_event: threading.Event,
    ) -> GeneratedFormContent | None:
        review_id = f"review-{time.time_ns()}"
        event = threading.Event()
        with self._lock:
            self._review = {
                "id": review_id,
                "url": url,
                "subject": content.subject,
                "message": content.message,
                "provider": content.provider,
                "model": content.model,
            }
            self._review_event = event
            self._review_decision = _UNDECIDED
        self._emit(f"Review required before submitting {url}")

        while not event.wait(0.2):
            if stop_event.is_set():
                self._resolve_review(None, review_id)
                break

        with self._lock:
            decision = self._review_decision
            if self._review is not None and self._review.get("id") == review_id:
                self._review = None
                self._review_event = None
                self._review_decision = _UNDECIDED
        return decision if isinstance(decision, GeneratedFormContent) else None

    def _resolve_review(self, decision: GeneratedFormContent | None, review_id: str | None = None) -> bool:
        with self._lock:
            if self._review is None or (review_id is not None and self._review.get("id") != review_id):
                return False
            self._review_decision = decision
            event = self._review_event
        if event is not None:
            event.set()
        return True

    def approve_review(self, review_id: str, subject: str, message: str) -> dict[str, Any]:
        with self._lock:
            review = dict(self._review) if self._review is not None else None
        if review is None or review.get("id") != review_id:
            return {"ok": False, "error": "That review is no longer pending."}
        if not subject.strip() or not message.strip():
            return {"ok": False, "error": "Subject and message cannot be empty."}
        content = GeneratedFormContent(
            subject=subject.strip(),
            message=message.strip(),
            provider=review.get("provider", ""),
            model=review.get("model", ""),
        )
        self._resolve_review(content, review_id)
        return {"ok": True}

    def skip_review(self, review_id: str) -> dict[str, Any]:
        if not self._resolve_review(None, review_id):
            return {"ok": False, "error": "That review is no longer pending."}
        self._emit("Submission skipped by review.")
        return {"ok": True}

    def poll(self) -> dict[str, Any]:
        with self._lock:
            lines = list(self._lines)
            self._lines.clear()
            review = dict(self._review) if self._review is not None else None
        try:
            settings = load_settings()
        except (OSError, ValidationError):
            self._emit("Settings are temporarily unavailable; retrying.")
            return {
                "lines": lines,
                "running": self._is_running(),
                "review": review,
                "lead_metrics": {},
                "health": self.get_health(),
            }
        with LeadRepository(data_dir()) as leads:
            lead_metrics = leads.metrics(settings.active_profile)
        return {
            "lines": lines,
            "running": self._is_running(),
            "review": review,
            "lead_metrics": lead_metrics,
            "health": self.get_health(),
        }


def _first_error(exc: ValidationError) -> str:
    error = exc.errors()[0]
    location = ".".join(str(part) for part in error["loc"])
    return f"{location}: {error['msg']}" if location else error["msg"]


def _profile_name_error(name: str) -> str | None:
    if not name:
        return "Campaign name cannot be empty."
    if name in {".", ".."} or any(char in name for char in '<>:"/\\|?*') or any(
        ord(char) < 32 for char in name
    ):
        return "Campaign names cannot contain path separators or Windows filename characters."
    if name.endswith((" ", ".")):
        return "Campaign names cannot end with a space or period."
    return None
