"""Standalone training project management."""

__version__ = "0.9.1"

from .client import StudioAPIError, StudioClient

__all__ = ["StudioClient", "StudioAPIError", "__version__"]
