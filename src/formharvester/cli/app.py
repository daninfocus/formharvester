"""The CLI Bot: assembles the engine + Google search + progress persistence.

This is the config-driven, file-backed orchestrator behind the ``formharvester``
command. It overrides the core status hooks to persist progress to disk.
"""

from __future__ import annotations

import configparser
import csv
import traceback
from collections import defaultdict

import pandas as pd
from rich import pretty
from rich.console import Console

from formharvester.captcha import create_solver
from formharvester.cli.progress import ProgressMixin
from formharvester.core import __FIGLET__, HarvesterCore
from formharvester.scraper import GoogleSearchMixin
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

    @staticmethod
    def read_csv(filename):
        with open(filename, encoding="utf-8-sig") as f:
            data = csv.DictReader(f)
            return list(data)

    @staticmethod
    def export_csv(obj, filename="output.csv"):
        df = pd.DataFrame(obj)
        df.to_csv(filename, index=False)

    def __init__(self):
        pretty.install()
        self.c = Console()
        self.bot_print(__FIGLET__, figlet=True)

        config = configparser.ConfigParser()
        config.read("config.txt")
        self.mode = config.get("settings", "mode")
        self.skip_ads = config.getboolean("settings", "skip_ads")
        self.send_form = config.getboolean("settings", "send_form")
        self.generate_email_sources = config.getboolean("settings", "generate_email_sources")
        self.max_time = config.getint("settings", "max_time")

        self.HEADLESS = config.getboolean("settings", "hide_browser")
        self.DEV_SETTINGS = config.getboolean("dev", "enabled")
        self.DEBUG = config.getboolean("dev", "debug_form")

        self.start_page = config.getint("google", "start_page")
        self.max_google_pages = config.getint("google", "max_google_pages")
        self.MIN_DELAY = config.getint("google", "min_delay")
        self.MAX_DELAY = config.getint("google", "max_delay")
        self.CAPTCHA_SLEEP = config.getint("google", "captcha_sleep")
        self.GOOGLE_TIMER = config.getint("google", "search_timer")

        self.captcha_solver = create_solver(
            config.get("captcha", "provider", fallback=None),
            dbc_username=config.get("captcha", "dbc_username", fallback=None)
            or config.get("captcha", "dbc_user", fallback=None),
            dbc_password=config.get("captcha", "dbc_password", fallback=None),
            twocaptcha_api_key=config.get("captcha", "twocaptcha_api_key", fallback=None),
        )

        self.visited_websites = self.load_txt("data/website_log.txt")  # visited urls globally (scraper)

        obj_list = self.read_csv(f"input/{self.mode}.csv")
        self.details = {
            "first_name": obj_list[0].get("First Name"),
            "last_name": obj_list[0].get("Last Name"),
            "phone": obj_list[0].get("Phone"),
            "email": obj_list[0].get("Email"),
            "location": obj_list[0].get("Location"),
            "city": obj_list[0].get("City"),
            "state": obj_list[0].get("State"),
            "subject": obj_list[0].get("Subject"),
            "message": obj_list[0].get("Message"),
        }
        self.google_queries = [i.get("Google Queries") for i in obj_list if i.get("Google Queries")]
        self.keywords = [i.get("Keywords") for i in obj_list if i.get("Keywords")]
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
        with open("data/website_log.txt", "a") as f:
            f.write(get_root_url(url) + "\n")
