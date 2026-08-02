# LUMU

> 跑在你自己机器上的 AI 智能体。有长期记忆，会用工具，能真的把事办完。

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)
[![CI](https://github.com/zhikekj-ui/LUMU/actions/workflows/ci.yml/badge.svg)](https://github.com/zhikekj-ui/LUMU/actions/workflows/ci.yml)
[![Website](https://img.shields.io/badge/Website-lumux.cn-7fdcff)](https://lumux.cn)
[![GitHub stars](https://img.shields.io/github/stars/zhikekj-ui/LUMU?style=social)](https://github.com/zhikekj-ui/LUMU)

🔗 想看 LUMU 实际能做什么？上 [官网 lumux.cn](https://lumux.cn) 看完整能力清单，或预约一场真实环境演示。

LUMU 不是又一个聊天窗口。它是一个**常驻在你私人服务器或本地机器上的智能体**：读写你的文件、跑你的终端命令、检索你的私有资料、把大任务拆开并行处理，并且**记得住你**——你的偏好、你纠正过它的地方、你项目里的约定，下次它直接照做。

配一个模型 Key（任何 OpenAI 兼容接口都行），`python run.py`，浏览器打开就能用。数据全部留在你自己的磁盘上。

---

## 它能做什么

**记忆是主线。** 多层记忆系统会自动沉淀你的偏好、习惯和项目上下文，并做衰减、整合与冲突消解——不是把聊天记录堆起来，而是提炼出「该记住的结论」。新开一个对话是干净的白板，不会翻旧账；但它对你的了解会持续累积。

**工具是手脚。** 文件读写、终端执行、浏览器操作、联网搜索、代码沙箱、数据可视化、定时任务、语音转写……工具通过 AST 自动发现，在 `tools/` 下丢一个带 `register()` 的文件就自动注册。为了控制上下文开销，工具按需暴露：核心集常驻，其余靠语义检索激活。

**知识库是记性外挂。** 上传私有资料，对话时走真向量检索（bge-small-zh-v1.5）精准增强，而不是把整份文档塞进提示词。

**技能是它自己长出来的能力。** 技能包就是一个 `SKILL.md`，用自然语言写清「遇到这类任务该怎么做」，放进 `skills/packs/` 立即热加载。**LUMU 自己也能写技能包**——它遇到重复出现的任务模式时，可以把方法固化下来，下次直接调用。

**它知道自己有什么。** `GET /api/capabilities` 会返回运行时真实的工具清单、已装技能、已配厂商和后端路由。这份清单不是写死在提示词里的，所以永远不会出现「实际有 139 个工具、自己以为只有 120 个」的认知漂移。

**多智能体编排。** 复杂任务可以拆给子智能体并行执行，各自隔离上下文。

**多渠道接入。** 钉钉 / 飞书 / 企业微信 / Telegram / Discord / 通用 Webhook，跨平台会话延续。

---

## 快速开始

### 方式一：直接跑（Windows / macOS / Linux 通用）

需要 **Python 3.10 或以上**（Windows 从 python.org 安装并勾选「Add to PATH」；macOS 用官方包或 brew；Linux 用系统包管理器）。

```bash
git clone https://github.com/zhikekj-ui/LUMU.git
cd LUMU

# 1) 创建并激活虚拟环境
python -m venv .venv
source .venv/bin/activate          # macOS / Linux
# .venv\Scripts\activate           # Windows (PowerShell)

# 2) 安装依赖
pip install -r requirements.txt

# 3)（可选但推荐）浏览器工具：让「网页浏览 / 截图 / PDF 渲染」可用
playwright install chromium

# 4) 准备配置（模型 Key 也可启动后在界面「设置」里填）
cp .env.example .env

# 5) 启动
python run.py
```

打开 `http://127.0.0.1:38473` 即可使用。首次进入在「设置 → 模型」里填一个模型 Key 就能对话。
数据默认落在项目目录的 `data/`（Windows / macOS / Linux 三端通用，无需任何额外设置）；想自定义位置，设环境变量 `AGENT_HOME` 指向你的目录即可。

### 方式二：Docker

```bash
git clone https://github.com/zhikekj-ui/LUMU.git
cd LUMU
docker compose up -d
docker compose logs -f agent      # 查看启动日志
```

容器默认只绑定宿主机环回地址（`127.0.0.1:38473`），局域网访问不到。

> 容器内服务默认绑 `0.0.0.0`，端口边界由 compose 的 `ports` 控制；**默认打开即用、零门禁、无需口令**。

---

## 安全：请读这一段

LUMU 会**真的执行操作**——写文件、跑命令、访问网络。所以：

> **谁能访问 LUMU 的接口，谁就约等于拿到了那台机器上一个 shell。**

安全策略因此**不按用户身份走，而按暴露面走**，没有登录页、没有账号体系：

| 情况 | 行为 |
|---|---|
| `HOST=127.0.0.1`（默认） | 只有本机能连，**零鉴权、打开即用** |
| `HOST=0.0.0.0` 或经反向代理 | 仍打开即用、零门禁（是否加固由你决定） |
| `LUMU_NO_AUTH=1` | 关闭校验 —— 任何人可执行任意命令，仅限隔离网络 |

另外内置了几层护栏：**核心代码写保护**（智能体改不了 `agent/`、`api/`、`providers/`、`config.py`，扩展只能落到 `plugins/`、`skills/`、`knowledge/`）、**代码沙箱**、**人在回路审批**（高危操作可要求人工确认）。

完整说明见 **[SECURITY.md](SECURITY.md)**。**不建议把 LUMU 直接暴露到公网**，需要远程访问请优先用 VPN 或 SSH 隧道。

---

## 你的数据在哪

全部在 `data/` 目录：对话、记忆、知识库、上传文件、模型配置。除了你主动配置的模型厂商 API，不向任何第三方发送数据。项目不做遥测、不回传统计。

> `data/` 里含有你的 API Key 和全部对话记录，已在 `.gitignore` 中排除。不要提交、不要打包分享。

---

## 升级

代码持续更新，升级**不丢数据**——`data/`（对话、记忆、配置）与 `skills/packs/`（自写技能）都已持久化在宿主机 / 挂载卷。

**Docker 方式**
```bash
git pull
docker compose up -d --build
```

**本地方式**
```bash
git pull
pip install -r requirements.txt
python run.py
```

---

## 目录结构

```
.
├── agent/            智能体核心循环（工具调用、审批、追踪）
├── api/              FastAPI 后端 + api/static 前端产物
├── core/             记忆 / 推理 / 访问守卫 / 配置
├── tools/            工具集（AST 自动发现，放入即注册）
├── skills/           技能系统（packs/ 下 SKILL.md 热加载）
├── memory/           记忆系统（衰减 / 整合 / 冲突消解）
├── knowledge/        RAG 知识库
├── rag/              检索增强实现
├── orchestration/    多智能体编排
├── channels/         渠道接入（钉钉/飞书/企微/Telegram/Discord/Webhook）
├── providers/        模型厂商适配
├── plugins/          第三方扩展（自定义 provider 等）
├── sandbox/          代码执行沙箱
├── scheduler/        定时任务
├── webui/            前端源码（React + Vite + Tailwind + shadcn/ui）
├── tests/            测试
├── config.py         配置加载
├── run.py            启动入口
└── .env.example      配置样例
```

---

## 扩展它

**写一个技能包**（不需要懂代码）：

```
skills/packs/weekly-report/SKILL.md
```

```markdown
---
name: weekly-report
description: 按公司格式写周报
---

当用户要写周报时：
1. 先问清本周做了哪几件事
2. 按「进展 / 问题 / 下周计划」三段组织
3. 每段不超过 5 条，用动词开头
```

放进去，下次对话即生效。

**写一个工具**（需要 Python）：在 `tools/` 下新建文件并暴露 `register()`，启动时自动发现。参考 `tools/` 里任意现有文件。

**改前端**：

```bash
cd webui
npm install
npm run dev        # 开发服务器
npm run build      # 产物输出到 ../api/static/
```

---

## 配置

模型、系统提示、渠道、记忆策略都可以在 Web 界面的「设置」里改，即时生效，不用重启。也可以走 `.env`，键名见 [.env.example](.env.example)。

支持任何 OpenAI 兼容接口——填上 Base URL 就能接自部署模型、中转 API 或各家云服务。

---

## 参与

欢迎报 bug、写技能包、提 PR。上手指引见 [CONTRIBUTING.md](CONTRIBUTING.md)，版本变更见 [CHANGELOG.md](CHANGELOG.md)。

## 许可

[MIT](LICENSE)
