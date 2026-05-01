"""CLI wrapper for v2 kill-switch operator commands."""

from v2.runtime.killctl import main

__all__ = ["main"]


if __name__ == "__main__":
    raise SystemExit(main())
