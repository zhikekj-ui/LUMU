# LUMU

> 本地优先的开源 AI Agent 框架。把「记忆、工具、知识、编排」打包成一个能端到端帮你办事的智能体。

LUMU 默认跑在你自己的机器 / 受信服务器上，数据不出域。你配一个模型（OpenAI 兼容即可），它就能记住你、调用工具、检索你的私有资料、把大任务拆给子智能体并行干。

## 特性

- 🧠 **记忆系统**：自动记住并整理你的偏好 / 知识 / 待办，支持衰减、整合、冲突消解
- 🛠️ **127+ 工具 / 26 能力域**：文件、终端、浏览器、联网搜索、RAG、可视化、定时任务、沙箱……
- 📚 **RAG 知识库**：上传私有资料，对话时精准检索增强
- 🤖 **多智能体编排**：把复杂任务拆给子智能体并行执行
- 🔌 **多渠道**：钉钉 / 飞书 / 企业微信 / Telegram / Discord
- 🧩 **技能市场**：浏览、安装、发布技能包，热加载生效
- 👁️ **多模态**：看图理解（依赖已配置的视觉模型）
- 🔒 **本地优先**：默认单用户、本地 / 受信网络运行，数据不出域

## 目录结构

```
.
├── agent/            智能体核心循环
├── api/              后端 API（FastAPI）+ 静态前端 api/static
├── core/             记忆 / 推理核心
├── channels/         渠道接入（钉钉/飞书/企微/Telegram/Discord）
├── memory/           记忆系统
├── knowledge/        RAG 知识库
├── orchestration/    多智能体编排
├── tools/            工具集（127+）
├── frontend/         前端源码（React + Ant Design + Vite）
├── config.py         配置加载
├── requirements.txt  Python 依赖
├── run.py            启动入口
├── Dockerfile        容器化构建
├── docker-compose.yml 一键编排
└── .env.example      配置样例
```

## 快速开始

### 方式一：直接运行（推荐）

```bash
pip install -r requirements.txt
cp .env.example .env        # 填入你的模型 API Key / Base URL
python run.py               # 默认监听 http://localhost:8000
```

浏览器打开 `http://localhost:8000` 即可使用（前端由后端在根路径同源提供）。

### 方式二：Docker

```bash
docker compose up -d        # 构建并后台启动，访问 http://localhost:8000
```

### 前端（仅当你要改 UI 时）

```bash
cd frontend
npm install
npm run build               # 产物输出到 frontend/dist
# 把 dist/* 复制到 api/static/ 即被后端同源托管
```

## 配置

编辑 `.env`（参考 `.env.example`）：

- `HOST` / `PORT`：服务监听地址（默认 `0.0.0.0:8000`）
- `OPENAI_API_KEY` / `DEEPSEEK_API_KEY` / `STEPFUN_API_KEY`：模型接入（OpenAI 兼容）
- `MEDIA_PROVIDER` + 各家密钥：图像 / 视频生成（留空即该能力不可用，不影响主对话）
- `TELEGRAM_BOT_TOKEN` / `DISCORD_BOT_TOKEN`：渠道接入（可选）
- `API_KEY`：若部署到不受信网络，可设一个访问密钥；本地 / 受信网络留空即可

> 模型通过「设置」面板随时切换 Provider / 模型，无需改代码。

## 开源协议

[MIT](https://opensource.org/licenses/MIT)
