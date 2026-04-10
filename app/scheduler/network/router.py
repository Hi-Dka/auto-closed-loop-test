import asyncio
from time import time
from typing import Any, Dict, Protocol, cast

from fastapi import APIRouter, HTTPException, Request

from app.scheduler.core.logger import base_log, TaskLoggerAdapter


log = TaskLoggerAdapter(base_log, {"tag": "SchedulerRouter"})
control_router = APIRouter(prefix="/control/v1", tags=["Scheduler Control"])


async def _run_scheduler_pipeline(request: Request):
    from app.scheduler.engine.master import MasterScheduler

    app = request.app
    scheduler: MasterScheduler = app.state.scheduler

    try:
        await asyncio.to_thread(scheduler.initialize)
        log.info("Suite configuration loaded, starting pipeline execution")
        run_ok = await asyncio.to_thread(scheduler.run)
        app.state.scheduler_last_outcome = "success" if run_ok else "failed"
        if run_ok:
            log.info("Scheduler pipeline completed")
        else:
            log.warning("Scheduler pipeline finished with failure")
    except (RuntimeError, ValueError, FileNotFoundError, TimeoutError) as e:
        app.state.scheduler_last_outcome = "failed"
        log.error(f"Scheduler execution failed: {e}")
    finally:
        app.state.scheduler_running = False
        app.state.scheduler_task = None


@control_router.post("/start")
async def start_scheduler(request: Request):
    app = request.app

    if not hasattr(app.state, "scheduler"):
        raise HTTPException(status_code=500, detail="Scheduler not initialized")

    if app.state.scheduler_running:
        return {"status": "already_running", "message": "Scheduler is already running"}

    app.state.scheduler_running = True
    app.state.scheduler_last_outcome = "running"
    log.info("Scheduler start requested")
    app.state.scheduler_task = asyncio.create_task(_run_scheduler_pipeline(request))

    return {
        "status": "started",
        "message": "Scheduler started in background",
    }


@control_router.post("/status")
async def get_scheduler_status(request: Request):
    app = request.app

    if not hasattr(app.state, "scheduler"):
        raise HTTPException(status_code=500, detail="Scheduler not initialized")

    scheduler: Any = app.state.scheduler
    status = (
        scheduler.get_current_status()
        if hasattr(scheduler, "get_current_status")
        else {}
    )

    run_status = (
        status.get("run_status", "unknown") if isinstance(status, dict) else "unknown"
    )
    if app.state.scheduler_running:
        scheduler_status = "running"
    elif run_status in {"success", "failed", "initialized", "idle"}:
        scheduler_status = run_status
    else:
        scheduler_status = "stopped"

    return {
        "scheduler_status": scheduler_status,
        "last_outcome": getattr(app.state, "scheduler_last_outcome", "unknown"),
        "flow_status": status,
    }


# ============================================== Scheduler Callback Router ==============================================


class SchedulerCallbackTarget(Protocol):

    def dispatch_callback(self, data: Dict[str, Any], callback_type: str) -> None: ...


_target_state: Dict[str, SchedulerCallbackTarget | None] = {"scheduler": None}


def set_callback_target(target: SchedulerCallbackTarget):
    _target_state["scheduler"] = target


def clear_callback_target():
    _target_state["scheduler"] = None


def _get_scheduler_target(request: Request) -> SchedulerCallbackTarget:
    del request
    target = _target_state["scheduler"]
    if target is None:
        raise HTTPException(status_code=500, detail="Callback handler not configured")
    return cast(SchedulerCallbackTarget, target)


router = APIRouter(prefix="/callback/v1", tags=["Sheduler Callbacks"])


def _normalize_callback_message(
    raw_data: Dict[str, Any], callback_type: str
) -> Dict[str, Any]:
    message = dict(raw_data)
    message["callback_type"] = (
        message.get("callback_type") or message.get("type") or callback_type
    )
    message["status"] = message.get("status", "ok")
    message["payload"] = message.get("payload", dict(message))
    message["timestamp"] = message.get("timestamp", time())
    message.setdefault("request_id", None)
    message.setdefault("group_id", None)
    return message


@router.post("/scan")
async def handle_generic(request: Request):
    body = await request.json()
    if not isinstance(body, dict):
        raise HTTPException(
            status_code=400, detail="Callback JSON body must be an object"
        )

    data = _normalize_callback_message(cast(Dict[str, Any], body), callback_type="scan")
    scheduler = _get_scheduler_target(request)
    scheduler.dispatch_callback(data, callback_type="scan")
    return {"status": "ok"}


@router.post("/upload/audio")
async def handle_audio(request: Request):
    raw_pcm = await request.body()
    scheduler = _get_scheduler_target(request)
    data = _normalize_callback_message(
        {"type": "audio", "payload": raw_pcm}, callback_type="audio"
    )
    scheduler.dispatch_callback(
        data,
        callback_type="audio",
    )
    return {"status": "received"}
