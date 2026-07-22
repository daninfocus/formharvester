"""Progress/log file persistence for the CLI harvesting flow."""

from __future__ import annotations

import json
import os

from formharvester.utils import get_root_url


class ProgressMixin:
    @staticmethod
    def load_txt(filename):
        if not os.path.exists(filename):
            open(filename, 'w').close()
            return []

        with open(filename) as f:
            return [i.strip() for i in f.readlines() if i.strip()]

    def get_progress_file(self, google):
        if google:
            return f'data/{self.mode}_progress_google.txt'
        else:
            return f'data/{self.mode}_progress.txt'

    def load_progress(self, google):
        filename = self.get_progress_file(google)
        progress = self.load_txt(filename)
        return [p.split('|') for p in progress]

    def write_progress(self, term_list, google):
        filename = self.get_progress_file(google=google)
        new_list = self.filter_unique(term_list, flat=True)  # filter duplicates
        if google:
            new_list = self.filter_duplicates_from_file(new_list, google=True)

        with open(filename, 'a') as f:
            for url in new_list:
                f.write(url + '|\n')

    def update_progress(self, term, status, google):

        filename = self.get_progress_file(google)
        progress = self.load_progress(google=google)
        progress = self.filter_unique(progress)

        for arr in progress:
            if arr[0] == term:
                arr[1] = status
                break
        with open(filename, 'w') as f:
            for arr in progress:
                f.write(f'{arr[0]}|{arr[1]}\n')

    @staticmethod
    def filter_unique(term_list, flat=False):
        unique = set()
        output = []

        if flat:
            for i in term_list:
                if i in unique:
                    continue
                unique.add(i)
                output.append(i)
        else:
            for li in term_list:
                if li[0] in unique:
                    continue
                unique.add(li[0])
                output.append(li)

        return output

    def filter_duplicates_from_file(self, term_list, google=False):
        progress = self.load_progress(google=google)
        terms = [i[0] for i in progress]
        return [i for i in term_list if i not in terms]

    def log_remaining_pages(self):
        with open('remaining_google_pages.json', 'w') as f:
            json.dump(self.remaining_pages_log, f)

    def get_remaining_pages(self):
        if os.path.exists('remaining_google_pages.json'):
            with open('remaining_google_pages.json') as f:
                self.remaining_pages_log = json.load(f)

    def get_no_progress(self, is_google=False):
        """
        Return urls with no progress
        :return: list
        """
        progress = self.load_progress(is_google)
        output = []
        for arr in progress:
            if not arr[1]:
                output.append(arr)
        return output

    def log_website(self, url):
        url = get_root_url(url)
        self.visited_websites.append(url)
        with open('data/website_log.txt', 'a') as f:
            f.write(url + '\n')

    def get_website_log(self):
        return self.load_txt('data/website_log.txt')

    def export_emails(self, filename='scraped_emails'):
        existing_emails = self.load_txt(f'data/{filename}_emails.txt')

        logged = set()
        with open(f'data/{filename}_emails.txt', 'a') as f:
            for (email, url) in self.scraped_emails:
                if email not in existing_emails and email not in logged:
                    f.write(email + '\n')
                    logged.add(email)

        if self.generate_email_sources:
            logged = set()
            with open(f'data/{filename}_emails_sources.txt', 'a') as f:
                for (email, url) in self.scraped_emails:
                    if email not in existing_emails:
                        f.write(f'{email} ({url})' + '\n')
                        logged.add(email)
