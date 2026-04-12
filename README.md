# Super Agent

一个基于 `FastAPI + LangGraph + PostgreSQL/PGVector + Next.js 15` 的智能体工作台项目。

当前仓库已经完成两层前端迁移：
- 后端：Python / FastAPI / LangGraph / MCP / RAG / PGVector
- 前端：React 19 / Next.js 15 / TypeScript / CSS Modules

浏览器主入口现在由新的 `frontend/` 应用承载，旧的静态 `web/` 前端已经移除。

## 技术栈

### 后端
- FastAPI
- LangGraph
- PostgreSQL
- PGVector
- Psycopg 3
- MCP
- Tavily / Playwright / BeautifulSoup / PDF 生成

### 前端
- Next.js 15.3.1
- React 19
- TypeScript
- CSS Modules
- Motion
- Lucide React
- Lenis

## 目录结构

```text
app/                  后端核心代码
frontend/             新的 Next.js 前端应用
main.py               FastAPI 入口
docker-compose.yml    标准容器编排
docker-compose.dev.yml 开发态容器覆盖
Dockerfile.backend    后端镜像
frontend/Dockerfile   前端镜像
```

## 环境变量

### 后端

复制根目录环境模板：

```powershell
copy .env.example .env
```

至少建议检查这些变量：

```env
DATABASE_URL=postgresql://postgres:postgres@127.0.0.1:5432/super_agent
FRONTEND_URL=http://127.0.0.1:3100
OPENAI_API_KEY=
OPENAI_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
OPENAI_MODEL=qwen-plus
TAVILY_API_KEY=
```

### 前端

复制前端模板：

```powershell
cd frontend
copy .env.example .env.local
```

默认配置：

```env
BACKEND_URL=http://127.0.0.1:8010
```

## 本地开发运行

### 1. 启动数据库

如果你只想起数据库：

```powershell
docker compose up -d db
```

### 2. 启动后端

```powershell
cd C:\Users\Administrator\Desktop\super-agnet
.\.venv\Scripts\python.exe main.py
```

后端地址：

- [http://127.0.0.1:8010](http://127.0.0.1:8010)

### 3. 启动前端

```powershell
cd C:\Users\Administrator\Desktop\super-agnet\frontend
npm install
npm run dev
```

前端地址：

- [http://127.0.0.1:3100](http://127.0.0.1:3100)

## Docker 运行

### 标准模式

适合接近生产的本地联调：

```powershell
docker compose up -d --build
```

服务地址：

- 前端：[http://127.0.0.1:3100](http://127.0.0.1:3100)
- 后端：[http://127.0.0.1:8010](http://127.0.0.1:8010)
- 数据库宿主机端口：`55432`

### 开发模式

适合前后端都需要热更新时使用：

```powershell
docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build
```

这个模式会：
- 挂载本地代码目录
- 后端使用 `uvicorn --reload`
- 前端使用 `next dev`

## 常用验证命令

### 后端

```powershell
python -m py_compile main.py
```

### 前端

```powershell
cd frontend
npm run typecheck
npm run build
```

### Compose 配置检查

```powershell
docker compose config
docker compose -f docker-compose.yml -f docker-compose.dev.yml config
```

## 功能验收建议

启动前后端后，按这个顺序验收：

1. 打开 [http://127.0.0.1:3100](http://127.0.0.1:3100)
2. 发送一条聊天消息，确认 SSE 流式输出正常
3. 勾选/取消“显示思考过程”，确认 thought 显示逻辑正常
4. 上传一个 `.md` 或 `.pdf`
5. 刷新知识状态，确认能看到 `pgvector`
6. 测试审批刷新、批准、拒绝、恢复
7. 访问 [http://127.0.0.1:8010](http://127.0.0.1:8010)，确认后端根入口会跳到前端

## 当前状态

已完成：
- 旧静态前端移除
- 新 Next.js 前端接入真实后端接口
- 前后端统一 Docker 化

仍可继续优化：
- 统一生产部署策略
- 反向代理整合
- 更完整的前端组件拆分与状态管理抽象
