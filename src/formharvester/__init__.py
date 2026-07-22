"""FormHarvester — AI-assisted form intelligence engine.

Public API:

    from formharvester import FormHarvester, FormFillDetails, HarvesterOptions
"""

from formharvester.api import (
    FormFillDetails,
    FormHarvester,
    HarvesterOptions,
    HarvestResult,
    HarvestStatus,
    harvest_site,
    harvest_sites,
)
from formharvester.core import __VERSION__

__version__ = __VERSION__

__all__ = [
    "FormFillDetails",
    "FormHarvester",
    "HarvestResult",
    "HarvestStatus",
    "HarvesterOptions",
    "__version__",
    "harvest_site",
    "harvest_sites",
]
