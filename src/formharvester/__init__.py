"""FormHarvester - AI-assisted form intelligence engine.

Public API:

    from formharvester import FormHarvester, FormFillDetails, HarvesterOptions
"""

from formharvester.api import (
    CaptchaError,
    FormFillDetails,
    FormHarvester,
    GeneratedFormContent,
    HarvesterOptions,
    HarvestResult,
    HarvestStatus,
    LlmClient,
    LlmError,
    discover_sites,
    harvest_site,
    harvest_sites,
)
from formharvester.core import __VERSION__
from formharvester.technology import TechnologyEvidence, TechnologyMatch

__version__ = __VERSION__

__all__ = [
    "FormFillDetails",
    "FormHarvester",
    "CaptchaError",
    "HarvestResult",
    "HarvestStatus",
    "TechnologyEvidence",
    "TechnologyMatch",
    "HarvesterOptions",
    "GeneratedFormContent",
    "LlmClient",
    "LlmError",
    "__version__",
    "discover_sites",
    "harvest_site",
    "harvest_sites",
]
