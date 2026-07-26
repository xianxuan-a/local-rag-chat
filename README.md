# Local RAG Chat

Local RAG Chat 是一个单机知识库服务。当前版本已经实现文件管理、文档解析与切分、DashScope Embedding、Chroma 持久化、版本化重建、回滚、相似度检索、会话历史，以及同步和流式 RAG 问答。

## 运行约束

索引存储采用本地 SQLite 和 `chromadb.PersistentClient`。当前版本只支持：

- 单机、单个 FastAPI 进程。
- `uvicorn --workers 1`。
- 只有 FastAPI 服务直接访问 SQLite、上传目录和 Chroma 目录。
- `scripts/rebuild_kb.py` 只通过 HTTP 调用服务，不直接打开数据库或 Chroma。

不要让多个 worker 或多个服务实例同时访问同一个本地 Chroma 目录。需要横向扩展时，应部署独立 Chroma Server 并将业务层切换到 `chromadb.HttpClient`。

## 安装与启动

需要 Python 3.11 或更高版本。

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
Copy-Item .env.example .env
```

在 `.env` 中配置 `DASHSCOPE_API_KEY` 和聊天模型。`qwen3-max` 仅为示例，程序不会为 `CHAT_MODEL` 提供业务默认值：

```dotenv
DASHSCOPE_API_KEY="..."
CHAT_MODEL="qwen3-max"
CHAT_TEMPERATURE=0.1
CHAT_MAX_TOKENS=1024
CHAT_TIMEOUT_SECONDS=60
CHAT_MAX_ATTEMPTS=2
RAG_CONTEXT_MAX_CHARS=12000

EMBEDDING_PROVIDER="dashscope"
EMBEDDING_MODEL="text-embedding-v4"
EMBEDDING_DIMENSION=1024
EMBEDDING_NORMALIZATION="l2"
EMBEDDING_PROTOCOL_VERSION="dashscope-text-embedding-v1"
VECTOR_DISTANCE_METRIC="cosine"
```

启动服务：

```powershell
python run.py
```

Swagger 位于 `http://localhost:8000/docs`。可选前端：

```powershell
streamlit run ui/streamlit_app.py
```

Streamlit 必须从项目根目录启动。页面只通过 FastAPI HTTP 接口访问数据，支持文件上传、同步处理、状态查看、删除、会话切换、历史恢复和真实流式回答。普通请求超时由 `API_TIMEOUT_SECONDS` 配置，文件处理和流式读取超时由 `API_STREAM_TIMEOUT_SECONDS` 配置。

## 文件与索引接口

所有接口使用 `{code, message, data}` 响应包装。

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/api/knowledge-bases` | 创建知识库 |
| GET | `/api/knowledge-bases` | 列出知识库 |
| DELETE | `/api/knowledge-bases/{id}` | 删除空知识库及其明确跟踪的 Collection |
| POST | `/api/files/upload` | 上传文件并快速返回 `PENDING` |
| GET | `/api/files?knowledge_base_id=...` | 查询文件 |
| POST | `/api/files/{id}/process` | 同步解析、切分、向量化并入库 |
| DELETE | `/api/files/{id}` | 删除文件、磁盘内容和各版本向量 |
| POST | `/api/sessions` | 创建知识库会话 |
| GET | `/api/sessions?knowledge_base_id=...` | 查询知识库会话 |
| GET | `/api/sessions/{id}/messages?knowledge_base_id=...` | 按顺序查询历史消息 |
| DELETE | `/api/sessions/{id}?knowledge_base_id=...` | 删除会话及关联消息 |
| POST | `/api/knowledge-bases/{id}/rebuild` | 构建新 generation 并原子切换 |
| POST | `/api/knowledge-bases/{id}/rollback` | 交换 active/previous 指针 |
| POST | `/api/knowledge-bases/{id}/abort-building` | 清理遗留候选 |
| POST | `/api/knowledge-bases/{id}/cleanup-retired` | 精确清理 cleanup 指针 |
| POST | `/api/chat` | 同步检索完整分块并生成带来源的回答 |
| POST | `/api/chat/stream` | 以结构化 NDJSON 流式生成回答 |

上传不会自动触发向量化。调用 `/process` 后，文件会从 `PENDING`、`FAILED` 或 `SUCCESS` 原子抢占为 `PROCESSING`，成功后进入 `SUCCESS`。配置冲突和 Collection 一致性错误在抢占前返回 409。

## Collection 与检索约定

- 每个 Collection 显式使用 `configuration={"hnsw": {"space": "cosine"}}`。
- 创建和读取均显式使用 `embedding_function=None`。
- 所有写入传入预计算 `embeddings`；所有查询只传 `query_embeddings`。
- 数据库中的 active 指针是查询路由的权威来源。
- 向量空间哈希包含 provider、model、dimension、normalization、distance metric 和协议版本。
- 模型、维度、归一化、距离度量或协议变化后，必须执行整库重建。

业务检索由 `RetrievalService` 提供，分数为原始余弦相似度 `1 - cosine_distance`，范围为 `[-1, 1]`，默认不设置阈值。

## RAG 问答约定

- 模型上下文使用 RetrievalService 返回的完整分块正文；`content_preview` 只用于响应中的来源展示。
- 文件名、问题和来源正文以 JSON 结构传给模型，明确标记知识库来源为不可信数据，以降低提示注入风险，但不宣称能够完全阻止提示注入。
- `RAG_CONTEXT_MAX_CHARS` 是最终来源 JSON 的 Python 字符数预算，不等同于 token 数。
- 聊天客户端仅在检索得到有效上下文后创建；无结果时不校验聊天模型配置，也不会请求 DashScope。
- `CHAT_MAX_ATTEMPTS=2` 是一次问答的全局模型请求上限。临时错误重试和上下文缩减重试共用该上限。
- `/api/chat` 保持同步兼容；`/api/chat/stream` 使用 DashScope 的真实增量输出并返回 `application/x-ndjson`。
- 流事件依次为 `start`、一个或多个 `delta`、`sources` 和 `done`；流内失败返回结构化 `error` 事件。
- 流式回答完整结束并通过引用校验后，用户消息和一条完整助手消息才会在同一数据库事务中保存；中断或失败不会保存部分助手回答。
- 模型回答中的合法 `[S1]` 引用会映射为公开 `SourceReference`；非法或越界编号不会生成来源。

## 重建 CLI

CLI 只发送 HTTP 请求：

```powershell
python scripts/rebuild_kb.py --knowledge-base-id <uuid>
python scripts/rebuild_kb.py --knowledge-base-id <uuid> --rollback-to-previous
python scripts/rebuild_kb.py --knowledge-base-id <uuid> --abort-building
python scripts/rebuild_kb.py --knowledge-base-id <uuid> --cleanup-retired
```

可通过 `--api-base-url` 和 `--timeout-seconds` 覆盖默认值。

## 测试

```powershell
pytest
python -m compileall app scripts
```

普通测试使用无网络 FakeEmbedding。真实 DashScope 冒烟测试应默认跳过，只有显式启用并提供 API Key 时才运行。

## 一致性边界

SQLite 与 Chroma 不具备跨系统原子事务。服务通过完整向量快照、写入校验、失败补偿、版本化 Collection 和数据库指针降低风险，但强制终止进程仍可能留下 `PROCESSING`、`BUILDING` 或活动 Collection 的混合状态。此时应先检查状态，再使用 abort、cleanup 或整库重建修复。
