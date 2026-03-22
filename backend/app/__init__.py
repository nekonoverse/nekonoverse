__version__ = "20260322-4"


def _resolve_version() -> str:
    """Append +git-<hash> suffix on non-release (develop) builds.

    Resolution order:
    1. GIT_VERSION file (written by Docker build ARG)
    2. git command (dev environment with .git available)
    3. Bare version string (fallback)
    """
    import pathlib

    # 1. ビルド時に書き出されたGIT_VERSIONファイルを読む
    git_version_file = pathlib.Path(__file__).resolve().parent.parent / "GIT_VERSION"
    try:
        content = git_version_file.read_text().strip()
        if content:
            branch, commit_hash = content.split(":", 1)
            if branch != "main":
                return f"{__version__}+git-{commit_hash[:7]}"
            return __version__
    except Exception:
        pass

    # 2. gitコマンドで取得 (dev環境)
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
