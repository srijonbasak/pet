"""Compatibility imports for the integrated studio."""

from .display_preview import DisplayPreview
from .scene import DESIGN_FILE
from .studio_window import StudioWindow as DisplayEditor

__all__ = ["DisplayPreview", "DisplayEditor", "DESIGN_FILE"]
