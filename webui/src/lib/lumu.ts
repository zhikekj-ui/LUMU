// LUMU 真实运行数据接口（全部对接 154 后端现有 / 新增端点，绝不编造数字）
import * as React from "react"

const BASE = "/api"

async function req(path: string, opts: RequestInit = {}) {
  const r = await fetch(BASE + path, {
    ...opts,
    headers: { "Content-Type": "application/json", ...(opts.headers || {}) },
  })
  if (!r.ok) throw new Error("HTTP " + r.status)
  return r
}

export interface Health {
  status: string
  model: string
  provider: string
  tools: number
  toolsets: string[]
  sessions: number
  memories: number
  skills: number
  plugins: string[]
  mcp_servers: number
  cron_jobs: number
  channels: string[]
}

export async function fetchHealth(): Promise<Health> {
  return (await req("/health")).json()
}

export interface Skill {
  name: string
  description: string
  tags: string
  space: string
  use_count: number
  updated_at: string
}

export async function fetchSkills(): Promise<Skill[]> {
  return (await req("/skills")).json()
}

export interface Provider {
  name: string
  display_name: string
  models: string[]
  enabled_models: string[]
  api_key_configured: boolean
}

export async function fetchProviders(): Promise<{ providers: Provider[] }> {
  return (await req("/config/providers")).json()
}

export async function fetchMemories(space: string): Promise<any[]> {
  return (await req(`/memory?space=${encodeURIComponent(space)}`)).json()
}

// 按 space 统计记忆（合并 primary + semantic，对话记忆实际落在 semantic）
export async function fetchMemoryUnified(
  space: string
): Promise<{ memories: any[]; total: number }> {
  return (await req(`/memory/unified?space=${encodeURIComponent(space)}`)).json()
}

// 清空某个 space 的全部记忆（primary + semantic）—— 用户侧隐私重置
export async function clearMemorySpace(space: string) {
  return (await req(`/memory/space/${encodeURIComponent(space)}`, { method: "DELETE" })).json()
}

export async function switchModel(provider: string, model: string) {
  return (await req("/config/model", {
    method: "POST",
    body: JSON.stringify({ provider, model }),
  })).json()
}

// 轻量数据获取 hook：统一处理 loading / error，避免各页面重复样板
export function useAsync<T>(fn: () => Promise<T>, deps: any[]) {
  const [state, setState] = React.useState<{
    data: T | null
    loading: boolean
    error: string | null
  }>({ data: null, loading: true, error: null })

  React.useEffect(() => {
    let alive = true
    setState((s) => ({ ...s, loading: true, error: null }))
    fn()
      .then((data) => {
        if (alive) setState({ data, loading: false, error: null })
      })
      .catch((e) => {
        if (alive)
          setState({ data: null, loading: false, error: String(e?.message || e) })
      })
    return () => {
      alive = false
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps)

  return state
}

// ---------------- 用量 / 学习洞察 / 时间线（仪表盘真实数据） ----------------

export interface UsageSummary {
  total_spans: number
  llm_calls: number
  total_prompt_tokens: number
  total_completion_tokens: number
  total_cost_usd: number
  avg_duration_ms: number
}

export interface UsageByDay {
  d: string
  prompt: number
  completion: number
  cost: number
  llm_calls: number
  total: number
}

export interface Usage {
  summary: UsageSummary
  by_day: UsageByDay[]
}

export async function fetchUsage(): Promise<Usage> {
  return (await req("/usage")).json()
}

export interface InsightStats {
  total: number
  outcomes: { failure: number; success: number }
  avg_score: number
  tool_usage: Record<string, number>
}

export interface Insights {
  stats: InsightStats
  failure_patterns?: { tools: string; count: number; reason: string }[]
}

export async function fetchInsights(): Promise<Insights> {
  return (await req("/learning/insights")).json()
}

export interface TimelineEvent {
  id: string
  turn_id: number
  kind: "user" | "assistant" | "tool"
  ts: string
  text: string
}

export async function fetchTimeline(): Promise<{ events: TimelineEvent[] }> {
  return (await req("/timeline")).json()
}

// ---------------- 资料库 / 知识图谱 ----------------
export interface KBDocument {
  id: string
  title: string
  category: string
  tags: string
  source: string
  created_at: string
  updated_at: string
}
export interface KBStats {
  total_entries: number
  categories: number
  entries_with_source: number
  db_path: string
}
export async function fetchKB(space = "work"): Promise<{ documents: KBDocument[]; stats: KBStats }> {
  return (await req(`/kb/documents?space=${encodeURIComponent(space)}`)).json()
}
export async function fetchKBStats(space = "work"): Promise<{ stats: KBStats; categories: { category: string; count: number }[] }> {
  return (await req(`/kb/stats?space=${encodeURIComponent(space)}`)).json()
}
export async function uploadKBDoc(space: string, file: File, meta?: { title?: string; category?: string; tags?: string }) {
  const fd = new FormData()
  fd.append("file", file)
  if (meta?.title) fd.append("title", meta.title)
  if (meta?.category) fd.append("category", meta.category)
  if (meta?.tags) fd.append("tags", meta.tags)
  const r = await fetch(`${BASE}/kb/documents?space=${encodeURIComponent(space)}`, { method: "POST", body: fd })
  if (!r.ok) throw new Error("上传失败 HTTP " + r.status)
  return r.json()
}
export async function deleteKBDoc(entryId: string) {
  return (await req(`/kb/documents/${encodeURIComponent(entryId)}`, { method: "DELETE" })).json()
}
export interface KBGraphNode {
  id: string
  type: string
  label: string
  text: string
  category: string
  x: number
  y: number
  z: number
  importance: number
}
export async function fetchKBGraph(space = "work"): Promise<{ nodes: KBGraphNode[]; relations?: any[] }> {
  return (await req(`/kb/graph?space=${encodeURIComponent(space)}`)).json()
}

// ---------------- 搜索（跨记忆 / 会话 / 技能） ----------------
export interface MemoryHit { key: string; content: string; category: string }
export async function fetchMemorySearch(q: string, limit = 10): Promise<MemoryHit[]> {
  return (await req(`/memory/search?q=${encodeURIComponent(q)}&limit=${limit}`)).json()
}
export interface SessionHit { id: string; preview: string; message_count: number; space: string }
export async function fetchSessions(space = "work"): Promise<SessionHit[]> {
  return (await req(`/sessions?space=${encodeURIComponent(space)}`)).json()
}
export async function fetchSkillsSearch(q: string): Promise<any[]> {
  // 注意：后端把 /api/skills/search 路由成 /api/skills/{name}（404），
  // 真实技能搜索走 /api/skills?search=<q>
  const data = await (await req(`/skills?search=${encodeURIComponent(q)}`)).json()
  return Array.isArray(data) ? data : (data?.skills ?? data?.results ?? [])
}

// ---------------- 设置（模型 / 系统提示词 / 参数 / TTS / STT） ----------------
export interface AppConfig {
  providers: Record<string, { enabled_models: string[]; api_key: string }>
  tts: { default_provider: string; mimo_api_key?: string }
  stt: { default_provider: string }
  provider_overrides: Record<string, any>
  model_preference: { provider: string; model: string }
  system_prompt: string
}
export async function fetchConfig(): Promise<AppConfig> {
  return (await req("/config")).json()
}
export async function saveSystemPrompt(text: string) {
  return (await req("/config/system-prompt", { method: "POST", body: JSON.stringify({ system_prompt: text }) })).json()
}
export async function saveParams(p: { temperature: number; top_p: number }) {
  return (await req("/config/params", { method: "POST", body: JSON.stringify(p) })).json()
}
export async function setProviderKey(provider: string, key: string) {
  return (await req(`/config/provider/${encodeURIComponent(provider)}/key`, { method: "POST", body: JSON.stringify({ api_key: key }) })).json()
}

// ---------------- 产品级用户反馈（个人市场反馈闭环） ----------------
export type FeedbackCategory = "suggest" | "bug" | "praise" | "question"
export interface FeedbackItem {
  id: number
  ts: string
  category: FeedbackCategory
  rating: number
  content: string
  feature: string
  page: string
  contact: string
  status: string
}
export interface FeedbackPayload {
  category: FeedbackCategory
  rating: number
  content: string
  feature?: string
  page?: string
  contact?: string
}
// 公开提交（个人用户无需密钥）
export async function submitFeedback(p: FeedbackPayload): Promise<{ status: string; message: string }> {
  const r = await fetch(BASE + "/feedback/submit", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(p),
  })
  const data = await r.json().catch(() => ({}))
  if (!r.ok) throw new Error(data?.detail || "提交失败")
  return data
}
// 后台列表（受 API key 保护，与现有接口一致）
export async function fetchFeedbackList(limit = 50): Promise<FeedbackItem[]> {
  const data = await (await req(`/feedback/admin?limit=${limit}`)).json()
  return data?.items ?? []
}

// ── 渠道接入配置（WebUI 设置页 → 个人市场切入点）──
export interface ChannelField {
  key: string
  label: string
  secret: boolean
  set: boolean
  value: string
}
export interface ChannelDef {
  key: string
  name: string
  desc: string
  doc: string
  enabled: boolean
  fields: ChannelField[]
}
export async function fetchChannelsConfig(): Promise<{ channels: ChannelDef[] }> {
  return (await req(`/config/channels`)).json()
}
// channels: { feishu: { FEISHU_APP_ID: "x", ... }, ... }（空字符串 = 不修改/清空）
export async function saveChannelsConfig(channels: Record<string, Record<string, string>>) {
  return (await req(`/config/channels`, {
    method: "POST",
    body: JSON.stringify({ channels }),
  })).json()
}

// ── 访问模式（小白开关：本机 / 对外分享）──
export interface AccessState {
  mode: "local" | "share"
  exposed: boolean
  auth_disabled: boolean
  token_present: boolean
  share_link: string | null
}
export async function fetchAccess(): Promise<AccessState> {
  return (await req("/access")).json()
}
export async function setAccess(
  action: "enable" | "rotate" | "disable",
): Promise<{ ok?: boolean; mode?: string; share_link?: string | null }> {
  return (await req("/access", {
    method: "POST",
    body: JSON.stringify({ action }),
  })).json()
}
