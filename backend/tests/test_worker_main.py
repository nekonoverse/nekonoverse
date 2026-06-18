"""Tests for worker/main.py — worker entry point."""

from unittest.mock import AsyncMock, patch


async def test_run_worker_calls_delivery_loop():
    with (
        patch("app.worker.main.run_delivery_loop", new_callable=AsyncMock) as mock_loop,
        patch("app.worker.main.run_delivery_purge_loop", new_callable=AsyncMock),
        patch("app.services.face_detect_queue.run_face_detect_loop", new_callable=AsyncMock),
        patch("app.services.summary_proxy_queue.run_summary_proxy_loop", new_callable=AsyncMock),
        patch("app.services.email_queue.run_email_loop", new_callable=AsyncMock),
        patch("app.services.export_queue.run_export_loop", new_callable=AsyncMock),
        patch("app.services.search_queue.run_search_index_loop", new_callable=AsyncMock),
        patch("app.services.vision_queue.run_vision_loop", new_callable=AsyncMock),
        patch("app.services.deletion_queue.run_deletion_check_loop", new_callable=AsyncMock),
        patch("app.services.video_thumb_queue.run_video_thumb_loop", new_callable=AsyncMock),
        patch("app.services.server_listing_worker.run_server_listing_loop", new_callable=AsyncMock),
    ):
        from app.worker.main import run_worker

        await run_worker()
        mock_loop.assert_called_once()


def test_main_calls_asyncio_run():
    with patch("app.worker.main.asyncio.run") as mock_run:
        from app.worker.main import main

        main()
        mock_run.assert_called_once()
