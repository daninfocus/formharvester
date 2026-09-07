"""Scraping mixins: Google search + on-page email extraction."""

from formharvester.scraper.emails import EmailScraperMixin
from formharvester.scraper.google import GoogleSearchMixin

__all__ = ["EmailScraperMixin", "GoogleSearchMixin"]
