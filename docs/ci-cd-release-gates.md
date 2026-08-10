# CI/CD 与生产发布门禁

## 自动 CI

`.github/workflows/frontend-build.yml` 的工作流名称为 `CI`，在 `main` 推送、Pull Request 和手动触发时运行。所有第三方 Action 固定到完整 commit SHA，工作流仅授予 `contents: read`。

并行检查及其稳定名称如下：

| Job | 覆盖范围 |
| --- | --- |
| `Python Ruff quality` | 独立安装 `requirements-dev.lock` 中的 Ruff 0.15.13，执行 E4/E7/E9/F 静态检查；开发工具不进入生产镜像 |
| `Backend locked tests` | Python 3.11.15、锁文件安装、pip check、compileall、完整 pytest |
| `Alembic fresh and round-trip` | fresh upgrade、downgrade/upgrade、离线恢复与最终切换契约 |
| `Frontend static and unit` | Node 24.14.0、npm ci、type-check、lint、颜色、Prettier、Vitest |
| `Vue Real and explicit Mock builds` | 默认 Real、Real 产物审计、显式 Mock 隔离构建 |
| `Production Compose contract` | Secret 展开、认证、迁移依赖和 healthcheck |
| `Production Docker health and restart` | 唯一临时卷、生产镜像、新卷迁移、健康、重启和非法生产配置拒绝 |
| `Mock browser E2E` | 隔离 Mock 浏览器回归，不接触付费服务 |
| `Deterministic Vue Real Docker E2E` | Vue Real—Nginx—FastAPI—SQLite—Chroma—Job、流式/停止/重试、401/5xx/后端断开 |
| `Dependency and secret security` | pip-audit、npm audit、Secret/发布树扫描、workflow 安全契约 |
| `Required checks` | 聚合以上结果；任何失败或跳过均失败 |

测试报告和依赖清单使用显式 allowlist 上传，不包含 `.env`、数据库、上传文件或真实 Secret。普通证据保留 14 天，浏览器 trace 保留 7 天。

## 受保护的生产门禁

`.github/workflows/production-gate.yml` 仅允许从 `main` 手动确认运行，或按受控周计划运行。它不会部署或推送镜像。

发布链路依次要求：

1. `Protected source commit` 确认来源为 `main`，手动运行还必须勾选确认项。
2. `Protected DashScope staging` 进入 GitHub `staging` Environment 后读取 Secret。无 `DASHSCOPE_API_KEY` 时明确记录 `BLOCKED_MISSING_SECRET` 并失败，不会生成生产证据。
3. DashScope 使用固定无业务数据提示、1024 维 Embedding、`qwen-turbo`、最多 16 tokens 和 20 秒超时，分别验证非流式与流式 Chat；429、超时和畸形响应由无网络契约测试验证。
4. `Release Vue Real chain` 运行完整确定性 Real Docker E2E；该结果不能冒充 DashScope staging。
5. `Restart and disaster recovery drill` 在测试临时目录和唯一 Compose 卷验证租约恢复、在线备份、离线恢复、SQLite/Chroma/上传/Manifest/HMAC、损坏成员、错误签名和路径穿越。
6. 只有前三项全部成功，才从同一 `GITHUB_SHA` 构建后端和 Vue Real 镜像，tag 与 OCI revision label 都使用完整 40 位 SHA。
7. 最终只上传 `release-manifest.json`、Python 依赖清单和 Node 依赖清单。manifest 中所有门禁必须为 `passed` 才允许 `production_candidate=true`。

需要在仓库 Settings → Environments 建立 `staging`：

- 添加必需 Secret `DASHSCOPE_API_KEY`；自定义端点才添加 `DASHSCOPE_BASE_URL`。
- 配置 required reviewers，只授权 staging 维护者。
- 禁止未受保护分支部署到该 Environment。
- 不要把生产数据库、用户数据或生产 API Key 用作 staging 输入。

Fork PR 只触发基础 `CI`，不会触发 production workflow，也不会引用任何 DashScope Secret。

## main 分支保护

具备仓库管理员权限后，在 Settings → Rules → Rulesets 为 `main` 创建 active branch ruleset：

1. 要求 Pull Request、至少一名审批者、对新提交撤销旧审批。
2. 要求分支在合并前更新。
3. 要求状态检查 `CI / Required checks`。
4. 禁止绕过规则；只给紧急维护角色受审计的 bypass。
5. 可选地同时要求九个明细 job，方便 GitHub UI 直接显示具体阻塞项。

生产发布不是 PR required check。发布负责人必须另外取得一次同 commit 的 `Production release gate / SHA-bound production images and evidence` 成功结果，并核对 artifact manifest 的 commit SHA。

## 本地等价验证

```powershell
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe -m pip install --requirement requirements-dev.lock
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m compileall -q app scripts ui tests
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe scripts/verify_security_policy.py
.\.venv\Scripts\python.exe scripts/verify_ci_contract.py

Set-Location frontend
npm ci
npm run type-check
npm run lint
npm run lint:colors
npm run format:check
npm run test:unit
npm run ci:build
Set-Location ..
```

Docker smoke、Mock E2E 和 Real E2E 命令见根 README 的完整验证段落。所有 Docker 测试生成唯一 Compose project 和测试卷，并在结束时仅清理该 project。

## 依赖安全例外

`security/pip-audit-policy.json` 是唯一允许的 pip-audit 例外来源。每项必须绑定锁文件中的准确版本、公开跟踪地址、具体隔离措施和不超过 30 天的到期日；`verify_security_policy.py` 在到期当天 fail closed。

ChromaDB 例外还必须声明责任人和复审日。当前责任人为 `repository-maintainers`，复审日为 2026-08-25，到期日为 2026-09-01；脚本在复审日或到期日当天 fail closed。`verify_chroma_boundary.py` 同时禁止生产代码使用 `HttpClient`、`AsyncHttpClient`、`chromadb.app`、server CLI、Chroma Compose 服务或服务端镜像，并要求保留本地 `PersistentClient`。如果出现不受影响的稳定版，必须升级并完成向量兼容、重建、回滚和全量门禁；若仍无修复版，只能重新审批并最多延长 30 天，且不得削弱本地隔离条件。

当前 ChromaDB 1.5.9 公告影响 Python HTTP server 和连接不可信服务器的 HttpClient。项目只使用本地 `PersistentClient`、应用自有 collection 配置和显式 Embedding，不启动 Chroma HTTP server。该临时例外于 2026-09-01 到期；届时若没有稳定修复版本，CI 将阻止合并和发布。
