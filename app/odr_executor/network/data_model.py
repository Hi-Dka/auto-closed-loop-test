from typing import Any, Dict, Literal, Optional

from pydantic import BaseModel


class BaseRequest(BaseModel):
    request_id: Optional[str] = None
    group_id: Optional[str] = None
    callback_type: Optional[str] = None
    timestamp: Optional[float] = None


class CommandRequest(BaseRequest):
    target: str
    data: Dict[str, Any] = {}
    port: Optional[int] = None


class DabMuxUpdateRequest(BaseRequest):
    data: Dict[str, Any] = {}


class DabModUpdateRequest(BaseRequest):
    mode: Optional[int] = 1
    format: Optional[str] = "s8"
    gain: Optional[float] = 0.8
    gainmode: Optional[str] = "max"
    rate: Optional[int] = 2048000


class HackRFUpdateRequest(BaseRequest):
    freq_hz: Optional[int] = 227360000
    sample_rate_hz: Optional[int] = 2048000
    amp_enable: Optional[int] = 1
    gain_db_tx: Optional[int] = 40


class AudioEncUpdateRequest(BaseRequest):
    output_port: Optional[int] = 9000
    bitrate: Optional[int] = 64
    sample_rate: Optional[Literal[24000, 32000, 48000]] = 48000
    channels: Optional[int] = 2
    format: Optional[str] = "raw"
    audio_gain: Optional[int] = 0
    pad: Optional[int] = 58


class PadEncUpdateRequest(BaseRequest):
    sleep: Optional[int] = 10
    dir: Optional[str] = None
    dls: Optional[str] = None


class SocatUpdateRequest(BaseRequest):
    data: Dict[str, Any] = {}
