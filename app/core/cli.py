"""Small, side-effect-free helpers shared by command-line entry points."""

from __future__ import annotations

import sys


def configure_utf8_stdio() -> None:
    """Keep Windows CLIs usable when paths or API messages contain Unicode."""

    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if not callable(reconfigure):
            continue
        try:
            reconfigure(encoding="utf-8", errors="backslashreplace")
        except (LookupError, OSError):
            # Captured/test streams can reject reconfiguration; their existing
            # text interface is already safe to use.
            continue
