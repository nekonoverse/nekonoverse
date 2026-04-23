import asyncio
import logging

from app.worker.delivery_purge_worker import run_delivery_purge_loop
from app.worker.delivery_worker import run_delivery_loop

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")
logger = logging.getLogger("nekonoverse.worker")


async def run_worker():
    logger.info("Nekonoverse worker started")

    from app.services.deletion_queue import run_deletion_check_loop
    from app.services.email_queue import run_email_loop
    from app.services.export_queue import run_export_loop
    from app.services.face_detect_queue import run_face_detect_loop
    from app.services.search_queue import run_search_index_loop
    from app.services.summary_proxy_queue import run_summary_proxy_loop
    from app.services.video_thumb_queue import run_video_thumb_loop
    from app.services.vision_queue import run_vision_loop

    await asyncio.gather(
        run_delivery_loop(),
        run_delivery_purge_loop(),
        run_face_detect_loop(),
        run_summary_proxy_loop(),
        run_email_loop(),
        run_export_loop(),
        run_search_index_loop(),
        run_vision_loop(),
        run_deletion_check_loop(),
        run_video_thumb_loop(),
    )


def main():
    asyncio.run(run_worker())


if __name__ == "__main__":
    main()
