# ODR Executor 使用说明（当前实现）

本文档对应当前 `app/odr_executor/network/router.py` 的实际接口：

- **全部控制接口统一为表单 (`multipart/form-data`)**
- 工作流为 **configure → start → stop**
- `dabmux`、`padenc` 作为会话子组件配置，**不提供独立 start 接口**

---

## 会话模型

### Stable Session（固定链路）

包含：

- `dabmux`
- `dabmod`
- `hackrf`

启动时由 `stable/start` 统一拉起。

### Active Session（按端口）

每个 `port` 对应一个会话，包含：

- `audioenc`
- `padenc`
- `socat`

先按端口 `active/configure`，再按端口 `active/start`。

### FFmpeg Guard（按端口）

独立于 stable/active，以端口区分，支持 `configure/start/stop`。

---

## 公共字段

除 `GET /command/v1/status` 外，所有 POST 接口都需要以下表单字段：

- `request_id`
- `group_id`
- `callback_type`
- `timestamp`

---

## 接口总览

### Stable

- `POST /command/v1/stable/configure`
- `POST /command/v1/stable/start`
- `POST /command/v1/stable/stop`

### Active

- `POST /command/v1/active/configure`
- `POST /command/v1/active/start`
- `POST /command/v1/active/stop`

### FFmpeg

- `POST /command/v1/ffmpeg/configure`
- `POST /command/v1/ffmpeg/start`
- `POST /command/v1/ffmpeg/stop`

### 全局

- `POST /command/v1/all/stop`
- `GET /command/v1/status`

---

## 详细字段说明

### 1) `POST /command/v1/stable/configure`

配置 stable 参数（不启动进程）。

表单字段：

- 公共字段（必填）
- `dabmod_mode`（默认 `1`）
- `dabmod_format`（默认 `s8`）
- `dabmod_gain`（默认 `0.8`）
- `dabmod_gainmode`（默认 `max`）
- `dabmod_rate`（默认 `2048000`）
- `hackrf_freq_hz`（默认 `227360000`）
- `hackrf_sample_rate_hz`（默认 `2048000`）
- `hackrf_amp_enable`（默认 `1`）
- `hackrf_gain_db_tx`（默认 `40`）
- `dabmux_file`（可选上传文件）

说明：

- 如果不上传 `dabmux_file`，使用已有/默认 dabmux 配置。

### 2) `POST /command/v1/stable/start`

按当前配置启动 stable 三件套。

### 3) `POST /command/v1/stable/stop`

停止 stable 三件套。

---

### 4) `POST /command/v1/active/configure`

按端口配置 active 会话（不启动）。

表单字段：

- 公共字段（必填）
- `port`（必填）
- `output_port`（默认 `9000`）
- `bitrate`（默认 `64`）
- `sample_rate`（默认 `48000`）
- `channels`（默认 `2`）
- `format`（默认 `raw`）
- `audio_gain`（默认 `0`）
- `pad`（默认 `58`）
- `padenc_sleep`（默认 `10`）
- `padenc_dls_file`（可选，上传 DLS 文本文件）
- `padenc_image`（可选，单图片文件）
- `padenc_archive`（可选，zip 文件）

说明：

- 上传图片或 zip 时，系统会把资源写入运行目录：
  - `/tmp/odr_executor/uploads/padenc/{port}/slides`
  - `/tmp/odr_executor/uploads/padenc/{port}/dls.txt`
- 如果传了 `padenc_dls_file`，优先使用上传文件内容作为 DLS。
- 不上传图片/zip 时，`padenc` 使用默认行为（由进程侧自行补默认内容）。

### 5) `POST /command/v1/active/start`

按端口启动 active 会话。

### 6) `POST /command/v1/active/stop`

按端口停止 active 会话。

---

### 7) `POST /command/v1/ffmpeg/configure`

配置 ffmpeg 任务（不启动）。

表单字段：

- 公共字段（必填）
- `port`（必填）
- `file`（必填，音频文件）

### 8) `POST /command/v1/ffmpeg/start`

按端口启动 ffmpeg guard。

### 9) `POST /command/v1/ffmpeg/stop`

按端口停止 ffmpeg guard。

---

### 10) `POST /command/v1/all/stop`

顺序停止：

1. 所有 ffmpeg guards
2. stable session
3. 所有 active sessions

超时时间使用服务端统一配置（当前为 `20s`）。

### 11) `GET /command/v1/status`

查询当前会话与 guard 运行状态快照。

---

## 推荐调用顺序

### 启动完整链路

1. `stable/configure`
2. `stable/start`
3. `active/configure`（port=5656）
4. `active/start`（port=5656）
5. `active/configure`（port=5657）
6. `active/start`（port=5657）
7. `ffmpeg/configure`（port=5656）
8. `ffmpeg/start`（port=5656）
9. `ffmpeg/configure`（port=5657）
10. `ffmpeg/start`（port=5657）

### 全量停止

1. `all/stop`

---

## 重要约束

- 不存在 `dabmux/start`、`padenc/start` 独立接口。
- `dabmux` 配置属于 stable，会在 `stable/start` 生效。
- `padenc` 配置属于 active，会在 `active/start`（对应端口）生效。
- 新配置不会自动启动，必须显式调用 `start`。

---

## 常见问题

### 1) 为什么 configure 成功但进程没起来？

因为当前设计是两阶段，`configure` 只写配置，必须再调用 `start`。

### 2) 为什么没有 dabmux/padenc 独立 start？

它们分别绑定在 stable/active 会话内，由会话统一编排生命周期，避免链路不一致。

### 3) 文档页里怎么传文件？

在 FastAPI docs 中选择对应接口后：

- 文件字段（`dabmux_file` / `padenc_image` / `padenc_archive` / `file`）可直接上传
- 文件字段（`dabmux_file` / `padenc_image` / `padenc_archive` / `padenc_dls_file` / `file`）可直接上传
- 其余参数填写表单文本即可
