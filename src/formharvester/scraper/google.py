"""Google search navigation and result-link scraping (CLI harvesting flow)."""

from __future__ import annotations

import threading
import time
from datetime import datetime, timedelta
from typing import TYPE_CHECKING
from urllib.parse import quote_plus

from formharvester.utils import filter_scraped_links, get_root_url

if TYPE_CHECKING:
    from formharvester._typing import EngineProtocol as _Base
else:
    _Base = object


class GoogleSearchMixin(_Base):
    SEARCH_URL = "https://www.google.com/search?q={query}&filter=0"

    # CSS
    GOOGLE_LINKS = '//*[@id="search"]//a[@data-ved and contains(@href, "http")]'  # xpath
    GOOGLE_LINKS_ADS = '//*[@id="search"]//a[@data-ved and contains(@href, "http")] | //a[@data-pcu]'  # xpath
    GOOGLE_NEXT = "#pnnext"
    GOOGLE_PAGE = '[aria-label="Page {}"]'  # format

    # xPath
    AD_XPATH = './ancestor::*[contains(@class, "ads")]'  # node

    def google_timer_thread(self):
        end_time = datetime.now() + timedelta(minutes=self.GOOGLE_TIMER)
        while datetime.now() < end_time:
            self.bot_print(f"[Google Timer] {datetime.now()} -> {end_time}")
            time.sleep(1)

    def google_popup_check(self):
        iframe = self.css('iframe[src*="consent"]', wait=3)
        if iframe:
            self.driver.switch_to.frame(iframe)
            btns = self.css("div[role=button]", getall=True)
            if btns:
                self.click(btns[1])
        self.driver.switch_to.default_content()

    def check_google_captcha(self):
        self.bot_print("Checking Google captcha...")
        while True:
            search_exists = self.css('input[type="text"]')
            if search_exists:
                return
            else:
                if self.CAPTCHA_SLEEP:
                    self.bot_print(f"Captcha found! Sleeping for {self.CAPTCHA_SLEEP} minutes.")
                    self.driver.quit()
                    time_in_seconds = int(self.CAPTCHA_SLEEP * 60)
                    time.sleep(time_in_seconds)
                    self.create_driver()
                    self.wait_google_timer()
                    self.get(self.SEARCH_URL.format(query=self.google_query))
                    if self.current_page:
                        self.start_at_x_page(self.current_page)
                else:
                    self.bot_print("Please solve the captcha to continue.", is_input=True)
                    return

    def wait_google_timer(self):
        if self.google_timer:
            self.bot_print("Waiting for last Google search...")
            self.get("https://onlineclock.net/")
            self.google_timer.join()
            self.google_timer = None

    def start_at_x_page(self, page_n):
        if page_n == 1:
            return

        last_page = 10
        while True:
            page = self.css(self.GOOGLE_PAGE.format(str(page_n)))
            if page:
                self.click(page)
                self.random_sleep(self.MIN_DELAY, self.MAX_DELAY)
                break
            else:
                self.click(self.GOOGLE_PAGE.format(str(last_page)), css=True)
                self.random_sleep(self.MIN_DELAY, self.MAX_DELAY)
                last_page += 4

    def scrape_google(self, start_page, page_count):
        assert self.google_term is not None, "scrape_google() requires an active google_term"

        scraped_links = []
        self.remaining_pages_log[self.google_term] = list(range(start_page, start_page + page_count))
        self.log_remaining_pages()
        self.start_at_x_page(start_page)
        remaining_pages = list(self.remaining_pages_log[self.google_term])
        for page in remaining_pages:
            self.current_page = page
            # Scrape links and go to next page
            if self.skip_ads:
                scraped_links.extend(self.xpath(self.GOOGLE_LINKS, getall=True, attr="href"))
            else:
                scraped_links.extend(self.xpath(self.GOOGLE_LINKS_ADS, getall=True, attr="href"))

            self.remaining_pages_log[self.google_term].remove(page)
            self.log_remaining_pages()
            scraped_links = self.filter_links(scraped_links)
            self.write_progress(scraped_links, google=False)

            next_btn = self.css(self.GOOGLE_NEXT, wait=1)
            if next_btn:
                self.click(next_btn)
                self.random_sleep(self.MIN_DELAY, self.MAX_DELAY)
                self.check_google_captcha()
            else:
                break

        self.google_timer = threading.Thread(
            target=self.google_timer_thread,
        )
        self.google_timer.start()
        return scraped_links

    def start_process_google(self, google_list):
        self.wait_google_timer()

        self.google_term = google_list.pop(0)
        self.bot_print(self.google_term)

        self.google_query = quote_plus(self.google_term)
        time.sleep(3)
        self.get(self.SEARCH_URL.format(query=self.google_query))

        self.check_google_captcha()
        self.google_popup_check()

        remaining_pages = self.remaining_pages_log.get(self.google_term)
        if remaining_pages:
            scraped_links = self.scrape_google(remaining_pages[0], len(remaining_pages))
        else:
            scraped_links = self.scrape_google(self.start_page, self.max_google_pages)

        if not scraped_links:
            return None

        self.update_progress(self.google_term, "DONE", google=True)
        return scraped_links

    def filter_links(self, scraped_links):
        scraped_links = [get_root_url(i) for i in scraped_links]  # map by root url
        scraped_links = list(dict.fromkeys(scraped_links))  # de-duplicate, keeping result order
        scraped_links = filter_scraped_links(self.keywords, scraped_links)  # keyword filter
        website_log = self.get_website_log()
        scraped_links = [i for i in scraped_links if i not in website_log]  # filter by global log
        return scraped_links
