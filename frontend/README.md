# Nexus RAG 前端

Nexus RAG 是一个本地知识库智能问答与检索管理前端。它支持确定性内存 Mock，以及知识库、文件、设置、检索、Sessions 和真实 NDJSON Chat 的 Real API 链路。

## 环境要求

- Node.js `^20.19.0 || >=22.12.0`
- npm

## 启动

Mock 模式：

```bash
cd frontend
npm install
npm run dev:mock
```

Real 模式需要先启动仓库根目录的 FastAPI：

```bash
python run.py
cd frontend
npm run dev:real
```

环境变量：

```env
VITE_API_MODE=real
VITE_API_BASE_URL=http://127.0.0.1:8000
VITE_API_TIMEOUT_MS=15000
```

`VITE_API_MODE` 必须明确为 `mock` 或 `real`；非法或缺失会直接报配置错误。Real 模式请求失败时不会加载或回退 Mock。`VITE_API_BASE_URL` 接受绝对 HTTP(S) 地址或安全的单斜杠根相对路径；拒绝 `//host`、凭据、query 和 fragment。前端可见的 `VITE_*` 变量不得保存 Secret。

`dev:real` 继续使用 `.env.real` 的 `http://127.0.0.1:8000`。标准 `npm run build` 等价于 `build:real`，固定以同源 `/` 构建，适用于仓库中的 Nginx 代理；Mock 只能由 `npm run build:mock` 显式生成。每次构建由 Vite 在独立的 `dist-real` 或 `dist-mock` 中执行 `emptyOutDir` 清理，不共享目录。每个产物根目录都有确定性的 `build-meta.json`，发布系统可核验 `build_mode` 与 `production_deployable`。`npm run audit:real` 会扫描 manifest 当前模块图和实际产物，确认正式包不包含 Mock 标识、fixtures、Mock 上传路径或本地开发 API 地址。

`npm run test:build` 会对 Real/Mock 各连续构建两次，比较完整文件清单与 SHA-256，并放入旧 chunk 哨兵验证构建前清理。`npm run analyze:bundle` 校验 manifest/index 引用、Dashboard 异步图表边界和 500 kB chunk 上限，并将 raw/gzip/brotli 统计写入 `artifacts/ci/bundle-report-*.json`。Dashboard 路由与基础指标先加载，ECharts/ZRender 仅在有图表数据时通过带 loading/error 状态的异步组件请求。

Docker build context 使用 deny-by-default allowlist，只包含 package lock、Vite/TypeScript 构建配置、`src`、`public`、Real 构建审计脚本和 `nginx.conf.template`；宿主 `node_modules`、`.env*`、dist、测试、截图与 Playwright 报告不会发送给构建器。Dockerfile 使用显式 `COPY`，依赖只能由 Linux builder 内的 `npm ci` 安装，最终非 root Nginx 镜像只复制 `dist-real`。

Mock 变更只存在于当前页面运行内存中。刷新页面后会恢复固定 ID、固定时间和固定排序的种子数据，不使用 `localStorage` 假装持久化，也不会发出真实业务网络请求。

## Real 模式认证边界

后端知识库、文件和 Job API 要求 Bearer JWT。Real 模式访问受保护路由时会自动进入 `/login`，同一页面可切换“登录/注册”：注册通过 `/api/auth/register` 创建普通用户，然后通过 `/api/auth/login` 自动登录；登录后调用 `/api/auth/me` 校验当前用户。密码规则统一为至少 8 个字符、最多 72 个 UTF-8 字节。登录页使用项目内置的 GSAP 依赖绘制黑白语义星图，不依赖 CDN；系统启用“减少动态效果”时会切换为静态图景。

令牌只保存在当前标签页的 `sessionStorage`，不会写入 `localStorage`、URL、源码或 `VITE_*` 环境变量。关闭标签页后需要重新登录；后端返回 `401` 或 JWT 到达 `exp` 时，前端会清除令牌并携带原路由跳回登录页。退出登录只清理浏览器会话，因为后端使用无状态 JWT。

登录接口返回 429 时，HTTP 客户端会读取同源或 CORS 暴露的 `Retry-After`，登录按钮在对应秒数内保持禁用并显示倒计时；倒计时结束后才允许重新提交。页面不会根据账号是否存在展示不同错误。

注册是否真正开放由服务端 `ALLOW_REGISTRATION` 决定。Windows 本地服务默认允许；正式 Compose 安全默认值为 `false`，需要注册时必须在根 `.env` 中显式设置 `ALLOW_REGISTRATION=true` 并重启 backend。客户端即使显示注册表单，也不能绕过服务端的开关、唯一性校验、密码规则或注册限流。

## 客户端与服务端边界

- 客户端是浏览器中运行的 Vue 应用，负责页面、输入提示和调用 `/api`；不能持有服务端 Secret，所有客户端校验都只能改善体验。
- 服务端是 FastAPI、SQLite/Chroma 和 Job worker，负责认证授权、最终数据校验、持久化、模型调用和限流；所有可信决策必须在这里执行。
- Docker 中 Nginx 提供客户端静态文件，并把同源 `/api` 转发到 FastAPI。Nginx 是入口/代理，不代替服务端业务校验。

Mock 模式的业务路由不要求登录，也不会调用认证接口。开发者仍可直接打开 `/login` 检查页面和表单交互；页面会明确显示 `MOCK MODE`，提交只说明认证边界，不写入 Token 或伪造成功，并可通过“进入工作区”返回 Dashboard。

Real 模式支持的真实文件类型以后端当前配置为准：PDF、TXT、CSV、JSON。文件处理接口返回持久化 Job，前端查询 `/api/jobs/{id}`，终态后重新读取服务端文件记录；不会在浏览器中伪造成功或分块数量。

## 质量命令

```bash
npm run type-check
npm run lint
npm run lint:colors
npm run format:check
npm run test:unit
npm run build
npm run audit:real
npm run build:mock
npm run test:build
npm run analyze:bundle
npm run ci:build
npm run test:e2e
```

仓库 `.github/workflows/frontend-build.yml` 在 GitHub Actions 中使用 Node 24 执行相同的安装、静态检查、单测与 `ci:build` 门禁。

默认 `test:e2e` 使用 `vite preview` 检查 Mock 构建。设置 `NEXUS_E2E_BASE_URL` 后不会启动 preview，而是直接测试指定的已部署入口；容器 Real 验收由根目录 `tests/test_frontend_compose_e2e.py` 编排。视觉 QA 截图保存在 `artifacts/visual-qa/`。

## 路由部署

应用使用 Vue Router History 模式。仓库 `nginx.conf.template` 将 `/dashboard`、`/chat` 等未知文件路径回退到 no-cache 的 `index.html`，但 `/api` 与 `/api/*` 始终代理 FastAPI，永不进入 SPA fallback。模板从 Compose 接收上传大小和普通 API 超时，Chat NDJSON stream/retry 仍使用 3600 秒并禁用代理 buffering、request buffering 和 gzip。`/assets/` 使用一年 immutable 缓存；Nginx 413 返回统一 JSON envelope，502/504 且没有后端 envelope 时，客户端显示真实“后端服务不可达”错误，不会切换 Mock。

## Real API 维护点

第一阶段接口集中在：

- `src/api/config.ts`：严格环境配置。
- `src/api/http.ts`：JSON、查询参数、multipart、超时、取消和错误。
- `src/api/mappers.ts`：后端 snake_case DTO 到前端领域模型。
- `src/api/adapters/realAdapter.ts`：知识库、文件和 Job 路由。
- `src/api/auth.ts`：短期令牌、到期检测和 401 会话失效边界。
- `src/api/authApi.ts`：注册、登录和当前用户的严格 API 契约。
- `src/stores/auth.ts`：运行期认证状态，不保存明文密码。

Dashboard、知识库、文件、Settings、Retrieval、Sessions、Chat、索引、用户管理和评测均使用 Real Adapter 的服务器状态。文件页使用 `/api/files/page` 的服务端分页；聊天引用绑定到具体 assistant message，流式停止/失败/重试后会重新读取历史，即使最新回答没有来源也不会回填旧引用。Real 请求失败不会回退 Mock。
