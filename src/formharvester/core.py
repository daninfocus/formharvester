"""The core harvesting engine.

Composes the browser (:class:`SeleniumBot`), captcha handling, email scraping
and contact-form handling into one engine, plus the shared bits both the CLI
(:class:`~formharvester.cli.app.Bot`) and the library API
(:class:`~formharvester.api.FormHarvester`) build on.

``_set_status`` / ``_note_visited`` are the persistence seam: the core keeps
them in memory; the CLI overrides them to also write progress/log files.
"""

from __future__ import annotations

import time
from importlib.metadata import PackageNotFoundError, version
from typing import TYPE_CHECKING

from formharvester.captcha.detector import CaptchaMixin
from formharvester.engine import SeleniumBot
from formharvester.form_handler import FormHandlerMixin
from formharvester.leads import LeadRecord
from formharvester.scraper.emails import EmailScraperMixin
from formharvester.technology import TechnologyDetector, TechnologyMatch
from formharvester.utils import get_root_url

if TYPE_CHECKING:
    from formharvester._typing import EngineProtocol as _StateBase
else:
    _StateBase = object

try:
    __VERSION__ = version("formharvester")
except PackageNotFoundError:
    # Running from source without an installed distribution (e.g. some editors' import
    # resolution). pyproject.toml remains the single source of truth for the real version.
    __VERSION__ = "0.0.0+unknown"
__FIGLET__ = r"""           @@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@
           @@@@@@@@@@@@@@@@@800GGGGGGGG00088@@@@@@@@@@@@@@@@@
           @@@@@@@@@@@@@@0GG00888@@@@@@8880GGG8@@@@@@@@@@@@@@
           @@@@@@@@@@@@0C08@@@@@@@@@@@@@@@@@@0CC@@@@@@@@@@@@@
           @@@@@@@@@@@0C8@@@@@@@@@@@@@@@@@@@@@@0L8@@@@@@@@@@@
           @@@@@@@@@@8L8@@@@@@@@@@@@@@@@@@@@@@@@0L8@@@@@@@@@@
           @@@@@@@@@@GG@@@@@@@@@@@@@@@@@@@@@@@@@@GC@@@@@@@@@@
           @@@@@@@@@0fLGGGGGGGGGGGGGGGGGGGGGGGGGGCt0@@@@@@@@@
           @@@@@@@@@t,,:,,,,,,,,,::::::,,,,,,,,,,:.t@@@@@@@@@
           @@@@@@@8CCtCi:,,,,,,:iG000001:,,,,,,,;GtCC8@@@@@@@
           @@@@@@@i,0CG:     .:1C88@@88C1:.     ,0f8i1@@@@@@@
           @@@@@@@i,0LCG;::itfL0@@@@@@@@0Cfti::;C8f8;i@@@@@@@
           @@@@@@@0fGfLG800GC0@@@@@@@@@@@@0CG008GGtGf0@@@@@@@
           @@@@@@@@0L1G0GGG0@@@@80CGGfL0@@@@8GGG08tLC@@@@@@@@
           @@@@@@@CL00f8@@@@@@0fL:.GC :GtC@@@@@@8CGGLL8@@@@@@
           @@@@@@LCCC0GLC08@8Li:LttCCi1G;,L8@@8GCGGLLCL@@@@@@
           @@@@@8f@0fLG0LffCtL08@@@@@@@8GCLtCLfC0GGGG@f8@@@@@
           @@@@@8f8@GCCG0888GG@@@80GG00@@@CC8880GCCG@@f8@@@@@
           @@@@@@GL8CG8@@@@@@0C8C0C;:f0C8CG@@@@@@@0CGGC@@@@@@
           @@@@@@@0fC@@@@800G0CfGG;  ,fGLf00G008@@@@fG@@@@@@@
           @@@@@@@@Gf@@8G8L;:iG8G:    .180C;,;CC8@@8t8@@@@@@@
           @@@@@@@@@LL80L8L;:188f      ,00G;:;GL8@0fG@@@@@@@@
           @@@@@@@@@@GLCLLCLLLLLfti,,:ttGGGGGGCGGCC0@@@@@@@@@
           @@@@@@@@@@@@0GCCCCCG0@@@888@@80GGCCGG08@@@@@@@@@@@
           @@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@
  _____                    _   _                           _
 |  ___|__  _ __ _ __ ___ | | | | __ _ _ ____   _____  ___| |_ ___ _ __
 | |_ / _ \| '__| '_ ` _ \| |_| |/ _` | '__\ \ / / _ \/ __| __/ _ \ '__|
 |  _| (_) | |  | | | | | |  _  | (_| | |   \ V /  __/\__ \ ||  __/ |
 |_|  \___/|_|  |_| |_| |_|_| |_|\__,_|_|    \_/ \___||___/\__\___|_|
"""


class HarvesterCore(SeleniumBot, CaptchaMixin, EmailScraperMixin, FormHandlerMixin, _StateBase):
    """Browser + captcha + scraper + form-handler, with in-memory status hooks."""

    max_time = 30
    crawl = True
    detect_technologies = True
    llm_enabled = False
    llm_client = None
    review_before_submit = False
    review_callback = None
    generated_content = None
    llm_error = None
    form_found = False
    qualification_score = 0.0
    qualification_reasons: list[str] = []

    def bot_print(self, message: object, is_input: bool = False, figlet: bool = False) -> None:
        if figlet:
            self.c.print(__FIGLET__, style="#00eeff")
        else:
            self.c.print(f"[bold red][FormHarvester {__VERSION__}][/bold red] {message}")
            if is_input:
                input()

    def check_time(self) -> None:
        """Per-site timeout thread (CLI behaviour). Sets ``crawl`` False at max_time."""
        start = time.time()
        while True:
            elapsed = time.time() - start
            self.bot_print(f"[Page Timer] {round(elapsed, 2)}")
            if elapsed >= self.max_time:
                self.crawl = False
                return
            time.sleep(1)

    # --- persistence seam (overridden by the CLI to write files) ----------

    def _set_status(self, url: str, status: str) -> None:
        self.last_status = status

    def _note_visited(self, url: str) -> None:
        self.visited_websites.append(get_root_url(url))

    def _scan_technologies(self) -> list[TechnologyMatch]:
        """Scan the current page without allowing detection to affect harvests."""
        if not getattr(self, "detect_technologies", True):
            return []
        try:
            matches = TechnologyDetector().detect(TechnologyDetector.from_driver(self.driver))
        except Exception:
            return []

        existing = {(item.name, item.category): item for item in getattr(self, "technologies", [])}
        for match in matches:
            key = (match.name, match.category)
            current = existing.get(key)
            if current is None:
                existing[key] = match
                continue
            current.confidence = max(current.confidence, match.confidence)
            if current.version is None:
                current.version = match.version
            evidence = {(item.source, item.value, item.detail) for item in current.evidence}
            current.evidence.extend(
                item for item in match.evidence if (item.source, item.value, item.detail) not in evidence
            )
        self.technologies = sorted(existing.values(), key=lambda item: (item.category.lower(), item.name.lower()))
        return matches

    def current_lead_snapshot(self, url: str) -> LeadRecord:
        """Build the observable lead state for persistence and policy checks."""
        from formharvester.qualification import qualify_site

        technologies = [item.to_dict() for item in getattr(self, "technologies", [])]
        emails = sorted({email for email, _source in getattr(self, "scraped_emails", set())})
        qualification = qualify_site(
            technologies=technologies,
            emails=emails,
            form_found=bool(getattr(self, "form_found", False)),
        )
        self.qualification_score = qualification.score
        self.qualification_reasons = qualification.reasons
        content = getattr(self, "generated_content", None)
        return LeadRecord(
            id="",
            campaign=str(getattr(self, "mode", "library")),
            domain=get_root_url(url),
            url=url,
            status=str(getattr(self, "last_status", None) or "VISITED"),
            score=qualification.score,
            reasons=qualification.reasons,
            technologies=technologies,
            emails=emails,
            form_found=bool(getattr(self, "form_found", False)),
            draft_subject=getattr(content, "subject", "") or "",
            draft_message=getattr(content, "message", "") or "",
            provider=getattr(content, "provider", "") or "",
            model=getattr(content, "model", "") or "",
            error=str(getattr(self, "llm_error", "") or ""),
        )
