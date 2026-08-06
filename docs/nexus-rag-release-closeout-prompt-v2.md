# Nexus RAG 正式版本审计、修复、联调与工程化收尾（执行版提示词 v2）

请基于当前真实仓库，对 Nexus RAG 执行一次可追溯、可恢复、可验证的正式版本收尾。目标不是让 Mock 页面“看起来可用”，而是让被声明支持的功能在 Real 模式下形成真实闭环，并用实际执行证据证明其质量。

本提示词是执行规范，不是仓库现状说明。任何实现状态都必须从当前代码、配置、迁移、运行行为和测试结果中确认，不得依据文件名、旧报告、Mock 数据或本提示词猜测。

## 0. 本次任务的产品边界

除非用户在执行前明确修改，按以下边界工作：

- `frontend/` 下的 Vue/Vite 应用是目标正式 Web 前端。
- `ui/` 下的 Streamlit 是兼容或运维入口；不得用它代替 Vue Real 模式验收，也不得在未获授权时删除。
- FastAPI 是所有正式业务数据和业务状态的唯一服务端入口。
- `VITE_API_MODE=mock` 仅用于单元测试、E2E、演示和离线 UI 开发。
- `VITE_API_MODE=real` 必须只访问 FastAPI，不得加载种子数据，不得在请求失败时回退 Mock。
- 当前产品按仓库实际实现判断为本地单实例、多用户所有权模型；若真实代码与此不符，先记录证据，再把差异作为架构阻塞处理。
- SQLite、上传目录和 Chroma 不被假定为分布式事务；必须通过状态机、补偿、幂等、恢复器和一致性检查保证可恢复性。
- 正式运行边界默认为单 FastAPI 进程、单业务 Job worker；不得在未重新设计锁和任务语义前宣称支持多 worker 或水平扩展。

## 1. 最终目标

至少实现并验证：

1. 正式前端可以登录，并在刷新后正确恢复或失效登录态。
2. 用户只能访问自己拥有或被授权访问的知识库、文件、会话、消息、Job、评估和备份能力。
3. 知识库能够真实创建、查询、更新（若产品保留此能力）、删除并保持关联状态一致。
4. 文件能够真实上传、落盘、入库、异步处理、向量化、查询、重试、取消和删除。
5. 前端能够处理 `202 → Job → 轮询/取消/重试/恢复`，不得用计时器伪造进度。
6. RAG 能够通过真实 active Collection 检索、真实生成、流式返回并产生合法引用。
7. 会话、消息和引用能够持久化，刷新、切换和重启后行为正确。
8. 索引能够重建、原子切换、回滚、中止 building 和清理 retired Collection。
9. Dashboard、Settings、Evaluation 页面只展示后端可证实的数据和能力；不受支持的能力必须隐藏、禁用或明确说明，不得伪造。
10. Alembic、日志、指标、健康检查、备份恢复、安全边界和 Docker 部署有可复现实现。
11. 所有“通过”结论来自本次真实执行；旧报告只能作为线索，不能作为当前通过证据。

## 2. 必须遵守的安全与工作区规则

1. 首先读取并遵守仓库内所有适用的 `AGENTS.md`、README、开发说明和更深层目录约束。
2. 先执行 `git status --short --branch`，保存基线。当前工作区可能包含用户未提交修改；不得覆盖、回退、格式化或清理无关改动。
3. 禁止执行：

   - `git add`
   - `git commit`
   - `git reset`
   - `git checkout`
   - `git clean`
   - 会破坏用户修改的恢复或清理命令

4. 禁止批量删除文件或目录。不得使用：

   - `del /s`
   - `rd /s`
   - `rmdir /s`
   - `Remove-Item -Recurse`
   - `rm -rf`

5. 如确需删除，只能一次删除一个已核对的明确文件路径。若需要批量删除，停止操作并要求用户手动完成。
6. 数据库迁移、恢复、数据删除、向量 Collection 清理、权限扩大、外部系统写入等高风险操作必须：

   - 先做只读核对；
   - 优先在副本、临时目录或 dry-run 中演练；
   - 明确列出目标、影响和恢复方法；
   - 需要影响真实数据时取得用户明确授权。

7. 不得读取、输出或提交 Secret 值。可以检查环境变量名称是否存在，但日志和报告中只能显示“已配置/未配置/无效”，不得显示 API Key、JWT、密码、Token、Cookie 或签名密钥。
8. 不自动创建或修改真实 `.env`。只维护 `.env.example`；真实 Secret 初始化必须由用户显式触发。
9. 禁止为了通过测试而删除有效断言、降低校验强度、吞掉异常、硬编码结果、返回虚假成功或在 Real 模式回退 Mock。
10. 不得用破坏性依赖升级命令（例如 `npm audit fix --force`）。每次升级必须评估兼容性、锁文件变化和漏洞可达性。
11. 不执行无授权的真实付费模型调用。只有用户明确授权，或同时存在项目规定的显式开关与有效 Secret 时，才执行最小真实 DashScope smoke/E2E。

## 3. 证据与表述规则

每一项验证必须记录：

| 字段 | 要求 |
| --- | --- |
| 时间 | 本地时间与时区 |
| 工作目录 | 实际 cwd |
| 命令 | 可复现的完整命令，Secret 用占位符 |
| 模式 | mock / real / test-double / real-external |
| 前置条件 | 服务、数据库副本、Docker、Secret、网络 |
| 退出码 | 实际退出码 |
| 结果 | passed / failed / skipped / blocked / not-run |
| 摘要 | 数量、关键响应、关键日志或产物路径 |

强制语义：

- `skipped`、`xfail`、未安装工具、Docker daemon 不可用、缺少 Secret、网络不可用都不等于通过。
- 重试后通过时，必须保留首次失败、重试原因和是否存在 flaky 风险。
- 静态阅读、类型检查、单元测试、Mock E2E、Real 联调、真实外部服务和 Docker E2E 是不同证据层级，禁止相互替代。
- 不得复用 README、旧 closeout report 或历史终端输出中的“已通过”数字作为本次证据。
- 无法验证时使用“代码已实现但环境未验证”或“阻塞”，不得写“基本完成”“应该可用”。

## 4. 开始实施前的强制输出与文档

先完成只读审计，并输出“正式版本问题审计与实施简介”。同时维护以下文档；已有同类文档时保留其可验证历史，只做增量更新，不得覆盖成更乐观的结论：

1. `docs/release-audit.md`
2. `docs/api-contract-matrix.md`
3. `docs/release-closeout-report.md`

`release-audit.md` 至少包含：

- 仓库说明与适用指令；
- Git 工作区基线；
- 实际技术栈、入口和部署拓扑；
- Python、Node、npm、Docker 等工具版本；
- 后端、Vue 前端、Streamlit、迁移、脚本和测试入口；
- 当前数据库、上传目录和 Chroma 的存在性与只读状态；
- 环境能力：Docker daemon、浏览器、网络、DashScope Secret，仅记录状态；
- 问题清单和实施顺序。

问题必须按以下状态分类：

- 已实现且经本次验证正确；
- 已实现但存在缺陷；
- 部分实现；
- 占位实现；
- 仅 Mock 实现；
- 完全缺失；
- 因环境无法确认；
- 与产品目标或仓库说明不一致。

每个有效发现尽量包含：严重度、证据、文件路径、符号或路由、真实调用链、用户影响、数据风险、修复建议和验证方法。严重度统一为：

- P0：数据损坏、越权、Secret 泄漏、Real 链路不可用、迁移/恢复不可控、正式入口不可部署；
- P1：核心功能缺失或错误、状态不一致、错误处理失真、主要页面无法联调；
- P2：非核心缺陷、性能、可访问性、文档和可维护性问题；
- P3：建议项，不阻塞当前发布目标。

## 5. 当前仓库的已知高风险线索

以下仅是提示词编写时观察到的线索，执行时必须重新验证：

1. `frontend/src/api/adapters/realAdapter.ts` 可能仍为统一占位实现。
2. Vue `AppApi` 可能声明了后端 OpenAPI 当前没有的能力，例如知识库更新、Dashboard、直接检索、消息追加/反馈、部分评估和索引列表能力。
3. 后端可能已经包含认证、所有权、持久化 Job、评估、备份、流式聊天、指标和恢复逻辑，但 Vue 前端尚未完整消费。
4. Vue 路由可能没有登录/初始化页面和认证守卫。
5. Docker Compose 可能仍把 Streamlit 作为 `frontend` 服务，没有构建或托管 Vue 正式产物。
6. 根 README、Vue README 和实际实现可能描述不同完成状态。
7. 现有工程化报告中的历史测试结果可能早于当前未提交改动。
8. 产品名称可能同时出现 “Local RAG Chat” 和 “Nexus RAG”。

不得直接把这些线索写成最终事实。应生成当前 OpenAPI，逐项核对源码、运行行为和测试后再下结论。

## 6. 审计与实施顺序

按依赖顺序推进。每阶段先修复，再运行最接近的测试，并更新审计/契约/验收文档。发现 P0 时优先解决 P0；不要为完成低优先级页面而绕过核心阻塞。

### 阶段 A：真实入口、产品名称与双前端边界

1. 确认 FastAPI、Vue、Streamlit、CLI、worker、迁移和 Docker 的真实入口。
2. 明确正式用户入口为 Vue；Streamlit 只保留已证实的兼容或运维用途。
3. 统一产品名称、页面标题、README、镜像/服务说明；避免无必要的大规模内部包名重命名。
4. Docker 和生产文档必须指向真正的正式前端，不能继续把 Streamlit 标成 Vue 正式前端。
5. 若保留两个前端，建立能力矩阵并明确各自支持范围、维护状态和弃用策略。

验收：

- 新用户能从 README 找到唯一明确的正式启动路径；
- 正式部署打开的是 Vue 生产构建；
- 深层路由刷新有 SPA fallback；
- 不存在把占位 Real Adapter 描述成已接通的文档。

### 阶段 B：OpenAPI、统一契约与 HTTP Client

1. 从当前 FastAPI OpenAPI 和 Pydantic Schema 生成接口事实表，至少包含：

   - 方法与 URL；
   - 认证/角色；
   - path/query/body；
   - 请求/响应 Schema；
   - 成功状态码；
   - 错误码；
   - ID、枚举、时间、分页和空值；
   - 同步、流式或 `202 Job`；
   - 幂等、冲突和取消语义；
   - 对应前端方法、Mapper 和页面。

2. 对前端每个 `AppApi` 方法做明确决策：

   - 连接现有后端接口；
   - 有充分产品依据时新增后端接口；
   - 合并到已有能力；
   - 明确移除、隐藏或禁用不受支持的 UI。

3. 不得为了匹配 Mock 视图而伪造后端字段。DTO 到 ViewModel 的映射集中在 Adapter/Mapper。
4. 统一 HTTP Client 必须正确处理：

   - Base URL 和 query 编码；
   - JSON、multipart、空响应、文件下载；
   - Bearer Token；
   - AbortSignal、客户端取消和 timeout；
   - NDJSON/流式分片；
   - 202、204、非 2xx；
   - FastAPI 校验错误和统一业务错误；
   - 401 登录失效、403 越权、404、409 冲突、422、429、5xx；
   - `X-Request-ID`；
   - 网络错误、无效 JSON、半截流和服务重启；
   - 日志脱敏。

5. 禁止使用 `any`、宽泛强制类型转换或散落在组件中的 `fetch` 掩盖契约问题。
6. 增加契约测试，至少验证 OpenAPI 关键路径与前端 Adapter 的方法、状态码和字段映射没有静默漂移。

### 阶段 C：认证、初始化与所有权

完成并验证：

- bootstrap admin 的一次性初始化边界；
- 注册开关；
- 登录、`/me`、登出语义和过期处理；
- Vue 登录页、路由守卫、401 全局处理和身份展示；
- Token 不出现在 URL、日志或持久化构建产物中；
- 如果使用 `sessionStorage`，明确其安全边界并保证任意 401 后清理；
- 密码长度、Unicode/大小写规范化、禁用用户和角色实时回查；
- KB、File、Session、Message、Job、Evaluation、Backup 的所有权或管理员授权；
- 跨用户 IDOR、猜测 UUID、父子资源不一致和管理员接口越权测试；
- CORS 与实际 Vue 来源一致，生产不使用不受控通配符。

### 阶段 D：Mock/Real 完全隔离

1. `VITE_API_MODE` 缺失或非法时启动失败，不得默认进入 Mock。
2. Real 模式的 ID、状态、时间、数量、指标、进度和错误全部来自后端。
3. Mock 模式显著标记“演示数据”，不保存真实 Token，不发真实业务请求。
4. Real 网络失败、401、403、404、409、422、429 和 5xx 必须显示真实错误，不得返回 Mock 成功。
5. 建立测试证明 Real bundle 不导入或初始化 Mock 种子数据；Mock bundle 不需要后端。
6. 更新 `.env.example`、开发命令、构建命令和部署说明。

### 阶段 E：知识库、文件和持久化 Job

知识库至少覆盖：

- 创建、列表、详情、删除；
- 若 UI 保留更新/重命名，后端必须存在受测契约，否则移除或禁用；
- 当前选择、刷新恢复、空/加载/错误/不存在状态；
- 重名策略、所有权和关联资源删除；
- active、previous、building、cleanup 指针一致性；
- 删除前的非终态 Job、评估 pin、文件状态和 Collection 冲突检查。

文件至少覆盖：

- multipart 上传、合法文件名、路径边界、大小、扩展名、MIME/内容校验、空文件、编码和空 PDF；
- 文件落盘与 FileRecord 的失败补偿；
- 内容哈希、重复文件和幂等策略；
- `PENDING → PROCESSING → SUCCESS/FAILED` 合法迁移；
- `POST process → 202 Job`；
- 前端 Job 轮询、真实进度、取消、重试、刷新恢复和终态显示；
- 重复提交、并发处理、租约过期、服务重启和恢复次数上限；
- 解析、清洗、切分、Embedding、Chroma replace/upsert；
- 稳定向量 ID、run metadata、旧向量处理和部分写入恢复；
- `chunk_count`、`has_active_vectors`、`active_index_config_hash`、`last_successful_indexed_at`；
- 删除磁盘文件、数据库记录和向量时的顺序、冲突与补偿。

Job 通用验收：

- 原子 claim；
- lease owner/expiry、独立 heartbeat 和进度节流；
- 取消只在安全 checkpoint 生效；
- 最终提交与取消竞争时结果语义明确；
- 自动恢复与手工 retry 有次数上限和 retry 链；
- 409 冲突携带可操作错误；
- 前端卸载组件后停止轮询，不能泄漏请求。

### 阶段 F：Embedding、Chroma、索引版本

Embedding 至少验证：

- 实际配置的 provider/model/protocol，不硬编码与真实配置矛盾的值；
- 维度、L2 归一化、batch 上限和输入/输出数量；
- `text_index` 顺序和完整性；
- 延迟初始化；
- timeout、指数退避、429、认证失败、无效响应和服务不可用；
- 可选 base URL；
- 普通自动化使用依赖替身，不产生付费调用。

Chroma 与索引至少验证：

- `embedding_function=None`；
- 写入显式 embeddings，查询显式 query_embeddings，禁止 `query_texts`；
- HNSW cosine 与 metadata/config hash 一致；
- Collection 和向量 ID 稳定；
- active 指针是普通检索的唯一权威来源；
- 文件级幂等替换和部分写入清理；
- rebuild、rollback、abort-building、cleanup-retired；
- rebuild run、building started time 和候选完整性；
- 原子指针切换，失败不影响 active；
- rollback 指针交换；
- pinned Collection 不得被写入或清理；
- 遗留 building、悬空 Collection 和锁冲突恢复；
- CLI 只通过 HTTP 使用业务能力。

### 阶段 G：真实 RAG、流式协议、会话和引用

正式调用链必须可追踪：

```text
POST /api/chat 或 /api/chat/stream
→ 认证与资源归属
→ 固定知识库 active Collection
→ RetrievalService
→ 来源清洗、去重、阈值和字符预算
→ [S1]...[Sk]
→ Generation
→ 引用解析与合法性校验
→ 原子会话历史写入
→ ChatResponse/流式终态
```

至少验证：

- RagService 不绕过 RetrievalService 直接访问 Chroma；
- top_k、threshold、candidate multiplier 边界；
- score 方向和阈值语义正确；
- `file_id + chunk_id` 去重；
- 无来源时不伪造引用或有依据回答；
- 检索内容被视为不可信数据，明确 Prompt Injection 边界；
- 字符预算不会截断引用编号与来源映射；
- 正文引用只使用合法编号；
- SourceReference 与正文一一对应，不暴露绝对路径；
- 模型 timeout、429、认证失败、无效响应和不可用；
- NDJSON/流式客户端可处理任意网络分片、空行、错误事件、终态和半截流；
- 用户取消后不保存半条助手回答；
- 同步和流式历史写入语义一致；
- 会话创建、列表、详情、重命名和删除；若不保留重命名能力，正式 UI 不得留下无后端契约的入口；
- 用户消息、助手消息、引用、排序和分页持久化；
- 页面刷新恢复、会话切换不串消息、快速连续提问不串流；
- 重试策略不会重复保存用户消息或重复扣用外部调用。

### 阶段 H：Dashboard、Settings、Evaluation 与运维页面

Dashboard：

- 只使用真实统计或明确显示“暂无数据/暂不支持”；
- 不展示虚构 delta、问题数、趋势或处理进度；
- 时间范围和时区明确；
- ECharts 按需加载，组件销毁时 dispose；
- 空、加载、失败和无权限状态完整。

Settings：

- 区分前端偏好与服务端环境配置；
- Secret 永不回传明文，也不存入 localStorage/sessionStorage；
- 不得提供看似可保存、实际不生效的表单；
- 模型、Embedding、base URL、top_k、threshold、chunk size、overlap 等若允许修改，必须有真实持久化、范围校验、权限和审计；
- 影响向量空间的配置变化必须提示重建，并保证 config hash 正确；
- 仅由环境变量控制的项目应展示只读摘要和修改说明。

Evaluation：

- 使用固定 Collection 和配置；
- JSONL 数据集边界、大小、案例数和字段长度；
- 外部调用次数、token 和运行时间预算；
- 不写会话历史，不破坏生产数据；
- Job 取消、重试、恢复、报告原子落盘和下载校验；
- 指标分母正确，缺少 expected source 时不伪造检索正确率；
- 至少包含 Hit/Recall@K、MRR、答案要点、引用合法/越界/来源命中、延迟、失败类型和失败样例；
- 前端只展示报告真实存在的字段。

### 阶段 I：数据库、迁移与一致性

1. 核对 Model 与 Alembic head，覆盖用户、KB、文件、会话、消息、Job、评估、运行状态等实际表。
2. 检查主键、外键、`ondelete`、唯一/检查约束、索引、枚举、时间字段和事务边界。
3. 应用启动只校验 migration head，不得用 `create_all` 或运行时 `ALTER TABLE` 掩盖迁移缺失。
4. 所有迁移验证先在空库和真实数据库副本执行：

   - upgrade；
   - 数据与行数保持；
   - schema contract；
   - `integrity_check`；
   - foreign key check；
   - 必要且安全的 downgrade/upgrade。

5. 真实数据库 final cutover 不在无授权情况下执行。必须先有最新停机备份、独立目录恢复演练、逻辑指纹匹配和明确回退步骤。
6. 一致性检查至少识别：

   - DB 有记录但文件丢失；
   - 文件存在但 DB 无记录；
   - SUCCESS 无完整 active 向量；
   - 向量无 FileRecord；
   - active/previous/building/cleanup 指向不存在 Collection；
   - 遗留 PROCESSING/BUILDING；
   - 悬空 Collection；
   - Job 终态与业务资源状态矛盾。

7. 修复工具默认 dry-run，破坏性修复必须逐项明确目标。

### 阶段 J：安全、日志、指标、健康与备份恢复

安全检查至少包含：

- 文件名/路径穿越、覆盖、symlink 和超大输入；
- Markdown XSS、危险链接和外部资源；
- Prompt Injection；
- SQL 注入；
- CORS；
- 错误堆栈、绝对路径和 Secret 泄漏；
- 请求体限制和基础限流；
- 登录与 bootstrap 防滥用；
- 依赖漏洞的真实可达性；
- 生产 debug/reload 关闭；
- 安全响应头与正式前端托管边界。

日志与监控至少包含：

- UTF-8 结构化或结构稳定日志；
- request ID、user ID、KB/File/Session/Job/Rebuild run ID；
- 外部请求、检索和端到端耗时；
- 轮转与保留；
- 不记录 Authorization、正文、问题、回答或 Secret；
- live 只表示进程存活；
- ready 检查 SQLite、必要目录、Chroma 和 Job worker，不产生付费调用；
- 指标低基数、独立鉴权且不接受普通管理员 JWT 替代 scrape token；
- 磁盘空间或可写性检查有明确边界。

备份恢复至少包含：

- SQLite 一致快照；
- 上传文件；
- 经 Chroma API 的在线逻辑导出，不能热复制正在写入的物理目录；
- 评估报告和必要配置摘要；
- manifest、成员哈希、签名/HMAC；
- 全局写屏障和只读请求语义；
- 备份 Job 不自动续跑；
- ZIP 路径、重复成员、大小写冲突、symlink、成员数、大小、压缩比和 zip bomb 防护；
- 离线恢复到一个不存在的新目录；
- 全部校验通过后才原子改名；
- 恢复后检查 DB、文件、Collection、指针和历史；
- 保留策略默认 dry-run，禁止批量删除归档。

### 阶段 K：正式前端质量

所有主要页面至少检查：

- 登录/未登录；
- 空、加载、失败、无权限和不存在；
- 请求取消、重复提交和快速切换；
- 响应式布局，无横向溢出；
- 键盘操作、焦点恢复、对话框焦点陷阱、可读标签和基本对比度；
- 浏览器控制台无未处理异常；
- 网络面板无 Mock 请求、重复轮询风暴或 Secret；
- 刷新深层路由；
- 日期、时区、文件大小、状态和错误映射；
- 大列表的分页/限制；
- 生产构建代码分割、主要 chunk 和 sourcemap 策略；
- Markdown 使用安全渲染；
- 组件卸载时释放流、轮询、计时器和图表。

## 7. Docker 与正式部署

必须完成并核对：

- 后端镜像；
- Vue 生产构建与静态托管镜像；
- 反向代理或明确的 API Base URL；
- SPA fallback；
- 非 root 运行；
- 固定单 backend worker；
- SQLite、上传、Chroma、日志、备份和评估数据卷；
- 显式迁移步骤；
- Secret 快速失败；
- 上传限制、代理 timeout、流式响应不被错误缓冲；
- live/ready healthcheck；
- 日志轮转；
- 生产关闭 debug/reload；
- `docker compose down` 不附加 `-v`。

Docker daemon 可用时实际执行：

1. `docker compose config`；
2. 构建镜像；
3. 在测试数据卷上运行迁移；
4. 启动服务并等待 ready；
5. 打开 Vue 正式入口；
6. 登录；
7. 执行最小 Real 全链路；
8. 重启容器；
9. 验证数据、会话和 active 指针仍存在；
10. 执行在线备份；
11. 停止 API，在新目录做最小离线恢复；
12. 验证恢复后可启动和查询；
13. 查看健康、日志和浏览器控制台。

Docker daemon 不可用时，只能将上述项目标记为 blocked/not-run；`docker compose config` 通过不能替代镜像、容器和持久化验收。

## 8. 测试矩阵与最终门禁

先从真实配置读取命令，不盲目套用。至少覆盖：

### 后端

- compile/import；
- unit；
- Repository；
- Service；
- API；
- 认证与 IDOR；
- 文件失败与恢复；
- Chroma 失败与部分写入；
- DashScope 依赖替身；
- Job 并发、租约、取消、retry 和恢复；
- rebuild/rollback/cleanup；
- backup/restore 安全；
- evaluation；
- Alembic；
- live/ready/metrics；
- 启动边界与第二实例锁。

### Vue 前端

- type-check；
- lint；
- color lint；
- format check；
- unit；
- Real Adapter/Mapper/HTTP/stream parser 契约测试；
- mock build；
- real build；
- Mock E2E；
- Real E2E；
- 登录失效；
- 网络失败和各类后端错误；
- Job 轮询/取消/恢复；
- 流式取消和半截流；
- 响应式、键盘和无横向溢出；
- 浏览器控制台与网络请求检查。

### 全链路

使用隔离测试用户、测试数据库和测试存储执行：

```text
初始化管理员/登录
→ 创建知识库
→ 上传一份含可验证事实的文件
→ 提交处理 Job
→ 观察真实状态与进度
→ 等待成功
→ 同步或流式提问
→ 验证答案与引用确实来自上传文件
→ 验证会话和引用已持久化
→ 刷新页面并恢复
→ 提交索引重建 Job
→ 验证 active 原子切换
→ 回滚
→ cleanup
→ 删除文件
→ 删除知识库
→ 重启服务
→ 验证应保留的数据仍存在
```

另做失败链路：

- 未登录、Token 过期、跨用户访问；
- 后端不可达；
- 非法/空/超大/重复文件；
- 重复处理、重复重建和冲突操作；
- Embedding/Generation timeout、429、认证失败；
- Chroma 部分写入；
- 流式中断；
- worker 或服务在关键窗口重启；
- 数据库 revision 不在 head；
- 备份 draining 时业务写入。

## 9. 外部服务与付费调用策略

自动化测试默认使用依赖替身，不访问网络。真实 DashScope 只做最小 smoke：

- 必须有用户明确授权或项目规定的显式开关；
- 只使用一份最小文档和一到两个问题；
- 记录模型、Embedding 配置、调用次数、延迟和结果，不记录 Secret；
- 验证答案语义、引用编号、SourceReference 和持久化；
- 失败时保留真实错误，不降级 Mock；
- 不因一次人工成功宣称性能、稳定性或整体质量达标。

未获授权或无 Secret 时，将“真实外部 RAG”标为 blocked；不得因此阻塞可以继续完成的本地实现和替身测试，但也不得宣称“正式版本完成”。

## 10. 长任务续作与停止条件

这是大范围任务。不要为了在单次上下文内结束而缩减测试或制造乐观结论。

- 每完成一个阶段就更新三份文档，写明已完成、未完成、失败证据和下一步。
- 若运行时间或上下文不足，在最近的安全检查点停止，保证仓库可构建或明确记录当前失败状态。
- 交接时给出下一条可执行命令、所需前置条件和剩余 P0/P1。
- 只有以下情况才请求用户决策：

  - 需要选择会导致明显不同产品行为或架构的方案；
  - 需要真实数据迁移、删除或不可逆操作；
  - 需要真实付费调用；
  - 需要新 Secret、外部权限、Docker daemon 或用户手工操作；
  - 用户现有改动与修复发生无法安全合并的冲突。

- 普通实现细节、可逆代码修改和隔离测试不等待重复确认。

## 11. 完成等级与发布判定

最终只能选择一个等级：

| 等级 | 判定 |
| --- | --- |
| 未完成 | 存在未解决 P0，或核心 Real 链路不可用 |
| 代码完成、环境未验证 | 本地代码和替身测试通过，但 Docker 或真实外部服务被环境阻塞 |
| 发布候选 | Real 前后端、迁移副本、Mock/Real E2E 和 Docker 本地链路通过；仍有明确列出的部署环境事项 |
| 正式版本完成 | 核心 Real 链路、真实外部模型、持久化、异常恢复、迁移演练、Docker 重启持久化、备份恢复和全部发布门禁均实际通过 |

任一必要验证为 failed、blocked、skipped 或 not-run 时，不得选择“正式版本完成”。

适用性必须分别判断：

- 本地使用；
- 可信内网部署；
- 公网部署。

公网部署不能仅因功能测试通过而判定可用；必须同时满足认证、授权、Secret、TLS/反代、安全响应头、限流、备份恢复、监控和运维边界。

## 12. 最终报告固定结构

最终输出先给结论，再给证据，至少包含：

1. 完成等级和一句话依据；
2. 本次范围与未触碰范围；
3. 审计基线和仓库实际架构；
4. 已解决问题，按 P0/P1/P2；
5. 未解决问题、原因、影响和下一步；
6. 修改文件及用途；
7. 数据库迁移与真实数据库是否被修改；
8. API 契约变化与兼容性；
9. Mock/Real 隔离结果；
10. 认证与越权测试；
11. Job、文件、索引、RAG、会话、评估和备份结果；
12. 所有实际命令及退出码；
13. 后端测试、前端测试、Real 联调、浏览器和 Docker 结果；
14. skipped/blocked/not-run 项，禁止隐藏；
15. 依赖漏洞处理；
16. 性能、包体、延迟和资源变化；没有基线时明确写无基线；
17. 安全边界和剩余风险；
18. 本地/内网/公网适用性；
19. 用户接下来需要执行的最少步骤。

最终结论必须与证据表完全一致。不要用“所有测试通过”概括包含 skipped、未运行真实外部服务或未运行 Docker 的结果。
