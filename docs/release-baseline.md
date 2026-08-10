# Git 发布基线

本文定义从一个明确 commit SHA 复现 Local RAG Chat 的最小发布门禁。发布证据必须来自全新 clone，不能从原工作区复制缺失文件，也不能用忽略规则隐藏必要源码。

## 文件分类

必须跟踪：

- `app/`、`ui/`、`frontend/src/` 与前端 E2E 源码；
- `alembic.ini`、`alembic/env.py` 和全部 `alembic/versions/`；
- `tests/`、`scripts/`、三个 Windows CMD 入口和 `run.py`；
- Dockerfile、Compose、Nginx、Vite、Vitest、Playwright 配置；
- `requirements.txt`、`requirements.lock`、`requirements-dev.lock`、`ruff.toml`、`frontend/package.json` 和 `frontend/package-lock.json`；
- Apache-2.0 `LICENSE`、`NOTICE` 和保留的项目资源 `RAG.png`；
- README、`docs/`、`.env.example`、前端公开的模式配置与 `data/**/.gitkeep`。

必须忽略：

- `.env` 及未显式公开的 `.env.*`、Secret 目录、私钥和证书私钥；
- `.venv`、`node_modules`、Python/前端工具缓存；
- SQLite、Chroma、上传、聊天记录、备份、评测报告、日志、PID 和本机运行身份；
- `dist-*`、coverage、Playwright report/test-results 和视觉验收产物。

需要用户确认：

- 来源不明的业务数据、截图、报告或大文件不能自动删除、忽略或提交；
- `RAG.png` 是保留的项目图片。曾与它逐字节相同且无有效引用的 `ChatGPT Image 2026年7月22日 01_55_53.png` 已按明确审核计划精确删除，未执行批量清理。

## 依赖与工具

- Python：支持 3.11+；容器发布 runtime 为 3.11.15。
- Node.js：`^20.19.0 || >=22.12.0`；容器 builder 为 Node 24 Alpine。
- npm：10+；`packageManager` 记录 npm 11.9.0，lockfileVersion 为 3。
- Ruff：开发/CI 固定为 0.15.13，只检查 E4/E7/E9/F；不安装进生产镜像。
- Docker Engine：24+；Docker Compose：2.20+；Git：2.39+。

D-005 建立时的实际验证工具为 Python 3.13.13、pip 26.1.1、Node 24.14.0、npm 11.9.0、Docker Engine 29.3.1、Docker Compose 5.1.1 和 Git 2.54.0.windows.1。最低支持范围不是对所有旧版本的穷举测试；精确发布证据以最终 commit 的 CI/验收记录为准。

`requirements.txt` 仅列直接依赖，供评审依赖意图；`requirements.lock` 是发布与 Docker 安装输入，锁定完整传递依赖。前端安装只能使用 `npm ci`。任何依赖清单变化都必须同时更新对应锁文件并重新执行隔离 clone 验证。

## 发布门禁

在候选工作树中执行：

```powershell
python scripts/verify_release_baseline.py
python scripts/verify_security_policy.py
python scripts/verify_chroma_boundary.py
python scripts/verify_ci_contract.py
python -m pip install --requirement requirements-dev.lock
python -m ruff check .
python -m compileall app scripts ui tests
pytest -q
docker compose config -q
Set-Location frontend
npm ci
npm run type-check
npm run lint
npm run lint:colors
npm run test:unit
npm run build
npm run audit:real
npm run build:mock
Set-Location ..
git diff --check
```

审计脚本检查必需路径与目录、ignore 正反例、README 本地链接、常见真实 Token/私钥/带凭据连接串、本机用户绝对路径、未忽略文件和 tracked 大文件。测试代码中的显式 fake/test 值不是生产凭据；仍会扫描具备真实格式的 Token 特征。

## 隔离 clone 复现

候选变更先形成一个语义明确的 commit，再从该 commit clone 到新的隔离目录：

```powershell
git clone --no-local D:\path\to\local-rag-chat D:\release-check\local-rag-chat
Set-Location D:\release-check\local-rag-chat
git checkout --detach <完整 commit SHA>
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.lock
Set-Location frontend
npm ci
Set-Location ..
```

随后在 clone 内执行迁移、后端测试、前端门禁、Real/Mock 构建、Compose 配置和至少一次 loopback 启动 smoke。结束后执行：

迁移入口有意拒绝隐式数据库位置；隔离验证必须明确指向 clone 内的测试库：

```powershell
$env:DATA_DIR="data"
$env:DATABASE_URL="sqlite:///./data/metadata/release-baseline.db"
.venv\Scripts\python.exe scripts/run_migrations.py
Remove-Item Env:DATA_DIR
Remove-Item Env:DATABASE_URL
```

不要对真实数据库或原工作区数据目录运行这条复现命令。随后检查发布工作树：

```powershell
python scripts/verify_release_baseline.py --require-clean
git status --short --untracked-files=all
```

生成的数据库、缓存和构建产物应全部被忽略，因此发布工作树仍为空。最终报告必须记录实际候选/发布 SHA、每条命令结果以及任何未执行项目的原因。
