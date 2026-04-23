import base64
import binascii
from typing import Any, Dict, Optional, Protocol

from fastapi import APIRouter, Body, HTTPException
from fastapi.openapi.models import Example

from app.odr_executor.network.data_model import (
    ApplyActiveRequest,
    ApplyAllRequest,
    ApplyAudioEncRequest,
    ApplyDabModRequest,
    ApplyDabMuxRequest,
    ApplyFFmpegRequest,
    ApplyHackRFRequest,
    ApplyPadEncRequest,
    ApplySocatRequest,
    ApplyStableRequest,
    ProcessApplyRequest,
    ProcessStopRequest,
    BaseRequest,
    StopActiveRequest,
    StopAllRequest,
    StopFFmpegRequest,
    StopStableRequest,
)

router = APIRouter(prefix="/command/v1", tags=["Odr-Tools Control"])


class SessionManagerObj(Protocol):
    def dispatch(
        self, target: str, data: Dict[str, Any], port: Optional[int] = None
    ) -> None: ...

    def launch_stable_session(self) -> None: ...
    def stop_stable_session(self, wait: bool = True, timeout: float = 8.0) -> None: ...
    def launch_active_session(self, socat_port: int) -> None: ...
    def stop_active_session(
        self,
        socat_port: int,
        release_port: bool = True,
        wait: bool = True,
        timeout: float = 8.0,
    ) -> None: ...
    def stop_all_active_sessions(
        self, wait: bool = True, timeout: float = 8.0
    ) -> None: ...
    def apply_active_session(
        self,
        socat_port: int,
        audioenc_data: dict | None = None,
        padenc_data: dict | None = None,
        socat_data: dict | None = None,
    ) -> None: ...
    def apply_all_active_sessions(self) -> None: ...
    def has_active_session(self, port: int) -> bool: ...
    def has_ffmpeg_guard(self, port: int) -> bool: ...

    def launch_ffmpeg_guard(self, port: int, command_data: dict) -> bool: ...

    def stop_ffmpeg_guards(self, port: int) -> bool: ...
    def stop_all_ffmpeg_guards(self, timeout: float = 8.0) -> bool: ...
    def snapshot(self) -> dict[str, Any]: ...


_response_state: Dict[str, SessionManagerObj | None] = {"manager": None}


def set_session_manager_obj(response: SessionManagerObj):
    _response_state["manager"] = response


def clear_session_manager_obj():
    _response_state["manager"] = None


def _get_session_manager_response() -> SessionManagerObj:
    target = _response_state["manager"]
    if target is None:
        raise HTTPException(status_code=500, detail="Session manager not configured")
    return target


def _dispatch_update(target: str, data: Dict[str, Any], port: Optional[int] = None):
    try:
        _get_session_manager_response().dispatch(target=target, data=data, port=port)
        return {"status": "success"}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Internal Server Error: {str(e)}"
        ) from e


def _payload_meta(payload: BaseRequest) -> dict[str, Any]:
    return BaseRequest(**payload.model_dump()).model_dump()


def _decode_file_data(config: dict[str, Any], process: str) -> tuple[bytes, str, str]:
    file_base64 = config.get("file_base64")
    if not file_base64:
        raise HTTPException(
            status_code=400,
            detail=f"config.file_base64 is required for process '{process}'",
        )

    try:
        file_bytes = base64.b64decode(file_base64, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise HTTPException(
            status_code=400, detail="Invalid config.file_base64"
        ) from exc

    filename = str(config.get("filename") or "uploaded.bin")
    content_type = str(config.get("content_type") or "application/octet-stream")
    return file_bytes, filename, content_type


APPLY_EXAMPLES = {
    "stable": {
        "summary": "启动 stable 会话",
        "value": {
            "process": "stable",
            "request_id": "req-stable-001",
            "group_id": "group-a",
            "callback_type": "start-odr",
            "timestamp": 1710000000.0,
            "config": {},
        },
    },
    "active_with_audioenc": {
        "summary": "按端口 apply active，并更新 audioenc",
        "value": {
            "process": "active",
            "selector": {"port": 5657},
            "config": {"audioenc": {"output_port": 9002, "bitrate": 64}},
        },
    },
    "dabmod": {
        "summary": "更新 dabmod 参数",
        "value": {
            "process": "dabmod",
            "config": {
                "mode": 1,
                "format": "s8",
                "gain": 0.8,
                "gainmode": "max",
                "rate": 2048000,
            },
        },
    },
    "ffmpeg": {
        "summary": "按端口 apply ffmpeg 文件输入",
        "value": {
            "process": "ffmpeg",
            "selector": {"port": 5656},
            "config": {
                "file_base64": "UklGRigAAABXQVZFZm10IBAAAAABAAEAESsAACJWAAACABAAZGF0YQAAAAA=",
                "filename": "lanlianhua.wav",
                "content_type": "audio/wav",
            },
        },
    },
}


STOP_EXAMPLES = {
    "stop_stable": {
        "summary": "停止 stable 会话",
        "value": {"process": "stable"},
    },
    "stop_active": {
        "summary": "按端口停止 active 会话",
        "value": {"process": "active", "selector": {"port": 5657}},
    },
    "stop_ffmpeg": {
        "summary": "按端口停止 ffmpeg guard",
        "value": {"process": "ffmpeg", "selector": {"port": 5656}},
    },
    "stop_all": {
        "summary": "停止所有会话",
        "value": {"process": "all"},
    },
}


COMMON_REQUEST_META = {
    "request_id": "req-odr-001",
    "group_id": "group-odr",
    "callback_type": "start-odr",
    "timestamp": 1710000000.0,
}


def _with_meta(
    body: dict[str, Any], *, callback_type: str = "start-odr"
) -> dict[str, Any]:
    meta = dict(COMMON_REQUEST_META)
    meta["callback_type"] = callback_type
    return {**meta, **body}


APPLY_OPENAPI_EXAMPLES: dict[str, Example] = {
    key: Example(summary=item["summary"], value=_with_meta(item["value"]))
    for key, item in APPLY_EXAMPLES.items()
}

STOP_OPENAPI_EXAMPLES: dict[str, Example] = {
    key: Example(
        summary=item["summary"],
        value=_with_meta(item["value"], callback_type="stop-odr"),
    )
    for key, item in STOP_EXAMPLES.items()
}


@router.post("/apply")
async def apply_process(
    payload: ProcessApplyRequest = Body(..., openapi_examples=APPLY_OPENAPI_EXAMPLES)
):
    payload_data = _payload_meta(payload)

    session_manager = _get_session_manager_response()

    if isinstance(payload, ApplyStableRequest):
        session_manager.launch_stable_session()
        return {**payload_data, "status": "success"}

    if isinstance(payload, ApplyAllRequest):
        session_manager.launch_stable_session()
        session_manager.apply_all_active_sessions()
        return {**payload_data, "status": "success"}

    if isinstance(payload, ApplyActiveRequest):
        port = int(payload.selector.port)
        active_config = payload.config.model_dump(exclude_none=True)
        audioenc_data = active_config.get("audioenc")
        padenc_data = active_config.get("padenc")
        socat_data = active_config.get("socat")

        if isinstance(padenc_data, dict):
            padenc_data = padenc_data.copy()
            if padenc_data.get("dir") is None:
                padenc_data["dir"] = f"/media/padenc/sls-PadEnc-{port}"
            if padenc_data.get("dls") is None:
                padenc_data["dls"] = f"/media/padenc/dls-PadEnc-{port}/dls.txt"

        if any(item is not None for item in (audioenc_data, padenc_data, socat_data)):
            session_manager.apply_active_session(
                socat_port=port,
                audioenc_data=(
                    audioenc_data if isinstance(audioenc_data, dict) else None
                ),
                padenc_data=padenc_data if isinstance(padenc_data, dict) else None,
                socat_data=socat_data if isinstance(socat_data, dict) else None,
            )
        else:
            if session_manager.has_active_session(port):
                session_manager.stop_active_session(socat_port=port)
            session_manager.launch_active_session(socat_port=port)

        return {**payload_data, "status": "success", "port": port}

    if isinstance(payload, ApplyFFmpegRequest):
        port = int(payload.selector.port)
        config = payload.config.model_dump(exclude_none=True)
        file_bytes, filename, content_type = _decode_file_data(config, payload.process)
        dynamic_data = {
            "port": port,
            "file_bytes": file_bytes,
            "filename": filename,
            "content_type": content_type,
        }

        if session_manager.has_ffmpeg_guard(port):
            _dispatch_update(target="ffmpeg", data=dynamic_data, port=port)
            return {**payload_data, "status": "success", "port": port}

        if session_manager.launch_ffmpeg_guard(port=port, command_data=dynamic_data):
            return {**payload_data, "status": "success", "port": port}

        raise HTTPException(
            status_code=500,
            detail=f"Failed to launch FFmpeg guard for port: {port}",
        )

    if isinstance(payload, ApplyDabMuxRequest):
        config = payload.config.model_dump(exclude_none=True)
        file_bytes, filename, content_type = _decode_file_data(config, payload.process)
        dynamic_data = {
            "file_bytes": file_bytes,
            "filename": filename,
            "content_type": content_type,
        }
        _dispatch_update(target="dabmux", data=dynamic_data)
        return {**payload_data, "status": "success"}

    if isinstance(payload, ApplyDabModRequest):
        _dispatch_update(
            target="dabmod", data=payload.config.model_dump(exclude_none=True)
        )
        return {**payload_data, "status": "success"}

    if isinstance(payload, ApplyHackRFRequest):
        _dispatch_update(
            target="hackrf", data=payload.config.model_dump(exclude_none=True)
        )
        return {**payload_data, "status": "success"}

    if isinstance(payload, ApplyAudioEncRequest):
        port = int(payload.selector.port)
        data = payload.config.model_dump(exclude_none=True)
        _dispatch_update(target="audioenc", data=data, port=port)
        return {**payload_data, "status": "success", "port": port}

    if isinstance(payload, ApplyPadEncRequest):
        port = int(payload.selector.port)
        data = payload.config.model_dump(exclude_none=True)
        if data.get("dir") is None:
            data["dir"] = f"/media/padenc/sls-PadEnc-{port}"
        if data.get("dls") is None:
            data["dls"] = f"/media/padenc/dls-PadEnc-{port}/dls.txt"

        _dispatch_update(target="padenc", data=data, port=port)
        return {**payload_data, "status": "success", "port": port}

    if isinstance(payload, ApplySocatRequest):
        port = int(payload.selector.port)
        _dispatch_update(target="socat", data=payload.config, port=port)
        return {**payload_data, "status": "success", "port": port}

    raise HTTPException(status_code=400, detail="Unsupported apply payload")


@router.post("/stop")
async def stop_process(
    payload: ProcessStopRequest = Body(..., openapi_examples=STOP_OPENAPI_EXAMPLES)
):
    payload_data = _payload_meta(payload)

    session_manager = _get_session_manager_response()

    if isinstance(payload, StopAllRequest):
        session_manager.stop_all_ffmpeg_guards(timeout=8.0)
        session_manager.stop_stable_session()
        session_manager.stop_all_active_sessions()
        return {**payload_data, "status": "success"}

    if isinstance(payload, StopStableRequest):
        session_manager.stop_stable_session()
        return {**payload_data, "status": "success"}

    if isinstance(payload, StopActiveRequest):
        port = int(payload.selector.port)
        session_manager.stop_active_session(socat_port=port)
        return {**payload_data, "status": "success", "port": port}

    if isinstance(payload, StopFFmpegRequest):
        port = int(payload.selector.port)
        if session_manager.stop_ffmpeg_guards(port):
            return {**payload_data, "status": "success", "port": port}
        raise HTTPException(
            status_code=404,
            detail=f"No FFmpeg guard found with port: {port}",
        )

    raise HTTPException(
        status_code=400,
        detail="Unsupported stop payload",
    )


@router.post("/stopall")
async def stop_all(payload: Optional[BaseRequest] = None):
    payload_data = payload.model_dump() if payload else {}
    _get_session_manager_response().stop_all_ffmpeg_guards(timeout=8.0)
    _get_session_manager_response().stop_stable_session()
    _get_session_manager_response().stop_all_active_sessions()
    return {**BaseRequest(**payload_data).model_dump(), "status": "success"}


@router.get("/status")
async def get_status():
    return {"status": "success", "data": _get_session_manager_response().snapshot()}
