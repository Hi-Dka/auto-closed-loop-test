import io
import shutil
import zipfile
from typing import Any, Dict, Protocol
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from app.odr_executor.network.data_model import BaseRequest

router = APIRouter(prefix="/command/v1", tags=["Odr-Tools Control"])

STOP_ALL_TIMEOUT_SECONDS = 20.0
UPLOAD_ROOT = Path("/tmp/odr_executor/uploads")


class SessionManagerObj(Protocol):

    def start_stable_session(self) -> None: ...
    def configure_stable_session(
        self,
        dabmux_data: dict | None = None,
        dabmod_data: dict | None = None,
        hackrf_data: dict | None = None,
    ) -> None: ...

    def stop_stable_session(self, wait: bool = True, timeout: float = 8.0) -> None: ...
    def start_active_session(self, socat_port: int) -> None: ...
    def configure_active_session(
        self,
        socat_port: int,
        audioenc_data: dict | None = None,
        padenc_data: dict | None = None,
        socat_data: dict | None = None,
    ) -> None: ...

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
    def configure_ffmpeg_guard(self, port: int, command_data: dict) -> bool: ...
    def start_ffmpeg_guard(self, port: int) -> bool: ...

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


def _handle_stop_failure(exc: RuntimeError) -> None:
    raise HTTPException(status_code=504, detail=str(exc)) from exc


def _safe_filename(filename: str | None) -> str:
    candidate = Path(filename or "uploaded.bin").name
    return candidate or "uploaded.bin"


def _clear_directory(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)


def _ensure_within_directory(base_dir: Path, target_path: Path) -> None:
    base_resolved = base_dir.resolve()
    target_resolved = target_path.resolve()
    try:
        target_resolved.relative_to(base_resolved)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail="Uploaded archive contains an invalid path.",
        ) from exc


async def _read_upload_bytes(upload: UploadFile) -> bytes:
    return await upload.read()


async def _save_single_upload(upload: UploadFile, destination_dir: Path) -> Path:
    destination_dir.mkdir(parents=True, exist_ok=True)
    file_path = destination_dir / _safe_filename(upload.filename)
    file_path.write_bytes(await _read_upload_bytes(upload))
    return file_path


async def _extract_zip_upload(upload: UploadFile, destination_dir: Path) -> None:
    archive_bytes = await _read_upload_bytes(upload)
    with zipfile.ZipFile(io.BytesIO(archive_bytes)) as archive:
        for member in archive.infolist():
            if member.is_dir():
                continue

            target_path = destination_dir / member.filename
            _ensure_within_directory(destination_dir, target_path)
            target_path.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(member) as source, open(target_path, "wb") as target:
                shutil.copyfileobj(source, target)


def _padenc_runtime_paths(port: int) -> tuple[Path, Path]:
    session_root = UPLOAD_ROOT / "padenc" / str(port)
    slides_dir = session_root / "slides"
    dls_path = session_root / "dls.txt"
    return slides_dir, dls_path


def _stable_dabmod_data(
    dabmod_mode: int,
    dabmod_format: str,
    dabmod_gain: float,
    dabmod_gainmode: str,
    dabmod_rate: int,
) -> dict[str, Any]:
    return {
        "mode": dabmod_mode,
        "format": dabmod_format,
        "gain": dabmod_gain,
        "gainmode": dabmod_gainmode,
        "rate": dabmod_rate,
    }


def _stable_hackrf_data(
    hackrf_freq_hz: int,
    hackrf_sample_rate_hz: int,
    hackrf_amp_enable: int,
    hackrf_gain_db_tx: int,
) -> dict[str, Any]:
    return {
        "freq_hz": hackrf_freq_hz,
        "sample_rate_hz": hackrf_sample_rate_hz,
        "amp_enable": hackrf_amp_enable,
        "gain_db_tx": hackrf_gain_db_tx,
    }


def _audioenc_data(
    output_port: int,
    bitrate: int,
    sample_rate: int,
    channels: int,
    audio_format: str,
    audio_gain: int,
    pad: int,
) -> dict[str, Any]:
    return {
        "output_port": output_port,
        "bitrate": bitrate,
        "sample_rate": sample_rate,
        "channels": channels,
        "format": audio_format,
        "audio_gain": audio_gain,
        "pad": pad,
    }


@router.post("/stable/configure")
async def configure_stable(
    request_id: str = Form(...),
    group_id: str = Form(...),
    callback_type: str = Form(...),
    timestamp: float = Form(...),
    dabmod_mode: int = Form(1),
    dabmod_format: str = Form("s8"),
    dabmod_gain: float = Form(0.8),
    dabmod_gainmode: str = Form("max"),
    dabmod_rate: int = Form(2048000),
    hackrf_freq_hz: int = Form(227360000),
    hackrf_sample_rate_hz: int = Form(2048000),
    hackrf_amp_enable: int = Form(1),
    hackrf_gain_db_tx: int = Form(40),
    dabmux_file: UploadFile | None = File(default=None),
):
    payload_data = BaseRequest(
        request_id=request_id,
        group_id=group_id,
        callback_type=callback_type,
        timestamp=timestamp,
    ).model_dump()

    dabmux_data: dict[str, Any] | None = None
    if dabmux_file is not None:
        dabmux_data = {
            "file_bytes": await _read_upload_bytes(dabmux_file),
            "filename": _safe_filename(dabmux_file.filename),
            "content_type": dabmux_file.content_type or "application/octet-stream",
        }

    _get_session_manager_response().configure_stable_session(
        dabmux_data=dabmux_data,
        dabmod_data=_stable_dabmod_data(
            dabmod_mode=dabmod_mode,
            dabmod_format=dabmod_format,
            dabmod_gain=dabmod_gain,
            dabmod_gainmode=dabmod_gainmode,
            dabmod_rate=dabmod_rate,
        ),
        hackrf_data=_stable_hackrf_data(
            hackrf_freq_hz=hackrf_freq_hz,
            hackrf_sample_rate_hz=hackrf_sample_rate_hz,
            hackrf_amp_enable=hackrf_amp_enable,
            hackrf_gain_db_tx=hackrf_gain_db_tx,
        ),
    )

    return {**payload_data, "status": "success"}


@router.post("/stable/start")
async def start_stable(
    request_id: str = Form(...),
    group_id: str = Form(...),
    callback_type: str = Form(...),
    timestamp: float = Form(...),
):
    payload_data = BaseRequest(
        request_id=request_id,
        group_id=group_id,
        callback_type=callback_type,
        timestamp=timestamp,
    ).model_dump()

    _get_session_manager_response().start_stable_session()
    return {**payload_data, "status": "success"}


@router.post("/active/configure")
async def configure_active(
    request_id: str = Form(...),
    group_id: str = Form(...),
    callback_type: str = Form(...),
    timestamp: float = Form(...),
    port: int = Form(...),
    output_port: int = Form(9000),
    bitrate: int = Form(64),
    sample_rate: int = Form(48000),
    channels: int = Form(2),
    audio_format: str = Form("raw", alias="format"),
    audio_gain: int = Form(0),
    pad: int = Form(58),
    padenc_sleep: int = Form(10),
    padenc_image: UploadFile | None = File(
        default=None,
        description="可选，单图片文件上传（在 docs 中请使用文件选择器）",
    ),
    padenc_archive: UploadFile | None = File(
        default=None,
        description="可选，zip 压缩包上传（目录上传推荐使用此字段）",
    ),
):
    payload_data = BaseRequest(
        request_id=request_id,
        group_id=group_id,
        callback_type=callback_type,
        timestamp=timestamp,
    ).model_dump()

    padenc_data: dict[str, Any] = {"sleep": padenc_sleep}

    if padenc_image is not None or padenc_archive is not None:
        slides_dir, dls_path = _padenc_runtime_paths(port)
        _clear_directory(slides_dir)

        if padenc_archive is not None:
            await _extract_zip_upload(padenc_archive, slides_dir)

        if padenc_image is not None:
            await _save_single_upload(padenc_image, slides_dir)

        dls_path.parent.mkdir(parents=True, exist_ok=True)
        dls_path.write_text(f"PadEnc-{port}", encoding="utf-8")
        padenc_data["dir"] = str(slides_dir)
        padenc_data["dls"] = str(dls_path)

    _get_session_manager_response().configure_active_session(
        socat_port=port,
        audioenc_data=_audioenc_data(
            output_port=output_port,
            bitrate=bitrate,
            sample_rate=sample_rate,
            channels=channels,
            audio_format=audio_format,
            audio_gain=audio_gain,
            pad=pad,
        ),
        padenc_data=padenc_data,
    )

    return {**payload_data, "status": "success", "port": port}


@router.post("/active/start")
async def start_active(
    request_id: str = Form(...),
    group_id: str = Form(...),
    callback_type: str = Form(...),
    timestamp: float = Form(...),
    port: int = Form(...),
):
    payload_data = BaseRequest(
        request_id=request_id,
        group_id=group_id,
        callback_type=callback_type,
        timestamp=timestamp,
    ).model_dump()

    _get_session_manager_response().start_active_session(socat_port=port)
    return {**payload_data, "status": "success", "port": port}


@router.post("/ffmpeg/configure")
async def configure_ffmpeg(
    request_id: str = Form(...),
    group_id: str = Form(...),
    callback_type: str = Form(...),
    timestamp: float = Form(...),
    port: int = Form(...),
    file: UploadFile = File(...),
):
    payload_data = BaseRequest(
        request_id=request_id,
        group_id=group_id,
        callback_type=callback_type,
        timestamp=timestamp,
    ).model_dump()

    command_data = {
        "port": port,
        "file_bytes": await _read_upload_bytes(file),
        "filename": _safe_filename(file.filename),
        "content_type": file.content_type or "application/octet-stream",
    }
    _get_session_manager_response().configure_ffmpeg_guard(
        port=port, command_data=command_data
    )
    return {**payload_data, "status": "success", "port": port}


@router.post("/ffmpeg/start")
async def start_ffmpeg(
    request_id: str = Form(...),
    group_id: str = Form(...),
    callback_type: str = Form(...),
    timestamp: float = Form(...),
    port: int = Form(...),
):
    payload_data = BaseRequest(
        request_id=request_id,
        group_id=group_id,
        callback_type=callback_type,
        timestamp=timestamp,
    ).model_dump()

    _get_session_manager_response().start_ffmpeg_guard(port=port)
    return {**payload_data, "status": "success", "port": port}


@router.post("/stable/stop")
async def stop_stable(
    request_id: str = Form(...),
    group_id: str = Form(...),
    callback_type: str = Form(...),
    timestamp: float = Form(...),
):
    payload_data = BaseRequest(
        request_id=request_id,
        group_id=group_id,
        callback_type=callback_type,
        timestamp=timestamp,
    ).model_dump()

    try:
        _get_session_manager_response().stop_stable_session(
            timeout=STOP_ALL_TIMEOUT_SECONDS
        )
    except RuntimeError as exc:
        _handle_stop_failure(exc)
    return {**payload_data, "status": "success"}


@router.post("/active/stop")
async def stop_active(
    request_id: str = Form(...),
    group_id: str = Form(...),
    callback_type: str = Form(...),
    timestamp: float = Form(...),
    port: int = Form(...),
):
    payload_data = BaseRequest(
        request_id=request_id,
        group_id=group_id,
        callback_type=callback_type,
        timestamp=timestamp,
    ).model_dump()

    try:
        _get_session_manager_response().stop_active_session(
            socat_port=port,
            timeout=STOP_ALL_TIMEOUT_SECONDS,
        )
    except RuntimeError as exc:
        _handle_stop_failure(exc)
    return {**payload_data, "status": "success", "port": port}


@router.post("/ffmpeg/stop")
async def stop_ffmpeg(
    request_id: str = Form(...),
    group_id: str = Form(...),
    callback_type: str = Form(...),
    timestamp: float = Form(...),
    port: int = Form(...),
):
    payload_data = BaseRequest(
        request_id=request_id,
        group_id=group_id,
        callback_type=callback_type,
        timestamp=timestamp,
    ).model_dump()

    if _get_session_manager_response().stop_ffmpeg_guards(port):
        return {**payload_data, "status": "success", "port": port}
    raise HTTPException(
        status_code=404,
        detail=f"No FFmpeg guard found with port: {port}",
    )


@router.post("/all/stop")
async def stop_all(
    request_id: str = Form(...),
    group_id: str = Form(...),
    callback_type: str = Form(...),
    timestamp: float = Form(...),
):
    payload_data = BaseRequest(
        request_id=request_id,
        group_id=group_id,
        callback_type=callback_type,
        timestamp=timestamp,
    ).model_dump()

    manager = _get_session_manager_response()
    try:
        manager.stop_all_ffmpeg_guards(timeout=STOP_ALL_TIMEOUT_SECONDS)
        manager.stop_stable_session(timeout=STOP_ALL_TIMEOUT_SECONDS)
        manager.stop_all_active_sessions(timeout=STOP_ALL_TIMEOUT_SECONDS)
    except RuntimeError as exc:
        _handle_stop_failure(exc)
    return {**payload_data, "status": "success"}


@router.get("/status")
async def get_status():
    return {"status": "success", "data": _get_session_manager_response().snapshot()}
