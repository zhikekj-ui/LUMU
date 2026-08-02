import React, { useState, useEffect, useRef, useCallback } from 'react'
import { Send, Square, Trash2, Wrench, Moon, Sun, ArrowDown } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import { SidebarProvider, SidebarInset, SidebarTrigger } from '@/components/ui/sidebar'
import { AppSidebar } from '@/components/app-sidebar'
import { ActivitySidebar } from '@/components/activity-sidebar'
import { LumuMark } from '@/components/lumu-mark'
import { chatStream, listSessions, createSession, deleteSession, getSession, health } from '@/lib/api'
import { MarkdownBlock } from '@/lib/markdown'
import { sanitizeLive } from '@/lib/sanitize'
import { cn } from '@/lib/utils'
import type { Session, Activity, Meta } from '@/types'

type Role = 'user' | 'assistant' | 'sys'
interface MsgItem {
  type: 'msg'
  id: string
  role: Role
  content: string
  streaming?: boolean
}
interface ToolItem {
  type: 'tool'
  id: string
  tool: string
  status: 'run' | 'ok' | 'err'
  args?: any
  result?: any
}
type Item = MsgItem | ToolItem

const SPACE = 'work'

export default function App() {
  const [sessions, setSessions] = useState<Session[]>([])
  const [sessionId, setSessionId] = useState<string | null>(null)
  const [items, setItems] = useState<Item[]>([])
  const [activities, setActivities] = useState<Activity[]>([])
  const [streaming, setStreaming] = useState(false)
  const [thinking, setThinking] = useState(false)
  const [toBottom, setToBottom] = useState(false)
  const [theme, setTheme] = useState<'dark' | 'light'>(
    (localStorage.getItem('lumu_theme') as 'dark' | 'light') || 'dark'
  )
  const [meta, setMeta] = useState<Meta>({})
  const [input, setInput] = useState('')

  const abortRef = useRef<AbortController | null>(null)
  const transcriptRef = useRef<HTMLDivElement>(null)
  const textRef = useRef<HTMLTextAreaElement>(null)
  const atBottomRef = useRef(true)
  const idRef = useRef(0)
  const nextId = () => 'i' + ++idRef.current

  useEffect(() => {
    document.documentElement.className = theme
    localStorage.setItem('lumu_theme', theme)
  }, [theme])

  const scrollToBottom = useCallback(() => {
    const el = transcriptRef.current
    if (el && atBottomRef.current) el.scrollTop = el.scrollHeight
  }, [])

  const onScroll = useCallback(() => {
    const el = transcriptRef.current
    if (!el) return
    const d = el.scrollHeight - el.scrollTop - el.clientHeight
    atBottomRef.current = d < 60
    setToBottom(d > 120)
  }, [])

  useEffect(() => {
    loadSessions()
    health().then(setMeta).catch(() => {})
  }, [])

  async function loadSessions() {
    try {
      const d = await listSessions(SPACE)
      const arr: Session[] = d || []
      setSessions(arr)
      if (!sessionId && arr.length) selectSession(arr[0].id)
    } catch (e) {}
  }

  async function selectSession(id: string) {
    setSessionId(id)
    try {
      const d = await getSession(id)
      const msgs: any[] = d.messages || []
      setItems(msgs.map((m) => ({ type: 'msg', id: nextId(), role: m.role, content: m.content })))
    } catch (e) {
      setItems([])
    }
  }

  async function newSession(): Promise<string | undefined> {
    try {
      const d = await createSession(SPACE)
      setSessions((s) => [d, ...s])
      setSessionId(d.id)
      setItems([])
      return d.id
    } catch (e) {
      return undefined
    }
  }

  async function delSession(id: string) {
    try {
      await deleteSession(id)
      setSessions((s) => s.filter((x) => x.id !== id))
      if (sessionId === id) {
        setSessionId(null)
        setItems([])
        const rest = sessions.filter((x) => x.id !== id)
        if (rest.length) selectSession(rest[0].id)
      }
    } catch (e) {}
  }

  function addActivity(type: string, action: string, detail: string, status?: 'run' | 'ok' | 'err') {
    setActivities((a) => [{ id: nextId(), type, action, detail, ts: Date.now(), status }, ...a].slice(0, 40))
  }

  function upsertTool(tool: string, status: 'run' | 'ok' | 'err', args?: any, result?: any) {
    setItems((prev) => {
      const exist = prev.find((it) => it.type === 'tool' && (it as ToolItem).tool === tool)
      if (exist) {
        return prev.map((it) =>
          it === exist
            ? {
                ...(it as ToolItem),
                status,
                args: args ?? (it as ToolItem).args,
                result: result ?? (it as ToolItem).result
              }
            : it
        )
      }
      return [...prev, { type: 'tool', id: nextId(), tool, status, args, result }]
    })
  }

  function appendToken(t: string) {
    setItems((prev) => {
      const last = prev[prev.length - 1]
      if (last && last.type === 'msg' && last.role === 'assistant' && last.streaming) {
        return prev.map((it) => (it === last ? { ...last, content: last.content + t } : it))
      }
      return [...prev, { type: 'msg', id: nextId(), role: 'assistant', content: t, streaming: true }]
    })
    scrollToBottom()
  }

  function commitStream() {
    setItems((prev) =>
      prev.map((it) => (it.type === 'msg' && it.streaming ? { ...it, streaming: false } : it))
    )
  }

  function handleEvent(ev: any) {
    if (!ev || !ev.type) return
    if (ev.type === 'token') {
      if (thinking) setThinking(false)
      appendToken(sanitizeLive(ev.content || ''))
    } else if (ev.type === 'tool_start') {
      upsertTool(ev.tool, 'run', ev.args, null)
      addActivity('tool', '执行 ' + ev.tool, ev.args ? JSON.stringify(ev.args).slice(0, 200) : '', 'run')
    } else if (ev.type === 'tool_result') {
      const ok = !ev.error
      upsertTool(ev.tool, ok ? 'ok' : 'err', null, ev.result != null ? ev.result : ev.error)
      addActivity(
        'tool_result',
        '完成 ' + ev.tool,
        ev.result != null ? String(ev.result).slice(0, 200) : '',
        ok ? 'ok' : 'err'
      )
    } else if (ev.type === 'error') {
      addActivity('error', '错误', ev.content || '', 'err')
    } else if (ev.type === 'session') {
      if (ev.session_id && !sessionId) setSessionId(ev.session_id)
    }
  }

  function stopStream() {
    if (!streaming) return
    commitStream()
    if (abortRef.current) abortRef.current.abort()
  }

  async function send() {
    const text = input.trim()
    if (!text || streaming) return
    let sid = sessionId
    if (!sid) {
      sid = await newSession()
      if (!sid) return
    }
    setInput('')
    if (textRef.current) textRef.current.style.height = 'auto'
    setItems((prev) => [...prev, { type: 'msg', id: nextId(), role: 'user', content: text }])
    setStreaming(true)
    setThinking(true)
    const ac = new AbortController()
    abortRef.current = ac
    try {
      await chatStream({ message: text, session_id: sid, space: SPACE }, ac.signal, handleEvent)
      commitStream()
    } catch (err: any) {
      commitStream()
      if (err?.name !== 'AbortError') {
        setItems((prev) => [
          ...prev,
          { type: 'msg', id: nextId(), role: 'sys', content: '请求失败：' + (err?.message || err) }
        ])
      }
    } finally {
      setStreaming(false)
      setThinking(false)
      abortRef.current = null
      loadSessions()
    }
  }

  function autoSize(el: HTMLTextAreaElement) {
    el.style.height = 'auto'
    el.style.height = Math.min(el.scrollHeight, 140) + 'px'
  }

  function renderItem(it: Item) {
    if (it.type === 'tool') {
      const c = it as ToolItem
      return (
        <div key={c.id} className={cn('toolcard', c.status)}>
          <div className="tc-h">
            <Wrench className="ic" />
            <span className="nm">{c.tool}</span>
            <span className="st">
              {c.status === 'run' ? '执行中…' : c.status === 'ok' ? '完成' : '失败'}
            </span>
          </div>
          <div className="tc-b">
            {c.args != null && (
              <div>
                <span className="k">输入</span>{' '}
                <span className="v">{typeof c.args === 'string' ? c.args : JSON.stringify(c.args)}</span>
              </div>
            )}
            {c.result != null && (
              <div>
                <span className="k">输出</span>{' '}
                <span className="v">
                  {typeof c.result === 'string' ? c.result : JSON.stringify(c.result)}
                </span>
              </div>
            )}
          </div>
        </div>
      )
    }
    const m = it as MsgItem
    if (m.role === 'user') {
      return (
        <div key={m.id} className="line you">
          <div className="bubble you-bubble typeset typeset-chat">{m.content}</div>
        </div>
      )
    }
    if (m.role === 'sys') {
      return (
        <div key={m.id} className="line sys">
          <div className="who">
            <span className="dot dim" />
            系统
          </div>
          <div className="bubble sys-bubble typeset typeset-chat">
            <p>{m.content}</p>
          </div>
        </div>
      )
    }
    return (
      <div key={m.id} className={cn('line assistant', m.streaming && 'streaming')}>
        <div className="who">
          <span className="dot cyan" />
          LUMU
        </div>
        <div className={cn('bubble asst-bubble typeset typeset-chat', m.streaming && 'streaming')}>
          {m.streaming ? (
            <span className="stream">
              {sanitizeLive(m.content)}
              <span className="caret" />
            </span>
          ) : (
            <MarkdownBlock content={m.content} sanitize={true} />
          )}
        </div>
      </div>
    )
  }

  return (
    <SidebarProvider>
      <AppSidebar
        sessions={sessions}
        sessionId={sessionId}
        onSelect={selectSession}
        onNew={newSession}
        onDelete={delSession}
        meta={meta}
      />
      <SidebarInset>
        <header className="flex h-14 shrink-0 items-center gap-2 border-b border-sidebar-border px-3">
          <SidebarTrigger className="-ml-1" />
          <div className="flex items-center gap-2">
            <LumuMark size={20} />
            <span className="text-sm font-semibold text-foreground">LUMU 控制台</span>
          </div>
          <div className="ml-auto flex items-center gap-1.5">
            {meta.model && (
              <span className="hidden font-mono text-[11px] text-muted-foreground sm:inline">
                {meta.model}
              </span>
            )}
            {meta.tools != null && (
              <span className="hidden font-mono text-[11px] text-cyan sm:inline">{meta.tools} 工具</span>
            )}
            <Button
              variant="ghost"
              size="icon"
              onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')}
              aria-label="主题"
            >
              {theme === 'dark' ? <Moon className="size-4" /> : <Sun className="size-4" />}
            </Button>
            <Button
              variant="ghost"
              size="icon"
              className={cn(!sessionId && 'pointer-events-none opacity-30')}
              onClick={() => sessionId && delSession(sessionId)}
              aria-label="删除对话"
            >
              <Trash2 className="size-4" />
            </Button>
          </div>
        </header>

        <div className="relative flex min-h-0 flex-1 flex-col">
          <div ref={transcriptRef} onScroll={onScroll} className="scroll-thin flex-1 overflow-y-auto px-4 py-4">
            {items.length === 0 && (
              <div className="empty-conv">没有历史消息。在下方输入指令，让 LUMU 开始工作。</div>
            )}
            {items.map(renderItem)}
            {thinking && (
              <div className="line assistant thinking">
                <div className="who">
                  <span className="dot cyan" />
                  LUMU
                </div>
                <div className="bubble asst-bubble thinking">
                  <span className="dotp" />
                  <span className="dotp" />
                  <span className="dotp" />
                  <span className="think-txt">思考中…</span>
                </div>
              </div>
            )}
          </div>

          {toBottom && (
            <button
              className={cn('to-bottom', toBottom && 'show')}
              onClick={() => {
                atBottomRef.current = true
                setToBottom(false)
                scrollToBottom()
              }}
              aria-label="回到底部"
            >
              <ArrowDown className="w-4 h-4" />
            </button>
          )}

          <div className="flex items-end gap-2 border-t border-sidebar-border bg-background p-3">
            <Textarea
              ref={textRef}
              value={input}
              onChange={(e) => {
                setInput(e.target.value)
                autoSize(e.target)
              }}
              onKeyDown={(e) => {
                if (
                  e.key === 'Enter' &&
                  !e.shiftKey &&
                  !e.nativeEvent.isComposing &&
                  e.keyCode !== 229
                ) {
                  e.preventDefault()
                  send()
                }
              }}
              placeholder="输入指令… (Enter 发送 / Shift+Enter 换行)"
              className="max-h-[140px] min-h-[42px] flex-1 resize-none bg-background font-mono text-[13px]"
              rows={1}
            />
            <Button
              variant="default"
              size="icon"
              className="size-10 shrink-0 rounded-full bg-primary text-primary-foreground hover:bg-primary/90"
              onClick={() => (streaming ? stopStream() : send())}
              aria-label={streaming ? '停止' : '发送'}
            >
              {streaming ? <Square className="size-4" /> : <Send className="size-4" />}
            </Button>
          </div>
        </div>
      </SidebarInset>
      <ActivitySidebar activities={activities} />
    </SidebarProvider>
  )
}
