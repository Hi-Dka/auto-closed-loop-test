from typing import Any, Dict, Optional, Protocol

from fastapi import APIRouter, HTTPException, File, UploadFile

from app.odr_executor.network.data_model import (
    CommandRequest,
    DabMuxUpdateRequest,
    DabModUpdateRequest,
    HackRFUpdateRequest,
    AudioEncUpdateRequest,
    PadEncUpdateRequest,
    SocatUpdateRequest,
    FFmpegUpdateRequest,
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
    def launch_all_active_sessions(self) -> None: ...
    def launch_ffmpeg_guard(self, port: int, command_data: dict) -> None: ...
    def stop_ffmpeg_guards(self, port: int) -> bool: ...


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


@router.post("/update", deprecated=True)
async def update(payload: CommandRequest):
    return _dispatch_update(target=payload.target, data=payload.data, port=payload.port)


@router.post("/socat/{port}/update", deprecated=True)
async def update_socat(port: int, payload: SocatUpdateRequest):
    return _dispatch_update(target="socat", data=payload.data, port=port)


@router.post("/launchffmpeg/{port}")
async def start_ffmpeg(port: int, file: UploadFile = File(...)):
    file_content = await file.read()
    dynamic_data = {
        "port": port,
        "file_bytes": file_content,
        "filename": file.filename,
        "content_type": file.content_type,
    }

    session_manager = _get_session_manager_response()
    if session_manager.launch_ffmpeg_guard(port=port, command_data=dynamic_data):
        return {"status": "success", "port": port}

    return HTTPException(
        status_code=500,
        detail=f"Failed to launch FFmpeg guard for port: {port}",
    )


@router.post("/stopffmpeg/{port}")
async def stop_ffmpeg(port: int):
    session_manager = _get_session_manager_response()
    if session_manager.stop_ffmpeg_guards(port):
        return {"status": "success", "port": port}

    return HTTPException(
        status_code=404,
        detail=f"No FFmpeg guard found with port: {port}",
    )


@router.post("/dabmux/update")
async def update_dabmux(file: UploadFile = File(...)):

    file_content = await file.read()
    dynamic_data = {
        "file_bytes": file_content,
        "filename": file.filename,
        "content_type": file.content_type,
    }

    return _dispatch_update(target="dabmux", data=dynamic_data)


@router.post("/dabmod/update")
async def update_dabmod(payload: DabModUpdateRequest):
    return _dispatch_update(target="dabmod", data=payload.model_dump())


@router.post("/hackrf/update")
async def update_hackrf(payload: HackRFUpdateRequest):
    return _dispatch_update(target="hackrf", data=payload.model_dump())


@router.post("/audioenc/{port}/update")
async def update_audioenc(port: int, payload: AudioEncUpdateRequest):
    if payload.bitrate % 8 != 0:
        raise HTTPException(status_code=400, detail="bitrate must be a multiple of 8")
    return _dispatch_update(target="audioenc", data=payload.model_dump(), port=port)


@router.post("/padenc/{port}/update")
async def update_padenc(port: int, payload: PadEncUpdateRequest):
    data = payload.model_dump()
    if data.get("dir") is None:
        data["dir"] = f"/media/padenc/sls-PadEnc-{port}"
    if data.get("dls") is None:
        data["dls"] = f"/media/padenc/dls-PadEnc-{port}/dls.txt"
    return _dispatch_update(target="padenc", data=data, port=port)


@router.post("/launchactive/{port}")
async def launch_active(port: int):
    _get_session_manager_response().launch_active_session(socat_port=port)
    return {"status": "success", "port": port}


@router.post("/stopactive/{port}")
async def stop_active(port: int):
    _get_session_manager_response().stop_active_session(socat_port=port)
    return {"status": "success", "port": port}


@router.post("/launchstable")
async def launch_stable():
    _get_session_manager_response().launch_stable_session()
    return {"status": "success"}


@router.post("/stopstable")
async def stop_stable():
    _get_session_manager_response().stop_stable_session()
    return {"status": "success"}


@router.post("/stopall")
async def stop_all():
    _get_session_manager_response().stop_stable_session()
    _get_session_manager_response().stop_all_active_sessions()
    return {"status": "success"}


@router.post("/launchall")
async def launch_all():
    _get_session_manager_response().launch_stable_session()
    _get_session_manager_response().launch_all_active_sessions()
    return {"status": "success"}
