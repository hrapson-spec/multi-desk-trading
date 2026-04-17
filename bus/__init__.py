"""Message bus (spec §2 topology, §3–§4 validation)."""

from __future__ import annotations

from .bus import Bus, BusMode, BusValidationError

__all__ = ["Bus", "BusMode", "BusValidationError"]
