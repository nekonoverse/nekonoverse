"""Tests for video_thumb_queue — 動画サムネイル生成キュー。"""

import json
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import httpx


# ── enqueue_local ──


async def test_enqueue_local_pushes_to_queue(mock_valkey):
    """video_thumb_enabled 時にジョブがキューに追加される。"""
    from app.services.video_thumb_queue import QUEUE_KEY, enqueue_local

    file_id = uuid.uuid4()
    with patch("app.services.video_thumb_queue.settings") as mock_settings:
        mock_settings.video_thumb_enabled = True
        with patch("app.services.video_thumb_queue.valkey_client", mock_valkey):
            await enqueue_local(file_id)
    mock_valkey.lpush.assert_called()
    last_call = mock_valkey.lpush.call_args
    assert last_call[0][0] == QUEUE_KEY
    job = json.loads(last_call[0][1])
    assert job["type"] == "local"
    assert job["drive_file_id"] == str(file_id)
    assert job["attempts"] == 0


async def test_enqueue_local_noop_when_disabled(mock_valkey):
    """video_thumb_enabled が False の場合は何もしない。"""
    from app.services.video_thumb_queue import enqueue_local

    initial_count = mock_valkey.lpush.call_count
    with patch("app.services.video_thumb_queue.settings") as mock_settings:
        mock_settings.video_thumb_enabled = False
        await enqueue_local(uuid.uuid4())
    assert mock_valkey.lpush.call_count == initial_count


async def test_enqueue_remote_pushes_to_queue(mock_valkey):
    """リモートジョブがキューに追加される。"""
    from app.services.video_thumb_queue import enqueue_remote

    note_id = uuid.uuid4()
    att_ids = [uuid.uuid4(), uuid.uuid4()]
    with patch("app.services.video_thumb_queue.settings") as mock_settings:
        mock_settings.video_thumb_enabled = True
        with patch("app.services.video_thumb_queue.valkey_client", mock_valkey):
            await enqueue_remote(note_id, att_ids)
    job = json.loads(mock_valkey.lpush.call_args[0][1])
    assert job["type"] == "remote"
    assert job["note_id"] == str(note_id)
    assert len(job["attachment_ids"]) == 2


# ── _process_local ──


async def test_process_local_skips_missing_file(mock_valkey):
    """DriveFile が見つからない場合はスキップする。"""
    from app.services.video_thumb_queue import _process_local

    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    mock_db.execute = AsyncMock(return_value=mock_result)

    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_db)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    with patch("app.database.async_session", return_value=mock_session):
        await _process_local({"drive_file_id": str(uuid.uuid4())})
    mock_db.commit.assert_not_called()


async def test_process_local_skips_already_processed(mock_valkey):
    """サムネイル済みの DriveFile はスキップする。"""
    from app.services.video_thumb_queue import _process_local

    mock_file = MagicMock()
    mock_file.thumbnail_s3_key = "thumb/existing.webp"
    mock_file.mime_type = "video/mp4"

    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = mock_file
    mock_db.execute = AsyncMock(return_value=mock_result)

    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_db)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    with patch("app.database.async_session", return_value=mock_session):
        await _process_local({"drive_file_id": str(uuid.uuid4())})
    mock_db.commit.assert_not_called()


async def test_process_local_skips_non_video(mock_valkey):
    """動画でないファイルはスキップする。"""
    from app.services.video_thumb_queue import _process_local

    mock_file = MagicMock()
    mock_file.thumbnail_s3_key = None
    mock_file.mime_type = "image/png"

    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = mock_file
    mock_db.execute = AsyncMock(return_value=mock_result)

    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_db)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    with patch("app.database.async_session", return_value=mock_session):
        await _process_local({"drive_file_id": str(uuid.uuid4())})
    mock_db.commit.assert_not_called()


async def test_process_local_generates_thumbnail(mock_valkey):
    """正常系: サムネイル生成して S3 保存、DB 更新する。"""
    from app.services.video_thumb_queue import _process_local

    mock_file = MagicMock()
    mock_file.thumbnail_s3_key = None
    mock_file.mime_type = "video/mp4"
    mock_file.s3_key = "u/abc/test.mp4"
    mock_file.width = None
    mock_file.height = None
    mock_file.duration = None

    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = mock_file
    mock_db.execute = AsyncMock(return_value=mock_result)

    thumb_bytes = b"\x00\x01\x02"
    mock_response = MagicMock(spec=httpx.Response)
    mock_response.content = thumb_bytes
    mock_response.headers = {
        "content-type": "image/webp",
        "x-video-duration": "30.5",
        "x-video-width": "1920",
        "x-video-height": "1080",
    }
    mock_response.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_db)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    with (
        patch("app.database.async_session", return_value=mock_session),
        patch(
            "app.storage.generate_presigned_get_url",
            return_value="http://nekono3s:8080/nekonoverse/u/abc/test.mp4?X-Amz-Signature=abc",
        ) as mock_presign,
        patch("app.storage.upload_file", new_callable=AsyncMock) as mock_ul,
        patch(
            "app.utils.http_client.make_video_thumb_client", return_value=mock_client
        ),
        patch("app.services.video_thumb_queue.settings") as mock_settings,
    ):
        mock_settings.video_thumb_base_url = "http://video-thumb:8005"

        await _process_local({"drive_file_id": str(uuid.uuid4())})

    # 動画は DL せず presigned URL を生成 → /thumbnail_from_url に JSON で渡す
    mock_presign.assert_called_once_with("u/abc/test.mp4", expires_in=300)
    mock_client.post.assert_called_once()
    call_args, call_kwargs = mock_client.post.call_args
    assert call_args[0] == "http://video-thumb:8005/thumbnail_from_url"
    assert call_kwargs["json"] == {
        "url": "http://nekono3s:8080/nekonoverse/u/abc/test.mp4?X-Amz-Signature=abc"
    }
    mock_ul.assert_called_once_with("thumb/u/abc/test.mp4.webp", thumb_bytes, "image/webp")
    assert mock_file.thumbnail_s3_key == "thumb/u/abc/test.mp4.webp"
    assert mock_file.thumbnail_mime_type == "image/webp"
    assert mock_file.duration == 30.5
    assert mock_file.width == 1920
    assert mock_file.height == 1080
    mock_db.commit.assert_called_once()


# ── _retry_or_dead ──


async def test_retry_or_dead_retries(mock_valkey):
    """MAX_ATTEMPTS 未満の場合は遅延キューに再追加する。"""
    from app.services.video_thumb_queue import _retry_or_dead

    job = {"type": "local", "drive_file_id": str(uuid.uuid4()), "attempts": 0}
    with patch("app.services.video_thumb_queue.valkey_client", mock_valkey):
        await _retry_or_dead(job, "test error")
    mock_valkey.zadd.assert_called()
    assert job["attempts"] == 1
    assert job["last_error"] == "test error"


async def test_retry_or_dead_dead_letters(mock_valkey):
    """MAX_ATTEMPTS に達した場合はデッドレターに移動する。"""
    from app.services.video_thumb_queue import DEAD_KEY, _retry_or_dead

    job = {"type": "local", "drive_file_id": str(uuid.uuid4()), "attempts": 4}
    with patch("app.services.video_thumb_queue.valkey_client", mock_valkey):
        await _retry_or_dead(job, "persistent error")
    # lpush でデッドレターに追加される
    found = False
    for call in mock_valkey.lpush.call_args_list:
        if call[0][0] == DEAD_KEY:
            found = True
            break
    assert found, "Expected lpush to DEAD_KEY"
    assert job["attempts"] == 5
