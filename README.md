<h1 align="center">Auto Closed Loop Test</h1>

## 项目简介

`Auto Closed Loop Test` 包含两个核心子系统：

- `odr_executor`：负责管理 ODR Tools 工具链、FFmpeg 与 HackRF 设备，并提供状态监听接口。
- `scheduler`：负责调度测试流程，执行测试套件中的测试用例，并提供状态监听接口。

应用启动后会同时拉起两个 FastAPI 服务：

- ODR Executor：`http://localhost:8080`（文档：`/docs`）
- Scheduler：`http://localhost:8090`（文档：`/docs`）

---

## 目录

- [环境要求](#环境要求)
- [快速开始](#快速开始)
    - [方式一：本地运行（Python）](#方式一本地运行python)
    - [方式二：Docker 运行](#方式二docker-运行)
- [配置说明](#配置说明)
- [ODR Executor](#odr-executor)
- [Scheduler](#scheduler)
- [ADB 配置与 pre-commit 脚本](#adb-配置与-pre-commit-脚本)
- [常见问题](#常见问题)

---

## 环境要求

- Python `3.12`（参考 `requirements.txt` 生成环境）
- Linux（当前项目在 Linux 环境下开发/部署）
- 可选：Docker / Docker Compose
- 设备相关（按需）：HackRF、ODR 工具链、ADB

> 项目根目录已包含 `.env`，启动时会自动加载。

---

## 快速开始

### 方式一：本地运行（Python）

1. 安装依赖（建议使用虚拟环境）
``` bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```
2. 在项目根目录运行如下指令
``` bash 
python -m app.scheduler.scheduler
python -m app.odr_executor.odr_executor
```
3. 打开接口文档：
     - `http://localhost:8080/docs`
     - `http://localhost:8090/docs`

### 方式二：Docker 运行

项目已提供：

- `Dockerfile`：构建运行镜像（包含 ODR 相关工具编译安装）
``` bash
docker build --pull --rm -f Dockerfile -t autoclosedlooptest:v1.0.0 . 
```
- `docker-compose.yaml`：启动容器（`host` 网络模式、USB 设备映射、配置文件挂载）
``` bash 
docker compose up -d
```
默认容器环境变量（节选）：

- `SCHEDULER_CONFIG_PATH=/app/config/scheduler/flows.yaml`
- `DABMUX_ADVANCED_CONFIG_PATH=/app/config/odr_executor/dabmux/advanced.mux`

---

## 配置说明

### 默认配置文件

- Scheduler 主流程：`config/scheduler/flows.yaml`
- Scheduler 模块配置：`config/scheduler/modules/*.yaml`
- ODR DabMux 高级配置：`config/odr_executor/dabmux/advanced.mux`

### active 会话中的 `port` 与 `output_port`

为便于管理，所有会话/程序采用“先配置，再启动”的策略。

- `output_port`：对应 `dabmux` 配置中 `subchannel.inputuri` 的输入端口。
- `port`：对应 `socat` 的输入端口，同时也是区分不同 active 会话的唯一键。

示例说明：

- 若某 subchannel 的 `inputuri = tcp://127.0.0.1:9000`，则 active 的 `output_port` 应为 `9000`。
- 若 FFmpeg 推流目标端口为 `5656`，则 active 的 `port` 应为 `5656`。

---

## ODR Executor

### 运行框架图

![ODR Executor 架构图](docs/image/odr-executor.png)

### 设计考量

- **`guard.py` 核心模块**
    - 统一管理外部进程生命周期，自动拉起崩溃进程，并向上层提供统一控制接口。
    - ODR 工具链由多个协同进程构成，单点崩溃常会连带影响整体链路；自动重启机制可提升稳定性与可恢复性。

- **`stable_session` 与 `active_session`**
    - `dabmux`、`dabmod`、`hackrf`：系统运行时通常只需单实例，且关联性强，使用 `stable_session` 统一管理。
    - `socat`、`padenc`、`audioenc`：按 subchannel 成套运行，使用 `active_session` 管理，并以 `socat` 输入端口区分。
    - 最终由 `session_manager` 统一调度。

- **Router 路由策略**
    - 当前 API 采用表单参数，便于直接通过 FastAPI Docs 进行交互式调试。
    - 若后续接入前端页面，可按需调整为 JSON 结构。

- **有名管道通信**
    - 当前设计目标为单机部署，强关联进程优先采用管道通信，兼顾实现复杂度与传输效率。

- **参数配置策略**
    - 对 DAB 发射链路中的固定参数（如部分 FFmpeg 采样相关项）采用内置策略，减少误配。
    - 特别说明：FFmpeg 播放音频时若使用 `readrate=1`，测试中会出现读取速率变慢、音频断续；当前固定使用 `1.06`。若直接采样声卡该问题不明显，初步判断与 FFmpeg 模拟时钟精度有关。

---

## Scheduler

### 运行框架图

![Scheduler 架构图](docs/image/Scheduler.png)

### 设计考量

- **模块化测试流程编排**
    - 为兼顾后续扩展与流程灵活性，测试模块采用 Python 动态注入方式加载。

- **CompletionPolicy**
    - 用于覆盖不同测试场景下的回调收敛逻辑，当前支持：
        1. **`exactly(n)`**：收到第 `n` 条匹配回调即完成（当前实现是“达到 n 即返回”，不要求最终总数严格等于 `n`）。
        2. **`at_least(n)`**：至少收到 `n` 条匹配回调才完成；达标后继续收集队列中当前可匹配回调。
        3. **`any_one()`**：任意收到 1 条匹配回调即完成。
        4. **`until(stop_when)`**：持续收集回调，直到满足 `stop_when(callback) == True`。
        5. **`time_window_collect(window_seconds)`**：在指定时间窗内收集匹配回调，窗口结束后完成。
        6. **MatchPolicy**：默认 `no_filter`（按 `callback_type/group_id` 匹配）；通过 `with_request_ids([...])` 启用 `by_request_ids` 后，完成条件按请求维度生效。

- **ActionPhase**
    - 每个 Phase 可独立控制：完成策略、超时时间、超时行为、是否等待回调、是否开启 `request_id` 检查、超时最小回调数量等。

- **`callback_type/group_id/request_id` 过滤机制**
    - `callback_type`：过滤测试模块。
    - `group_id`：过滤 phase。
    - `request_id`：过滤请求维度。
    - 目的：剔除后续无关回调（例如切台后残留的 DLS/SLS 或音频回调），提高判定准确性。

### 扩展新测试模块（开发指引）

1. 定义 `ActionPhase`。
2. 继承 `BaseParam`，添加成员变量，并与 YAML 中 `config` 字段对齐。
3. 创建日志对象并指定 tag。
4. 继承 `TemplateAction`，至少实现：
     - `build_phase`
     - `dispatch_request`
     - `_validate_phase_callbacks`
     - `_build_request_id`
     - `_build_group_id`
     - `callback_type`
     - `phase_timeout_seconds`
5. 修改 `flows.yaml`，添加测试配置。
6. 调用 `start` 接口执行流程。

---

## ADB 配置与 pre-commit 脚本

典型场景：

- 程序在开发服务器完成构建；
- 希望在 `git commit` 时自动执行测试；
- 测试通过后才允许提交。

可通过 **ADB C/S 架构 + SSH 隧道** 实现开发服务器对本地连接设备的远程操作。

- 默认 ADB 端口：`5037`
- 可通过环境变量 `ANDROID_ADB_SERVER_PORT` 修改

基本思路：

1. 先通过 SSH 将开发服务器到本地的 ADB 端口打通。参考如下配置文件
``` bash
Host dev
	Hostname 10.100.193.16
	User yangxinxin
	RemoteForward 7897 localhost:7897
	RemoteForward 5037 127.0.0.1:5037
	RemoteForward 17878 127.0.0.1:17878
	RemoteForward 17879 127.0.0.1:17879
	RemoteForward 17880 127.0.0.1:17880
	RemoteForward 8090 127.0.0.1:8090
	ServerAliveInterval 60
	ServerAliveCountMax 3
	# ExitOnForwardFailure yes
```

2. 在本地启动 ADB Server。
3. 在开发服务器执行 ADB 命令（如 `adb push`、`adb shell`），即可操作本地连接设备。
4. 将 pre-commit 脚本挂入 git hooks，在提交时自动执行测试流程。

### Python 环境建议

若开发服务器权限受限，建议使用 **Miniconda** 管理 Python 环境（见 `docs/miniconda.md`）。

---

## 常见问题

- **音频断续问题（FFmpeg）**
    - 已知 `readrate=1` 可能导致读取速率变慢、音频断续；当前建议固定使用 `1.06`。

- **接口无法访问**
    - 检查服务是否已启动。
    - 检查端口 `8080/8090` 是否被占用。
    - Docker 模式下确认容器是否正常运行、日志是否有报错。

- **设备不可用（HackRF/ADB）**
    - 检查 USB 权限与设备映射（Docker 场景需确认 `/dev/bus/usb` 挂载）。

---

## 更多文档

- `docs/odr_executor.md`
- `docs/scheduler.md`
- `docs/miniconda.md`
- `docs/git-hooks-setup.md`