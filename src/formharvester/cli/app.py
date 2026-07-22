"""The CLI Bot: assembles the engine + Google search + progress persistence.

This is the config-driven, file-backed orchestrator behind the ``formharvester``
command. It overrides the core status hooks to persist progress to disk.
"""

from __future__ import annotations

import traceback
from collections import defaultdict

from rich import pretty
from rich.console import Console

from formharvester.captcha import create_solver
from formharvester.cli.progress import ProgressMixin
from formharvester.core import __FIGLET__, HarvesterCore
from formharvester.scraper import GoogleSearchMixin
from formharvester.settings import CampaignProfile, Settings, data_dir, log_dir
from formharvester.utils import get_root_url


class Bot(HarvesterCore, GoogleSearchMixin, ProgressMixin):
    def run(self):
        self.bot_print("Running...")
        self.write_progress(self.google_queries, google=True)

        while self.google_queries:
            scraped_links = self.start_process_google(self.google_queries)
            # Process scraped links
            if scraped_links:
                self.start_process_url(scraped_links)

        self.driver.quit()
        self.bot_print("Done!", is_input=True)

    def resume(self, url_list, google_list):
        self.bot_print("Resuming harvest...")

        # Finish remaining urls first
        if url_list:
            self.start_process_url(url_list)
            url_list.clear()

        while google_list:
            scraped_links = self.start_process_google(google_list)
            if scraped_links:
                self.start_process_url(scraped_links)

        self.bot_print("Done!", is_input=True)

    def start_process_url(self, url_list):
        self.bot_print("Processing URLs...")

        for url in url_list:
            self.crawl = True
            try:
                if url in self.visited_websites:
                    self.update_progress(url, status="VISITED", google=False)
                    continue
                status = self.process_url(url)
                if status is None:
                    self.update_progress(url, status="VISITED", google=False)
            except:
                self.update_progress(url, status="ERROR", google=False)
                e = traceback.format_exc()
                self.log(screenshot=True, error=e)
                self.restart_driver()
            self.export_emails(filename=self.mode)
            # Wait for thread to finish
            if self.threads:
                t = self.threads.pop()
                t.join()
            # Re-enable crawl
            self.crawl = True

    def __init__(self, settings: Settings, profile: CampaignProfile):
        pretty.install()
        self.c = Console()
        self.bot_print(__FIGLET__, figlet=True)

        self.settings = settings
        self.profile = profile

        engine, google, captcha = settings.engine, settings.google, settings.captcha
        self.mode = profile.name
        self.skip_ads = engine.skip_ads
        self.send_form = engine.send_form
        self.generate_email_sources = engine.generate_email_sources
        self.max_time = engine.max_time

        self.HEADLESS = engine.headless
        self.DEV_SETTINGS = engine.debug_form
        self.DEBUG = engine.debug_form

        self.start_page = google.start_page
        self.max_google_pages = google.max_pages
        self.MIN_DELAY = google.min_delay
        self.MAX_DELAY = google.max_delay
        self.CAPTCHA_SLEEP = google.captcha_sleep
        self.GOOGLE_TIMER = google.search_timer

        self.captcha_solver = create_solver(
            captcha.provider or None,
            dbc_username=captcha.dbc_username or None,
            dbc_password=captcha.dbc_password or None,
            twocaptcha_api_key=captcha.twocaptcha_api_key or None,
        )

        # Runtime output lives beside the config, not in the working directory:
        # the executable is launched from wherever the user keeps it.
        self.data_dir = data_dir()
        self.log_dir = str(log_dir())

        self.visited_websites = self.load_txt(self.website_log_file)  # visited urls globally (scraper)

        self.details = profile.form_fill.as_engine_details()
        self.google_queries = list(profile.queries)
        self.keywords = list(profile.keywords)
        self.write_progress(self.google_queries, google=True)

        self.name_filled = False
        self.visited_links = []  # visited links within a site
        self.scraped_emails = set()

        self.crawl = True  # stop current page crawl
        self.threads = []
        self.google_term = None
        self.google_query = None
        self.google_timer = None
        self.current_page = None
        self.remaining_pages_log = defaultdict(list)
        self.get_remaining_pages()

        self.create_driver()

    # --- persistence overrides (write files, then delegate to core state) --

    def _set_status(self, url, status):
        super()._set_status(url, status)
        self.update_progress(url, status=status, google=False)

    def _note_visited(self, url):
        super()._note_visited(url)
        with open(self.website_log_file, "a") as f:
            f.write(get_root_url(url) + "\n")
