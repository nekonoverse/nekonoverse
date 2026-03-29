"""neko-visionジョブキューのテスト。"""

import json
import uuid
from unittest.mock import AsyncMock, patch

from app.services.vision_queue import (
    DEAD_KEY,
    DELAYED_KEY,
    MAX_ATTEMPTS,
    QUEUE_KEY,
    _process_job,
    _retry_or_dead,
    enqueue_local,
    enqueue_remote,
)

# vision_queue.py は `from app.valkey_client import valkey as valkey_client` で
# モジュールレベルのバインドを持つため、conftest の mock_valkey だけでは不十分。
# 各テストで `app.services.vision_queue.valkey_client` も直接パッチする。

VALKEY_PATH = "app.services.vision_queue.valkey_client"


# --- enqueue_local ---


async def test_enqueue_local(mock_valkey):
    """ローカルジョブがValkeyにJSON形式で追加される。"""
    drive_file_id = uuid.uuid4()
    note_id = uuid.uuid4()
    mock_vk = AsyncMock()
    mock_vk.lpush = AsyncMock(return_value=1)

    with patch("app.services.vision_queue.settings") as mock_settings, \
         patch(VALKEY_PATH, mock_vk):
        mock_settings.neko_vision_enabled = True
        await enqueue_local(
            drive_file_id,
            note_id,
            note_text="Hello world",
            context=["Parent text"],
        )

    mock_vk.lpush.assert_called_once()
    args = mock_vk.lpush.call_args
    assert args[0][0] == QUEUE_KEY

    job = json.loads(args[0][1])
    assert job["type"] == "local"
    assert job["drive_file_id"] == str(drive_file_id)
    assert job["note_id"] == str(note_id)
    assert job["note_text"] == "Hello world"
    assert job["context"] == ["Parent text"]
    assert job["attempts"] == 0


async def test_enqueue_local_disabled(mock_valkey):
    """neko-vision無効時はエンキューしない。"""
    mock_vk = AsyncMock()

    with patch("app.services.vision_queue.settings") as mock_settings, \
         patch(VALKEY_PATH, mock_vk):
        mock_settings.neko_vision_enabled = False
        await enqueue_local(uuid.uuid4(), uuid.uuid4())

    mock_vk.lpush.assert_not_called()


async def test_enqueue_local_truncates_text(mock_valkey):
    """note_text が1000文字を超える場合は切り詰める。"""
    mock_vk = AsyncMock()
    mock_vk.lpush = AsyncMock(return_value=1)

    with patch("app.services.vision_queue.settings") as mock_settings, \
         patch(VALKEY_PATH, mock_vk):
        mock_settings.neko_vision_enabled = True
        await enqueue_local(
            uuid.uuid4(),
            uuid.uuid4(),
            note_text="x" * 2000,
        )

    job = json.loads(mock_vk.lpush.call_args[0][1])
    assert len(job["note_text"]) == 1000


# --- enqueue_remote ---


async def test_enqueue_remote(mock_valkey):
    """リモートジョブがValkeyにJSON形式で追加される。"""
    note_id = uuid.uuid4()
    att_ids = [uuid.uuid4(), uuid.uuid4()]
    mock_vk = AsyncMock()
    mock_vk.lpush = AsyncMock(return_value=1)

    with patch("app.services.vision_queue.settings") as mock_settings, \
         patch(VALKEY_PATH, mock_vk):
        mock_settings.neko_vision_enabled = True
        await enqueue_remote(
            note_id,
            att_ids,
            note_text="Image post",
            context=["context1", "context2"],
        )

    job = json.loads(mock_vk.lpush.call_args[0][1])
    assert job["type"] == "remote"
    assert job["note_id"] == str(note_id)
    assert len(job["attachment_ids"]) == 2
    assert job["note_text"] == "Image post"


async def test_enqueue_remote_disabled(mock_valkey):
    """neko-vision無効時はエンキューしない。"""
    mock_vk = AsyncMock()

    with patch("app.services.vision_queue.settings") as mock_settings, \
         patch(VALKEY_PATH, mock_vk):
        mock_settings.neko_vision_enabled = False
        await enqueue_remote(uuid.uuid4(), [uuid.uuid4()])

    mock_vk.lpush.assert_not_called()


# --- _process_job ---


async def test_process_job_routes_local(mock_valkey):
    """localジョブが_process_localにルーティングされる。"""
    job = {"type": "local", "drive_file_id": str(uuid.uuid4())}

    with patch(
        "app.services.vision_queue._process_local",
        new=AsyncMock(),
    ) as mock_process:
        await _process_job(job)

    mock_process.assert_called_once_with(job)


async def test_process_job_routes_remote(mock_valkey):
    """remoteジョブが_process_remoteにルーティングされる。"""
    job = {
        "type": "remote",
        "note_id": str(uuid.uuid4()),
        "attachment_ids": [str(uuid.uuid4())],
    }

    with patch(
        "app.services.vision_queue._process_remote",
        new=AsyncMock(),
    ) as mock_process:
        await _process_job(job)

    mock_process.assert_called_once_with(job)


async def test_process_job_unknown_type(mock_valkey):
    """不明なジョブタイプはスキップされる（例外なし）。"""
    job = {"type": "unknown"}
    await _process_job(job)  # 例外が発生しなければOK


# --- _retry_or_dead ---


async def test_retry_or_dead_retries(mock_valkey):
    """MAX_ATTEMPTS未満のジョブは遅延キューに追加される。"""
    job = {"type": "local", "drive_file_id": str(uuid.uuid4()), "attempts": 1}
    mock_vk = AsyncMock()
    mock_vk.zadd = AsyncMock()

    with patch(VALKEY_PATH, mock_vk):
        await _retry_or_dead(job, "test error")

    assert job["attempts"] == 2
    assert job["last_error"] == "test error"
    mock_vk.zadd.assert_called_once()
    args = mock_vk.zadd.call_args[0]
    assert args[0] == DELAYED_KEY


async def test_retry_or_dead_dead_letters(mock_valkey):
    """MAX_ATTEMPTS以上のジョブはデッドレターキューに移動される。"""
    job = {
        "type": "local",
        "drive_file_id": str(uuid.uuid4()),
        "attempts": MAX_ATTEMPTS - 1,
    }
    mock_vk = AsyncMock()
    mock_vk.lpush = AsyncMock(return_value=1)

    with patch(VALKEY_PATH, mock_vk):
        await _retry_or_dead(job, "final error")

    assert job["attempts"] == MAX_ATTEMPTS
    mock_vk.lpush.assert_called_once()
    args = mock_vk.lpush.call_args[0]
    assert args[0] == DEAD_KEY


# --- _promote_delayed ---


async def test_promote_delayed_moves_ready_jobs(mock_valkey):
    """期限切れの遅延ジョブがメインキューに戻される。"""
    from app.services.vision_queue import _promote_delayed

    ready_job = json.dumps({"type": "local", "drive_file_id": str(uuid.uuid4())})
    mock_vk = AsyncMock()
    mock_vk.zrangebyscore = AsyncMock(return_value=[ready_job])
    mock_vk.lpush = AsyncMock(return_value=1)
    mock_vk.zremrangebyscore = AsyncMock()

    with patch(VALKEY_PATH, mock_vk):
        count = await _promote_delayed()

    assert count == 1
    mock_vk.lpush.assert_called_once_with(QUEUE_KEY, ready_job)
    mock_vk.zremrangebyscore.assert_called_once()


async def test_promote_delayed_no_ready_jobs(mock_valkey):
    """期限切れの遅延ジョブがなければ何もしない。"""
    from app.services.vision_queue import _promote_delayed

    mock_vk = AsyncMock()
    mock_vk.zrangebyscore = AsyncMock(return_value=[])

    with patch(VALKEY_PATH, mock_vk):
        count = await _promote_delayed()

    assert count == 0
    mock_vk.lpush.assert_not_called()
