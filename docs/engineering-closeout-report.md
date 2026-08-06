# 工程化收尾验收报告

报告时间：2026-07-26（Asia/Shanghai）

## 结论

工程化收尾的代码、自动化测试、真实旧库备份/恢复演练和迁移副本验证已经完成。当前真实数据库没有执行最终切换，仍保持原四表且无 Alembic revision；这是有意保留的安全边界，因为 `.env` Secret 和可登录 bootstrap admin 尚未由用户显式初始化，Docker daemon 也未运行。

## 已经实际通过

- `.venv\Scripts\python.exe -m compileall -q app scripts ui tests`：通过。
- `.venv\Scripts\python.exe -m pytest -q`：`195 passed, 1 skipped`。跳过项是必须显式提供 `RUN_DASHSCOPE_SMOKE=1` 与真实 `DASHSCOPE_API_KEY` 的 DashScope smoke test。
- 迁移自动化覆盖空库 upgrade、`0002` owner 回填与 batch recreate、规范化 Schema 比对、测试库 downgrade/upgrade、跨所有者同名时拒绝 downgrade、迁移前备份/恢复/最终切换保护和备份后数据库变化拒绝。
- 队列自动化覆盖 SQLite WAL/timeout、并发原子 claim、心跳、同阶段进度节流、租约 reaper、恢复次数上限、第二实例锁、备份不续跑、文件/重建关键崩溃窗口和操作冲突。
- 认证自动化覆盖 Unicode/大小写归一化、bcrypt 12–72 UTF-8 字节边界、每请求角色/启用状态重查、跨用户 KB/File/Session/Job 越权和管理员维护权限。
- 评估自动化覆盖 JSONL 所有资源上限、固定 Collection、无会话历史写入、调用预算、指标报告、原子报告恢复及受校验的报告下载。
- 在线逻辑备份/离线恢复集成测试实际使用 SQLite Backup API 和本地 Chroma，验证 BACKUP 自身在快照中失败、逻辑 Collection 内容往返、HMAC、成员哈希、重复/大小写冲突、路径穿越、symlink、非普通文件、成员/总大小和压缩比限制。模型/Embedding 使用测试替身。
- `docker compose config --quiet` 在显式测试 Secret 下返回 0；将生产 Secret 置空时 Compose 按预期快速失败。

## 真实旧库演练

真实数据库：`data/metadata/local_rag_chat.db`

- 当前状态：SQLite `integrity_check=ok`、外键违规 0、Alembic revision 为空。
- 历史行数：`knowledge_bases=1`、`file_records=0`、`chat_sessions=0`、`chat_messages=0`。
- 最新离线物理备份：`data/backups/pre-migration-verification-20260726-164300.zip`
- 归档 SHA-256：`0341f8f52b5cf337f6486021bef769780e211cf10462faddc4a878f48be99880`
- SQLite 逻辑指纹：`40f7edc54a6e5afe124d24810c2f05e568409cecf9bcd22d688b8aa1803b2083`
- 恢复演练目录：`<TEMP>/local-rag-chat-pre-migration-drill-20260726-164300`
- 迁移候选副本：`<TEMP>/local-rag-chat-migration-candidate-20260726-164300.db`
- 候选结果：revision `0002_auth_jobs_ownership`、完整性通过、外键违规 0、四张历史表行数迁移前后完全一致。
- 真实数据库复查仍为原四表、无 revision，证明演练未执行真实切换。

## 已实现的运行边界

- Alembic `0001_current_schema` 与 `0002_auth_jobs_ownership`，应用启动只校验 head。
- SQLite WAL、`busy_timeout=5000`、`synchronous=FULL`、短事务和 `UPDATE … RETURNING` claim。
- API 与单线程 worker 同进程，跨平台 OS 实例锁，Uvicorn/Compose 固定一个 worker。
- 每种 Job 的业务恢复器、两次执行上限、手工 retry 链、固定 Collection pin 和完整冲突检查。
- `NFKC + casefold` 用户身份、bcrypt 边界、JWT `sub` 实时回查、独立 metrics token、显式 Secret 初始化。
- writer-preferring 全局备份屏障；在线备份只做 Chroma API 逻辑导出，离线迁移前工具才归档停止状态的物理 Chroma。
- 评估数据上限、外部调用预算、原子 JSON 报告、检索/生成/引用/耗时/失败指标。
- 请求/Job 关联日志、文件与 Docker 日志轮转、live/ready、低基数 Prometheus 指标。
- 安全 ZIP 恢复到新目录，验证全部通过后才原子改名；失败 staging 保留供人工检查。
- Streamlit 登录、客户端 logout 语义和任意 401 后失效 Token 清理。

## 因环境原因未验证

Docker 客户端存在，但 `docker info` 无法连接 `npipe:////./pipe/dockerDesktopLinuxEngine`，因此没有执行或宣称以下项目通过：

- `docker compose build`
- `docker compose up -d`、容器 health/日志检查
- 容器重建后的持久化
- 容器内在线逻辑备份与离线恢复
- 真实 `qwen3-max` 最小 RAG 链路和引用结果

## 需要用户配置后执行

1. 显式创建 `.env` 并初始化 Secret：

   ```powershell
   Copy-Item .env.example .env
   .venv\Scripts\python.exe scripts\init_secrets.py --env-file .env
   ```

2. 在最终停机窗口重新生成一次最新迁移前备份并完成恢复演练；随后运行 `final-cutover`。工具会比较逻辑指纹，数据库在备份之后有任何变化都会拒绝切换。
3. 使用 `scripts/bootstrap_admin.py` 安全交互初始化可登录管理员，或首次启动后用 bootstrap Secret 调用一次接口。
4. 启动 Docker daemon 后依次执行：

   ```powershell
   docker compose build
   docker compose --profile tools run --rm migrate
   docker compose up -d
   docker compose ps
   ```

5. 提供真实 DashScope 配置后运行最小链路；需要执行真实 smoke test 时设置 `RUN_DASHSCOPE_SMOKE=1`。

## 剩余风险

- 设计目标是单机、单 API 进程、单业务 worker，不支持水平扩展。
- JWT 本阶段没有服务端撤销表；`jti` 仅追踪，logout 只清除客户端 Token。
- SQLite、Chroma 与上传目录不是共同事务；在线备份 Manifest 明确记录这一点。
- Chroma 1.5.9 在测试中产生 legacy embedding function 配置弃用警告，不影响当前测试结果，但后续升级 Chroma 时应重新验证配置序列化兼容性。
- Docker 与真实外部模型链路仍属于环境未验证项。
- 恢复失败目录和旧验证归档按安全策略不会自动批量删除，需要人工逐个核对处理。
