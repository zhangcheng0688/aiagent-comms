"""V3.0 Celery 任务队列（生产路径）。

V2.1 用 FastAPI BackgroundTasks（单进程）。V3.0 升级到 Celery + Redis：
- 多 worker 并发
- 任务失败可重试（指数退避）
- 任务状态可查
- 不影响主 API 进程

默认不启用（需要 REDIS_URL + celery worker）。开发环境用 BackgroundTasks 即可。
"""
from __future__ import annotations
import os
import logging
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from celery import Celery

log = logging.getLogger("aiagent.celery")

CELERY_ENABLED = os.getenv("CELERY_ENABLED", "0") == "1"

_celery_app: Optional["Celery"] = None


def get_celery_app():
    """懒加载 Celery app。"""
    global _celery_app
    if _celery_app is not None:
        return _celery_app
    if not CELERY_ENABLED:
        return None
    try:
        from celery import Celery
        from .config import CELERY_BROKER_URL, CELERY_RESULT_BACKEND
        _celery_app = Celery(
            "aiagent",
            broker=CELERY_BROKER_URL,
            backend=CELERY_RESULT_BACKEND,
        )
        _celery_app.conf.update(
            task_serializer="json",
            accept_content=["json"],
            result_serializer="json",
            timezone="Asia/Shanghai",
            enable_utc=False,
            task_track_started=True,
            task_acks_late=True,
            worker_prefetch_multiplier=1,
            task_default_retry_delay=10,
            task_default_max_retries=3,
        )
        log.info(f"Celery initialized broker={CELERY_BROKER_URL}")
        return _celery_app
    except ImportError:
        log.warning("Celery not installed, falling back to FastAPI BackgroundTasks")
        return None


# === 任务定义（仅在 CELERY_ENABLED=1 时生效）===
if get_celery_app() is not None:
    app = get_celery_app()

    @app.task(bind=True, name="aiagent.run_order")
    def run_order_task(self, order_id: str):
        """Celery worker 跑订单。"""
        import asyncio
        from .main import _run_order_in_background
        return asyncio.run(_run_order_in_background(order_id))

    @app.task(bind=True, name="aiagent.evaluate_order")
    def evaluate_order_task(self, order_id: str):
        """Celery worker 跑评估。"""
        import asyncio
        from .main import _evaluate_order_v2
        return asyncio.run(_evaluate_order_v2(order_id))
