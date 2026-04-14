# ODR Executor 设计与使用指南

这份文档用于说明 `odr_executor` 的当前实现：它负责管理 ODR 相关进程与会话，并通过 HTTP 接口接收更新命令。

---

## 快速理解（先看这个）

ODR Executor 的核心职责：

1. 维护一组长期运行的无线链路进程（stable session）
2. 维护一组按端口区分的任务会话（active session）
3. 通过统一接口更新进程参数并触发安全重启

它本质上是一个“**进程守护 + 会话编排 + API 控制**”服务。

---

## 总体架构

### 1) 应用入口层

- 路径：`app/odr_executor/odr_executor.py`
- 作用：创建 FastAPI 应用并在生命周期内初始化会话管理器。
- 启动时行为：
  - 注册全局 `session_manager`
  - 自动拉起 `stable session`
  - 自动拉起一个默认 `active session`（端口 `5656`）
- 停止时行为：
  - 清理全局 manager 引用
  - 停止 stable session
  - 停止所有 active session

### 2) 接口层

- 路径：`app/odr_executor/network/router.py`
- 路由前缀：`/command/v1`
- 主要能力：
  - 更新进程参数（dabmux / dabmod / hackrf / audioenc / padenc / socat / ffmpeg）
  - 启停 stable session
  - 启停指定端口 active session
  - 一键停全部或拉起全部

### 3) 数据模型层

- 路径：`app/odr_executor/network/data_model.py`
- 作用：约束 API 入参，提供默认值和基础校验。
- 典型约束：
  - `audioenc` 的 `sample_rate` 仅允许固定枚举值
  - `bitrate` 需要满足编码约束（接口层和进程层都有保护）

### 4) 会话编排层

- 路径：`app/odr_executor/session/session_manager.py`
- 核心对象：`SessionManager`（单例）
- 职责：
  - 管理 stable/active 会话生命周期
  - 管理 active 端口占用
  - 接收 `dispatch` 指令并路由到对应进程 guard
  - 按目标类型执行“更新后重启”策略

### 5) 会话实例层

- stable session：`app/odr_executor/session/stable_session.py`
  - 包含：`dabmux`、`dabmod`、`hackrf`
  - 启动前会准备共享 FIFO
- active session：`app/odr_executor/session/active_session.py`
  - 包含：`padenc`、`socat`、`audioenc`
  - 每个 active session 绑定一个端口和独立 FIFO

### 6) 进程守护层

- 路径：`app/odr_executor/core/guard.py`
- 基类：`ProcessGuard`
- 机制：
  - 子线程监控进程
  - 异常退出自动重启
  - 统一日志采集
  - 支持 deploy / undeploy / wait_until_stopped

---

## 会话模型与运行关系

### stable session（稳定链路）

用于维持基础发送链路，包含：

- DabMux
- DabMod
- HackRF

这部分通常在服务启动时就拉起，属于全局基础能力。

### active session（任务链路）

用于按任务端口进行动态接入，包含：

- PadEnc
- Socat
- AudioEnc

每个 active session 与端口绑定，支持按端口单独启停和更新。

---

## 更新与重启策略（非常关键）

`dispatch` 的策略不是“仅更新内存参数”，而是“更新后按目标重启对应进程链路”。

- 目标是 `ffmpeg`：更新后重启对应 FFmpeg guard（按 id 管理）
- 目标是 stable 组件（dabmux/dabmod/hackrf）：更新后重启 stable session
- 目标是 active 组件（audioenc/padenc/socat）：更新后重启该端口对应 active session

这能保证配置生效一致，但也意味着更新操作会触发短暂中断。

---

## 使用方式

### 1) 启动服务

- ODR Executor 应用入口是 `odr_executor_app`。

### 2) 常用接口分组

#### 会话控制

- 启动 stable session
- 停止 stable session
- 启动指定端口 active session
- 停止指定端口 active session
- 一键启动全部 / 停止全部

#### 参数更新

- `dabmux` 更新
- `dabmod` 更新
- `hackrf` 更新
- `audioenc`（按端口）更新
- `padenc`（按端口）更新
- `ffmpeg` 启停（按 id）

### 3) 使用建议顺序

1. 先确认会话已拉起（stable + 对应 active 端口）
2. 再下发参数更新
3. 观察进程重启日志，确认重启后运行稳定
4. 对于 ffmpeg，按唯一 id 管理启动/停止

---

## 关键输入语义

### 1) 端口语义

- `audioenc` / `padenc` / `socat` 更新都依赖端口路由到 active session
- 端口不存在或未拉起时会返回错误

### 2) 文件上传语义

- `dabmux` 与 `ffmpeg/start` 支持文件上传
- 文件内容会被读取并参与目标命令构建

### 3) 默认值与自动补齐

- 多个组件具备默认参数（例如采样率、增益、路径）
- `padenc` 会自动准备目录与默认 DLS 文件
- 部分输入会在接口层和进程层双重校验

---

## 进程可靠性机制

`ProcessGuard` 提供以下稳定性保障：

- 子进程异常退出自动拉起
- stdout/stderr 合并并实时写日志
- 停止时先优雅退出，超时后强杀
- 提供快照能力（状态、pid、重启次数）

---

## 常见问题排查

### 1) 更新成功但效果不生效

优先检查：

- 是否命中了正确 target
- active 类型更新是否传了正确端口
- 更新后是否确实触发了对应会话重启

### 2) active 更新报端口无效

优先检查：

- 该端口 active session 是否已拉起
- 端口是否被重复占用或已释放

### 3) 进程频繁重启

优先检查：

- 参数是否越界（采样率、码率等）
- FIFO / 文件路径是否可访问
- 外部依赖命令是否可执行（odr-* / hackrf_transfer / socat / ffmpeg）

### 4) 启停卡住或超时

优先检查：

- 子进程是否可被正常终止
- 系统权限与资源占用
- 相关 guard 的 `wait_until_stopped` 是否超时

---

## 扩展建议

新增一个受控进程时，建议遵循当前分层：

1. 新增对应 Guard（命令解析 + 参数校验）
2. 将 Guard 放入 stable 或 active session
3. 在 `SessionManager.dispatch` 增加 target 路由与重启策略
4. 在接口层新增对应 update 路由与数据模型

这样可以保持“接口层、会话层、进程层”职责清晰，后续维护成本最低。

---

## 维护建议

- 使用一致的 target 命名，避免路由歧义
- 对每个 target 明确“更新后重启范围”
- 参数默认值与接口文档保持同步
- 将外部依赖命令安装检查纳入部署流程
- 对关键会话（stable）优先保证可观测性和重启稳定性
