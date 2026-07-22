"""Backwards-compatibility shim.

The engine moved into the ``formharvester`` package in 3.0.0. Prefer the
``formharvester`` console command, or ``from formharvester import FormHarvester``.
This shim keeps ``python bot.py`` and ``from bot import Bot`` working.
"""

from formharvester.cli import Bot, main  # noqa: F401

if __name__ == "__main__":
    main()
