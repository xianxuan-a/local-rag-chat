# Local RAG Chat

## 安全凭据与泄露响应

`.env` 只属于当前机器，已被 Git 忽略，不得提交、截图、粘贴到聊天或写入日志。Secret 也不得放入任何 `VITE_*` 变量，因为该前缀会进入浏览器产物。首次初始化只补齐空值：

```powershell
python scripts/init_secrets.py --env-file .env
```

如果 JWT、metrics、备份或 bootstrap Secret 可能泄露，使用显式确认一次性轮换四项应用 Secret；命令只输出变量名，不输出新旧值，原子更新并保留其他变量、注释和顺序：

```powershell
python scripts/init_secrets.py --env-file .env --rotate-all --yes
docker compose up -d --force-recreate backend
```

轮换后，旧 JWT、旧 metrics token 和旧 bootstrap secret 应立即失效。`BACKUP_SIGNING_KEY` 轮换前生成的备份应视为不可信且不能再用新 Key 验签；不要删除旧备份，应立即生成新签名备份并在隔离目录完成恢复演练。外部服务 Key（例如 DashScope）必须在供应商控制台撤销并重新创建，新值只写本机 `.env` 和 GitHub 受保护的 `staging` Environment Secret。

## 许可证

仓库自有源码、文档和 `RAG.png` 按 [Apache License 2.0](LICENSE) 授权，归属信息见 [NOTICE](NOTICE)。第三方依赖及其资源继续适用各自许可证；分发者应同时保留相应依赖许可证和声明。

Local RAG Chat 是单机、单实例的本地知识库服务，包含认证与所有权、文件索引、版本化 Chroma Collection、会话历史、同步/流式 RAG、持久化 Job、固定 Collection 评估、在线逻辑备份及安全离线恢复。

## 可复现发布基线

发布候选必须绑定完整 Git commit SHA，并从该提交的全新 clone 验证，不能依赖原工作区中未跟踪的文件。`requirements.txt` 是人工维护的 Python 直接依赖清单，`requirements.lock` 锁定发布安装使用的完整传递依赖；前端使用 lockfile v3 的 `frontend/package-lock.json` 和 `npm ci`。Docker 后端同样只从 `requirements.lock` 安装。

支持范围为 Python 3.11 或更高、Node.js `^20.19.0 || >=22.12.0`、npm 10 或更高、Docker Engine 24 或更高、Docker Compose 2.20 或更高，以及 Git 2.39 或更高。本次基线验证环境的精确版本、文件分类和复现流程记录在 [`docs/release-baseline.md`](docs/release-baseline.md)。

每次发布前先运行仓库自带审计；`--require-clean` 会同时拒绝已修改或未跟踪的发布工作树：

```powershell
python scripts/verify_release_baseline.py --require-clean
```

审计会检查必需源码、迁移、测试、脚本、锁文件和 README 本地链接是否均被 Git 跟踪，并检查 ignore 边界、常见真实凭据特征、用户本机绝对路径及超过 10 MiB 的 tracked 文件。`.env`、数据库、Chroma、上传、备份、日志、PID、依赖目录和构建/Playwright 产物不得提交；`.env.example` 和五个不含 Secret 的前端模式配置必须保持可跟踪。

## 不可突破的运行边界

- FastAPI 与 Job worker 在同一进程运行，业务 worker 只有一个线程。
- Uvicorn 必须使用 `--workers 1`；进程启动会取得 `data/.instance.lock`，第二个实例立即失败。
- SQLite 使用 `WAL`、`foreign_keys=ON`、`busy_timeout=5000`、`synchronous=FULL`。
- 应用启动只校验 Alembic revision 等于 head，不会 `create_all`、运行 `ALTER TABLE` 或自动迁移。
- 应用、迁移和 bootstrap 都不会创建或修改 `.env`。只有用户显式运行的 `scripts/init_secrets.py` 可以写指定 env 文件。
- SQLite、Chroma 和上传目录不构成分布式事务。SQLite Backup API 只保证 SQLite 快照本身一致。
- 在线备份只经 Chroma API 逻辑导出，不复制正在运行的 Chroma 目录。Chroma 物理目录只允许在 API 已停止并取得实例锁后备份。

## 新环境初始化

需要 Python 3.11 或更高版本。

```powershell
python -m venv .venv
.venv\Scripts\activate
python -m pip install -r requirements.lock
Copy-Item .env.example .env
python scripts/init_secrets.py --env-file .env
Set-Location frontend
npm ci
Set-Location ..
.\scripts\init_local_runtime.ps1 -RuntimeRoot "D:\local-rag-runtime"
```

最后一条命令会在明确指定的目录创建数据库和
`.local-rag-runtime.json`，并在项目根目录原子写入本机专用的
`.local-rag-chat.json`。这些文件均被 Git 忽略。初始化器不会覆盖其他运行时，
也不会在失败后批量删除文件。不要另外对项目默认 `data` 目录执行
`alembic upgrade head`。

### Windows 本地启动

双击 `启动项目.cmd`，或在 PowerShell 中执行 `./启动项目.cmd`，会读取本机
`.local-rag-chat.json` 中固定的数据目录，并启动 FastAPI 与 Vue Real 开发服务器。
默认访问地址为 `http://127.0.0.1:5173/`；启动成功后自动打开浏览器。
启动器不会猜测、回退或自动切换到项目 `data` 目录。固定运行目录还必须包含
匹配的 `.local-rag-runtime.json` 身份文件；配置缺失或身份不一致时拒绝启动，
避免代码升级后误连另一套空库。

三个根目录入口都可从任意当前目录调用，路径含中文或空格也无需修改：

```powershell
./启动项目.cmd                 # 启动 Vue Real + FastAPI
./查看状态.cmd                 # 完整运行返回 0；停止/陈旧返回 3；检查错误返回 1
./停止项目.cmd                 # 正常停止和重复停止都返回 0
```

自动化或排错时可绕过 CMD 薄包装，直接调用同一套 PowerShell 核心逻辑：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\start_local.ps1 -NoBrowser
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\status_local.ps1
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\stop_local.ps1
```

停止入口只处理状态文件中项目根目录、运行时身份、PID、启动时间、可执行文件和
命令行全部匹配的进程。状态陈旧或 PID 已复用时会跳过该进程，绝不按端口强杀。
启动期间若前端失败，已启动的后端会自动回滚，临时状态不会冒充“运行中”。
状态写入采用同目录原子替换，并发启动/停止通过项目级互斥锁串行化。

启动器会检查 SQLite Schema 版本；版本落后时显示迁移范围并等待确认。确认后，
先在固定运行目录的 `backups/startup-migrations` 保留独立数据库备份，再迁移
数据库副本并原子切换；迁移失败不会替换原数据库。

需要使用其他本地运行目录时，可通过参数指定：

```powershell
./启动项目.cmd -RuntimeRoot "D:\local-rag-runtime"
```

也可设置 `LOCAL_RAG_RUNTIME_ROOT` 或直接设置 `LOCAL_RAG_DATABASE`，显式参数
优先于本机固定配置。若启动时临时指定了另一运行时，查看状态和停止时也要传入
相同参数；日常使用应通过初始化脚本更新固定配置。自动化的
本地环境可传入 `-AutoUpgrade` 跳过确认，传入 `-NoBrowser` 可禁止自动打开浏览器。
默认端口是后端 `8000`、前端 `5173`；需要与当前 Docker 栈并行验收时可使用：

```powershell
./启动项目.cmd -NoBrowser -BackendPort 18000 -FrontendPort 15173
```

再次启动时必须使用与当前状态相同的端口。日常使用建议在本地入口和 Docker
入口之间二选一；Docker 正式入口仍是 `http://localhost:8501`。
生产环境仍应遵循下文的备份、恢复
演练和停机切换流程，不应使用本地启动器自动升级。

启动日志位于固定运行目录的 `logs`。失败信息会给出该目录和修正建议；命令行
调用不会被 `pause` 阻塞，只有从资源管理器双击且发生错误时才等待用户确认。

在 `.env` 中显式配置 `DASHSCOPE_API_KEY`、`CHAT_MODEL` 及 Embedding 参数。生产环境缺少 `JWT_SECRET`、`METRICS_SCRAPE_TOKEN`、`BACKUP_SIGNING_KEY` 或 `BOOTSTRAP_SECRET` 时会快速失败。

API 停止时可离线初始化 bootstrap admin，密码从环境变量读取或安全交互输入，不出现在命令行参数中：

```powershell
$env:BOOTSTRAP_ADMIN_PASSWORD="<至少 8 个字符，最多 72 个 UTF-8 字节>"
python scripts/bootstrap_admin.py --username admin --email admin@example.com
Remove-Item Env:BOOTSTRAP_ADMIN_PASSWORD
```

也可在首次启动后调用一次 `POST /api/auth/bootstrap`，并提供 `X-Bootstrap-Secret`。成功后该入口拒绝重复初始化。

Swagger 位于 `http://localhost:8000/docs`。根入口不启动 Mock 或 Streamlit；
Mock 只用于下节的显式前端开发命令，Streamlit 只保留在 Docker `legacy` profile。

## Vue 前端与 Real/Mock 边界

Vue 前端位于 `frontend`。API 模式必须显式选择，Real 请求失败不会回退
Mock，也不会在前端伪造持久化、Job 进度或流式回答。

```powershell
Set-Location frontend
npm ci
npm run dev:real   # VITE_API_MODE=real，默认连接 http://127.0.0.1:8000
npm run dev:mock   # VITE_API_MODE=mock，仅使用隔离的内存 Mock Service
```

标准生产构建 `npm run build` 固定等价于 Real 构建并使用同源 `/`，不会把本地开发地址写入产物。Mock 只能通过显式命令构建：

```powershell
npm run build          # 标准入口：Real
npm run audit:real
npm run build:mock     # 仅用于 Mock 开发/测试
npm run test:build     # Real/Mock 各连续构建两次并验证旧 chunk 清理
npm run analyze:bundle # manifest 完整性、Dashboard 分包统计与预算门禁
npm run ci:build       # CI：确定性构建、Real 隔离审计与 bundle 预算
```

GitHub Actions 的 `Frontend build` 工作流在推送到 `main`、Pull Request 和手动触发时执行同一门禁；工作流只授予仓库内容读取权限。

Real 配置见 `frontend/.env.real`，Mock 配置见
`frontend/.env.mock`。两种模式不共享浏览器持久化状态，Mock 不注册网络
拦截器。构建产物分别写入 `frontend/dist-real` 和
`frontend/dist-mock`。每次构建只清理自身模式的输出目录，并生成
`build-meta.json`；其中 `build_mode`、`production_deployable` 和输出目录可供发布系统核验，未知或缺失模式会直接失败。

## P1 Dashboard

`GET /api/dashboard` 返回当前登录用户可见范围内的真实聚合，可选
`knowledge_base_id`、`window_days`（1–30）和 `recent_limit`（1–20）。
指标、文件状态、连续日期趋势、最近文件/会话/索引 Job/评测 Job 均由
SQLite 在后端聚合；时间窗口按 UTC 自然日计算。管理员沿用全局可见语义，
普通用户仅能看到自己的知识库和运行。响应只返回 Chat/Embedding 是否已配置，
不返回 Secret 内容。

Dashboard 的核心指标查询失败会返回明确错误；非核心最近记录或趋势查询单独失败
时，响应通过 `section_errors` 标记对应区域，前端展示“部分数据暂时不可用”，
不会用 Mock 数据补齐。

## 现有真实数据库迁移

所有开发、baseline、downgrade/upgrade 和数据检查必须针对副本。真实数据库只在最终停机窗口切换。

```powershell
# 1. 停止 API 后生成无新 Schema 依赖的离线物理备份
python scripts/pre_migration_backup.py `
  --output D:\backups\pre-migration-20260726.zip

# 2. 在一个全新目录完成恢复演练
python scripts/restore_pre_migration_backup.py `
  --archive D:\backups\pre-migration-20260726.zip `
  --target D:\restore-drills\pre-migration-20260726

# 3. 可先迁移任意副本并检查报告
python scripts/migrate_database.py copy-upgrade `
  --source data\metadata\local_rag_chat.db `
  --target D:\migration-tests\candidate.db

# 4. 仅在最终停机窗口切换真实数据库
python scripts/migrate_database.py final-cutover `
  --database data\metadata\local_rag_chat.db `
  --pre-migration-backup D:\backups\pre-migration-20260726.zip `
  --restore-drill D:\restore-drills\pre-migration-20260726
```

`copy-upgrade` 会规范化比较列、类型亲和性与长度、nullable、server default、主键顺序、外键及 `ondelete`、唯一/检查约束、索引列和 partial 条件，随后检查完整性、外键和历史表行数。`final-cutover` 还会校验恢复演练 marker 确实对应所选备份，并比较当前数据库与备份内 SQLite 逻辑指纹；停机备份之后只要数据库发生变化就拒绝切换。切换成功后保留原数据库文件。

当前 Alembic head 为 `0007_retrieval_modes`。`alembic downgrade -1`
只用于临时测试库。若不同所有者已存在同名知识库，`0002` 会明确拒绝
downgrade。应用不会迁移真实数据库；升级仍需用户在停机窗口显式执行。

## 认证边界

- 本地开发默认 `HOST=127.0.0.1`、`AUTH_REQUIRED=false`，前端不提供登录页，所有请求以迁移内置的本地单用户管理员身份执行。该身份具有管理员权限，因此免认证模式只能用于当前机器。
- 免认证只接受 `localhost`、IPv4 `127.0.0.0/8`、IPv6 `::1`（配置可写成 `[::1]`）。程序不会通过 DNS 证明其他主机名安全；`localhost.`、自定义主机名、通配地址、局域网 IP 和公网 IP 均要求 `AUTH_REQUIRED=true`。
- 监听 `0.0.0.0`、`::`，或通过容器/反向代理提供访问时必须启用认证。CORS 和 `X-Forwarded-For` 都不是访问控制，不能让不安全的免认证监听变得安全；不要把 loopback 免认证端口再通过本地代理暴露出去。
- 生产环境强制要求 `AUTH_REQUIRED=true`；关闭认证会在配置校验阶段直接拒绝启动。
- 仓库支持的后端入口是 `python run.py`，监听地址统一来自 `HOST`。当前启动体系不提供 Unix socket；直接使用 Uvicorn CLI 覆盖 `--host` 会绕过统一配置，不属于受支持部署方式。
- 用户名和邮箱保留展示值，`user_identities` 使用 `NFKC + casefold` 后的值作为全局唯一身份；用户名与其他账号邮箱之间也不能冲突，登录只通过该表定位唯一用户。迁移遇到跨账号冲突会输出脱敏摘要并安全失败，不自动改名或合并。
- 密码必须至少包含 8 个 Unicode 字符；由于使用 bcrypt，UTF-8 编码后不能超过 72 字节。首尾空格属于密码本身，不会被客户端或服务端裁剪；客户端会先做同样校验，服务端仍是最终安全边界。
- JWT 只以 `sub` 定位用户。每个请求都从数据库重新读取 `is_active` 和 `role`，不信任 token 中的旧权限。
- `jti` 只用于追踪，本版本没有撤销表。退出登录只是客户端删除 token；已经签发的 token 不会被服务端撤销。
- 用户注册由 `ALLOW_REGISTRATION` 显式控制；Compose 生产默认关闭。
- `/health`、`/health/live` 和 `/health/ready` 保持匿名，便于本机和容器健康检查；它们不提供管理员业务操作。`/metrics` 仍要求独立 scrape token。
- `/metrics` 不接受管理员 JWT 代替鉴权，必须提供独立长期请求头 `X-Metrics-Scrape-Token`。

认证敏感入口使用与单 worker 架构一致的进程内限流。登录失败同时累计来源 IP、`NFKC + casefold` 账号以及 IP+账号组合；默认窗口 300 秒，阈值分别为 50/10/5，达到阈值后从 2 秒开始指数退避，最大 300 秒。正确密码在冷却期间仍返回 429；成功登录只清理该账号和当前组合，不清理来源 IP 对其他账号产生的失败状态。注册按 IP 和规范化目标限制（默认每小时 20/5 次）；Bootstrap 使用更严格的 IP/全局限制（默认每小时 5/10 次）。429 响应包含整数秒 `Retry-After` 和 JSON `data.retry_after`，Vue 登录页会禁用提交并显示倒计时。

限流状态使用单调时钟、进程锁、有界 LRU key 集合和 TTL 清理；默认最多 10000 个匿名化 key，重启进程后状态会清空，因此当前保证仅对应仓库支持的单进程部署。安全日志只记录请求 ID、入口、限流维度、进程内匿名摘要和等待秒数；Prometheus 指标 `local_rag_auth_rate_limit_events_total` 只使用入口和有限维度标签，不包含账号、邮箱或 IP。`run.py` 关闭会输出完整对端 IP 的 Uvicorn access log，由不记录客户端地址的 `app.http` 请求日志统一替代。

客户端地址默认只取直接 TCP 对端，客户端自行发送的 `Forwarded` 或 `X-Forwarded-For` 不受信任。只有直接对端匹配 `TRUSTED_PROXY_CIDRS`，或匹配 `TRUSTED_PROXY_HOSTS` 的短期 DNS 解析结果时，程序才从代理链右侧跳过可信节点并选择第一个非可信地址；无效 header 会保守回退到直接对端。官方 Compose 只将 Docker DNS 中的 `frontend` 服务设为可信代理，Nginx 会把实际连接地址追加到 `X-Forwarded-For`。外部反向代理应优先把准确 IP/CIDR 加入 `TRUSTED_PROXY_CIDRS`，不要填写开放网络（例如 `0.0.0.0/0`），也不要仅因为收到代理 header 就扩大信任范围。

需要从局域网访问时，正确做法是生成 Secret、启用认证并显式设置非 loopback Host，而不是关闭校验：

```powershell
python scripts/init_secrets.py --env-file .env
$env:ENVIRONMENT="production"
$env:HOST="0.0.0.0"
$env:AUTH_REQUIRED="true"
python run.py
```

生产 Secret 应来自 `.env` 或部署系统的 Secret 注入；不要把真实值写进脚本、日志、构建参数或提交到 Git。`JWT_SECRET`、`METRICS_SCRAPE_TOKEN`、`BACKUP_SIGNING_KEY`、`BOOTSTRAP_SECRET` 必须至少 32 UTF-8 bytes、具备不低于 128 bits 的观测符号多样性，且四者不能使用相同值。`changeme`、`default`、`placeholder`、重复字符等明显弱值即使长度足够也会在应用监听端口前被拒绝。该检查不适用于 DashScope 等第三方 API Key。

推荐直接运行初始化器；它只补齐缺失或空值，每个用途都独立调用系统安全随机源，并且不会在终端打印 Secret：

```powershell
python scripts/init_secrets.py --env-file .env
```

如需人工注入部署系统，可分别运行下面任一命令四次，每次输出只分配给一个用途，切勿复制同一个值：

```powershell
python -c "import secrets; print(secrets.token_urlsafe(48))"
[Convert]::ToBase64String([Security.Cryptography.RandomNumberGenerator]::GetBytes(48))
```

轮换时应先做可恢复备份并逐项更换：更换 `JWT_SECRET` 会立即使现有 JWT 失效，用户需要重新登录；更换 `METRICS_SCRAPE_TOKEN` 必须同步更新采集器；更换 `BACKUP_SIGNING_KEY` 后新 key 无法验证旧备份，因此应在安全位置保留旧 key，并在切换前实际测试恢复；更换 `BOOTSTRAP_SECRET` 只影响尚未完成的首次管理员初始化，初始化成功后 bootstrap 接口仍由数据库状态阻止再次使用。当前版本没有双 key 兼容或自动轮换，不能以旧值回退启动校验。

主要认证接口：

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/api/auth/register` | 注册普通用户 |
| POST | `/api/auth/login` | 获取 Bearer JWT |
| GET | `/api/auth/me` | 返回数据库中的实时用户状态与角色 |
| POST | `/api/auth/bootstrap` | 使用 bootstrap Secret 初始化一次管理员 |
| GET | `/metrics` | 使用独立 scrape token 抓取 Prometheus 指标 |

管理员用户管理与审计接口：

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/users?limit=50&offset=0&query=&role=&is_active=` | 分页查询用户 |
| PATCH | `/api/users/{id}` | 修改角色/启停状态并记录可选原因 |
| GET | `/api/users/audit-events` | 分页读取不可修改的管理审计事件 |

普通用户调用管理接口返回 403；管理员不能降级或停用自己。服务层与 SQLite 触发器同时保护最后一个有效管理员，每次真实变更都记录操作者、目标、前后状态、原因、request ID 与时间。Vue `/users` 路由和导航只对 ADMIN 展示，但后端始终独立执行权限校验。

## 日志、健康检查与监控

- 控制台和 UTF-8 文件日志共用一套配置；`app.log` 按 `LOG_MAX_BYTES` 轮转并最多保留 `LOG_BACKUP_COUNT` 份。
- 统一请求中间件生成或校验 UUID `request_id`，响应返回 `X-Request-ID`，日志只记录 request/user ID、Method、路由模板、状态和耗时，不记录认证头、正文、问题或回答。
- `GET /health/live` 只判断进程存活；`GET /health/ready` 检查 SQLite、必要目录、Chroma heartbeat 和 Job worker，不调用 Embedding 或 Generation。`GET /health` 仅为旧客户端保留的 live 别名。
- `/metrics` 提供低基数的 HTTP 数量/错误/延迟、Job 终态/耗时、文件处理结果、Embedding/Generation 错误、检索耗时和 RAG 耗时指标。

## 持久化 Job

文件处理、知识库重建、retired cleanup、评估和在线备份均由 SQLite Job 执行。提交接口返回 `202`，客户端通过 `/api/jobs/{id}` 查询。

Job 使用 `run_after`、`lease_owner`、`lease_expires_at` 和 `retry_of_job_id`。抢占是条件 `UPDATE … RETURNING`，没有使用 SQLite 不支持的 `SKIP LOCKED`。业务调用不持有数据库写事务；独立心跳在线程阻塞于模型或 IO 时也会续租，进度写入至少间隔 1 秒。

| Job 类型 | 租约过期后的恢复 |
| --- | --- |
| `FILE_PROCESS` | 只恢复本 Job 拥有的 `PROCESSING`；核对目标、配置、分块数和向量 run 元数据。完整则补成功，部分写入则清除本 run 并完整 replace，不可验证则要求整库重建。 |
| `KB_REBUILD` | 校验 rebuild run、源指针、候选内每个文件的声明分块数和向量所有权。完整候选可继续切换，已切换则补成功，不完整候选标记失败后从头重建，指针变化则人工处理。 |
| `KB_CLEANUP_RETIRED` | 重新检查 cleanup 指针、Collection 是否存在以及评估 pin；无 pin 才幂等删除。 |
| `RAG_EVALUATION` | 报告已原子落盘但数据库尚未登记时，会校验路径、身份字段和完整结构并补记哈希后成功；否则从案例 0 写新 attempt。已预留预算不返还，剩余预算不足则失败。 |
| `BACKUP` | 永不自动续跑或自动 retry；清除 draining 并隔离单个 `.partial`。管理员手工 retry 会创建新的归档目标。 |

只有恢复器返回可重试后 Job 才会重新排队。文件、重建、cleanup 和评估 Job 最多执行两次；第二次仍需重跑时进入失败终态并要求手工 retry，等待评估 pin 不消耗该次数。取消在安全 checkpoint 生效；最终文件向量提交、Collection 指针切换或归档原子改名已经完成时，实际提交结果胜出。

Job 接口：

| 方法 | 路径 |
| --- | --- |
| GET | `/api/jobs/page?limit=50&offset=0` |
| GET | `/api/jobs`（弃用，下一版本删除） |
| GET | `/api/jobs/{id}` |
| POST | `/api/jobs/{id}/cancel` |
| POST | `/api/jobs/{id}/retry` |

## 操作冲突

- 同一文件处理去重；活动 Collection 被评估 pin 时拒绝文件处理。
- 同一知识库的文件维护、rebuild、rollback、abort、cleanup 和删除按资源状态与非终态 Job 互斥。
- 评估固定提交时的 Collection 和配置；rebuild 可以构建新候选，但不能清理被 pin 的旧 Collection。
- rollback 若会把 pinned Collection 变为写入目标则拒绝。
- File/KB 删除会检查所有引用资源的非终态 Job、Collection pin 及 `PROCESSING/BUILDING`。
- BACKUP 提交要求没有其他非终态 Job；提交请求先进入 writer-preferring 独占门闩，阻止新共享写并等待已有共享操作退出，再在同一临界区持久化 `BACKUP_DRAINING` 和 Job。
- 备份期间只读 GET 可继续；上传、注册、会话、聊天和同步维护写入被拒绝。心跳是控制面写入，可绕过业务屏障。
- 对应知识库进入 `BUILDING` 后，新上传、会话写入和聊天历史写入会被拒绝；已经固定旧 Collection 的评估可继续。

## 文件、重建与聊天接口

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST/GET | `/api/knowledge-bases` | 创建/列出当前所有者知识库 |
| GET/PATCH/DELETE | `/api/knowledge-bases/{id}` | 查询、更新名称/描述或安全删除 |
| POST | `/api/files/upload` | 上传并返回 `PENDING` |
| GET | `/api/files/page?knowledge_base_id=...&limit=50&offset=0` | 分页查询文件与总数 |
| GET | `/api/files?knowledge_base_id=...` | 弃用的数组响应，下一版本删除 |
| POST | `/api/files/{id}/process` | 返回 `202 FILE_PROCESS` Job |
| DELETE | `/api/files/{id}` | 安全删除文件与引用向量 |
| GET/PUT | `/api/settings` | 读取有效配置；管理员持久化安全业务配置 |
| POST | `/api/retrieval` | 基于活动 Collection 和 query embedding 执行独立检索 |
| POST | `/api/knowledge-bases/{id}/rebuild` | 返回 `202 KB_REBUILD` Job |
| POST | `/api/knowledge-bases/{id}/rollback` | 原子交换 active/previous |
| POST | `/api/knowledge-bases/{id}/abort-building` | 清理无人引用的失败候选 |
| POST | `/api/knowledge-bases/{id}/cleanup-retired` | 返回 `202 cleanup` Job |
| POST | `/api/chat` | 同步 RAG 与原子历史写入 |
| POST | `/api/chat/stream` | NDJSON 真流式 RAG；完成、失败和取消均持久化 |
| POST | `/api/chat/messages/{id}/retry/stream` | 原位重试已有助手回答 |
| POST | `/api/chat/messages/{id}/cancel` | 对精确消息发出协作式停止信号 |
| POST/GET/DELETE | `/api/sessions...` | 会话历史管理 |

Collection 创建/读取始终使用 `embedding_function=None`，写入使用预计算 embedding，查询只传 `query_embeddings`。数据库 active 指针是普通检索路由的权威来源；模型、维度、归一化、距离度量或协议变化后必须整库重建。

`product_settings` 持久化 Chat 模型、默认检索数量、分数阈值、RAG 上下文字符预算、全局联网开关、默认检索模式、最小证据数和时效词。API Key、Embedding 空间和基础设施参数仍只来自环境变量；Settings API 仅返回 Provider/密钥是否已配置，不返回任何密钥内容。

## 三种检索模式

- `knowledge_only` 仅调用活动 Collection，本地引用使用 `[Kx]`，联网 Provider 调用次数为零。
- `knowledge_first` 先执行本地检索，再按“异常、无结果、时效词、现有阈值、证据数量、确定性实体覆盖”的固定顺序决定是否联网。
- `hybrid` 在统一时间预算内并行执行本地与联网分支；单侧成功可降级，双侧没有可靠证据时不调用生成模型。

在线模式依次受全局开关、用户角色和知识库 `web_access_policy` 约束；知识库的 `allow` 不能绕过上层禁令。网页引用使用 `[Wx]`。当前仓库默认安装显式的 `disabled` Provider，因此未接入指定供应商前会返回 `not_configured`，不会伪造搜索结果或回退 Mock。

联网查询只使用当前问题，经 NFKC 规范化、隐私脱敏和长度校验后交给 Provider；日志仅记录脱敏查询的 SHA-256 摘要。抓取器逐跳只解析一次 DNS，拒绝含任意非公网结果的域名，再把 TCP 连接固定到已验证 IP；HTTPS 仍使用原域名执行 Host、SNI 和证书校验。带凭据 URL、公网到私网重定向、非文本/压缩内容和超限响应都会被拒绝。知识库与网页正文都按不可信数据处理，高风险提示注入段不会进入生成上下文。

## 固定 Collection 评估

`POST /api/evaluations` 接受 multipart JSONL，提交时固定 `knowledge_base_id`、`collection_name`、Embedding 配置哈希、数据集 SHA-256、`top_k` 和 threshold。评估直接调用纯检索与生成服务，不创建 Session 或 Message。

资源上限：

- 文件 5 MiB，最多 100 个案例，单行 64 KiB。
- `question` 最多 4000 字符。
- `expected_answer` 为 1–20 个答案点，每项最多 500 字符。
- source ID 最多 100 个；tag 最多 20 个且每项最多 64 字符。
- 每案例最多一次检索 Embedding 和一次 Generation。
- 提交时必须给出足够的总调用数、生成 token 和运行时间预算；调用前原子预留，崩溃后不重复使用已预留预算。

报告先写 attempt 临时文件，再用 `os.replace` 原子覆盖。每个案例的错误独立记录。
机器报告同时给出 Hit@K、Recall@K、MRR、平均检索耗时、回答成功率、答案要点召回、引用格式合法率、引用越界率、引用来源命中率、平均生成/端到端耗时和失败类型分布；未提供预期 source ID 的案例不会被伪计入检索正确率分母。
成功后可通过 `GET /api/evaluations/{job_id}/report` 获取经过路径、大小和 SHA-256 校验的报告。

```powershell
python scripts/evaluate_rag.py `
  --knowledge-base-id <uuid> `
  --dataset dataset.jsonl `
  --token <jwt> `
  --report-output evaluation-report.json
```

## 在线逻辑备份与离线恢复

管理员调用 `POST /api/backups` 或 HTTP-only CLI：

```powershell
python scripts/backup.py submit --token <jwt>
```

BACKUP 在独占写屏障中执行 SQLite Backup API 快照，并将快照内所有非终态 Job 改为恢复失败；其中 BACKUP 使用 `RESTORED_BACKUP_NOT_RESUMED`。它通过 Chroma API 分批导出 active/previous/cleanup 指针引用的 Collection，保存配置、元数据、ID、文档、embedding 和 metadata，同时归档上传文件、评估文件及安全配置摘要。

Manifest 对每个成员记录 SHA-256，并用独立 `BACKUP_SIGNING_KEY` 对规范化 JSON 做 HMAC-SHA256。哈希证明完整性，HMAC 验证备份来源；它们不把多存储系统变成共同事务。

恢复只能在 API 停止后写入一个不存在的新目录：

```powershell
python scripts/restore_backup.py `
  --archive data\backups\online-logical-....zip `
  --target D:\restores\local-rag-restored
```

恢复不使用 `extractall`，会拒绝重复成员、Unicode/Windows 大小写冲突、绝对路径、盘符、UNC、`..`、NUL、symlink、非普通文件、超额成员/单文件/总大小/压缩比、无效 HMAC、无效 Manifest 和成员哈希。逐成员流式写入并持续校验 staging 边界。验证数据库指针、Collection 配置与数量后才原子改名；失败 staging 保留供人工检查。

备份保留策略默认只 dry-run 列出过期归档；实际清理每次必须用 `scripts/backup.py` 明确删除一个文件，不提供批量删除。

## HTTP-only 运维 CLI

```powershell
python scripts/rebuild_kb.py --knowledge-base-id <uuid> --token <jwt>
python scripts/rebuild_kb.py --knowledge-base-id <uuid> --rollback-to-previous --token <jwt>
python scripts/rebuild_kb.py --knowledge-base-id <uuid> --abort-building --token <jwt>
python scripts/rebuild_kb.py --knowledge-base-id <uuid> --cleanup-retired --token <jwt>
```

`rebuild_kb.py`、`evaluate_rag.py` 和在线 `backup.py` 不直接打开 SQLite 或 Chroma。

## Docker

Compose 的正式 `frontend` 是 Vue Real：Node 24 builder 执行 `npm ci`、Real 构建和 manifest 图审计，运行镜像只包含 `dist-real` 与非 root Nginx。Nginx 在容器内监听 8080，主机仍默认使用 `http://localhost:8501`；同源 `/api` 直接代理 `backend:8000`。Compose 通过 `python run.py` 统一读取监听配置，并固定 backend `HOST=0.0.0.0`、`workers=1`、`AUTH_REQUIRED=true`、认证限流开启以及可信代理主机 `frontend`。生产环境不能关闭认证或认证限流；Compose 使用 `${NAME:?required}` 在创建容器前拦截缺失 Secret，应用配置模型再于监听端口前校验长度、明显弱值、符号多样性和用途隔离。

Compose 镜像 tag 可通过 `IMAGE_TAG` 覆盖；发布门禁固定传入完整 commit SHA，并验证镜像 OCI revision label 与 SHA 一致。CI/CD jobs、DashScope staging、恢复演练、artifact allowlist 和 main 分支保护操作见 [CI/CD 与生产发布门禁](docs/ci-cd-release-gates.md)。仓库不会自动部署生产。

后端镜像基于固定的 Python 3.11 runtime，并从 `requirements.lock` 安装完整传递依赖；更新 `requirements.txt` 后必须在干净环境重新解析锁文件、运行完整验证并与代码一起提交，不能只更新直接依赖清单。

后端与前端 Docker context 均采用 deny-by-default allowlist：只向构建器发送锁文件、运行源码、迁移、必要脚本和静态构建配置。宿主机 `.env*`、`.git`、虚拟环境、`node_modules`、测试/Playwright 产物、数据库、Chroma、上传、日志和备份不会进入 context。两个 Dockerfile 也只执行显式 `COPY`；后端通过独立依赖阶段从 `requirements.lock` 安装并校验依赖，前端通过 Node builder 的 `npm ci` 生成 `dist-real`，两个运行镜像都不携带宿主依赖、测试文件或构建期源码。修改 Dockerfile 输入时必须同步更新对应 `.dockerignore` allowlist，并重新执行无缓存和缓存构建。

首次部署先从示例生成本机 `.env`，不要把生成后的值提交到仓库：

```powershell
Copy-Item .env.example .env
python scripts/init_secrets.py --env-file .env
```

标准启动会自动运行一次性 `migrate` 服务。迁移入口与 API 取得同一个实例锁，避免对同一 SQLite 并发迁移；只有迁移成功后 backend 才会启动。backend 随后再次校验数据库 revision，迁移失败不会出现假健康服务：

```powershell
docker compose config -q
docker compose build --no-cache backend frontend
docker compose build --progress=plain backend frontend
docker compose up -d
docker compose ps
Invoke-WebRequest http://localhost:8501/healthz
Invoke-WebRequest http://localhost:8000/health/live
Invoke-WebRequest http://localhost:8000/health/ready
```

默认构建源为官方 PyPI。受限网络可在 `.env` 中设置 `PIP_INDEX_URL` 为组织批准的镜像；该值只影响镜像构建，不会写入应用运行配置。

可用 `docker history local-rag-chat:0.1.0` 和 `docker history local-rag-chat-frontend:0.1.0` 检查层输入，再用临时容器检查 `/app` 与 `/usr/share/nginx/html`；运行镜像中不应出现 `.env`、`.git`、数据库、上传、测试产物或前端 `node_modules`。

`/health/live` 只表示 FastAPI 进程存活；`/health/ready` 还会校验 SQLite、Alembic head、全部持久目录、Chroma 和 Job worker。前端 `/healthz` 只检查 Nginx/静态服务，启动顺序仍要求 backend healthy。主机端口可用 `.env` 中的 `BACKEND_PORT`、`FRONTEND_PORT` 调整，容器内端口保持 8000/8080。Nginx 模板默认允许 `21m` multipart 请求、普通 API 读取超时 `75s`，后端仍精确执行默认 20 MiB 文件限制；代理和后端的超限响应都保持 JSON 413。

Vue History 路由（例如 `/dashboard`、`/chat`、`/knowledge-bases`、`/settings`）都回退到 `index.html`，且使用 `no-cache`；带 hash 的 `/assets/` 使用一年 `immutable` 缓存和静态 gzip。`/api` 永不进入 SPA fallback，FastAPI 的 Bearer、`X-Request-ID`、JSON envelope 和 HTTP 状态码会原样穿过；Chat NDJSON 流与 retry 流关闭代理 buffering 和 gzip。

Streamlit 作为兼容入口保留，但不参与默认启动。需要时单独启用 `legacy` profile，默认访问 `http://localhost:8502`：

```powershell
docker compose --profile legacy up -d legacy-ui
```

整套停止或重建容器时使用 `docker compose down`，随后再次执行 `docker compose up -d`；迁移是幂等的，命名卷会保留。版本升级前必须先停止旧 backend，否则 migrate 会因实例锁被占用而明确失败。不要附加 `-v`，否则会删除持久卷。

故障排查：

```powershell
docker compose ps -a
docker compose logs migrate
docker compose logs backend
docker compose logs frontend
docker compose config --format json
```

- `variable is required`：`.env` 缺少生产 Secret；重新运行 `init_secrets.py` 只会补齐空值，不会替换已有值。
- `Secret 不符合强度策略` 或 `用途隔离失败`：已有值过短、明显可预测或被多个用途复用；初始化器不会擅自覆盖它，必须先备份并按上面的影响说明手动轮换对应项。
- migrate 非零退出：backend 会保持未启动；先根据 migrate 日志修复数据库/卷权限或迁移问题，再重新 `docker compose up -d`。
- backend 非零退出：检查生产认证、Secret 强度、数据库 revision 和实例锁日志，不要用 `AUTH_REQUIRED=false` 或 `ENVIRONMENT=development` 绕过。
- backend 为 `unhealthy`：直接查看 `/health/ready` 返回的失败检查项和 backend 日志。

本地 Python 开发仍沿用 `.env.example` 的 `ENVIRONMENT=development`、`HOST=127.0.0.1`、`AUTH_REQUIRED=false`；Windows 启动器也会显式覆盖为相同 loopback。Compose 固定使用生产认证和非 loopback Host，不接受本地免认证默认值。

## 验证

```powershell
python scripts/verify_release_baseline.py
pytest -q
python -m compileall app scripts ui tests
# 需要正在运行的 Docker daemon；测试只创建并清理唯一项目名下的新卷。
$env:RUN_DOCKER_COMPOSE_SMOKE=1
$env:COMPOSE_SMOKE_PIP_INDEX_URL="https://mirrors.aliyun.com/pypi/simple"
pytest -q tests/test_compose_smoke.py
Remove-Item Env:RUN_DOCKER_COMPOSE_SMOKE
Remove-Item Env:COMPOSE_SMOKE_PIP_INDEX_URL
Set-Location frontend
npm run type-check
npm run lint
npm run lint:colors
npm run test:unit
npm run build
npm run audit:real
npm run build:mock
npm run test:build
npm run analyze:bundle
npm run test:e2e
```

完整的容器 Real 浏览器验收使用唯一 Compose 项目与新卷，外部模型由测试专用确定性本地 provider 替换，其余 FastAPI、SQLite、Chroma、Job worker、NDJSON 代理和刷新持久化均为真实链路：

```powershell
$env:RUN_DOCKER_FRONTEND_E2E=1
pytest -q tests/test_frontend_compose_e2e.py
Remove-Item Env:RUN_DOCKER_FRONTEND_E2E
```

普通测试不访问网络，真实 DashScope 测试默认跳过。Docker daemon、真实 `qwen3-max` 链路、容器重启持久化、在线备份和离线临时恢复需在具备对应环境与 Secret 后单独验收。

服务重启时会重新加载持久化 Settings，将遗留流式消息标记为失败，并由
持久化 Job 恢复器处理可验证的文件、索引和评测运行；前端页面刷新只恢复服务器
状态，不会续接旧浏览器请求。跨进程续流、分布式 Worker 和水平扩展不在 P1
支持范围内。

参考边界：[Chroma backup guidance](https://cookbook.chromadb.dev/strategies/backup/)、[SQLite Backup API](https://www.sqlite.org/backup.html)、[Alembic SQLite batch migration](https://alembic.sqlalchemy.org/en/latest/batch.html)、[Python ZIP security guidance](https://docs.python.org/3.13/library/zipfile.html)。

P1 四轮实现与本次实测结果见
[`docs/p1-closeout-report.md`](docs/p1-closeout-report.md)。
