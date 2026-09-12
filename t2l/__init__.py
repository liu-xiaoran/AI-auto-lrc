"""Public v2 API for AI Auto LRC."""

from ._version import PACKAGE_VERSION
from .api import AlignmentRuntime, create_runtime, process
from .contracts import (
    AlignmentRequest,
    AlignmentResult,
    Diagnostic,
    FrameSpan,
    RuntimeConfig,
    Timebase,
    TokenAlignment,
    VocalSeparationOptions,
)

__version__ = PACKAGE_VERSION

__all__ = [
    "AlignmentRequest",
    "AlignmentResult",
    "AlignmentRuntime",
    "Diagnostic",
    "FrameSpan",
    "RuntimeConfig",
    "Timebase",
    "TokenAlignment",
    "VocalSeparationOptions",
    "create_runtime",
    "process",
]
