"""Standalone training project management."""

__version__ = "0.7.0"

from .client import StudioAPIError, StudioClient

__all__ = ["StudioClient", "StudioAPIError", "__version__"]
