from typing import Annotated, Any, Dict, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field


class BaseRequest(BaseModel):
    request_id: Optional[str] = Field(default=None, description="请求唯一 ID")
    group_id: Optional[str] = Field(default=None, description="请求分组 ID")
    callback_type: Optional[str] = Field(default=None, description="回调类型标识")
    timestamp: Optional[float] = Field(
        default=None, description="请求时间戳（Unix seconds）"
    )


class ProcessSelector(BaseModel):
    port: int = Field(..., description="目标端口，例如 5656")


class EmptyConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")


class FileTransferConfig(BaseModel):
    file_base64: str = Field(
        ...,
        min_length=1,
        description="文件内容（Base64 编码字符串）",
        examples=["UklGRigAAABXQVZFZm10IBAAAAABAAEA..."],
    )
    filename: str = Field(default="uploaded.bin", description="文件名")
    content_type: str = Field(
        default="application/octet-stream", description="文件 MIME 类型"
    )


class DabModConfig(BaseModel):
    mode: int = Field(default=1, description="调制模式")
    format: str = Field(default="s8", description="输出采样格式")
    gain: float = Field(default=0.8, description="输出增益")
    gainmode: str = Field(default="max", description="增益模式")
    rate: int = Field(default=2048000, description="输出采样率（Hz）")


class HackRFConfig(BaseModel):
    freq_hz: int = Field(default=227360000, description="发射频率（Hz）")
    sample_rate_hz: int = Field(default=2048000, description="采样率（Hz）")
    amp_enable: int = Field(default=1, description="是否启用放大器（0/1）")
    gain_db_tx: int = Field(default=40, description="发射增益（dB）")


class AudioEncConfig(BaseModel):
    output_port: int = Field(default=9000, description="音频输出 UDP 端口")
    bitrate: int = Field(default=64, multiple_of=8, description="编码码率（kbps）")
    sample_rate: Literal[24000, 32000, 48000] = Field(
        default=48000, description="音频采样率（Hz）"
    )
    channels: int = Field(default=2, description="声道数")
    format: str = Field(default="raw", description="音频格式")
    audio_gain: int = Field(default=0, description="音频增益")
    pad: int = Field(default=58, description="PAD 长度")


class PadEncConfig(BaseModel):
    sleep: int = Field(default=10, description="轮询间隔（秒）")
    dir: Optional[str] = Field(default=None, description="SLS 目录路径")
    dls: Optional[str] = Field(default=None, description="DLS 文本文件路径")


class ActiveApplyConfig(BaseModel):
    audioenc: Optional[AudioEncConfig] = Field(
        default=None, description="audioenc 子进程参数"
    )
    padenc: Optional[PadEncConfig] = Field(
        default=None, description="padenc 子进程参数"
    )
    socat: Optional[Dict[str, Any]] = Field(
        default=None, description="socat 子进程参数（对象）"
    )


class ApplyStableRequest(BaseRequest):
    process: Literal["stable"] = Field(description="目标进程类型")
    config: EmptyConfig = Field(default_factory=EmptyConfig, description="必须为空对象")


class ApplyAllRequest(BaseRequest):
    process: Literal["all"] = Field(description="目标进程类型")
    config: EmptyConfig = Field(default_factory=EmptyConfig, description="必须为空对象")


class ApplyActiveRequest(BaseRequest):
    process: Literal["active"] = Field(description="目标进程类型")
    selector: ProcessSelector = Field(description="active 会话定位条件")
    config: ActiveApplyConfig = Field(
        default_factory=ActiveApplyConfig, description="active 会话参数"
    )


class ApplyDabMuxRequest(BaseRequest):
    process: Literal["dabmux"] = Field(description="目标进程类型")
    config: FileTransferConfig = Field(description="dabmux 文件参数")


class ApplyDabModRequest(BaseRequest):
    process: Literal["dabmod"] = Field(description="目标进程类型")
    config: DabModConfig = Field(
        default_factory=DabModConfig, description="dabmod 参数"
    )


class ApplyHackRFRequest(BaseRequest):
    process: Literal["hackrf"] = Field(description="目标进程类型")
    config: HackRFConfig = Field(
        default_factory=HackRFConfig, description="hackrf 参数"
    )


class ApplyAudioEncRequest(BaseRequest):
    process: Literal["audioenc"] = Field(description="目标进程类型")
    selector: ProcessSelector = Field(description="audioenc 实例定位条件")
    config: AudioEncConfig = Field(
        default_factory=AudioEncConfig, description="audioenc 参数"
    )


class ApplyPadEncRequest(BaseRequest):
    process: Literal["padenc"] = Field(description="目标进程类型")
    selector: ProcessSelector = Field(description="padenc 实例定位条件")
    config: PadEncConfig = Field(
        default_factory=PadEncConfig, description="padenc 参数"
    )


class ApplySocatRequest(BaseRequest):
    process: Literal["socat"] = Field(description="目标进程类型")
    selector: ProcessSelector = Field(description="socat 实例定位条件")
    config: Dict[str, Any] = Field(default_factory=dict, description="socat 参数对象")


class ApplyFFmpegRequest(BaseRequest):
    process: Literal["ffmpeg"] = Field(description="目标进程类型")
    selector: ProcessSelector = Field(description="ffmpeg 实例定位条件")
    config: FileTransferConfig = Field(description="ffmpeg 文件参数")


ProcessApplyRequest = Annotated[
    Union[
        ApplyStableRequest,
        ApplyAllRequest,
        ApplyActiveRequest,
        ApplyDabMuxRequest,
        ApplyDabModRequest,
        ApplyHackRFRequest,
        ApplyAudioEncRequest,
        ApplyPadEncRequest,
        ApplySocatRequest,
        ApplyFFmpegRequest,
    ],
    Field(discriminator="process"),
]


class StopStableRequest(BaseRequest):
    process: Literal["stable"] = Field(description="停止 stable 会话")


class StopAllRequest(BaseRequest):
    process: Literal["all"] = Field(description="停止全部会话")


class StopActiveRequest(BaseRequest):
    process: Literal["active"] = Field(description="停止 active 会话")
    selector: ProcessSelector = Field(description="active 会话定位条件")


class StopFFmpegRequest(BaseRequest):
    process: Literal["ffmpeg"] = Field(description="停止 ffmpeg guard")
    selector: ProcessSelector = Field(description="ffmpeg 实例定位条件")


ProcessStopRequest = Annotated[
    Union[StopStableRequest, StopAllRequest, StopActiveRequest, StopFFmpegRequest],
    Field(discriminator="process"),
]
