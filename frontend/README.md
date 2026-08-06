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

`VITE_API_MODE` 必须明确为 `mock` 或 `real`；非法或缺失会直接报配置错误。Real 模式请求失败时不会加载或回退 Mock。前端可见的 `VITE_*` 变量不得保存 Secret。

Mock 变更只存在于当前页面运行内存中。刷新页面后会恢复固定 ID、固定时间和固定排序的种子数据，不使用 `localStorage` 假装持久化，也不会发出真实业务网络请求。

## Real 模式认证边界

后端知识库、文件和 Job API 要求 Bearer JWT。Real 模式访问受保护路由时会自动进入 `/login`，登录表单通过 `/api/auth/login` 换取短期令牌，并调用 `/api/auth/me` 校验当前用户。登录页使用项目内置的 GSAP 依赖绘制黑白语义星图，不依赖 CDN；系统启用“减少动态效果”时会切换为静态图景。

令牌只保存在当前标签页的 `sessionStorage`，不会写入 `localStorage`、URL、源码或 `VITE_*` 环境变量。关闭标签页后需要重新登录；后端返回 `401` 或 JWT 到达 `exp` 时，前端会清除令牌并携带原路由跳回登录页。退出登录只清理浏览器会话，因为后端使用无状态 JWT。

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
npm run test:e2e
```

`test:e2e` 使用 `vite preview` 检查构建产物。视觉 QA 截图保存在 `artifacts/visual-qa/`。

## 路由部署

应用使用 Vue Router History 模式。生产静态服务器必须将 `/dashboard`、`/chat` 等未知文件路径回退到 `index.html`，否则刷新子路由会返回服务器 404。

## Real API 维护点

第一阶段接口集中在：

- `src/api/config.ts`：严格环境配置。
- `src/api/http.ts`：JSON、查询参数、multipart、超时、取消和错误。
- `src/api/mappers.ts`：后端 snake_case DTO 到前端领域模型。
- `src/api/adapters/realAdapter.ts`：知识库、文件和 Job 路由。
- `src/api/auth.ts`：短期令牌、到期检测和 401 会话失效边界。
- `src/api/authApi.ts`：登录和当前用户的严格 API 契约。
- `src/stores/auth.ts`：运行期认证状态，不保存明文密码。

Dashboard、索引和评测仍未接入 Real API，调用时会明确返回“该功能尚未在本阶段接入 Real API”。Settings、Retrieval、Sessions 和 Chat 已使用服务器持久化状态；流式停止后会重新读取历史，重试会原位替换助手消息，Real 请求失败不会回退 Mock。
