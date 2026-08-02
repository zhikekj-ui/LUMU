# 参与贡献

欢迎。LUMU 还很年轻，任何形式的参与都有价值——修一个错别字、报一个 bug、写一个技能包，都算。

## 最快的三种参与方式

**1. 写一个技能包（不用懂 Python）**

技能包就是一个 `SKILL.md`，用自然语言告诉 LUMU「遇到某类任务时该怎么做」。放进 `skills/packs/<名字>/SKILL.md`，下次对话它就自动生效。

```
skills/packs/weekly-report/
└── SKILL.md
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

觉得好用就发到 Discussions，我们会考虑收进官方技能库。

**2. 报一个 bug**

带上这些信息能让我们快很多：你用的模型和厂商、复现步骤、终端里的报错日志。

**3. 写一个工具**

在 `tools/` 下新建一个 `.py` 文件，暴露一个 `register()` 函数，启动时会被自动发现并注册。参考 `tools/` 里任意现有文件的写法。

## 开发环境

```bash
git clone https://github.com/<your-account>/LUMU.git
cd LUMU
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env        # 填入你的模型 API Key
python run.py
```

打开 `http://127.0.0.1:38473`。

### 前端（只有改 UI 才需要）

```bash
cd webui
npm install
npm run dev      # 开发服务器，接口代理到后端
npm run build    # 产物输出到 ../api/static/，由后端同源托管
```

## 提交前请自查

```bash
pytest tests/ -v          # 测试要过
black .                   # 代码格式化
ruff check .              # 静态检查
```

## 代码约定

- **不要在核心目录塞业务逻辑。** `agent/`、`api/`、`providers/` 是内核，扩展能力请走 `tools/`、`plugins/`、`skills/`。这条同样被运行时的写保护强制执行。
- **不要提交任何密钥。** `data/`、`.env` 已在 `.gitignore` 中，提交前再确认一遍 `git status`。
- **不要写死可变数字。** 比如「支持 127 个工具」这类说明，请改成运行时查询（`GET /api/capabilities`），否则很快就会和实际不符。
- **新增端点默认加鉴权。** 除非明确是探活或回调类的公开端点，否则请挂上 `Depends(verify_api_key)`。

## 提交信息

用 [Conventional Commits](https://www.conventionalcommits.org/)：

```
feat: 新增飞书渠道适配器
fix: 修复流式输出在长文本下断行错乱
docs: 补充 Docker 部署说明
chore: 升级依赖
```

## Pull Request

1. 从 `main` 切分支：`git checkout -b feat/your-feature`
2. 保持单个 PR 聚焦一件事，方便 review
3. 描述里说清**改了什么**、**为什么**、**怎么验证的**
4. 涉及 UI 改动请附截图

## 行为准则

参与本项目即表示你同意遵守 [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md)。

## 许可

提交贡献即表示你同意以 [MIT 许可证](LICENSE) 授权你的代码。
