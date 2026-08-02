# 多 Agent 协作与任务执行系统

一个本地运行的多 Agent 工作台。系统支持持续对话，由 Architect、Reviewer 和 Designer 协作分析任务，并通过受控工具执行、人工确认和结果验证完成任务。

项目包含：

- **后端：** FastAPI、MySQL、Anthropic SDK
- **前端：** React、TypeScript、Vite

## 启动项目

### 1. 启动后端

确保已安装 Python 3.12+、uv 和 MySQL 8，并创建数据库。

```powershell
cd backend
Copy-Item .env.example .env
```

编辑 `backend/.env`，配置数据库连接和 API Key：

```env
DATABASE_URL=mysql+asyncmy://用户名:密码@127.0.0.1:3306/agent
ANTHROPIC_API_KEY=你的_API_Key
```

安装依赖并启动：

```powershell
py -m uv sync
py -m uv run uvicorn app.main:app --host 127.0.0.1 --port 8000
```

后端接口文档：<http://127.0.0.1:8000/docs>

### 2. 启动前端

打开新的终端：

```powershell
cd frontend
Copy-Item .env.example .env
npm install
npm run dev
```

前端工作台：<http://127.0.0.1:5173>

## 构建前端

```powershell
cd frontend
npm run lint
npm run build
```

构建结果位于 `frontend/dist/`。
