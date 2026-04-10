from typing import Any, Dict, Literal, Optional

from pydantic import BaseModel


class CommandRequest(BaseModel):
    target: str
    data: Dict[str, Any] = {}
    port: Optional[int] = None


class DabMuxUpdateRequest(BaseModel):
    data: Dict[str, Any] = {}


class FFmpegUpdateRequest(BaseModel):
    id: str
    content: str


class DabModUpdateRequest(BaseModel):
    mode: int = 1
    format: str = "s8"
    gain: float = 0.8
    gainmode: str = "max"
    rate: int = 2048000


class HackRFUpdateRequest(BaseModel):
    freq_hz: int = 227360000
    sample_rate_hz: int = 2048000
    amp_enable: int = 1
    gain_db_tx: int = 40


class AudioEncUpdateRequest(BaseModel):
    output_port: int = 9000
    bitrate: int = 64
    sample_rate: Literal[24000, 32000, 48000] = 48000
    channels: int = 2
    format: str = "raw"
    audio_gain: int = 0
    pad: int = 58


class PadEncUpdateRequest(BaseModel):
    sleep: int = 10
    dir: Optional[str] = None
    dls: Optional[str] = None


class SocatUpdateRequest(BaseModel):
    data: Dict[str, Any] = {}
