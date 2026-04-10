from fastapi import FastAPI
from contextlib import asynccontextmanager

from fastapi.responses import JSONResponse

from app.odr_executor.session.session_manager import session_manager as manager
from app.odr_executor.core.logger import TaskLoggerAdapter, base_log
from app.odr_executor.network.router import (
    router,
    set_session_manager_obj,
    clear_session_manager_obj,
)

log = TaskLoggerAdapter(base_log, {"tag": "OdrExecutorApp"})


def create_odr_executor_app() -> FastAPI:
    @asynccontextmanager
    async def lifespan(_: FastAPI):
        log.info("Starting up the application...")
        set_session_manager_obj(manager)

        try:
            manager.launch_stable_session()
            manager.launch_active_session(socat_port=5656)

            yield

        finally:
            log.info("Shutting down the application...")
            clear_session_manager_obj()
            manager.stop_stable_session()
            manager.stop_all_active_sessions()

    odr_executor_app = FastAPI(
        lifespan=lifespan,
        title="Radio Control System",
        version="1.0.0",
        description="API for controlling radio processes",
    )

    @odr_executor_app.exception_handler(ValueError)
    async def value_error_exception_handler(request, exc):
        log.error(f"URL: {request.url.path} | ValueError: {exc}")
        return JSONResponse(
            status_code=400,
            content={"detail": str(exc)},
        )

    odr_executor_app.include_router(router)
    return odr_executor_app


odr_executor_app = create_odr_executor_app()

# if __name__ == "__main__":
#     import uvicorn

#     uvicorn.run(odr_executor_app, host="localhost", port=8888)
