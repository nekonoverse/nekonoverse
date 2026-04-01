__version__ = "20260401-2"


def _resolve_version() -> str:
    """非リリース (develop) ビルドに +git-<hash> サフィックスを付加する。

    解決順序:
    1. GIT_VERSION ファイル (Docker ビルド ARG で書き出し)
    2. git コマンド (.git が利用可能な開発環境)
    3. バージョン文字列そのまま (フォールバック)
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
