"""Contact form handling: discovery, field filling, submission."""

from __future__ import annotations

import random
import re
import threading
import time
from typing import TYPE_CHECKING
from urllib.parse import urljoin

from selenium.webdriver.common.keys import Keys

if TYPE_CHECKING:
    from formharvester._typing import EngineProtocol as _Base
else:
    _Base = object


class FormHandlerMixin(_Base):
    @staticmethod
    def clean_text(text):
        return text.replace("-", "").lower()

    def wait_get_inputs(self):
        self.wait_show_element("input", wait=3)
        return self.css("input", getall=True)

    def find_radio_divs(self):
        radios = self.css("input[type=radio]", getall=True)
        radio_divs = set()
        for radio in radios:
            x = self.xpath("./ancestor::div[1]", node=radio)
            radio_divs.add(x)
        return list(radio_divs)

    def check_calculation_captcha(self):
        match = re.findall(r"(\d+)\s([+\-*])\s(\d+)(\s=)?", self.driver.page_source)
        if match:
            match = match[0]
            no1 = int(match[0])
            op = match[1]
            no2 = int(match[2])
            if op == "+":
                return str(no1 + no2)
            elif op == "-":
                return str(no1 - no2)
            elif op == "*":
                return str(no1 * no2)

    def check_and_fill(self, element, field_type=None):
        if field_type == "number":
            random_n = str(random.randint(1, 5))
            element.send_keys(random_n)
            return True

        tag = element.get_attribute("outerHTML")

        ancestor = self.xpath(
            "./preceding::label[1]",
            node=element,
            attr="outerHTML",
        )
        if not ancestor:
            ancestor = ""

        fields = [
            self.clean_text(tag),
            self.clean_text(ancestor),
        ]

        element.clear()

        for field in fields:
            if "email" in field:
                element.send_keys(self.details["email"])
                return True
            elif bool(re.findall(r"(captcha)", field)):
                calc_res = self.check_calculation_captcha()
                if calc_res:
                    element.send_keys(calc_res)
                    return True
                captcha_text = self.check_solve_captchas(image=True)
                if captcha_text:
                    element.send_keys(captcha_text)
                    return True
            elif "phone" in field:
                element.send_keys(self.details["phone"])
                return True
            elif "city" in field:
                element.send_keys(self.details["city"])
                return True
            elif "state" in field:
                element.send_keys(self.details["state"])
                return True
            elif bool(re.findall(r"(location|address)", field)):
                element.send_keys(self.details["location"])
            elif bool(re.findall(r"(location|address)", field)):
                element.send_keys(self.details["location"])
            elif bool(re.findall(r"(subject|topic)", field)):
                element.send_keys(self.details["subject"])
                return True
            elif bool(re.findall(r"(firstname|givenname|fname|first)", field)):
                element.send_keys(self.details["first_name"])
                self.name_filled = True
                return True
            elif bool(re.findall(r"(lastname|lname|surname|last)", field)):
                element.send_keys(self.details["last_name"])
                self.name_filled = True
                return True
        if any(["name" in i for i in fields]) and not self.name_filled:
            element.send_keys(f"{self.details['first_name']} {self.details['last_name']}")
            self.name_filled = True
            return True
        else:
            element.send_keys("N/A")
            return True

    def find_contact_page(self, url):
        contact_links = []
        contact_links.extend(
            self.xpath(
                """//a[contains(translate(.,'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'contact')]""",
                getall=True,
            )
        )
        contact_links.extend(self.css('a[href*="contact"]', getall=True))
        if not contact_links:
            return []

        contact_hrefs = [i.get_attribute("href") for i in set(contact_links)]

        try:
            self.click(contact_links[0])
        except:
            pass

        inputs = self.wait_get_inputs()
        if not self.css("textarea"):
            if contact_hrefs:
                for href in contact_hrefs:
                    full_url = urljoin(url, href)

                    if full_url in self.visited_links:
                        continue
                    else:
                        x = self.get(full_url, sleep=1, timeout=10)
                        if not x:
                            return

                        self.scrape_emails()
                        # Switch to first tab
                        self.driver.switch_to.window(self.driver.window_handles[0])
                        self.cms_check()
                        self.visited_links.append(full_url)
                        inputs = self.wait_get_inputs()
                        if len(inputs) > 2:
                            break
        return inputs

    def find_submit_button(self):
        possible_css = [
            "input[type=submit]",
            "input[name=submit]",
            "input[value=submit]",
            "button[class=submit]",
            "button[name=submit]",
        ]
        possible_names = [
            "submit",
            "send",
            "enviar",
            "inviare",
            "book now",
        ]

        for css in possible_css:
            found = self.css(css)
            if found:
                return found

        for name in possible_names:
            found = self.xpath(
                f"""
                //button[contains(translate(.,'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'send')] | //input[contains(translate(.,'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'{name}')]
                """
            )
            if found:
                return found

        return None

    def submit_button(self, btn):
        try:
            self.click(btn)
        except:
            try:
                btn.click()
            except:
                try:
                    form = self.css("form")
                    if form:
                        self.script("arguments[0].submit();", form)
                except:
                    return False

    def cms_check(self):
        existing = []
        existing.extend(self.xpath('//script[contains(text(), "squarespace")]', getall=True))
        if not existing:
            # Popup check
            self.press_key(Keys.ESCAPE)
            time.sleep(1)

    def process_url(self, url):
        time.sleep(1)
        self.bot_print(url)
        self._note_visited(url)  # record globally (file for CLI, memory for API)

        # Technology matches belong to one target site.  The detector is
        # passive and must never prevent the existing harvest flow.
        self.technologies = []
        self.name_filled = False
        self.scraped_emails = set()
        self.visited_links.clear()

        contact_url = urljoin(url, "/contact/")
        contact = self.get(contact_url, sleep=1, check=True)
        if not contact:
            return

        self._scan_technologies()

        # Start time thread
        t = threading.Thread(target=self.check_time)
        self.threads.append(t)
        t.start()

        self.scrape_emails()
        # Switch to first tab
        self.driver.switch_to.window(self.driver.window_handles[0])

        self.cms_check()
        inputs = self.wait_get_inputs()

        if contact and not self.css("textarea"):
            inputs = self.find_contact_page(url)

        if not self.crawl:
            return

        if not self.css("textarea"):
            x = self.get(url, sleep=1, timeout=10)
            if not x:
                return

            self._scan_technologies()
            self.scrape_emails()
            # Switch to first tab
            self.driver.switch_to.window(self.driver.window_handles[0])
            self.cms_check()
            inputs = self.wait_get_inputs()
            if not self.css("textarea"):
                inputs = self.find_contact_page(url)

        if not self.crawl:
            return

        if not self.send_form:
            self._set_status(url, "VISITED")
            return True

        if inputs:
            # Fill text/email inputs
            for i in inputs:
                if i.get_attribute("type") in ["text", "email", "tel"]:
                    try:
                        self.check_and_fill(i)
                    except:
                        continue
                if i.get_attribute("type") in ["number"]:
                    try:
                        self.check_and_fill(i, field_type="number")
                    except:
                        continue

            # Check any radios
            radio_divs = self.find_radio_divs()
            for div in radio_divs:
                radios = self.css(
                    "input[type=radio]",
                    node=div,
                    getall=True,
                )
                for radio in radios[::-1]:
                    try:
                        self.click(radio)
                        time.sleep(0.5)
                        break
                    except:
                        continue

            # Select any options
            selects = self.css("form select", getall=True)
            for select in selects:
                options = self.css("option", node=select, getall=True)
                for option in options[::-1]:
                    try:
                        option.click()
                        break
                    except:
                        continue

            # Fill message textarea
            textarea = self.css("textarea")
            if textarea:
                self.click(textarea)
                self.write(textarea, self.details["message"])

            # Sleep
            time.sleep(3)

            captcha_solved = self.check_solve_captchas(recaptcha=True)

            # Submit
            btn = self.find_submit_button()
            if btn and not self.DEBUG:
                self.submit_button(btn)

                if not captcha_solved:
                    captcha_solved = self.check_solve_captchas(recaptcha=True)
                    if captcha_solved:
                        self.submit_button(btn)
                self._set_status(url, "SUBMITTED")
            elif btn and self.DEBUG:
                self.highlight(btn)
            else:
                self._set_status(url, "BUTTON_NOT_FOUND")
            return True
        else:
            self._set_status(url, "FORM_NOT_FOUND")
            return False
