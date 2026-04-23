import os
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from dotenv import load_dotenv

from app.scheduler.core.logger import base_log, TaskLoggerAdapter
from app.scheduler.engine.master import MasterScheduler
from app.scheduler.network.router import (
    clear_callback_target,
    control_router,
    router as callback_router,
    set_callback_target,
)


load_dotenv(dotenv_path=Path(__file__).resolve().parents[2] / ".env")

log = TaskLoggerAdapter(base_log, {"tag": "SchedulerApp"})


class _SuppressStatusAccessLogFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args or ()
        args_text = " ".join(str(arg) for arg in args)
        return "/control/v1/status" not in args_text


logging.getLogger("uvicorn.access").addFilter(_SuppressStatusAccessLogFilter())

DEFAULT_SCHEDULER_CONFIG_PATH = (
    Path(__file__).resolve().parents[2] / "config" / "scheduler" / "flows.yaml"
)


def create_scheduler_app(config_path: str) -> FastAPI:
    @asynccontextmanager
    async def lifespan(fastapi_app: FastAPI):
        log.info("Starting Scheduler API...")
        try:
            scheduler = MasterScheduler(config_path=config_path)
            fastapi_app.state.scheduler = scheduler
            set_callback_target(scheduler)
            fastapi_app.state.scheduler_running = False
            fastapi_app.state.scheduler_task = None
            fastapi_app.state.scheduler_last_outcome = "idle"

            yield

        finally:
            clear_callback_target()
            log.info("Scheduler API stopped.")

    app_instance = FastAPI(
        lifespan=lifespan,
        title="Scheduler Callback API",
        version="1.0.0",
        description="API for scheduler callback ingestion",
    )
    app_instance.include_router(callback_router)
    app_instance.include_router(control_router)

    return app_instance


scheduler_app = create_scheduler_app(
    config_path=os.getenv(
        "SCHEDULER_CONFIG_PATH",
        str(DEFAULT_SCHEDULER_CONFIG_PATH),
    )
)

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(scheduler_app, host="localhost", port=8090)
