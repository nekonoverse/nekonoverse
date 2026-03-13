__version__ = "20260313-1"


def _resolve_version() -> str:
    """Append +git-<hash> suffix on non-release (develop) builds."""
    import subprocess

    try:
        branch = subprocess.check_output(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
        if branch == "main":
            return __version__
        short_hash = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
        return f"{__version__}+git-{short_hash}"
    except Exception:
        return __version__


VERSION = _resolve_version()
