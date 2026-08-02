import * as React from "react"
import type { Msg } from "@/components/conversation"

export interface ConversationMeta {
  id: string
  title: string
  sessionId: string
  space: string // 每对话独立空间 → 记忆彼此隔离
  createdAt: number
  updatedAt: number
  preview: string
  messages: Msg[]
  archived?: boolean // 生命周期：已归档的会话
}

const STORAGE_KEY = "lumu_conversations_v1"

// 兼容旧版本/异常数据：把任意历史消息规整成当前 Msg 形状，避免渲染崩溃
function normalizeMsg(m: any): Msg | null {
  if (!m || typeof m !== "object") return null
  let blocks = m.blocks
  if (!Array.isArray(blocks)) {
    if (typeof m.content === "string") blocks = [{ type: "text", text: m.content }]
    else if (typeof m.text === "string") blocks = [{ type: "text", text: m.text }]
    else blocks = []
  }
  const role = m.role === "assistant" ? "assistant" : "user"
  return {
    id: typeof m.id === "string" ? m.id : genId("m"),
    role,
    blocks: blocks as Msg["blocks"],
    ts: typeof m.ts === "number" ? m.ts : Date.now(),
    streaming: false,
  } as Msg
}

// 规整历史对话：补齐 id/space/sessionId，确保每个对话独立 space（记忆隔离不丢）
function normalizeConv(c: any): ConversationMeta | null {
  if (!c || typeof c !== "object" || !c.id) return null
  const msgs = Array.isArray(c.messages)
    ? c.messages.map(normalizeMsg).filter((x: Msg | null): x is Msg => x !== null)
    : []
  return {
    id: c.id,
    title: typeof c.title === "string" ? c.title : "新对话",
    sessionId: typeof c.sessionId === "string" ? c.sessionId : genId("sess-"),
    space: typeof c.space === "string" ? c.space : c.id, // 缺 space 时用 id 兜底，记忆仍隔离
    createdAt: typeof c.createdAt === "number" ? c.createdAt : Date.now(),
    updatedAt: typeof c.updatedAt === "number" ? c.updatedAt : Date.now(),
    preview: typeof c.preview === "string" ? c.preview : "",
    messages: msgs,
    archived: c.archived === true,
  }
}

function loadAll(): ConversationMeta[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return []
    const arr = JSON.parse(raw)
    if (!Array.isArray(arr)) return []
    return arr
      .map(normalizeConv)
      .filter((x: ConversationMeta | null): x is ConversationMeta => x !== null)
  } catch {
    return []
  }
}

function genId(prefix: string) {
  return prefix + Date.now().toString(36) + Math.random().toString(36).slice(2, 7)
}

function msgText(m: Msg): string {
  return (m.blocks || [])
    .map((b) => {
      if (b.type === "text") return b.text
      if (b.type === "file") return `「文件：${(b as any).file?.name ?? ""}」`
      return `「执行 ${(b as any).tool ?? ""}」`
    })
    .join("\n\n")
}

interface Ctx {
  conversations: ConversationMeta[]
  activeId: string | null
  active: ConversationMeta | null
  createConversation: () => ConversationMeta
  selectConversation: (id: string) => void
  deleteConversation: (id: string) => void
  setActiveMessages: (updater: (prev: Msg[]) => Msg[]) => void
  setActiveSessionId: (sid: string) => void
  toggleArchive: (id: string) => void
  refreshMetaFromMessages: (msgs: Msg[]) => void
}

const ConversationsContext = React.createContext<Ctx | null>(null)

export function ConversationsProvider({ children }: { children: React.ReactNode }) {
  const [conversations, setConversations] = React.useState<ConversationMeta[]>(() => loadAll())
  const [activeId, setActiveId] = React.useState<string | null>(() => {
    const all = loadAll()
    return all.length ? all[0].id : null
  })

  // 统一持久化到 localStorage
  React.useEffect(() => {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(conversations))
    } catch {
      /* 隐私模式 / 容量超限时忽略写入失败 */
    }
  }, [conversations])

  const active = React.useMemo(
    () => conversations.find((c) => c.id === activeId) || null,
    [conversations, activeId]
  )

  const createConversation = React.useCallback((): ConversationMeta => {
    const id = genId("c")
    const now = Date.now()
    const conv: ConversationMeta = {
      id,
      title: "新对话",
      sessionId: genId("sess-"),
      space: id, // 每对话一个独立 space，记忆天然隔离
      createdAt: now,
      updatedAt: now,
      preview: "",
      messages: [],
      archived: false,
    }
    setConversations((prev) => [conv, ...prev])
    setActiveId(id)
    return conv
  }, [])

  const selectConversation = React.useCallback((id: string) => setActiveId(id), [])

  const deleteConversation = React.useCallback(
    (id: string) => {
      setConversations((prev) => {
        const next = prev.filter((c) => c.id !== id)
        if (id === activeId) setActiveId(next.length ? next[0].id : null)
        return next
      })
    },
    [activeId]
  )

  const toggleArchive = React.useCallback(
    (id: string) => {
      setConversations((prec) =>
        prec.map((c) => (c.id === id ? { ...c, archived: !c.archived } : c))
      )
    },
    []
  )

  const setActiveMessages = React.useCallback(
    (updater: (prev: Msg[]) => Msg[]) => {
      setConversations((prev) =>
        prev.map((c) =>
          c.id === activeId
            ? { ...c, messages: updater(c.messages), updatedAt: Date.now() }
            : c
        )
      )
    },
    [activeId]
  )

  const setActiveSessionId = React.useCallback(
    (sid: string) => {
      setConversations((prev) =>
        prev.map((c) => (c.id === activeId ? { ...c, sessionId: sid } : c))
      )
    },
    [activeId]
  )

  const refreshMetaFromMessages = React.useCallback(
    (msgs: Msg[]) => {
      const firstUser = msgs.find((m) => m.role === "user")
      const title = firstUser ? msgText(firstUser).slice(0, 20) || "新对话" : "新对话"
      const last = msgs[msgs.length - 1]
      const preview = last ? msgText(last).slice(0, 40) : ""
      setConversations((prev) =>
        prev.map((c) => {
          if (c.id !== activeId) return c
          if (c.title === title && c.preview === preview) return c
          return { ...c, title, preview, updatedAt: Date.now() }
        })
      )
    },
    [activeId]
  )

  const value: Ctx = {
    conversations,
    activeId,
    active,
    createConversation,
    selectConversation,
    deleteConversation,
    toggleArchive,
    setActiveMessages,
    setActiveSessionId,
    refreshMetaFromMessages,
  }
  return <ConversationsContext.Provider value={value}>{children}</ConversationsContext.Provider>
}

export function useConversations() {
  const ctx = React.useContext(ConversationsContext)
  if (!ctx) throw new Error("useConversations 必须在 ConversationsProvider 内使用")
  return ctx
}
