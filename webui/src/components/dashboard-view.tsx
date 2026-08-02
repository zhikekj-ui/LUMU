"use client"

import * as React from "react"
import {
  IconBrain,
  IconMessages,
  IconTool,
  IconStack,
  IconRefresh,
  IconPlus,
  IconListDetails,
  IconActivity,
  IconDatabase,
  IconCircleFilled,
  IconCpu,
  IconTrendingUp,
} from "@tabler/icons-react"

import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Skeleton } from "@/components/ui/skeleton"
import { Separator } from "@/components/ui/separator"
import { cn } from "@/lib/utils"
import { useConversations } from "@/components/conversations"
import {
  fetchHealth,
  fetchSkills,
  fetchUsage,
  fetchInsights,
  fetchTimeline,
  useAsync,
  type Health,
  type Skill,
  type Usage,
  type Insights,
  type TimelineEvent,
} from "@/lib/lumu"
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts"

const AXIS = "#64748b"
const PRIMARY = "#5ed0f5"
const AMBER = "#f5b454"
const TOOLTIP_STYLE = {
  background: "#0b0f14",
  border: "1px solid #1f2733",
  borderRadius: 8,
  fontSize: 12,
  color: "#e2e8f0",
}

function timeAgo(ts: number): string {
  const s = Math.floor((Date.now() - ts) / 1000)
  if (s < 60) return "刚刚"
  const m = Math.floor(s / 60)
  if (m < 60) return `${m} 分钟前`
  const h = Math.floor(m / 60)
  if (h < 24) return `${h} 小时前`
  const d = Math.floor(h / 24)
  return `${d} 天前`
}

// ---- 分区标题：给页面叙事结构，而非一摞散卡片 ----
function Section({
  icon: Icon,
  title,
  desc,
  children,
}: {
  icon: React.ElementType
  title: string
  desc?: string
  children: React.ReactNode
}) {
  return (
    <section className="space-y-3">
      <div className="flex items-center gap-2 px-1">
        <span className="h-4 w-1 rounded-full bg-cyan" />
        <Icon className="size-4 text-cyan/80" />
        <h2 className="text-sm font-medium tracking-tight text-foreground">{title}</h2>
        {desc ? <span className="text-xs text-muted-foreground">· {desc}</span> : null}
      </div>
      {children}
    </section>
  )
}

// ---- 指标单元格：图标瓦片 + 大数字 + 有意义上下文（非同义复述）----
function Metric({
  label,
  value,
  icon: Icon,
  tint,
  context,
  loading,
}: {
  label: string
  value: number | string
  icon: React.ElementType
  tint: { text: string; bg: string }
  context?: React.ReactNode
  loading?: boolean
}) {
  return (
    <div className="flex flex-col gap-2 rounded-lg px-3 py-3 transition-colors hover:bg-white/[0.02]">
      <div className="flex items-center gap-2">
        <span
          className={cn(
            "flex size-7 items-center justify-center rounded-md",
            tint.bg,
            tint.text
          )}
        >
          <Icon className="size-4" />
        </span>
        <span className="text-xs text-muted-foreground">{label}</span>
      </div>
      <div className="text-[28px] font-semibold leading-none tabular-nums text-foreground">
        {loading ? <Skeleton className="h-7 w-12" /> : value}
      </div>
      {context ? (
        <div className="text-[11px] leading-tight text-muted-foreground/80">{context}</div>
      ) : null}
    </div>
  )
}

export function DashboardView({
  onGoChat,
  onGoLifecycle,
}: {
  onGoChat: () => void
  onGoLifecycle: () => void
}) {
  const { conversations, createConversation } = useConversations()
  const [nonce, setNonce] = React.useState(0)
  const health = useAsync<Health>(() => fetchHealth(), [nonce])
  const skills = useAsync<Skill[]>(() => fetchSkills(), [nonce])
  const usage = useAsync<Usage>(() => fetchUsage(), [nonce])
  const insights = useAsync<Insights>(() => fetchInsights(), [nonce])
  const timeline = useAsync<{ events: TimelineEvent[] }>(
    () => fetchTimeline(),
    [nonce]
  )

  const refresh = () => setNonce((n) => n + 1)

  // 工具调用总数
  const toolTotal = insights.data
    ? Object.values(insights.data.stats.tool_usage).reduce((a, b) => a + b, 0)
    : 0
  // 成功率
  const st = insights.data?.stats
  const successRate = st
    ? ((st.outcomes.success / (st.outcomes.success + st.outcomes.failure || 1)) * 100).toFixed(1)
    : "—"

  // 衍生上下文（让数字之间有信息差，而非复述）
  const sessions = health.data?.sessions ?? 0
  const convCount = conversations.length
  const archived = conversations.filter((c) => c.archived).length
  const totalRounds = insights.data?.stats.total ?? 0
  const avgPerConv = convCount ? Math.round(totalRounds / convCount) : 0

  // token 按天
  const tokenData = React.useMemo(
    () =>
      (usage.data?.by_day || []).map((d) => ({
        date: d.d.slice(5),
        prompt: d.prompt || 0,
        completion: d.completion || 0,
        total: d.total || 0,
      })),
    [usage.data]
  )

  // 活跃度按天（来自 timeline 真实事件）
  const activityData = React.useMemo(() => {
    const evs = timeline.data?.events || []
    const map: Record<string, number> = {}
    for (const e of evs) {
      const day = (e.ts || "").slice(0, 10)
      if (day) map[day] = (map[day] || 0) + 1
    }
    return Object.entries(map)
      .sort((a, b) => a[0].localeCompare(b[0]))
      .map(([day, count]) => ({ date: day.slice(5), count }))
  }, [timeline.data])

  // 工具调用 TOP12
  const toolData = React.useMemo(() => {
    const tu = insights.data?.stats.tool_usage || {}
    return Object.entries(tu)
      .sort((a, b) => b[1] - a[1])
      .slice(0, 12)
      .map(([name, calls]) => ({ name, calls }))
  }, [insights.data])

  const totalMsgs = conversations.reduce((a, c) => a + c.messages.length, 0)
  const maxMsgs = Math.max(1, ...conversations.map((c) => c.messages.length))
  const recent = [...conversations]
    .sort((a, b) => b.updatedAt - a.updatedAt)
    .slice(0, 6)

  const us = usage.data?.summary

  return (
    <div className="flex flex-col gap-6 p-4 md:p-6">
      {/* 页面标题 */}
      <div className="flex items-end justify-between gap-4">
        <div className="space-y-1">
          <h1 className="text-xl font-semibold tracking-tight text-foreground">运行态势</h1>
          <p className="text-sm text-muted-foreground">
            LUMU agent 框架 · 实时运行数据与执行质量
          </p>
        </div>
        <Button variant="outline" size="sm" onClick={refresh} className="gap-1.5 shrink-0">
          <IconRefresh className={cn("size-4", health.loading && "animate-spin")} />
          刷新
        </Button>
      </div>

      {/* 状态条 */}
      <Card>
        <CardContent className="flex flex-wrap items-center gap-x-6 gap-y-2 py-1">
          <div className="flex items-center gap-2">
            <IconCircleFilled className="size-3 text-emerald-500" />
            <span className="text-sm font-medium text-foreground">
              {health.data?.status === "ok" ? "运行中" : "连接中"}
            </span>
          </div>
          <div className="flex items-center gap-1.5 text-sm text-muted-foreground">
            <IconTool className="size-4" />
            模型
            <span className="font-medium text-foreground">
              {health.data ? `${health.data.model}` : "—"}
            </span>
          </div>
          <div className="flex items-center gap-1.5 text-sm text-muted-foreground">
            <IconStack className="size-4" />
            供应商
            <span className="font-medium text-foreground">
              {health.data?.provider || "—"}
            </span>
          </div>
          <div className="flex items-center gap-1.5 text-sm text-muted-foreground">
            <IconMessages className="size-4" />
            服务端会话
            <span className="font-medium tabular-nums text-foreground">
              {health.data?.sessions ?? "—"}
            </span>
          </div>
        </CardContent>
      </Card>

      {/* 能力概览：统一面板，6 个指标并列 */}
      <Section icon={IconStack} title="能力概览" desc="agent 框架当前的真实体量">
        <Card>
          <CardContent className="py-4">
            <div className="grid grid-cols-2 gap-y-2 sm:grid-cols-3 lg:grid-cols-6">
              <Metric
                label="已加载工具"
                value={health.data?.tools ?? "—"}
                icon={IconTool}
                tint={{ text: "text-cyan", bg: "bg-cyan/10" }}
                loading={health.loading}
                context={
                  <span className="inline-flex items-center gap-1 text-cyan">
                    <span className="size-1.5 animate-pulse rounded-full bg-cyan" />
                    注册表实时在线
                  </span>
                }
              />
              <Metric
                label="已启用技能"
                value={skills.data?.length ?? "—"}
                icon={IconStack}
                tint={{ text: "text-amber", bg: "bg-amber/10" }}
                loading={skills.loading}
                context="技能市场已安装"
              />
              <Metric
                label="长期记忆"
                value={health.data?.memories ?? "—"}
                icon={IconBrain}
                tint={{ text: "text-violet-300", bg: "bg-violet-400/10" }}
                loading={health.loading}
                context={`覆盖 ${sessions} 个会话空间`}
              />
              <Metric
                label="会话总数"
                value={convCount || "—"}
                icon={IconMessages}
                tint={{ text: "text-emerald-400", bg: "bg-emerald-400/10" }}
                context={`${archived} 个已归档`}
              />
              <Metric
                label="对话轮次"
                value={totalRounds || "—"}
                icon={IconCpu}
                tint={{ text: "text-sky-400", bg: "bg-sky-400/10" }}
                loading={insights.loading}
                context={`平均 ${avgPerConv} 轮 / 会话`}
              />
              <Metric
                label="工具调用"
                value={toolTotal || "—"}
                icon={IconTrendingUp}
                tint={{ text: "text-rose-400", bg: "bg-rose-400/10" }}
                loading={insights.loading}
                context={`成功率 ${successRate}%`}
              />
            </div>
          </CardContent>
        </Card>
      </Section>

      {/* 趋势 */}
      <Section icon={IconTrendingUp} title="趋势" desc="用量与活跃度随时间">
        <div className="grid gap-4 lg:grid-cols-3">
          <Card className="lg:col-span-2">
            <CardHeader>
              <CardTitle className="flex items-center gap-2 text-base">
                <IconTrendingUp className="size-4 text-muted-foreground" />
                Token 用量
              </CardTitle>
              <CardDescription>
                来自后端 tracing 真实记录 · 实时累计
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="grid grid-cols-3 gap-3">
                <div>
                  <div className="text-2xl font-semibold tabular-nums text-primary">
                    {us ? (us.total_prompt_tokens || 0).toLocaleString() : "—"}
                  </div>
                  <div className="text-xs text-muted-foreground">Prompt Tokens</div>
                </div>
                <div>
                  <div className="text-2xl font-semibold tabular-nums text-amber-400">
                    {us ? (us.total_completion_tokens || 0).toLocaleString() : "—"}
                  </div>
                  <div className="text-xs text-muted-foreground">Completion Tokens</div>
                </div>
                <div>
                  <div className="text-2xl font-semibold tabular-nums">
                    {us
                      ? ((us.total_prompt_tokens || 0) + (us.total_completion_tokens || 0)).toLocaleString()
                      : "—"}
                  </div>
                  <div className="text-xs text-muted-foreground">合计 Tokens</div>
                </div>
              </div>
              <div className="h-52 w-full">
                <ResponsiveContainer width="100%" height="100%">
                  <AreaChart data={tokenData} margin={{ top: 8, right: 8, left: -18, bottom: 0 }}>
                    <defs>
                      <linearGradient id="gPrompt" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="0%" stopColor={PRIMARY} stopOpacity={0.5} />
                        <stop offset="100%" stopColor={PRIMARY} stopOpacity={0.02} />
                      </linearGradient>
                      <linearGradient id="gComp" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="0%" stopColor={AMBER} stopOpacity={0.4} />
                        <stop offset="100%" stopColor={AMBER} stopOpacity={0.02} />
                      </linearGradient>
                    </defs>
                    <CartesianGrid strokeDasharray="3 3" stroke="#1f2733" vertical={false} />
                    <XAxis dataKey="date" stroke={AXIS} fontSize={11} tickLine={false} axisLine={false} />
                    <YAxis stroke={AXIS} fontSize={11} tickLine={false} axisLine={false} width={48} />
                    <Tooltip contentStyle={TOOLTIP_STYLE} />
                    <Area type="monotone" dataKey="prompt" name="Prompt" stroke={PRIMARY} fill="url(#gPrompt)" strokeWidth={2} />
                    <Area type="monotone" dataKey="completion" name="Completion" stroke={AMBER} fill="url(#gComp)" strokeWidth={2} />
                  </AreaChart>
                </ResponsiveContainer>
              </div>
              {tokenData.length === 0 ? (
                <p className="text-xs text-muted-foreground">暂无用量记录</p>
              ) : null}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2 text-base">
                <IconActivity className="size-4 text-muted-foreground" />
                每日活跃度
              </CardTitle>
              <CardDescription>按天的交互事件量</CardDescription>
            </CardHeader>
            <CardContent>
              <div className="h-52 w-full">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={activityData} margin={{ top: 8, right: 8, left: -18, bottom: 0 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#1f2733" vertical={false} />
                    <XAxis dataKey="date" stroke={AXIS} fontSize={11} tickLine={false} axisLine={false} />
                    <YAxis stroke={AXIS} fontSize={11} tickLine={false} axisLine={false} width={48} />
                    <Tooltip contentStyle={TOOLTIP_STYLE} cursor={{ fill: "#ffffff08" }} />
                    <Bar dataKey="count" name="事件" fill={PRIMARY} radius={[4, 4, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
              {activityData.length === 0 ? (
                <p className="text-xs text-muted-foreground">暂无活动记录</p>
              ) : null}
            </CardContent>
          </Card>
        </div>
      </Section>

      {/* 执行 */}
      <Section icon={IconTool} title="执行" desc="工具调用与任务质量">
        <div className="grid gap-4 lg:grid-cols-3">
          <Card className="lg:col-span-2">
            <CardHeader>
              <CardTitle className="flex items-center gap-2 text-base">
                <IconTool className="size-4 text-muted-foreground" />
                工具调用排行（Top 12）
              </CardTitle>
              <CardDescription>全部工具累计调用次数</CardDescription>
            </CardHeader>
            <CardContent>
              <div className="h-[340px] w-full">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart
                    data={toolData}
                    layout="vertical"
                    margin={{ top: 4, right: 16, left: 8, bottom: 4 }}
                  >
                    <CartesianGrid strokeDasharray="3 3" stroke="#1f2733" horizontal={false} />
                    <XAxis type="number" stroke={AXIS} fontSize={11} tickLine={false} axisLine={false} />
                    <YAxis
                      type="category"
                      dataKey="name"
                      stroke={AXIS}
                      fontSize={11}
                      tickLine={false}
                      axisLine={false}
                      width={130}
                    />
                    <Tooltip contentStyle={TOOLTIP_STYLE} cursor={{ fill: "#ffffff08" }} />
                    <Bar dataKey="calls" name="调用" radius={[0, 4, 4, 0]}>
                      {toolData.map((_, i) => (
                        <Cell key={i} fill={i % 2 === 0 ? PRIMARY : AMBER} />
                      ))}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              </div>
              {toolData.length === 0 ? (
                <p className="text-xs text-muted-foreground">暂无工具调用</p>
              ) : null}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2 text-base">
                <IconCpu className="size-4 text-muted-foreground" />
                执行质量
              </CardTitle>
              <CardDescription>基于学习洞察的真实统计</CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <div>
                <div className="flex items-end justify-between">
                  <span className="text-xs text-muted-foreground">任务成功率</span>
                  <span className="text-lg font-semibold tabular-nums text-emerald-400">{successRate}%</span>
                </div>
                <div className="mt-1.5 h-2 w-full overflow-hidden rounded-full bg-muted">
                  <div
                    className="h-full rounded-full bg-emerald-500/70"
                    style={{ width: `${successRate === "—" ? 0 : Number(successRate)}%` }}
                  />
                </div>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-xs text-muted-foreground">平均评分</span>
                <span className="text-lg font-semibold tabular-nums">
                  {st ? `${st.avg_score} / 10` : "—"}
                </span>
              </div>
              <Separator />
              <div className="grid grid-cols-2 gap-3">
                <div className="rounded-md border border-border px-3 py-2">
                  <div className="text-xl font-semibold tabular-nums text-emerald-400">
                    {st?.outcomes.success ?? "—"}
                  </div>
                  <div className="text-xs text-muted-foreground">成功</div>
                </div>
                <div className="rounded-md border border-border px-3 py-2">
                  <div className="text-xl font-semibold tabular-nums text-red-400">
                    {st?.outcomes.failure ?? "—"}
                  </div>
                  <div className="text-xs text-muted-foreground">失败</div>
                </div>
              </div>
              <Badge variant="outline" className="w-full justify-center">
                累计轮次 {st?.total ?? "—"}
              </Badge>
            </CardContent>
          </Card>
        </div>
      </Section>

      {/* 记忆与活动 */}
      <Section icon={IconDatabase} title="记忆与活动" desc="对话隔离与近期动态">
        <div className="grid gap-4 lg:grid-cols-3">
          <Card className="lg:col-span-2">
            <CardHeader>
              <CardTitle className="flex items-center gap-2 text-base">
                <IconDatabase className="size-4 text-muted-foreground" />
                记忆分布（按对话）
              </CardTitle>
              <CardDescription>
                每个对话独立空间，记忆彼此隔离 · 本地消息数
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-3">
              {conversations.length === 0 ? (
                <p className="py-6 text-center text-sm text-muted-foreground">
                  还没有对话，先在「对话」里新建一个吧
                </p>
              ) : (
                conversations.map((c) => {
                  const pct = Math.round((c.messages.length / maxMsgs) * 100)
                  return (
                    <div key={c.id} className="space-y-1">
                      <div className="flex items-center justify-between text-xs">
                        <span className="truncate text-foreground/90" title={c.title}>
                          {c.title || "新对话"}
                        </span>
                        <span className="shrink-0 tabular-nums text-muted-foreground">
                          {c.messages.length} 条
                        </span>
                      </div>
                      <div className="h-2 w-full overflow-hidden rounded-full bg-muted">
                        <div
                          className="h-full rounded-full bg-primary/70"
                          style={{ width: `${pct}%` }}
                        />
                      </div>
                    </div>
                  )
                })
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2 text-base">
                <IconActivity className="size-4 text-muted-foreground" />
                近期活动
              </CardTitle>
              <CardDescription>本地对话时间线</CardDescription>
            </CardHeader>
            <CardContent>
              {recent.length === 0 ? (
                <p className="py-6 text-center text-sm text-muted-foreground">暂无活动</p>
              ) : (
                <ul className="space-y-3">
                  {recent.map((c) => (
                    <li key={c.id} className="flex items-start gap-2">
                      <span className="mt-1.5 size-1.5 shrink-0 rounded-full bg-primary/60" />
                      <div className="min-w-0 flex-1">
                        <p className="truncate text-sm text-foreground/90" title={c.title}>
                          {c.title || "新对话"}
                        </p>
                        <p className="text-xs text-muted-foreground">{timeAgo(c.updatedAt)}</p>
                      </div>
                    </li>
                  ))}
                </ul>
              )}
            </CardContent>
          </Card>
        </div>
      </Section>

      {/* 快捷操作 */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">快捷操作</CardTitle>
          <CardDescription>常用动作收于一处</CardDescription>
        </CardHeader>
        <CardContent className="flex flex-wrap gap-3">
          <Button
            className="gap-1.5"
            onClick={() => {
              createConversation()
              onGoChat()
            }}
          >
            <IconPlus className="size-4" />
            新建对话
          </Button>
          <Button variant="outline" className="gap-1.5" onClick={onGoLifecycle}>
            <IconListDetails className="size-4" />
            生命周期管理
          </Button>
          <Button variant="ghost" className="gap-1.5" onClick={refresh}>
            <IconRefresh className="size-4" />
            刷新数据
          </Button>
        </CardContent>
      </Card>

      {health.error ? (
        <p className="text-center text-xs text-red-400">
          运行数据获取失败：{health.error}
        </p>
      ) : null}
    </div>
  )
}
