"""Email address scraping from the current page."""

from __future__ import annotations

import re

from formharvester.utils import EMAIL_RGX


class EmailScraperMixin:
    def scrape_emails(self):
        emails = set(re.findall(EMAIL_RGX, str(self.driver.page_source).lower()))
        emails = [
            i for i in emails if
            not any(
                x for x in
                ['.svg', '.png', '.jpg', '/', 'unpkg', 'sentry.wixpress.com', 'static.', 'indexOf', '.js'] if
                x in i
            )
        ]
        if emails:
            self.scraped_emails.update([(e, self.driver.current_url) for e in emails])
