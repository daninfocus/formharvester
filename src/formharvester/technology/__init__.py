"""Local website technology detection.

The detector is intentionally evidence based.  It identifies technologies that
leave browser-visible fingerprints, but does not pretend that an arbitrary
backend framework can be proven from a public page.
"""

from formharvester.technology.detector import (
    PageSignals,
    TechnologyDetector,
    TechnologyEvidence,
    TechnologyMatch,
)

__all__ = [
    "PageSignals",
    "TechnologyDetector",
    "TechnologyEvidence",
    "TechnologyMatch",
]
