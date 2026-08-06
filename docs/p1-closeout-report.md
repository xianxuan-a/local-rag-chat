# P1 四轮收尾报告

日期：2026-07-28
范围：P1 第一至第四轮，重点为 Dashboard、Real/Mock 边界和全链路收尾

## 1. P1 已实现结果

- 系统设置：管理员可读取和保存非敏感业务配置；普通用户只读；API Key
  仅返回是否已配置。配置写入 `product_settings`，重启后重新加载。
- 知识库：创建、列表、详情、名称/描述编辑和安全删除均使用真实数据库，
  并按所有者隔离。
- 文件：上传、持久化处理 Job、真实状态/进度、失败与手工重试、删除及向量
  补偿闭环已接通；离页只停止客户端轮询。
- 检索：使用活动 Collection 和 query embedding 返回真实正文、分数、来源及
  安全元数据；无索引、模型失败和超时使用稳定错误语义。
- 会话与聊天：分页 CRUD、真实历史、自动标题、NDJSON 流式回答、结构化引用、
  原位重试和反馈持久化已接通。停止操作现在先向精确的“会话 + 助手消息”
  发出协作式取消信号，再关闭浏览器流，partial 可落为 `cancelled`。
- 索引：真实状态、rebuild、协作式取消、rollback、building abort、previous /
  orphan 安全 cleanup 均经持久化 Job 和服务器状态驱动，页面不伪造进度。
- 评测：可复用数据集、`retrieval` / `rag` 两种模式、真实 Job 进度、报告、
  指标、案例和失败过滤已接通；历史运行在知识库删除后按快照保留。
- Dashboard：`GET /api/dashboard` 在后端完成所有者范围聚合，返回 6 个真实
  指标卡、连续 UTC 日期趋势、文件状态、最近文件/会话/索引 Job/评测 Job、
  安全运行配置和可分区失败信息。最近记录可跳转到真实页面。
- 全局状态：所有 P1 页面通过统一契约访问 Adapter；Real 失败显示真实错误，
  不回退 Mock。聊天初始化期间禁止抢先新建会话，避免旧会话恢复覆盖新上下文。

## 2. 关键文件

```text
app/api/dashboard.py：Dashboard 聚合 API、范围参数和响应契约
app/services/dashboard_service.py：所有者隔离、UTC 趋势、指标和最近记录聚合
app/schemas/dashboard.py：Dashboard 公开 Schema
app/api/chat.py：流式 Chat、原位重试及精确消息协作式取消
app/services/runtime_coordinator.py：会话级占用和消息级取消信号
app/services/chat_history_service.py：取消目标授权、partial 与消息终态持久化
alembic/versions/0006_dashboard_aggregates.py：Dashboard 常用筛选/排序索引
frontend/src/views/DashboardView.vue：真实指标、趋势、状态、最近记录和部分失败 UI
frontend/src/views/ChatView.vue：显式停止、迟到响应保护和初始化竞态保护
frontend/src/api/adapters/realAdapter.ts：Dashboard 与 Chat cancel Real 契约
frontend/src/api/adapters/mockAdapter.ts：显式 Mock 契约
frontend/src/api/adapters/realRuntimeAdapter.ts：Real 生产构建入口
frontend/src/api/adapters/mockRuntimeAdapter.ts：Mock 生产构建入口
frontend/vite.config.ts：按 VITE_API_MODE 选择单一 Adapter 和独立产物目录
frontend/vitest.config.ts：单测显式使用 Mock runtime，契约测试单独构造 Real Adapter
tests/test_dashboard_api.py：聚合、空状态、权限和部分失败测试
tests/test_sessions_chat_round_two.py：精确停止、幂等和错误目标保护测试
frontend/e2e/real-api.spec.ts：隔离 Real 全链路与无 Mock fallback 验收
tests/real_api_integration_app.py：真实 FastAPI/SQLite/解析/Chroma/Job 的隔离测试应用
README.md：启动、迁移、Real/Mock、Dashboard、恢复与限制说明
```

## 3. API、数据库和配置变化

### API

- 新增 `GET /api/dashboard`：
  - `knowledge_base_id` 可选；
  - `window_days` 为 1–30，默认 7；
  - `recent_limit` 为 1–20；
  - 普通用户仅见自己的资源，管理员沿用全局可见语义；
  - 核心指标失败返回错误，非核心分区失败写入 `section_errors`。
- 新增 `POST /api/chat/messages/{assistant_message_id}/cancel`：
  - 请求带 `knowledge_base_id` 和 `session_id`；
  - 只取消精确匹配的当前活动助手消息；
  - 已取消重复提交幂等，错误消息或已完成回答不被误取消。

两项接口均为增量兼容变更，既有客户端可以继续使用原接口。

### 数据库

- Alembic head 更新为 `0006_dashboard_aggregates`。
- `0006` 只新增有界聚合所需索引，未新增业务表或 Secret 字段：
  - 知识库所有者/更新时间；
  - 文件知识库/状态/更新时间；
  - 会话知识库/更新时间；
  - 消息角色/状态/创建时间；
  - Job 类型/创建人/创建时间。
- Chat 显式取消复用 `chat_messages.status/error_*`，不需要新列。

### 前端配置

- `VITE_API_MODE` 必须显式为 `real` 或 `mock`。
- Real 产物写入 `frontend/dist-real`，Mock 产物写入
  `frontend/dist-mock`；构建不会批量删除已有目录。
- Vite 在构建时把 runtime Adapter 指向单一模式入口，避免另一模式进入当前
  生产依赖图。
- ESLint 忽略两个构建产物目录，避免把压缩产物当源代码检查。

真实数据库未迁移、未修改；需要用户在停机窗口显式运行
`alembic upgrade head`。

## 4. 实际验证

### 后端

- `python -m pytest -q`
  - 结果：`219 passed, 1 skipped, 175 warnings`
  - 耗时：73.94 秒
  - 唯一跳过项为需要真实 DashScope 的条件式冒烟测试。
  - warnings 为 Chroma legacy embedding config 弃用提示。
- `python -m compileall -q app scripts ui tests`
  - 结果：通过。
- Dashboard 目标测试：
  - 空数据/连续日期/Secret 安全；
  - 真实聚合和最近记录；
  - 所有权与管理员范围；
  - 非核心分区失败；
  - 结果均通过。
- Chat 显式停止目标测试：
  - 精确消息匹配；
  - 错误目标不取消；
  - 重复停止幂等；
  - partial 和 `cancelled` 历史；
  - 结果均通过。

### 迁移

在保留的临时数据库
`artifacts/alembic-round4-20260728.db` 上实际执行：

1. 空库升级到 `0005_indexes_evaluation_round_three`；
2. `0005 → 0006`；
3. `0006 → 0005`；
4. 再次 `0005 → 0006`；
5. `alembic check`；
6. `alembic current`。

结果：无新增迁移差异，最终 revision 为
`0006_dashboard_aggregates (head)`。没有操作真实数据库。

### 前端

- `npm run type-check`：通过。
- `npm run lint`：通过。
- `npm run lint:colors`：通过。
- `npm run test:unit`：13 个测试文件、63 项测试全部通过。
- `npm run build:real`：通过。
- `npm run build:mock`：通过。
- `npm run dev:mock -- --host 127.0.0.1`：Vite 开发服务实际启动成功。
- 两个构建均出现 Dashboard chunk 超过 500 kB 的 Vite 性能提示，不影响构建
  成功，但列为剩余优化项。

### 构建边界审计

从两个当前 `index.html` 引用的生产 client chunk 实际检查：

- Real：包含 `/api/dashboard`，不包含 Mock 固定知识库或 `/mock/uploads/`；
- Mock：包含 Mock 路径，不包含 `/api/dashboard` 或 `/api/chat/stream`。

### 浏览器端到端

- Mock 完整 Playwright：
  - 7 项通过；
  - 3 项仅 Real 环境用例按设计跳过；
  - 包括 15 张视觉 QA 截图。
- 隔离 Real Playwright：
  - 1 项完整链路通过，耗时 11.8 秒；
  - 覆盖 Settings 保存并重读、知识库创建/编辑/刷新、文件上传/处理/刷新、
    Retrieval、会话创建、NDJSON 回答、引用、停止、模型失败、原位重试、
    反馈、历史刷新、索引重建/回滚/清理、retrieval/rag 评测、Dashboard
    指标/最近记录/跳转、删除冲突和安全删除；
  - 网络断言确认经过 `/api/dashboard`、`/api/chat/stream`、
    `/api/chat/messages/{id}/retry/stream`、
    `/api/chat/messages/{id}/cancel` 等 Real 路径。
- 后端关闭后的 Real Playwright：
  - 1 项通过；
  - 页面明确显示服务不可达，Mock 固定内容未出现。

隔离 Real 用例使用真实 FastAPI、SQLite、文件解析、Chroma、Retrieval、
持久化 Job worker 和 NDJSON 网络流；Embedding 与 Chat provider 使用确定性
本地替身，因此不计作真实 DashScope 模型联调。

### 重启恢复

- 第一次重启实际检测并恢复了 1 条遗留 `streaming` 回答，启动日志明确记录。
- 完整 E2E 将 `retrieval_top_k` 保存为 6 后再次重启：
  - `GET /api/settings` 返回 `retrieval_top_k=6`、`source=persistent`；
  - Dashboard 重启后仍返回 7 个知识库、7 个成功文件、4 个会话和 7 个活动
    索引（隔离目录包含此前保留的失败重试数据）；
  - Evaluation 历史总数为 9，包含已删除知识库的 complete2 两条成功报告快照。
- 最终已停止测试后端和前端，5173、4173、8012 均无监听进程。

## 5. Real/Mock 审计结果

- Real 仍为零 Mock fallback；网络、401/403/404/409/422/5xx、超时和取消均按
  真实错误处理。
- Mock 仅保留于显式 `VITE_API_MODE=mock`、单元测试和 Mock Playwright。
- Mock 使用自己的内存状态与延时，不注册网络拦截器，也不与 Real 共享浏览器
  持久化数据。
- Dashboard 中固定 KPI、随机趋势、固定运行信息和伪状态已移除。
- Files 不再乐观伪造 `PROCESSING`；Indexes/Evaluation 不再使用伪进度和固定
  指标；Chat 不再以关闭浏览器读取代替服务端停止。
- 对 `mock/fake/demo/random/setInterval/固定时间` 的命中按用途审计后，仅保留
  显式 Mock、测试替身、合法轮询和确定性测试数据。

## 6. 与开发简介相比的变化

侦察后的主方案保持不变：新增后端 Dashboard 聚合、`0006` 索引和单模式构建。
真实联调又提供了两项不能只靠静态阅读发现的证据，因此做了最小阻塞修复：

1. 浏览器 Abort 在当前 Starlette/Uvicorn 链路上不能稳定触发生成器断开处理，
   消息会遗留为 `streaming`。因此新增精确消息取消 API 和进程内协作式取消
   checkpoint；外部模型调用仍只能在下一个 checkpoint 停止。
2. Chat 首次加载会话时，过早点击“新建会话”会与服务器最近会话恢复竞争。
   因此初始化期间禁用新建入口，并增强 Real E2E 的会话 ID 对账。

此外，独立 Real/Mock 构建目录使 ESLint 开始扫描压缩产物，故补充了构建目录
ignore；Vitest 显式别名到 Mock runtime，避免测试配置误走 Real。

## 7. 未完成和风险

### 已实现但未做真实外部联调

- 当前测试未调用真实 DashScope document/query embedding 或 Chat 模型。
- `CHAT_MODEL` 的付费真实调用没有执行；确定性替身结果没有计为真实模型成功。
- Docker daemon、容器重启、在线备份和离线恢复演练未在本轮环境执行。

### 需要用户执行

- 在停机窗口备份真实数据库后，显式运行 `alembic upgrade head`。
- 配置真实 `DASHSCOPE_API_KEY` 和 `CHAT_MODEL` 后，另行显式执行付费冒烟。

### 当前架构限制

- 单 FastAPI 进程、单 Job worker、SQLite 和本地 Chroma，不支持水平扩展。
- 流式回答不支持跨进程续流；外部 SDK 已开始的单次调用不能强杀。
- Dashboard 时间窗口按 UTC 自然日，不是浏览器本地日。

### 已知剩余风险

- Dashboard 页面生产 chunk 约 542 kB（gzip 约 185 kB），后续可拆分 ECharts
  或按需加载。
- `prettier --check .` 曾发现工作区大量既有格式差异；本轮未做全仓机械改写，
  以免覆盖与范围无关的用户改动。TypeScript、ESLint、颜色审计、测试和构建均
  已通过。
- 隔离 E2E 的中间失败产物与数据按要求保留，未批量删除；它们会使隔离
  Dashboard 的重启计数高于单次成功流程。
