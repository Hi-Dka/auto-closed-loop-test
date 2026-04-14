# Scheduler 设计与使用指南

---

## 快速理解（先看这个）

Scheduler 的核心职责只有三件事：

1. 从配置读取测试流水线（pipeline）
2. 按步骤顺序执行 Action
3. 通过回调判断步骤是否完成或失败

它本质上是一个“配置驱动 + 回调驱动”的流程引擎。

---

## 总体架构

### 1) 应用入口层

- 路径：`app/scheduler/scheduler.py`
- 作用：创建 FastAPI 应用，挂载控制路由与回调路由。
- 生命周期初始化时会准备运行态：
  - `scheduler_running = False`
  - `scheduler_task = None`
  - `scheduler_last_outcome = "idle"`

### 2) 接口层

- 路径：`app/scheduler/network/router.py`
- 控制接口：
  - `POST /control/v1/start`：启动执行
  - `POST /control/v1/status`：查询当前状态
- 回调接口：
  - `POST /callback/v1/scan`
  - `POST /callback/v1/upload/audio`

接口层会把回调数据标准化，然后转发给当前运行中的 Action。

### 3) 调度核心层

- 路径：`app/scheduler/engine/master.py`
- 作用：
  - 解析 suite 配置
  - 动态装配 `action_class`
  - 串行执行每个步骤
  - 维护运行状态、失败步骤、错误信息

### 4) 配置解析层

- 路径：`app/scheduler/core/parse_config.py`
- 支持：
  - 主配置（例如 `config/scheduler/flows.yaml`）
  - 步骤配置（例如 `config/scheduler/modules/scan.yaml`）
- 解析阶段会做结构校验，缺字段或字段类型错误会直接报错。

### 5) Action 执行基础层

- 路径：`app/scheduler/core/base_action.py`
  - 提供参数模型、回调队列、匹配策略、等待与超时能力
  - 回调队列有 TTL 清理机制
  - 当前实现中，TTL 以入队时间 `received_at` 为主，避免外部时间戳漂移造成误判
- 路径：`app/scheduler/actions/template_action.py`
  - 提供 phase 模式执行模板
  - 支持多次发送、策略收敛和超时行为控制

---

## 执行流程（运行时视角）

1. 调用 `start` 接口后，Scheduler 后台启动执行任务。
2. 加载主配置并解析 pipeline。
3. 按 step 顺序动态创建并执行 Action。
4. Action 发起请求后，等待满足策略的回调。
5. 当前 step 成功后进入下一步；失败则流程结束并记录失败信息。
6. 可通过 `status` 接口持续查询当前进度与结果。

---

## 如何使用

### 1) 准备配置

你需要维护两类配置文件：

- 主流程配置：定义步骤顺序（pipeline）
- 模块配置：定义每个 step 对应的 `action_class`、`callback_type`、`config`

### 2) 启动执行

- 启动服务后，调用 `POST /control/v1/start`。
- Scheduler 会在后台执行，不阻塞接口线程。

### 3) 观察状态

通过 `POST /control/v1/status` 关注这些字段即可：

- `scheduler_running`
- `scheduler_status`
- `last_outcome`
- `flow_status.run_status`
- `flow_status.current_step_id`
- `flow_status.failed_step_id`

### 4) 对接回调

回调必须与当前 phase 的筛选条件一致，至少保证：

- `callback_type` 正确
- `group_id` 正确
- 如果启用了 request_id 校验，`request_id` 也必须正确

---

## 扩展新能力：继承 TemplateAction

新增一个测试动作时，推荐按这条路径做：

1. 新建 Action，继承 `TemplateAction`
2. 定义参数模型（用于解析模块配置中的 `config`）
3. 定义 phase（发送次数、完成策略、超时策略）
4. 实现请求发送逻辑
5. 生成可追踪的请求标识（request/group）
6. 在模块配置中声明该 Action
7. 把该 step 加入主流程 pipeline

这条模式的好处是：扩展新业务步骤时，通常不需要改调度核心。

---

## 状态语义

### 调度器结果态

- `scheduler_last_outcome` 初始值：`idle`
- 启动后通常为：`running`
- 执行结束后：`success` 或 `failed`

### 流程运行态

`flow_status.run_status` 常见值：

- `idle`：未执行
- `initialized`：已完成初始化
- `running`：执行中
- `success`：全部步骤成功
- `failed`：存在失败步骤

---

## 常见问题排查

### 1) 回调到了，但 step 超时

优先检查：

- 回调类型是否匹配当前 step
- `group_id` / `request_id` 是否匹配当前 phase
- 回调是否在超时窗口内

### 2) Action 无法装配

优先检查：

- `action_class` 路径是否正确
- 类是否可导入、可实例化
- 是否继承了调度框架要求的基类

### 3) 参数解析失败

优先检查：

- 模块配置里的 `config` 键名是否与参数模型一致
- 是否传入了未声明字段

---

## 维护建议

- 一个 Action 只负责一种业务动作，保持单职责
- phase 名称保持语义化，便于日志检索
- 回调契约先稳定，再扩展策略复杂度
- 配置和参数模型始终同步演进
- 新增 step 后先做一次端到端联调，再加入大套件

