"""Command-line entry point for FormHarvester."""

from __future__ import annotations

from formharvester.cli.app import Bot

__all__ = ["Bot", "main"]


def main() -> None:
    """Run the config-driven harvest loop (reads ``config.txt``)."""
    while True:
        bot = Bot()
        try:
            remaining_google = bot.get_no_progress(is_google=True)
            remaining_urls = bot.get_no_progress()
            if remaining_urls or remaining_google:
                urls = [i[0] for i in remaining_urls]
                googles = [i[0] for i in remaining_google]
                bot.resume(urls, googles)
            else:
                bot.bot_print("Done!", is_input=True)
        except Exception as e:
            bot.close()
            print(e)


if __name__ == "__main__":
    main()
