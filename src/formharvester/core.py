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

from formharvester.captcha.detector import CaptchaMixin
from formharvester.engine import SeleniumBot
from formharvester.form_handler import FormHandlerMixin
from formharvester.scraper.emails import EmailScraperMixin
from formharvester.utils import get_root_url

__VERSION__ = "1.0.0"
__FIGLET__ = r'''           @@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@
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

                          ░▀▀▄░░░░▀▀▄░░░░▀▀▄
                          ░▄▀░░░░░▄▀░░░░░▄▀░
                          ░▀▀▀░▀░░▀▀▀░▀░░▀▀▀
'''


class HarvesterCore(SeleniumBot, CaptchaMixin, EmailScraperMixin, FormHandlerMixin):
    """Browser + captcha + scraper + form-handler, with in-memory status hooks."""

    max_time = 30
    crawl = True

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
