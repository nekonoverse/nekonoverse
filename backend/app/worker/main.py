import asyncio
import logging

from app.worker.delivery_worker import run_delivery_loop

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")
logger = logging.getLogger("nekonoverse.worker")


async def run_worker():
    logger.info("Nekonoverse worker started")

    from app.services.face_detect_queue import run_face_detect_loop
    from app.services.summary_proxy_queue import run_summary_proxy_loop

    await asyncio.gather(
        run_delivery_loop(),
        run_face_detect_loop(),
        run_summary_proxy_loop(),
    )


def main():
    asyncio.run(run_worker())


if __name__ == "__main__":
    main()
