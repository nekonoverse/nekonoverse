"""Rust ネイティブ拡張 (`nekonoverse_native`, PyO3/maturin) のロードヘルパー。

Rust ツールチェーン未導入のローカル開発環境や、ネイティブ拡張のビルドに
失敗した環境でもインポートエラーでテスト収集自体が落ちないよう、失敗時は
`native` を `None` にする。呼び出し側は `NATIVE_AVAILABLE` を見て既存の
純 Python 実装にフォールバックすること。
"""

try:
    import nekonoverse_native as native

    NATIVE_AVAILABLE = True
except ImportError:
    native = None
    NATIVE_AVAILABLE = False
