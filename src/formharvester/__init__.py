"""FormHarvester - AI-assisted form intelligence engine.

Public API:

    from formharvester import FormHarvester, FormFillDetails, HarvesterOptions
"""

from formharvester.api import (
    CaptchaError,
    FormFillDetails,
    FormHarvester,
    HarvesterOptions,
    HarvestResult,
    HarvestStatus,
    discover_sites,
    harvest_site,
    harvest_sites,
)
from formharvester.core import __VERSION__

__version__ = __VERSION__

__all__ = [
    "FormFillDetails",
    "FormHarvester",
    "CaptchaError",
    "HarvestResult",
    "HarvestStatus",
    "HarvesterOptions",
    "__version__",
    "discover_sites",
    "harvest_site",
    "harvest_sites",
]
