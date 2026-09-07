"""Live smoke test against the public smoke-target page.

Requires Chrome + a matching driver and network access, so it is marked
``smoke`` and skipped by default. Run explicitly with:

    pytest -m smoke

(remove ``-m "not smoke"`` filtering). See issue #7.
"""

from __future__ import annotations

import pytest

from formharvester import FormFillDetails, FormHarvester, HarvesterOptions

SMOKE_TARGET = "https://dariomory.github.io/formharvester-smoke-target"
_VALID_STATUSES = {"SUBMITTED", "FORM_NOT_FOUND", "BUTTON_NOT_FOUND", "VISITED", "ERROR"}


@pytest.mark.smoke
def test_live_smoke_target_submits_form() -> None:
    details = FormFillDetails(
        first_name="Smoke",
        last_name="Test",
        email="smoke@example.com",
        phone="1234567890",
        subject="Hello",
        message="This is an automated smoke test.",
    )
    with FormHarvester(details, HarvesterOptions(headless=True, send_form=True)) as fh:
        result = fh.harvest(SMOKE_TARGET)

    # The engine reached the page and reported a well-formed outcome.
    assert result.status in _VALID_STATUSES
    assert result.url == SMOKE_TARGET
