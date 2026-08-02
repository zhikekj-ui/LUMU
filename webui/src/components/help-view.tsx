"use client"

import * as React from "react"
import {
  IconHelp,
  IconMessageCircle,
  IconBrain,
  IconSearch,
  IconReport,
  IconSettings,
  IconMicrophone,
} from "@tabler/icons-react"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"

const SECTIONS = [
  {
    icon: IconMessageCircle,
    title: "对话",
    body: "左侧「对话」可折叠，展开后显示历史会话与「新对话」。每个对话拥有独立记忆，互不干扰。输入框支持语音输入（点击麦克风按钮录音，自动转写）。",
  },
  {
    icon: IconBrain,
    title: "资料库",
    body: "LUMU 的长期知识库。它会跨会话自动沉淀策略、经验与事实，也可在「资料库」页面手动上传文档存入。支持检索、删除与关系图谱查看。",
  },
  {
    icon: IconSearch,
    title: "搜索",
    body: "统一检索记忆、历史会话与技能。输入关键词即可跨三大来源查找 LUMU 掌握的一切。",
  },
  {
    icon: IconReport,
    title: "报告",
    body: "基于真实运行轨迹生成的用量、学习与活跃度报告，可一键导出 Markdown。所有数字均来自后端统计，绝不编造。",
  },
  {
    icon: IconSettings,
    title: "设置",
    body: "切换运行模型、编辑系统提示词、调整采样参数（Temperature / Top P）、管理供应商 API Key 与语音配置。",
  },
]

const FAQ = [
  { q: "LUMU 是什么？", a: "一个开源、本地优先、跨平台的 AI Agent 框架，常驻在你的服务器上，能调用工具、记忆知识、执行任务。" },
  { q: "我的对话数据安全吗？", a: "记忆与资料库默认存储在本地空间，数据不出域；各对话独立隔离，不会跨会话共享。" },
  { q: "如何更换底层模型？", a: "进入「设置 → 当前模型」，选择已配置 API Key 的供应商与模型后点击切换，运行期即时生效。" },
  { q: "为什么某些功能需要配置？", a: "多模态、语音等能力依赖你已在「设置」中配置好的模型与密钥，LUMU 不内置任何外部密钥。" },
]

export function HelpView() {
  return (
    <div className="space-y-5 p-4 md:p-6">
      <div>
        <h1 className="font-display text-2xl font-semibold tracking-tight">获取帮助</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          LUMU 使用指南 —— 了解每个模块能做什么，以及如何用得更顺手。
        </p>
      </div>

      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
        {SECTIONS.map((s) => (
          <Card key={s.title}>
            <CardHeader>
              <CardTitle className="flex items-center gap-2 text-base">
                <span className="flex size-8 items-center justify-center rounded-lg bg-white/10 text-[#7fdcff]">
                  <s.icon className="size-4" />
                </span>
                {s.title}
              </CardTitle>
            </CardHeader>
            <CardContent>
              <p className="text-sm leading-relaxed text-muted-foreground">{s.body}</p>
            </CardContent>
          </Card>
        ))}
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">常见问题</CardTitle>
          <CardDescription>关于能力与数据的高频疑问</CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          {FAQ.map((f, i) => (
            <div key={i} className="rounded-md border border-border bg-white/5 p-3">
              <div className="mb-1 flex items-center gap-2">
                <Badge variant="secondary">Q{i + 1}</Badge>
                <span className="font-medium">{f.q}</span>
              </div>
              <p className="text-sm text-muted-foreground">{f.a}</p>
            </div>
          ))}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <IconMicrophone className="size-4 text-[#7fdcff]" /> 快捷提示
          </CardTitle>
        </CardHeader>
        <CardContent>
          <ul className="list-inside list-disc space-y-1.5 text-sm text-muted-foreground">
            <li>对话输入框按 <kbd className="rounded bg-white/10 px-1.5 py-0.5 text-xs">Enter</kbd> 发送，<kbd className="rounded bg-white/10 px-1.5 py-0.5 text-xs">Shift+Enter</kbd> 换行。</li>
            <li>点麦克风按钮可语音输入，录音结束后自动转写并回填。</li>
            <li>「资料库」里的大白点越多，代表该知识节点越重要（按 importance 着色）。</li>
            <li>所有报告数据均可在「设置」中对应的运行配置里追溯来源。</li>
          </ul>
        </CardContent>
      </Card>
    </div>
  )
}
