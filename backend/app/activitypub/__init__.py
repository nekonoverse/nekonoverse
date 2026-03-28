"""ActivityPub プロトコルヘルパー。"""

# MFM (Misskey Flavored Markdown) としてレンダリングしても安全な source の mediaType 一覧。
# text/x.misskeymarkdown: MFM そのもの
# text/plain: プレーンテキストは有効な MFM; Nekonoverse も歴史的にこれを送信していた
MFM_MEDIA_TYPES = frozenset({"text/x.misskeymarkdown", "text/plain"})


def extract_mfm_source(note_data: dict) -> str | None:
    """AP Note オブジェクトから MFM 互換のソーステキストを抽出する。

    mediaType が MFM 互換の場合のみ source.content を返し、
    該当しなければ _misskey_content (常に MFM) にフォールバックする。
    MFM ソースが利用できない場合は None を返す。
    """
    source_data = note_data.get("source")
    if isinstance(source_data, dict):
        media_type = source_data.get("mediaType")
        if media_type is None or media_type in MFM_MEDIA_TYPES:
            content = source_data.get("content")
            if isinstance(content, str):
                return content

    # Misskey フォールバック: _misskey_content は常に MFM
    misskey_content = note_data.get("_misskey_content")
    if isinstance(misskey_content, str):
        return misskey_content

    return None


def resolve_source_media_type(source: str, preferences: dict | None = None) -> str:
    """ユーザー設定に基づいて送信時の source.mediaType を決定する。

    設定値:
      "mfm"   -> 常に text/x.misskeymarkdown
      "plain" -> 常に text/plain
      "auto"  -> MFM 固有構文が見つかれば text/x.misskeymarkdown、なければ text/plain
    """
    pref = (preferences or {}).get("source_media_type", "auto")
    if pref == "mfm":
        return "text/x.misskeymarkdown"
    if pref == "plain":
        return "text/plain"
    # auto: MFM 固有の関数構文を検出
    if "$[" in source:
        return "text/x.misskeymarkdown"
    return "text/plain"
