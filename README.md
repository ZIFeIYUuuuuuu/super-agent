# Super Agent

一个基于 `FastAPI + LangGraph + PostgreSQL/PGVector + Redis + Next.js 15` 的智能体工作台项目。

它把几个核心能力放在了一套前后端应用里：

- 流式聊天（SSE）
- 工具调用与 MCP 接入
- RAG 文档上传与检索
- 人工审批 / 恢复执行
- Redis 会话历史缓存
- Next.js 前端工作台界面

当前浏览器主入口由 `frontend/` 提供，后端根路径会重定向到前端页面。

## 双语概览 / Bilingual Overview

| 中文 | English |
| --- | --- |
| 一个基于 FastAPI、LangGraph、PGVector、Redis 和 Next.js 的 Agent 工作台。 | An agent workspace built with FastAPI, LangGraph, PGVector, Redis, and Next.js. |
| 支持流式聊天、RAG 文档检索、工具调用、MCP 接入、人工审批和恢复执行。 | Supports streaming chat, RAG document retrieval, tool calls, MCP integration, human approval, and resumed execution. |
| README 展示 eval harness、trace 截图、部署 checklist 和可量化指标。 | The README includes an eval harness, trace screenshot, deployment checklist, and measurable metrics. |

## 架构 / Architecture

```mermaid
flowchart LR
  User["Browser workspace"] --> Frontend["Next.js 15 frontend"]
  Frontend --> Proxy["Frontend API proxy"]
  Proxy --> API["FastAPI backend"]
  API --> Graph["LangGraph agent runtime"]
  Graph --> RAG["PGVector RAG retrieval"]
  Graph --> Tools["Tools + MCP clients"]
  Graph --> Approval["Human approval checkpoint"]
  API --> Redis["Redis thread cache"]
  API --> Postgres["PostgreSQL persistence"]
  Graph --> SSE["SSE token/tool stream"]
  SSE --> Frontend
```

## 演示 GIF / Demo GIF

![Demo GIF](docs/assets/demo.gif)

## Trace 截图 / Trace Screenshot

![Trace screenshot](docs/assets/trace-screenshot.png)

Trace 视图用于解释 Agent 行为：检索决策、chunk 分数、工具调用、审批节点、恢复执行事件和最终来源引用。

The trace view is the surface I use to explain agent behavior: retrieval decisions, chunk scores, tool calls, approval gates, resume events, and final source references.

## 评估 Harness / Eval Harness

无需模型、数据库、Redis 或向量库凭据即可运行本地确定性 eval harness：

Run the local deterministic eval harness without model, database, Redis, or vector-store credentials:

```powershell
python tests\eval_harness.py
```

Current local output:

| Metric | Current portfolio baseline | Measurement note |
| --- | ---: | --- |
| Latency | P50 `0.84ms`, P95 `1.57ms` | Deterministic planner/retrieval reviewer, 3 local cases |
| RAG hit rate | `100%` | Strong retrieved chunks at `rerank_score >= 0.80` |
| Agent success rate | `100%` | Required answer terms and source refs present |
| Report generation time | `N/A` | Report/PDF route is not part of this harness yet |
| Cost | `$0.00 / eval run` | No external model calls in deterministic harness |

## 技术栈

后端：

- Python 3.12
- FastAPI
- LangGraph
- PostgreSQL
- PGVector
- Redis
- Psycopg 3
- MCP
- Tavily / Playwright / BeautifulSoup / PDF 生成

前端：

- Next.js 15.3.1
- React 19
- TypeScript
- CSS Modules
- Motion
- Lucide React
- Lenis

## 目录结构

```text
app/                    后端核心代码
frontend/               Next.js 前端应用
main.py                 FastAPI 启动入口
docker-compose.yml      标准容器编排
docker-compose.dev.yml  开发态覆盖配置
Dockerfile.backend      后端镜像
frontend/Dockerfile     前端镜像
test_sse.py             SSE / 工具链验证脚本
```

## 默认端口

| 服务 | 地址 |
| --- | --- |
| 前端 | `http://127.0.0.1:3100` |
| 后端 | `http://127.0.0.1:8010` |
| PostgreSQL | `127.0.0.1:55432` |
| Redis | `127.0.0.1:63790` |

## 快速开始

### 1. 准备环境变量

复制根目录环境变量模板：

```powershell
copy .env.example .env
```

复制前端环境变量模板：

```powershell
cd frontend
copy .env.example .env.local
```

至少确认这些变量是正确的：

```env
DATABASE_URL=postgresql://postgres:postgres@127.0.0.1:5432/super_agent
REDIS_URL=redis://127.0.0.1:63790/0
FRONTEND_URL=http://127.0.0.1:3100
BACKEND_URL=http://127.0.0.1:8010
OPENAI_API_KEY=
OPENAI_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
OPENAI_MODEL=qwen-plus
TAVILY_API_KEY=
```

### 2. 启动基础依赖

如果你只想先启动数据库和 Redis：

```powershell
docker compose up -d db redis
```

### 3. 启动后端

```powershell
cd C:\Users\Administrator\Desktop\super-agnet
.\.venv\Scripts\python.exe main.py
```

启动后访问：

- [http://127.0.0.1:8010](http://127.0.0.1:8010)

### 4. 启动前端

```powershell
cd C:\Users\Administrator\Desktop\super-agnet\frontend
npm install
npm run dev
```

启动后访问：

- [http://127.0.0.1:3100](http://127.0.0.1:3100)

## Docker 运行

### 标准模式

适合本地联调或接近生产的运行方式：

```powershell
docker compose up -d --build
```

启动后可访问：

- 前端：[http://127.0.0.1:3100](http://127.0.0.1:3100)
- 后端：[http://127.0.0.1:8010](http://127.0.0.1:8010)

### 开发模式

适合前后端都需要热更新时使用：

```powershell
docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build
```

这个模式会：

- 挂载本地代码目录
- 后端使用 `uvicorn --reload`
- 前端使用 `next dev`

## 常用命令

后端语法检查：

```powershell
python -m py_compile main.py
```

前端类型检查：

```powershell
cd frontend
npm run typecheck
```

前端生产构建：

```powershell
cd frontend
npm run build
```

Compose 配置检查：

```powershell
docker compose config
docker compose -f docker-compose.yml -f docker-compose.dev.yml config
```

SSE / 工具链验证：

```powershell
python test_sse.py --base-url http://127.0.0.1:8010
```

本地 eval harness：

```powershell
python tests\eval_harness.py
```

## 核心接口

常用后端接口包括：

- `POST /v1/chat/completions`
- `POST /v1/knowledge/documents`
- `GET /v1/knowledge/status`
- `GET /v1/approvals/pending/{thread_id}`
- `POST /v1/approvals/decision`
- `POST /v1/approvals/resume`

前端在 `frontend/app/api/*` 下提供了一层代理，浏览器侧通常不需要直接写死后端地址。

## 验收建议

启动前后端后，建议按这个顺序检查：

1. 打开 [http://127.0.0.1:3100](http://127.0.0.1:3100)
2. 发送一条消息，确认 SSE 流式输出正常
3. 切换“是否显示 thought / 思考过程”，确认界面行为正常
4. 上传一个 `.md` 或 `.pdf` 文件
5. 刷新知识库状态，确认能够看到检索后端状态
6. 测试审批、批准、拒绝、恢复执行链路
7. 访问 [http://127.0.0.1:8010](http://127.0.0.1:8010)，确认后端根入口会跳转到前端

## 部署说明

这个项目更适合以“独立应用”的形式部署，再通过博客导航或 `iframe` 接入，而不是直接塞进博客主题源码里。

推荐方式：

- 博客：`https://yourblog.com`
- Agent 应用：`https://agent.yourblog.com`
- 反向代理到前端 `3100`
- 前端再通过 `BACKEND_URL` 访问后端 `8010`

### Production Deployment Checklist

1. Put the app behind HTTPS, preferably `agent.yourdomain.com`.
2. Run `docker compose up -d --build` on the host or deploy equivalent backend/frontend/db/redis services.
3. Set `FRONTEND_URL`, `BACKEND_URL`, `OPENAI_API_KEY`, `OPENAI_BASE_URL`, `OPENAI_MODEL`, `DATABASE_URL`, `REDIS_URL`, and any tool provider keys in environment variables.
4. Restrict database and Redis ports to the private network; expose only the reverse proxy.
5. Run `python tests\eval_harness.py` and `python test_sse.py --base-url https://agent.yourdomain.com` after deployment.
6. Capture a fresh trace screenshot after one RAG + approval run and replace `docs/assets/trace-screenshot.png`.

如果你一定要挂在子路径，比如 `https://yourblog.com/agent`，通常还需要额外处理 Next.js 的 `basePath`、反向代理规则和静态资源路径。

## 当前状态

已完成：

- Next.js 前端接管浏览器入口
- FastAPI 后端提供聊天、知识库、审批和流式接口
- PostgreSQL / PGVector / Redis 接入
- Docker 方式运行前后端和基础依赖

后续可以继续优化：

- 生产环境反向代理与域名方案
- 前端组件拆分与状态管理收敛
- 更完整的自动化测试和部署流程
