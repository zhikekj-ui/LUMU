"use client"

import * as React from "react"
import {
  IconArchive,
  IconTrash,
  IconBrain,
  IconTool,
  IconMessages,
  IconCheck,
  IconX,
  IconStack,
  IconDatabase,
  IconCircleFilled,
  IconPlayerStop,
  IconRefresh,
  IconChevronRight,
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
import { Separator } from "@/components/ui/separator"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { cn } from "@/lib/utils"
import { useConversations } from "@/components/conversations"
import {
  fetchHealth,
  fetchProviders,
  fetchSkills,
  fetchMemoryUnified,
  clearMemorySpace,
  switchModel,
  useAsync,
  type Health,
  type Provider,
  type Skill,
} from "@/lib/lumu"

type StageState = "done" | "active" | "todo"
interface Stage {
  label: string
  value?: number | string
  state: StageState
}

// 阶段块：方形卡片 + 箭头连接，当前阶段高亮；视觉统一、不花哨
function StageBar({ stages }: { stages: Stage[] }) {
  return (
    <div className="flex items-stretch gap-1.5">
      {stages.map((s, i) => (
        <React.Fragment key={s.label}>
          <div
            className={cn(
              "flex flex-1 flex-col items-center justify-center rounded-lg border px-2 py-3 text-center transition-colors",
              s.state === "active" &&
                "border-[#7fdcff]/50 bg-[#7fdcff]/10 shadow-[0_0_20px_rgba(127,220,255,0.12)]",
              s.state === "done" && "border-border bg-white/[0.04]",
              s.state === "todo" && "border-dashed border-border"
            )}
          >
            <div
              className={cn(
                "text-[11px] font-medium leading-tight",
                s.state === "active" ? "text-[#7fdcff]" : "text-muted-foreground"
              )}
            >
              {s.label}
            </div>
            {typeof s.value !== "undefined" ? (
              <div className="mt-1 text-lg font-semibold tabular-nums font-display text-foreground">
                {s.value}
              </div>
            ) : (
              <div className="mt-1 h-[22px]" />
            )}
          </div>
          {i < stages.length - 1 ? (
            <IconChevronRight className="my-auto size-4 shrink-0 text-muted-foreground/40" />
          ) : null}
        </React.Fragment>
      ))}
    </div>
  )
}

function ConfirmRow({
  onYes,
  onNo,
  label,
}: {
  onYes: () => void
  onNo: () => void
  label: string
}) {
  return (
    <div className="flex items-center gap-1.5">
      <span className="text-xs text-muted-foreground">{label}</span>
      <Button size="sm" variant="destructive" className="h-6 px-2" onClick={onYes}>
        <IconCheck className="size-3.5" /> 确认
      </Button>
      <Button size="sm" variant="ghost" className="h-6 px-2" onClick={onNo}>
        <IconX className="size-3.5" /> 取消
      </Button>
    </div>
  )
}

function SectionHeader({
  icon: Icon,
  title,
  desc,
}: {
  icon: React.ElementType
  title: string
  desc: string
}) {
  return (
    <CardHeader className="pb-3">
      <CardTitle className="flex items-center gap-2 text-base">
        <span className="flex size-7 items-center justify-center rounded-md bg-[#7fdcff]/10 text-[#7fdcff]">
          <Icon className="size-4" />
        </span>
        {title}
      </CardTitle>
      <CardDescription>{desc}</CardDescription>
    </CardHeader>
  )
}

export function LifecycleView({ onGoChat }: { onGoChat: () => void }) {
  const {
    conversations,
    deleteConversation,
    toggleArchive,
    selectConversation,
    activeId,
    createConversation,
  } = useConversations()
  const [nonce, setNonce] = React.useState(0)
  const health = useAsync<Health>(() => fetchHealth(), [nonce])
  const providers = useAsync<{ providers: Provider[] }>(() => fetchProviders(), [nonce])
  const skills = useAsync<Skill[]>(() => fetchSkills(), [nonce])

  const [confirm, setConfirm] = React.useState<
    | { kind: "delete"; id: string }
    | { kind: "clear"; id: string; space: string }
    | { kind: "global" }
    | null
  >(null)
  const [busy, setBusy] = React.useState(false)
  const [toast, setToast] = React.useState<string | null>(null)

  // 各 space 服务端记忆计数（真实）
  const [memCounts, setMemCounts] = React.useState<Record<string, number>>({})
  React.useEffect(() => {
    let alive = true
    Promise.all(
      conversations.map((c) =>
        fetchMemoryUnified(c.space)
          .then((r) => [c.id, r.total ?? 0] as const)
          .catch(() => [c.id, 0] as const)
      )
    )
      .then((entries) => {
        if (alive) setMemCounts(Object.fromEntries(entries))
      })
      .catch(() => {})
    return () => {
      alive = false
    }
  }, [conversations])

  const flash = (msg: string) => {
    setToast(msg)
    window.setTimeout(() => setToast(null), 2600)
  }

  const doClearSpace = async (id: string, space: string) => {
    setBusy(true)
    try {
      const r = await clearMemorySpace(space)
      setMemCounts((m) => ({ ...m, [id]: 0 }))
      flash(`已清理该空间记忆（删除 ${r.primary_deleted + r.semantic_deleted} 条）`)
    } catch (e: any) {
      flash("清理失败：" + (e?.message || e))
    } finally {
      setBusy(false)
      setConfirm(null)
    }
  }

  const doGlobalClear = async () => {
    setBusy(true)
    try {
      await Promise.all(conversations.map((c) => clearMemorySpace(c.space)))
      setMemCounts(Object.fromEntries(conversations.map((c) => [c.id, 0])))
      flash(`已清理全部 ${conversations.length} 个空间的记忆`)
    } catch (e: any) {
      flash("清理失败：" + (e?.message || e))
    } finally {
      setBusy(false)
      setConfirm(null)
    }
  }

  // 供应商显示名规范化（stepfun_plan → StepFun）
  const providerName = React.useCallback(
    (name: string) => {
      const base = name.replace(/_(plan|fallback|backup|备用)$/i, "")
      return (
        providers.data?.providers.find((p) => p.name === base)?.display_name ?? name
      )
    },
    [providers.data]
  )

  // 模型热切换：仅显示已配置 API Key 的供应商（不显示未配置的）
  const allProviders = providers.data?.providers || []
  const list = React.useMemo(() => {
    const conf = allProviders.filter((p) => p.api_key_configured)
    if (health.data?.provider && !conf.some((p) => p.name === health.data!.provider)) {
      const cur = allProviders.find((p) => p.name === health.data!.provider)
      if (cur) conf.push(cur)
    }
    return conf
  }, [allProviders, health.data?.provider])
  const [selProvider, setSelProvider] = React.useState("")
  const [selModel, setSelModel] = React.useState("")
  React.useEffect(() => {
    if (health.data && !selProvider) {
      setSelProvider(health.data.provider)
      setSelModel(health.data.model)
    }
  }, [health.data, selProvider])
  const curProvider = list.find((p) => p.name === selProvider)
  const modelOptions =
    curProvider?.enabled_models?.length
      ? curProvider.enabled_models
      : curProvider?.models || []

  const doSwitch = async () => {
    if (!selProvider || !selModel) return
    setBusy(true)
    try {
      const r = await switchModel(selProvider, selModel)
      flash(r?.message || "已切换模型")
      setNonce((n) => n + 1)
    } catch (e: any) {
      flash("切换失败：" + (e?.message || e))
    } finally {
      setBusy(false)
    }
  }

  // ---- 真实数据口径（修正旧版 health 字段缺失 bug）----
  const toolsLoaded = health.data?.tools_loaded ?? 0
  const totalMem = Object.values(memCounts).reduce((a, b) => a + b, 0)
  const spaceCount = conversations.length
  const skillList = skills.data || []
  const totalUse = skillList.reduce((a, s) => a + (s.use_count || 0), 0)

  const convNew = conversations.filter((c) => c.messages.length === 0 && !c.archived).length
  const convActive = conversations.filter((c) => c.messages.length > 0 && !c.archived).length
  const convArchived = conversations.filter((c) => c.archived).length

  const topSkills = [...skillList].sort((a, b) => (b.use_count || 0) - (a.use_count || 0)).slice(0, 5)

  const runtimeOk = health.data?.status === "ok"

  return (
    <div className="flex flex-col gap-5 p-4 md:p-6">
      {/* 页面标题 */}
      <div className="flex items-end justify-between gap-4">
        <div className="space-y-1">
          <h1 className="text-xl font-semibold tracking-tight text-foreground">生命周期</h1>
          <p className="text-sm text-muted-foreground">
            框架四类核心实体的真实状态流转 · 记忆重置权始终在你手里
          </p>
        </div>
        <Button
          variant="outline"
          size="sm"
          onClick={() => setNonce((n) => n + 1)}
          className="gap-1.5 shrink-0"
        >
          <IconRefresh className={cn("size-4", health.loading && "animate-spin")} />
          刷新
        </Button>
      </div>

      {/* Hero：运行时状态条 */}
      <Card className="overflow-hidden border-[#7fdcff]/15 bg-gradient-to-br from-[#7fdcff]/[0.04] to-transparent">
        <CardContent className="flex flex-wrap items-center justify-between gap-4 p-5">
          <div className="flex items-center gap-3">
            <div className="relative flex size-11 items-center justify-center">
              <span
                className={cn(
                  "absolute inline-flex size-11 rounded-full",
                  runtimeOk ? "animate-ping bg-emerald-500/20" : "bg-amber-500/20"
                )}
              />
              <span className="relative flex size-3 items-center justify-center rounded-full bg-emerald-500" />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <span className="text-lg font-semibold text-foreground">
                  {runtimeOk ? "运行中" : "未就绪"}
                </span>
                <Badge variant="outline" className="border-[#7fdcff]/40 text-[#7fdcff]">
                  {health.data ? `${providerName(health.data.provider)} / ${health.data.model}` : "—"}
                </Badge>
              </div>
              <div className="text-sm text-muted-foreground">agent 运行时 · 自启动持续服务</div>
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <MetricChip label="工具" value={toolsLoaded} />
            <MetricChip label="会话" value={conversations.length} />
            <MetricChip label="记忆" value={totalMem} />
            <MetricChip label="技能" value={skillList.length} />
            {confirm?.kind === "global" ? (
              <ConfirmRow
                label="确认清空全部记忆？"
                onYes={doGlobalClear}
                onNo={() => setConfirm(null)}
              />
            ) : (
              <Button
                variant="outline"
                size="sm"
                className="gap-1.5"
                disabled={busy || conversations.length === 0}
                onClick={() => setConfirm({ kind: "global" })}
              >
                <IconPlayerStop className="size-4" />
                全局清理记忆
              </Button>
            )}
          </div>
        </CardContent>
      </Card>

      {/* 2x2 实体生命周期卡 */}
      <div className="grid gap-4 lg:grid-cols-2">
        {/* 会话 */}
        <Card>
          <SectionHeader
            icon={IconMessages}
            title="会话生命周期"
            desc="每个对话独立记忆空间，状态实时流转"
          />
          <CardContent className="space-y-1">
            <StageBar
              stages={[
                { label: "新建", value: convNew, state: "done" },
                { label: "对话中", value: convActive, state: "active" },
                { label: "已归档", value: convArchived, state: "todo" },
              ]}
            />
          </CardContent>
        </Card>

        {/* 记忆 */}
        <Card>
          <SectionHeader
            icon={IconBrain}
            title="记忆生命周期"
            desc="按空间隔离沉淀 · 你随时可清理"
          />
          <CardContent className="space-y-1">
            <StageBar
              stages={[
                { label: "写入", state: "done" },
                { label: "累积", value: totalMem, state: "active" },
                { label: "按空间隔离", value: spaceCount, state: "done" },
                { label: "可清理", state: "todo" },
              ]}
            />
          </CardContent>
        </Card>

        {/* 技能 */}
        <Card>
          <SectionHeader
            icon={IconStack}
            title="技能生命周期"
            desc="从技能市场到被调用执行的完整链路"
          />
          <CardContent className="space-y-4">
            <StageBar
              stages={[
                { label: "技能市场", state: "done" },
                { label: "已启用", value: skillList.length, state: "active" },
                { label: "累计调用", value: totalUse, state: "done" },
              ]}
            />
            {topSkills.length > 0 && (
              <div className="space-y-1.5 border-t border-border pt-3">
                <div className="text-xs font-medium text-muted-foreground">高频技能</div>
                {topSkills.map((s) => (
                  <div key={s.name} className="flex items-center gap-2 text-sm">
                    <IconStack className="size-3.5 shrink-0 text-[#ffb454]/80" />
                    <span className="flex-1 truncate" title={s.name}>
                      {s.name}
                    </span>
                    <span className="shrink-0 text-xs tabular-nums text-muted-foreground">
                      {s.use_count || 0} 次
                    </span>
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>

        {/* 能力 & 模型 */}
        <Card>
          <SectionHeader
            icon={IconTool}
            title="能力与模型"
            desc="已注册工具与运行时热切换"
          />
          <CardContent className="space-y-4">
            <StageBar
              stages={[
                { label: "注册", state: "done" },
                { label: "加载", value: toolsLoaded, state: "active" },
                { label: "运行中", state: "done" },
              ]}
            />
            <div className="space-y-2 border-t border-border pt-3">
              <div className="flex items-center gap-2 text-sm">
                <IconCircleFilled className="size-3 text-emerald-500" />
                <span className="text-muted-foreground">当前模型</span>
                <span className="font-medium">
                  {health.data
                    ? `${providerName(health.data.provider)} / ${health.data.model}`
                    : "—"}
                </span>
              </div>
              <div className="flex gap-2">
                <Select value={selProvider} onValueChange={setSelProvider}>
                  <SelectTrigger className="flex-1">
                    <SelectValue placeholder="选择供应商" />
                  </SelectTrigger>
                  <SelectContent>
                    {list.map((p) => (
                      <SelectItem key={p.name} value={p.name}>
                        {p.display_name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <Select value={selModel} onValueChange={setSelModel}>
                  <SelectTrigger className="flex-1">
                    <SelectValue placeholder="选择模型" />
                  </SelectTrigger>
                  <SelectContent>
                    {modelOptions.map((m) => (
                      <SelectItem key={m} value={m}>
                        {m}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <Button
                className="w-full gap-1.5"
                disabled={busy || !selProvider || !selModel}
                onClick={doSwitch}
              >
                <IconRefresh className={cn("size-4", busy && "animate-spin")} />
                切换模型
              </Button>
              <p className="text-xs text-muted-foreground">
                仅显示已配置 API Key 的供应商（未配置的不列出）
              </p>
            </div>
          </CardContent>
        </Card>
      </div>

      {/* 可操作管理区：会话 + 记忆 */}
      <div className="grid gap-4 lg:grid-cols-2">
        {/* 会话管理 */}
        <Card>
          <SectionHeader
            icon={IconMessages}
            title="会话管理"
            desc="归档或删除历史对话"
          />
          <CardContent className="space-y-2">
            {conversations.length === 0 ? (
              <p className="py-6 text-center text-sm text-muted-foreground">还没有对话</p>
            ) : (
              conversations.slice(0, 8).map((c) => {
                const stage = c.archived
                  ? "已归档"
                  : c.messages.length > 0
                    ? "对话中"
                    : "新建"
                return (
                  <div
                    key={c.id}
                    className={cn(
                      "flex items-center gap-2 rounded-md border border-border px-3 py-1.5",
                      c.id === activeId && "border-[#7fdcff]/40 bg-[#7fdcff]/5"
                    )}
                  >
                    <button
                      className="flex-1 truncate text-left text-sm"
                      onClick={() => {
                        selectConversation(c.id)
                        onGoChat()
                      }}
                      title={c.title}
                    >
                      {c.title || "新对话"}
                    </button>
                    <Badge variant={c.archived ? "secondary" : "outline"} className="shrink-0">
                      {stage}
                    </Badge>
                    {confirm?.kind === "delete" && confirm.id === c.id ? (
                      <ConfirmRow
                        label="删除？"
                        onYes={() => {
                          deleteConversation(c.id)
                          setConfirm(null)
                        }}
                        onNo={() => setConfirm(null)}
                      />
                    ) : (
                      <div className="flex shrink-0 items-center gap-0.5">
                        <Button
                          size="sm"
                          variant="ghost"
                          className="h-7 px-2"
                          onClick={() => toggleArchive(c.id)}
                        >
                          <IconArchive className="size-3.5" />
                        </Button>
                        <Button
                          size="sm"
                          variant="ghost"
                          className="h-7 px-2 text-muted-foreground hover:text-red-400"
                          onClick={() => setConfirm({ kind: "delete", id: c.id })}
                        >
                          <IconTrash className="size-3.5" />
                        </Button>
                      </div>
                    )}
                  </div>
                )
              })
            )}
            {conversations.length > 8 ? (
              <p className="pt-1 text-center text-xs text-muted-foreground">
                还有 {conversations.length - 8} 个会话…
              </p>
            ) : null}
            <Button
              variant="outline"
              size="sm"
              className="mt-1 w-full justify-start gap-1.5"
              onClick={() => {
                createConversation()
                onGoChat()
              }}
            >
              <IconMessages className="size-4" />
              新对话
            </Button>
          </CardContent>
        </Card>

        {/* 记忆空间管理 */}
        <Card>
          <SectionHeader
            icon={IconBrain}
            title="记忆空间管理"
            desc="按会话空间隔离 · 单空间清理"
          />
          <CardContent className="space-y-2">
            {conversations.length === 0 ? (
              <p className="py-6 text-center text-sm text-muted-foreground">还没有对话</p>
            ) : (
              conversations.slice(0, 8).map((c) => (
                <div
                  key={c.id}
                  className="flex items-center gap-2 rounded-md border border-border px-3 py-1.5"
                >
                  <IconDatabase className="size-4 shrink-0 text-muted-foreground" />
                  <span className="flex-1 truncate text-sm" title={c.title}>
                    {c.title || "新对话"}
                  </span>
                  <span className="shrink-0 text-xs tabular-nums text-muted-foreground">
                    {memCounts[c.id] ?? "·"} 条
                  </span>
                  {confirm?.kind === "clear" && confirm.id === c.id ? (
                    <ConfirmRow
                      label="清空？"
                      onYes={() => doClearSpace(c.id, c.space)}
                      onNo={() => setConfirm(null)}
                    />
                  ) : (
                    <Button
                      size="sm"
                      variant="ghost"
                      className="h-7 px-2 text-muted-foreground hover:text-red-400"
                      disabled={busy}
                      onClick={() => setConfirm({ kind: "clear", id: c.id, space: c.space })}
                    >
                      清理
                    </Button>
                  )}
                </div>
              ))
            )}
            {conversations.length > 8 ? (
              <p className="pt-1 text-center text-xs text-muted-foreground">
                还有 {conversations.length - 8} 个空间…
              </p>
            ) : null}
          </CardContent>
        </Card>
      </div>

      {toast ? (
        <p className="text-center text-xs text-[#7fdcff]">{toast}</p>
      ) : null}
    </div>
  )
}

function MetricChip({ label, value }: { label: string; value: number | string }) {
  return (
    <div className="flex items-center gap-1.5 rounded-md border border-border bg-white/[0.03] px-2.5 py-1.5">
      <span className="text-xs text-muted-foreground">{label}</span>
      <span className="text-sm font-semibold tabular-nums font-display text-foreground">
        {value}
      </span>
    </div>
  )
}
