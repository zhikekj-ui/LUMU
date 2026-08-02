"use client"

import * as React from "react"
import {
  IconDownload,
  IconCheck,
  IconX,
} from "@tabler/icons-react"
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import {
  fetchUsage,
  fetchInsights,
  fetchTimeline,
  useAsync,
  type Usage,
  type Insights,
} from "@/lib/lumu"

const AXIS = { stroke: "rgba(255,255,255,0.35)", fontSize: 11 }
const tooltipStyle = {
  background: "rgba(10,14,20,0.95)",
  border: "1px solid rgba(255,255,255,0.12)",
  borderRadius: 8,
  fontSize: 12,
}

export function ReportsView() {
  const usage = useAsync<Usage>(() => fetchUsage(), [])
  const insights = useAsync<Insights>(() => fetchInsights(), [])
  const timeline = useAsync<{ events: any[] }>(() => fetchTimeline(), [])

  const exportMd = () => {
    const u = usage.data?.summary
    const ins = insights.data?.stats
    const md = `# LUMU 运行报告

## 用量
- 总 Token：${(u?.total_prompt_tokens ?? 0) + (u?.total_completion_tokens ?? 0).toLocaleString()}（输入 ${u?.total_prompt_tokens ?? 0} / 输出 ${u?.total_completion_tokens ?? 0}）
- 平均响应：${u ? (u.avg_duration_ms / 1000).toFixed(1) : "—"} 秒
- 追踪片段：${u?.total_spans ?? 0}

## 学习洞察
- 交互总数：${ins?.total ?? 0}
- 成功率：${ins ? ((ins.stats.outcomes.success / (ins.stats.outcomes.success + ins.stats.outcomes.failure || 1)) * 100).toFixed(1) : "—"}%
- 平均评分：${ins?.avg_score?.toFixed(2) ?? "—"}
- 高频工具：${ins ? Object.entries(ins.tool_usage).slice(0, 5).map(([k, v]) => `${k}(${v})`).join("、") : "—"}
`
    const blob = new Blob([md], { type: "text/markdown" })
    const a = document.createElement("a")
    a.href = URL.createObjectURL(blob)
    a.download = "lumu-report.md"
    a.click()
    URL.revokeObjectURL(a.href)
  }

  const toolTop = insights.data
    ? Object.entries(insights.data.stats.tool_usage)
        .map(([name, count]) => ({ name, count }))
        .sort((a, b) => b.count - a.count)
        .slice(0, 12)
    : []

  return (
    <div className="space-y-5 p-4 md:p-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="font-display text-2xl font-semibold tracking-tight">报告</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            基于真实运行轨迹生成的用量、学习与活跃度报告。
          </p>
        </div>
        <Button variant="outline" size="sm" onClick={exportMd}>
          <IconDownload className="size-4" /> 导出 Markdown
        </Button>
      </div>

      {/* 用量概览 */}
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <StatCard label="累计 Token" value={usage.data ? ((usage.data.summary.total_prompt_tokens + usage.data.summary.total_completion_tokens)).toLocaleString() : "—"} />
        <StatCard label="平均响应" value={usage.data ? (usage.data.summary.avg_duration_ms / 1000).toFixed(1) + "s" : "—"} />
        <StatCard label="交互总数" value={insights.data?.stats.total ?? "—"} />
        <StatCard
          label="成功率"
          value={
            insights.data
              ? ((insights.data.stats.outcomes.success / (insights.data.stats.outcomes.success + insights.data.stats.outcomes.failure || 1)) * 100).toFixed(0) + "%"
              : "—"
          }
        />
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Token 用量（按日）</CardTitle>
            <CardDescription>输入 / 输出 Token 趋势</CardDescription>
          </CardHeader>
          <CardContent>
            {usage.loading ? (
              <Skeleton className="h-64 w-full" />
            ) : (
              <ResponsiveContainer width="100%" height={260}>
                <AreaChart data={usage.data?.by_day ?? []}>
                  <defs>
                    <linearGradient id="gp" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="0%" stopColor="#7fdcff" stopOpacity={0.5} />
                      <stop offset="100%" stopColor="#7fdcff" stopOpacity={0} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.06)" />
                  <XAxis dataKey="d" tick={AXIS} />
                  <YAxis tick={AXIS} />
                  <Tooltip contentStyle={tooltipStyle} />
                  <Area type="monotone" dataKey="prompt" name="输入" stroke="#7fdcff" fill="url(#gp)" />
                  <Area type="monotone" dataKey="completion" name="输出" stroke="#ffb454" fill="url(#gp)" />
                </AreaChart>
              </ResponsiveContainer>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="text-base">工具调用 TOP 12</CardTitle>
            <CardDescription>高频工具使用分布</CardDescription>
          </CardHeader>
          <CardContent>
            {insights.loading ? (
              <Skeleton className="h-64 w-full" />
            ) : (
              <ResponsiveContainer width="100%" height={260}>
                <BarChart data={toolTop} layout="vertical">
                  <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.06)" />
                  <XAxis type="number" tick={AXIS} />
                  <YAxis type="category" dataKey="name" tick={AXIS} width={110} />
                  <Tooltip contentStyle={tooltipStyle} cursor={{ fill: "rgba(255,255,255,0.04)" }} />
                  <Bar dataKey="count" name="调用" fill="#7fdcff" radius={[0, 4, 4, 0]} />
                </BarChart>
              </ResponsiveContainer>
            )}
          </CardContent>
        </Card>
      </div>

      {/* 学习洞察 + 活跃度 */}
      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle className="text-base">学习洞察</CardTitle>
            <CardDescription>执行质量与成败分布</CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            {insights.loading ? (
              <Skeleton className="h-40 w-full" />
            ) : (
              <>
                <div className="flex items-center gap-4">
                  <Badge variant="outline" className="border-[#34d399]/40 text-[#34d399]">
                    <IconCheck className="mr-1 size-3" /> 成功 {insights.data?.stats.outcomes.success ?? 0}
                  </Badge>
                  <Badge variant="outline" className="border-red-400/40 text-red-400">
                    <IconX className="mr-1 size-3" /> 失败 {insights.data?.stats.outcomes.failure ?? 0}
                  </Badge>
                  <span className="text-sm text-muted-foreground">
                    平均评分 {insights.data?.avg_score?.toFixed(2) ?? "—"}
                  </span>
                </div>
                <p className="text-sm text-muted-foreground">
                  失败模式 {insights.data?.failure_patterns?.length ?? 0} 类，已沉淀经验
                  {insights.data?.stats.total ?? 0} 条。
                </p>
              </>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="text-base">近期活跃度</CardTitle>
            <CardDescription>最近事件流</CardDescription>
          </CardHeader>
          <CardContent>
            {timeline.loading ? (
              <Skeleton className="h-40 w-full" />
            ) : (
              <div className="max-h-44 space-y-1 overflow-y-auto text-sm">
                {(timeline.data?.events ?? []).slice(0, 12).map((e, i) => (
                  <div key={i} className="flex items-center gap-2">
                    <Badge variant="secondary" className="w-16 justify-center">
                      {e.kind}
                    </Badge>
                    <span className="truncate text-muted-foreground">{e.text}</span>
                  </div>
                ))}
                {(timeline.data?.events?.length ?? 0) === 0 && (
                  <p className="text-muted-foreground">暂无事件</p>
                )}
              </div>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  )
}

function StatCard({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <Card>
      <CardContent className="p-4">
        <div className="text-2xl font-semibold leading-none">{value}</div>
        <div className="mt-1 text-xs text-muted-foreground">{label}</div>
      </CardContent>
    </Card>
  )
}
