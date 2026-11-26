"""HENTAI Studio: Hub for Experiments, Neural Training, Analysis & Inference."""

__version__ = "0.9.2"

from .client import StudioAPIError, StudioClient

__all__ = ["StudioClient", "StudioAPIError", "__version__"]
