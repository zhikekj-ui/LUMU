import * as React from "react"
import { Send, Wrench, Loader2, Check, ChevronDown, Copy, Mic, Square, Paperclip, X, Upload } from "lucide-react"
import { Button } from "@/components/ui/button"
import { cn } from "@/lib/utils"
import { FileBlock, FileCard, splitFileLinks } from "@/components/file-card"
import { useConversations } from "@/components/conversations"

// —— 数据模型：一条消息由「阶段块」按发生顺序组成 ——
// text 块：一段输出内容（段落/标题/列表）
// tool 块：一次工具调用，折叠在它发生的那句话下面
interface TextBlock {
  type: "text"
  text: string
  streaming?: boolean
}

interface ToolBlock {
  type: "tool"
  id: string
  tool: string
  args?: string
  result?: string
 status: "running" | "done"
  startedAt?: number
  finishedAt?: number
}

interface ApprovalBlock {
  type: "approval"
  id: string
  tool: string
  args?: string
  risk: string
  reason?: string
  actionId: string
  decision: "pending" | "approved" | "denied" | "timeout"
}


// 用户上传的附件块（随对话持久化）。
// 注意：图片只存压缩后的小缩略图，绝不存原图 dataURL——对话历史写在 localStorage，
// 原图 base64 几张就会撑爆 5MB 配额，导致整个对话历史保存失败。
interface AttachBlock {
  type: "attach"
  id: string
  name: string
  mime: string
  size: number
  thumb?: string
}

type Block = TextBlock | ToolBlock | ApprovalBlock | FileBlock | AttachBlock

// —— 附件容量限制 ——
// 线上 Nginx client_max_body_size = 10M，而 base64 编码会让体积膨胀约 33%，
// 再加上 JSON 结构本身的开销，这里把原始文件卡在 6MB 以内，留足安全余量。
const MAX_ATTACH_FILES = 5 // 后端视觉链路也只取前 5 张图
const MAX_ATTACH_SINGLE = 6 * 1024 * 1024
const MAX_ATTACH_TOTAL = 6 * 1024 * 1024

// 待发送的附件（data 为完整 dataURL；不进 localStorage，发完即弃）
interface PendingAttach {
  id: string
  name: string
  mime: string
  size: number
  data: string
  thumb?: string
}

function readAsDataURL(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const r = new FileReader()
    r.onload = () => resolve(String(r.result || ""))
    r.onerror = () => reject(new Error("读取失败"))
    r.readAsDataURL(file)
  })
}

// 图片压成小缩略图用于气泡展示与持久化（最长边 160px，jpeg 0.6，约几 KB）
function makeThumb(dataUrl: string): Promise<string | undefined> {
  return new Promise((resolve) => {
    try {
      const img = new Image()
      img.onload = () => {
        try {
          const max = 160
          const scale = Math.min(1, max / Math.max(img.width || 1, img.height || 1))
          const w = Math.max(1, Math.round((img.width || 1) * scale))
          const h = Math.max(1, Math.round((img.height || 1) * scale))
          const cv = document.createElement("canvas")
          cv.width = w
          cv.height = h
          const ctx = cv.getContext("2d")
          if (!ctx) return resolve(undefined)
          ctx.drawImage(img, 0, 0, w, h)
          resolve(cv.toDataURL("image/jpeg", 0.6))
        } catch {
          resolve(undefined)
        }
      }
      img.onerror = () => resolve(undefined)
      img.src = dataUrl
    } catch {
      resolve(undefined)
    }
  })
}

function attachIcon(mime: string, name: string): string {
  const m = (mime || "").toLowerCase()
  const n = (name || "").toLowerCase()
  if (m.startsWith("image/")) return "🖼"
  if (m.startsWith("audio/")) return "🔊"
  if (m.startsWith("video/")) return "🎬"
  if (m.includes("pdf") || n.endsWith(".pdf")) return "📄"
  if (n.endsWith(".zip") || n.endsWith(".rar") || n.endsWith(".7z")) return "🗜"
  if (n.endsWith(".xlsx") || n.endsWith(".xls") || n.endsWith(".csv")) return "📊"
  if (n.endsWith(".docx") || n.endsWith(".doc")) return "📝"
  return "📎"
}

function humanBytes(n: number): string {
  n = n || 0
  if (n < 1024) return n + " B"
  if (n < 1024 * 1024) return (n / 1024).toFixed(1) + " KB"
  return (n / 1024 / 1024).toFixed(1) + " MB"
}

export interface Msg {
  id: string
  role: "user" | "assistant"
  blocks: Block[]
  streaming?: boolean
  ts: number // 发送时间（用户消息=发送时刻；助手消息=开始生成时刻）
  startedAt?: number // 助手开始执行时刻
  finishedAt?: number // 助手执行结束时刻
}

const GREETING: Msg = {
  id: "greeting",
  role: "assistant",
  blocks: [
    {
      type: "text",
      text: "你好，我是 LUMU。把任务告诉我，我来帮你拆解并执行。",
    },
  ],
  ts: 0,
}

// 轻量结构化渲染：标题 / 列表 / 加粗 / 段落，给输出内容层次感（非挤在一个气泡里）
function renderInline(text: string, keyBase: string) {
  const parts = text.split(/(\*\*[^*]+\*\*)/g)
  return parts.map((p, i) => {
    const m = p.match(/^\*\*([^*]+)\*\*$/)
    if (m)
      return (
        <strong key={keyBase + i} className="font-semibold text-foreground">
          {m[1]}
        </strong>
      )
    return <React.Fragment key={keyBase + i}>{p}</React.Fragment>
  })
}

function renderRich(text: string) {
  const lines = text.split("\n")
  const out: React.ReactNode[] = []
  let buf: string[] = []
  const flush = (key: string) => {
    if (buf.length) {
      const text = buf.join("\n")
      const segs = splitFileLinks(text)
      if (segs.length === 1 && segs[0].kind === "md") {
        out.push(
          <p key={key} className="whitespace-pre-wrap leading-relaxed">
            {renderInline(text, key)}
          </p>
        )
      } else {
        // 段落里若含内部文件链接（[label](/api/files/fid)），拆出来渲染成 FileCard
        segs.forEach((seg, si) => {
          if (seg.kind === "file") {
            out.push(
              <FileCard key={key + "f" + si} block={{ type: "file", id: seg.file.id, file: seg.file }} />
            )
          } else {
            out.push(
              <p key={key + "m" + si} className="whitespace-pre-wrap leading-relaxed">
                {renderInline(seg.text, key + "m" + si)}
              </p>
            )
          }
        })
      }
      buf = []
    }
  }
  let i = 0
  while (i < lines.length) {
    const line = lines[i]
    const t = line.trim()
    // 标题
    const h = t.match(/^(#{1,3})\s+(.*)$/)
    if (h) {
      flush("p" + i)
      const lvl = h[1].length
      const cls =
        lvl === 1
          ? "text-base font-bold text-cyan mt-0.5"
          : lvl === 2
          ? "text-sm font-semibold text-cyan/90 mt-0.5"
          : "text-sm font-medium text-cyan/80"
      out.push(
        <p key={"h" + i} className={cn("leading-relaxed", cls)}>
          {renderInline(h[2], "h" + i)}
        </p>
      )
      i++
      continue
    }
    // 无序列表
    if (/^[-*]\s+/.test(t)) {
      flush("p" + i)
      const items: string[] = []
      while (i < lines.length && /^[-*]\s+/.test(lines[i].trim())) {
        items.push(lines[i].trim().replace(/^[-*]\s+/, ""))
        i++
      }
      out.push(
        <ul
          key={"u" + i}
          className="list-disc space-y-1 pl-5 leading-relaxed marker:text-cyan/60"
        >
          {items.map((it, k) => {
            const segs = splitFileLinks(it)
            if (segs.length === 1 && segs[0].kind === "md")
              return <li key={k}>{renderInline(it, "u" + i + "k" + k)}</li>
            return (
              <li key={k}>
                {segs.map((seg, si) =>
                  seg.kind === "file" ? (
                    <FileCard key={si} block={{ type: "file", id: seg.file.id, file: seg.file }} />
                  ) : (
                    <React.Fragment key={si}>{renderInline(seg.text, "u" + i + "k" + k + si)}</React.Fragment>
                  )
                )}
              </li>
            )
          })}
        </ul>
      )
      continue
    }
    // 有序列表
    if (/^\d+\.\s+/.test(t)) {
      flush("p" + i)
      const items: string[] = []
      while (i < lines.length && /^\d+\.\s+/.test(lines[i].trim())) {
        items.push(lines[i].trim().replace(/^\d+\.\s+/, ""))
        i++
      }
      out.push(
        <ol
          key={"o" + i}
          className="list-decimal space-y-1 pl-5 leading-relaxed marker:text-cyan/60"
        >
          {items.map((it, k) => {
            const segs = splitFileLinks(it)
            if (segs.length === 1 && segs[0].kind === "md")
              return <li key={k}>{renderInline(it, "o" + i + "k" + k)}</li>
            return (
              <li key={k}>
                {segs.map((seg, si) =>
                  seg.kind === "file" ? (
                    <FileCard key={si} block={{ type: "file", id: seg.file.id, file: seg.file }} />
                  ) : (
                    <React.Fragment key={si}>{renderInline(seg.text, "o" + i + "k" + k + si)}</React.Fragment>
                  )
                )}
              </li>
            )
          })}
        </ol>
      )
      continue
    }
    // 空行 -> 段落分隔
    if (t === "") {
      flush("p" + i)
      i++
      continue
    }
    buf.push(line)
    i++
  }
  flush("p_end")
  return out
}

// 取一条消息的纯文本（用于复制 / 用户气泡显示）
function textOf(m: Msg): string {
  return (m.blocks || [])
    .map((b) => {
      if (b.type === "text") return b.text
      if (b.type === "file") return `「文件：${b.file.name}」`
      if (b.type === "attach") return "" // 附件在气泡里单独渲染，避免正文重复
      return `「执行 ${b.tool}」`
    })
    .join("\n\n")
}


// 模块级 id 计数器：新消息 id 自增，避免同一会话内消息 id 撞车（React key 冲突）
let seq = 0
let stepSeq = 0

// 消息持久化已交由 ConversationsProvider（localStorage lumu_conversations_v1）统一管理。
// 这里保留模块级 id 计数器，避免同一会话内消息 id 撞车。
const nextId = () => "m" + ++seq
const nextStepId = () => "s" + ++stepSeq

function fmtTime(ts?: number) {
  if (!ts) return ""
  const d = new Date(ts)
  const hh = String(d.getHours()).padStart(2, "0")
  const mm = String(d.getMinutes()).padStart(2, "0")
  return `${hh}:${mm}`
}

function fmtDur(ms: number) {
  if (ms < 0 || !isFinite(ms)) ms = 0
  const s = ms / 1000
  if (s < 60) return s.toFixed(1) + "s"
  const m = Math.floor(s / 60)
  const r = Math.round(s % 60)
  return `${m}m${r}s`
}

export function Conversation() {
  const {
    active,
    activeId,
    setActiveMessages,
    refreshMetaFromMessages,
    createConversation,
    setActiveSessionId,
  } = useConversations()
  // 当前对话的消息（无消息时显示问候语）
  const messages = (active?.messages && active.messages.length
    ? active.messages
    : [GREETING]) as Msg[]
  const [input, setInput] = React.useState("")
  const [streaming, setStreaming] = React.useState(false)
  // 工具块展开状态：执行中转 true（阶段性展示）；做完转 false（折叠）；手动可切换
  const [expanded, setExpanded] = React.useState<Record<string, boolean>>({})
  const [copiedId, setCopiedId] = React.useState<string>("")
  const scrollRef = React.useRef<HTMLDivElement>(null)
  const textRef = React.useRef<HTMLTextAreaElement>(null)
  // 开箱引导：检测是否已配置模型 Key，未配置则在空对话给出醒目提示（避免新用户误以为装坏）
  const [modelReady, setModelReady] = React.useState<boolean | null>(null)
  React.useEffect(() => {
    let alive = true
    fetch("/api/config/providers")
      .then((r) => r.json())
      .then((d: any) => {
        const ps = (d && d.providers) || []
        if (alive) setModelReady(ps.some((p: any) => p.api_key_configured))
      })
      .catch(() => alive && setModelReady(null))
    return () => { alive = false }
  }, [])

  // —— 附件上传：待发送队列 + 拖拽态 + 超限提示 ——
  const [attachments, setAttachments] = React.useState<PendingAttach[]>([])
  const [dragOver, setDragOver] = React.useState(false)
  const [attachErr, setAttachErr] = React.useState("")
  const fileInputRef = React.useRef<HTMLInputElement>(null)
  const dragDepth = React.useRef(0)
  // 中止控制器：供「停止」按钮取消进行中的流式请求
  const abortRef = React.useRef<AbortController | null>(null)
  // 后端连接状态：驱动输入框「在线/离线」提示与禁用逻辑，避免「输进去没反应」无从判断
  const [backend, setBackend] = React.useState<"online" | "offline" | "connecting">(
    "connecting"
  )
  // 镜像队列：addFiles 是稳定回调（空依赖），必须靠 ref 读到最新值，否则闭包过期会漏算已有附件
  const attachmentsRef = React.useRef<PendingAttach[]>([])
  React.useEffect(() => {
    attachmentsRef.current = attachments
  }, [attachments])

  // 超限提示 4 秒后自动消失
  React.useEffect(() => {
    if (!attachErr) return
    const t = setTimeout(() => setAttachErr(""), 4000)
    return () => clearTimeout(t)
  }, [attachErr])

  // 后端健康探测：进入即探一次，之后每 5s 轮询；标签页重新可见时也补探，保证状态灯实时
  React.useEffect(() => {
    let alive = true
    const probe = async () => {
      try {
        const r = await fetch("/api/health", { cache: "no-store" })
        if (alive) setBackend(r.ok ? "online" : "offline")
      } catch {
        if (alive) setBackend("offline")
      }
    }
    probe()
    const t = setInterval(probe, 5000)
    const onVis = () => {
      if (document.visibilityState === "visible") probe()
    }
    document.addEventListener("visibilitychange", onVis)
    return () => {
      alive = false
      clearInterval(t)
      document.removeEventListener("visibilitychange", onVis)
    }
  }, [])

  const addFiles = React.useCallback(
    async (list: File[]) => {
      if (!list.length) return
      const errs: string[] = []
      // 读取现有队列的快照（走 ref，避免闭包过期）
      const cur = attachmentsRef.current
      let count = cur.length
      let total = cur.reduce((s, a) => s + a.size, 0)
      const accepted: File[] = []
      for (const f of list) {
        if (count >= MAX_ATTACH_FILES) {
          errs.push(`最多只能同时上传 ${MAX_ATTACH_FILES} 个文件`)
          break
        }
        if (f.size > MAX_ATTACH_SINGLE) {
          errs.push(`「${f.name}」超过 ${humanBytes(MAX_ATTACH_SINGLE)}，无法上传`)
          continue
        }
        if (total + f.size > MAX_ATTACH_TOTAL) {
          errs.push(`附件合计不能超过 ${humanBytes(MAX_ATTACH_TOTAL)}`)
          break
        }
        // 同名同大小去重
        if (cur.some((a) => a.name === f.name && a.size === f.size)) continue
        accepted.push(f)
        count++
        total += f.size
      }
      if (errs.length) setAttachErr(errs[0])
      if (!accepted.length) return

      const built: PendingAttach[] = []
      for (const f of accepted) {
        try {
          const data = await readAsDataURL(f)
          const mime = f.type || "application/octet-stream"
          const thumb = mime.startsWith("image/") ? await makeThumb(data) : undefined
          built.push({
            id: Math.random().toString(36).slice(2),
            name: f.name || "file",
            mime,
            size: f.size,
            data,
            thumb,
          })
        } catch {
          setAttachErr(`「${f.name}」读取失败`)
        }
      }
      if (built.length) setAttachments((prev) => [...prev, ...built])
    },
    []
  )

  const removeAttach = React.useCallback((id: string) => {
    setAttachments((prev) => prev.filter((a) => a.id !== id))
  }, [])

  // 确保存在激活对话；新用户首次进入（localStorage 为空）时 activeId 为 null，
  // send() 走兜底 createConversation 时 conversations 还在异步合并，
  // setActiveMessages 拿到的 m 是空数组 → 用户消息会落空。
  // 提前在这里建好对话，send 就能直接拿到 active 并写入消息。
  React.useEffect(() => {
    if (!activeId) createConversation()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // —— 语音输入：浏览器录音 → 后端 faster-whisper 识别为文字回填 ——
  const [sttAvailable, setSttAvailable] = React.useState<boolean | null>(null)
  const [recording, setRecording] = React.useState(false)
  const [recSeconds, setRecSeconds] = React.useState(0)
  const mediaRecorderRef = React.useRef<MediaRecorder | null>(null)
  const recChunksRef = React.useRef<Blob[]>([])
  const recTimerRef = React.useRef<number | null>(null)
  const streamRef = React.useRef<MediaStream | null>(null)

  // 探测后端 STT 是否可用，决定是否显示麦克风按钮
  React.useEffect(() => {
    fetch("/api/stt/status")
      .then((r) => r.json())
      .then((d) => setSttAvailable(!!d.available))
      .catch(() => setSttAvailable(false))
  }, [])

  // 录音计时
  React.useEffect(() => {
    if (recording) {
      setRecSeconds(0)
      recTimerRef.current = window.setInterval(() => setRecSeconds((s) => s + 1), 1000)
    }
    return () => {
      if (recTimerRef.current) {
        clearInterval(recTimerRef.current)
        recTimerRef.current = null
      }
    }
  }, [recording])

  // 录音开关：点一下开始、再点停止并识别
  async function toggleRecord() {
    if (recording) {
      mediaRecorderRef.current?.stop()
      setRecording(false)
      return
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      streamRef.current = stream
      const mr = new MediaRecorder(stream)
      recChunksRef.current = []
      mr.ondataavailable = (e) => {
        if (e.data.size > 0) recChunksRef.current.push(e.data)
      }
      mr.onstop = async () => {
        const blob = new Blob(recChunksRef.current, { type: mr.mimeType || "audio/webm" })
        stream.getTracks().forEach((t) => t.stop())
        streamRef.current = null
        if (blob.size === 0) return
        try {
          const fd = new FormData()
          fd.append("audio", blob, "rec.webm")
          fd.append("language", "zh")
          const resp = await fetch("/api/stt/transcribe", { method: "POST", body: fd })
          if (!resp.ok) throw new Error("STT 服务返回 " + resp.status)
          const data = await resp.json()
          const text = data.text || data.transcript || ""
          if (text) {
            setInput((prev) => (prev ? prev + (prev.endsWith(" ") ? "" : " ") : "") + text)
            requestAnimationFrame(() => {
              if (textRef.current) {
                textRef.current.style.height = "auto"
                textRef.current.style.height = Math.min(textRef.current.scrollHeight, 136) + "px"
              }
            })
          }
        } catch (err: any) {
          console.error("语音识别失败", err)
          alert("语音识别失败：" + (err?.message || err))
        }
      }
      mediaRecorderRef.current = mr
      mr.start()
      setRecording(true)
    } catch (err: any) {
      console.error("无法访问麦克风", err)
      alert("无法访问麦克风：" + (err?.message || err))
    }
  }

  // 主视角固定在最新内容：每次消息变化都滚到底部（刷新后也滚到最新）
  React.useEffect(() => {
    const el = scrollRef.current
    if (!el) return
    const toBottom = () => {
      el.scrollTop = el.scrollHeight
    }
    toBottom()
    // 字体/布局延迟稳定后再校正一次，避免刷新后停在最旧消息
    const raf = requestAnimationFrame(toBottom)
    if (typeof document !== "undefined" && (document as any).fonts?.ready) {
      ;(document as any).fonts.ready.then(toBottom).catch(() => {})
    }
    return () => cancelAnimationFrame(raf)
  }, [messages])

  // 消息变化后刷新当前对话的标题/预览（首条用户消息为标题，末条为预览）
  React.useEffect(() => {
    if (activeId) refreshMetaFromMessages(active?.messages ?? [])
  }, [active?.messages, activeId, refreshMetaFromMessages])

  async function copyText(id: string, text: string) {
    try {
      await navigator.clipboard.writeText(text)
    } catch {
      const ta = document.createElement("textarea")
      ta.value = text
      ta.style.position = "fixed"
      ta.style.opacity = "0"
      document.body.appendChild(ta)
      ta.select()
      try {
        document.execCommand("copy")
      } catch {
        /* 忽略复制失败 */
      }
      document.body.removeChild(ta)
    }
    setCopiedId(id)
    setTimeout(() => setCopiedId((c) => (c === id ? "" : c)), 1500)
  }

  function autoSize(el: HTMLTextAreaElement) {
    el.style.height = "auto"
    el.style.height = Math.min(el.scrollHeight, 136) + "px"
  }

  // 把 token 追加到「当前最后一个 text 块」；若最后不是 text 块（如刚插入工具块）则新建一段
  function appendBlockText(aid: string, t: string) {
    if (!t) return
    setActiveMessages((m) =>
      m.map((x) => {
        if (x.id !== aid) return x
        const blocks = [...x.blocks]
        const last = blocks[blocks.length - 1]
        if (last && last.type === "text") {
          blocks[blocks.length - 1] = { ...last, text: last.text + t }
        } else {
          blocks.push({ type: "text", text: t, streaming: true })
        }
        return { ...x, blocks }
      })
    )
  }

  // 插入一个新的工具块（阶段性地出现在当前输出之后）
  function pushToolBlock(aid: string, block: ToolBlock) {
    setActiveMessages((m) =>
      m.map((x) =>
        x.id === aid ? { ...x, blocks: [...x.blocks, block] } : x
      )
    )
  }

  // 插入一个新的审批块（人工审批卡片）
  function pushApprovalBlock(aid: string, block: ApprovalBlock) {
    setActiveMessages((m) =>
      m.map((x) =>
        x.id === aid ? { ...x, blocks: [...x.blocks, block] } : x
      )
    )
  }

  // 插入一个新的文件块（语音/图片/视频/文档），成为对话的一部分
  function pushFileBlock(aid: string, block: FileBlock) {
    setActiveMessages((m) =>
      m.map((x) =>
        x.id === aid ? { ...x, blocks: [...x.blocks, block] } : x
      )
    )
  }

  // 把结果填回「最后一个仍在 running 的工具块」
  function finishToolBlock(aid: string, result: string) {
    const at = Date.now()
    setActiveMessages((m) =>
      m.map((x) => {
        if (x.id !== aid) return x
        const blocks = [...x.blocks]
        for (let i = blocks.length - 1; i >= 0; i--) {
          const b = blocks[i]
          if (b.type === "tool" && b.status === "running") {
            blocks[i] = { ...b, result, status: "done", finishedAt: at }
            break
          }
        }
        return { ...x, blocks }
      })
    )
  }

  function handleEvent(ev: any, aid: string) {
    switch (ev?.type) {
      case "session":
        if (ev.session_id) {
          setActiveSessionId(ev.session_id)
        }
        return
      case "token":
        appendBlockText(aid, ev.content ?? "")
        return
      case "tool_start":
        pushToolBlock(aid, {
          type: "tool",
          id: nextStepId(),
          tool: ev.tool ?? "未知工具",
          args: ev.args ? JSON.stringify(ev.args) : undefined,
          status: "running",
          startedAt: Date.now(),
        })
        return
      case "tool_result":
        finishToolBlock(aid, String(ev.result ?? "").slice(0, 280))
        return
      case "approval_required":
        pushApprovalBlock(aid, {
          type: "approval",
          id: ev.action_id,
          tool: ev.tool ?? "未知工具",
          args: ev.args ? JSON.stringify(ev.args) : undefined,
          risk: ev.risk ?? "UNKNOWN",
          reason: ev.reason,
          actionId: ev.action_id,
          decision: "pending",
        })
        return
      case "error":
        appendBlockText(aid, "\n\n[错误] " + (ev.content ?? ""))
        return
      case "file":
        // agent 生成的文件：作为对话块持久化，刷新随对话恢复
        if (ev.file && ev.file.id) {
          pushFileBlock(aid, {
            type: "file",
            id: nextStepId(),
            file: {
              id: ev.file.id,
              name: ev.file.name || "file",
              mime: ev.file.mime || "application/octet-stream",
              size: ev.file.size || 0,
            },
          })
        }
        return
      default:
        return
    }
  }

  async function send() {
    if (backend === "offline") return
    const text = input.trim()
    const atts = attachments
    // 允许「只发附件不打字」
    if ((!text && !atts.length) || streaming) return
    setInput("")
    setAttachments([])
    setAttachErr("")
    const ta = textRef.current
    if (ta) {
      ta.style.height = ta.scrollHeight + "px"
      requestAnimationFrame(() =>
        requestAnimationFrame(() => {
          if (textRef.current) textRef.current.style.height = "auto"
        })
      )
    }
    const sendTs = Date.now()
    const aid = nextId()
    setActiveMessages((m) => [
      ...m,
      {
        id: nextId(),
        role: "user",
        blocks: [
          ...atts.map(
            (a): Block => ({
              type: "attach",
              id: a.id,
              name: a.name,
              mime: a.mime,
              size: a.size,
              thumb: a.thumb, // 仅小缩略图进 localStorage
            })
          ),
          ...(text ? [{ type: "text", text } as Block] : []),
        ],
        ts: sendTs,
      },
      {
        id: aid,
        role: "assistant",
        blocks: [],
        streaming: true,
        ts: sendTs,
        startedAt: sendTs,
      },
    ])
    setStreaming(true)

    // 确保有激活对话；没有则先创建一个（每对话独立 space → 独立记忆）
    let cur = active
    if (!cur) {
      cur = createConversation()
    }
    const sid = cur.sessionId || ""
    const space = cur.space || cur.id // 兜底：缺 space 时用 id，记忆仍隔离

    try {
      const ctrl = new AbortController()
      abortRef.current = ctrl
      // 只发附件不打字时补一句默认指令（后端 message 为必填）
      const outMsg = text || "请查看我上传的附件。"
      const body: any = { message: outMsg, session_id: sid, space }
      // 附件契约：files:[{name, mime, data}]。
      // data 必须是完整 dataURL——后端对不以 "data:" 开头的图片会硬拼 png 前缀，
      // jpeg 若传纯 base64 会被厂商判为格式不符而报错。
      if (atts.length) {
        body.files = atts.map((a) => ({ name: a.name, mime: a.mime, data: a.data }))
      }
      const res = await fetch("/api/chat/stream", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
        signal: ctrl.signal,
      })
      if (!res.ok || !res.body) throw new Error("后端返回 " + res.status)
      const reader = res.body.getReader()
      const decoder = new TextDecoder()
      let buf = ""
      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buf += decoder.decode(value, { stream: true })
        let idx
        while ((idx = buf.indexOf("\n\n")) !== -1) {
          const chunk = buf.slice(0, idx)
          buf = buf.slice(idx + 2)
          const dataLine = chunk.split("\n").find((l) => l.startsWith("data:"))
          if (!dataLine) continue
          const payload = dataLine.slice(5).trim()
          if (!payload) continue
          try {
            handleEvent(JSON.parse(payload), aid)
          } catch {
            /* 忽略坏帧 */
          }
        }
      }
    } catch (e: any) {
      appendBlockText(aid, "\n\n[连接后端失败] " + (e?.message || String(e)))
    } finally {
      abortRef.current = null
      // 本轮执行结束：写入结束时刻
      setActiveMessages((m) =>
        m.map((x) =>
          x.streaming ? { ...x, streaming: false, finishedAt: Date.now() } : x
        )
      )
      setStreaming(false)
    }
  }

  // 停止当前生成：中止流式请求并收尾（避免「发了没反应」时用户无法中断）
  function stop() {
    abortRef.current?.abort()
    abortRef.current = null
    setStreaming(false)
    setActiveMessages((m) =>
      m.map((x) => {
        if (!x.streaming) return x
        const blocks =
          x.blocks && x.blocks.length
            ? x.blocks
            : ([{ type: "text", text: "（已停止）" }] as Block[])
        return { ...x, blocks, streaming: false, finishedAt: Date.now() }
      })
    )
  }

  return (
    <div
      className="lumu-term relative flex min-h-0 flex-1 flex-col overflow-hidden"
      onDragEnter={(e) => {
        if (!Array.from(e.dataTransfer?.types || []).includes("Files")) return
        e.preventDefault()
        dragDepth.current++
        setDragOver(true)
      }}
      onDragOver={(e) => {
        if (!Array.from(e.dataTransfer?.types || []).includes("Files")) return
        e.preventDefault()
        e.dataTransfer.dropEffect = "copy"
      }}
      onDragLeave={(e) => {
        if (!Array.from(e.dataTransfer?.types || []).includes("Files")) return
        e.preventDefault()
        // 用计数抵消子元素冒泡产生的 leave，避免遮罩闪烁
        dragDepth.current = Math.max(0, dragDepth.current - 1)
        if (dragDepth.current === 0) setDragOver(false)
      }}
      onDrop={(e) => {
        if (!Array.from(e.dataTransfer?.types || []).includes("Files")) return
        e.preventDefault()
        dragDepth.current = 0
        setDragOver(false)
        const fs = Array.from(e.dataTransfer?.files || [])
        if (fs.length) addFiles(fs)
      }}
    >
      {dragOver && (
        <div className="pointer-events-none absolute inset-0 z-30 flex items-center justify-center border-2 border-dashed border-[var(--cyan)]/60 bg-background/80">
          <div className="flex flex-col items-center gap-2 text-sm text-[var(--cyan)]">
            <Upload className="size-7" />
            <span>松手即可添加附件</span>
            <span className="text-[11px] text-muted-foreground">
              最多 {MAX_ATTACH_FILES} 个 · 单个不超过 {humanBytes(MAX_ATTACH_SINGLE)}
            </span>
          </div>
        </div>
      )}

      <div
        ref={scrollRef}
        className="scroll-thin flex min-h-0 flex-1 flex-col gap-5 overflow-y-auto px-4 py-4"
      >
        {messages.length === 0 && (
          <div className="term-welcome">
            <p>Last login: {new Date().toLocaleString()} on lumu-local</p>
            <p className="term-welcome-title">LUMU Terminal — 本地智能体控制台</p>
            <p>输入指令开始工作。支持拖拽 / 粘贴文件、语音输入。</p>
            <p className="term-welcome-hint">› 在下方输入框键入指令，Enter 发送</p>
          </div>
        )}
        {modelReady === false && (active?.messages?.length ?? 0) === 0 && (
          <div className="term-setup-tip">
            <span className="term-setup-icon">⚠</span>
            <span>
              尚未配置模型：请先到左侧 <b>设置 → 模型</b> 填入一个模型 Key（任何 OpenAI 兼容接口均可），即可开始对话。
            </span>
          </div>
        )}
        {messages.map((m) => {
          return (
            <div
              key={m.id}
              className={cn(
                "flex",
                m.role === "user" ? "justify-end" : "justify-start"
              )}
            >
              {m.role === "assistant" && (
                <span className="term-prompt asst mt-3 shrink-0 select-none">lumu ➜</span>
              )}
              <div className="flex max-w-[82%] flex-col gap-1">
                {/* 气泡：用户=纯文本；助手=阶段块（段落 + 穿插的工具调用） */}
                {m.role === "user" ? (
                  (() => {
                    const atts = (m.blocks || []).filter(
                      (b): b is AttachBlock => b.type === "attach"
                    )
                    const body = m.blocks.length ? textOf(m) : ""
                    return (
                      <div className="flex flex-col items-end gap-1.5">
                        {atts.length > 0 && (
                          <div className="flex flex-wrap justify-end gap-1.5">
                            {atts.map((a) => (
                              <div
                                key={a.id}
                                className="flex items-center gap-2 rounded-xl border border-white/10 bg-sidebar/60 px-2.5 py-1.5"
                                title={`${a.name} · ${humanBytes(a.size)}`}
                              >
                                {a.thumb ? (
                                  <img
                                    src={a.thumb}
                                    alt={a.name}
                                    className="size-9 shrink-0 rounded-md object-cover"
                                  />
                                ) : (
                                  <span className="text-base leading-none">
                                    {attachIcon(a.mime, a.name)}
                                  </span>
                                )}
                                <span className="max-w-[150px] truncate text-xs text-foreground">
                                  {a.name}
                                </span>
                                <span className="shrink-0 text-[10px] text-muted-foreground">
                                  {humanBytes(a.size)}
                                </span>
                              </div>
                            ))}
                          </div>
                        )}
                        {body && (
                          <div className="text-sm leading-relaxed">
                            <span className="term-prompt user">user@lumu ~ %</span>
                            <span className="whitespace-pre-wrap text-foreground">{body}</span>
                          </div>
                        )}
                      </div>
                    )
                  })()
                ) : (
                  <div className="text-sm leading-relaxed">
                    {(m.blocks || []).length === 0 ? m.streaming ? (
                      <div className="flex items-center gap-2 py-0.5 text-[var(--faint)]">
                        <span className="flex gap-1">
                          <i className="dotp" />
                          <i className="dotp" />
                          <i className="dotp" />
                        </span>
                        <span className="think-txt">思考中…</span>
                      </div>
                    ) : (
                      <span className="text-[var(--dim)] text-xs">（无响应内容）</span>
                    ) : (
                      <div className="flex flex-col gap-3">
                        {(m.blocks || []).map((b, bi) => {
                          const isLast = bi === m.blocks.length - 1
                          // 文件块：语音/图片/视频/文档，随对话持久化，刷新不丢
                          if (b.type === "file") {
                            return <FileCard key={b.id} block={b} />
                          }
                          // 附件块只属于用户消息，这里显式排除以保证下方工具块的类型收窄
                          if (b.type === "attach") {
                            return null
                          }
                          if (b.type === "text") {
                            return (
                              <div key={"t" + bi}>
                                {b.text ? (
                                  <div className="space-y-3">
                                    {renderRich(b.text)}
                                  </div>
                                ) : (
                                  <span className="term-caret" />
                                )}
                                {m.streaming && isLast && b.text && (
                                  <span className="term-caret" />
                                )}
                              </div>
                            )
                          }
                          // 审批块
                          if (b.type === "approval") {
                            const onDecide = async (
                              kind: "approve" | "deny",
                              scope: "once" | "session" = "once"
                            ) => {
                              try {
                                const url =
                                  kind === "deny"
                                    ? `/api/approvals/${b.actionId}/deny`
                                    : `/api/approvals/${b.actionId}/approve`
                                await fetch(url, {
                                  method: "POST",
                                  headers: { "Content-Type": "application/json" },
                                  body:
                                    kind === "deny"
                                      ? undefined
                                      : JSON.stringify({ scope, feedback: "" }),
                                })
                              } catch {}
                              setActiveMessages((m) =>
                                m.map((x) =>
                                  x.id === aid
                                    ? {
                                        ...x,
                                        blocks: x.blocks.map((bb) =>
                                          bb.id === b.id
                                            ? {
                                                ...bb,
                                                decision:
                                                  kind === "deny"
                                                    ? "denied"
                                                    : "approved",
                                              }
                                            : bb
                                        ),
                                      }
                                    : x
                                )
                              )
                            }
                            return (
                              <div
                                key={b.id}
                                className="overflow-hidden rounded-xl border border-amber-500/30 bg-amber-500/5"
                              >
                                <div className="flex flex-col gap-2 px-3 py-2.5">
                                  <div className="flex items-center gap-2 text-xs">
                                    <Wrench className="size-3.5 text-amber-400" />
                                    <span className="font-medium text-foreground/90">
                                      {b.tool}
                                    </span>
                                    <span
                                      className={cn(
                                        "ml-auto rounded px-1.5 py-0.5 text-[10px] font-medium",
                                        b.risk === "CRITICAL"
                                          ? "bg-red-500/15 text-red-400"
                                          : b.risk === "HIGH"
                                          ? "bg-amber-500/15 text-amber-400"
                                          : b.risk === "MEDIUM"
                                          ? "bg-yellow-500/15 text-yellow-400"
                                          : "bg-sky-500/15"
                                      )}
                                    >
                                      {b.risk}
                                    </span>
                                  </div>
                                  {b.args && (
                                    <pre className="whitespace-pre-wrap break-words font-mono text-[11px] text-muted-foreground">
                                      参数：{b.args}
                                    </pre>
                                  )}
                                  {b.reason && (
                                    <div className="text-[11px] text-muted-foreground">
                                      原因：{b.reason}
                                    </div>
                                  )}
                                  {b.decision === "pending" ? (
                                    <div className="flex flex-wrap gap-2 pt-1">
                                      <Button
                                        size="sm"
                                        className="bg-emerald-600 hover:bg-emerald-500"
                                        onClick={() => onDecide("approve")}
                                      >
                                        允许
                                      </Button>
                                      <Button
                                        size="sm"
                                        variant="destructive"
                                        onClick={() => onDecide("deny")}
                                      >
                                        拒绝
                                      </Button>
                                      <Button
                                        size="sm"
                                        variant="outline"
                                        onClick={() => onDecide("approve", "session")}
                                      >
                                        始终允许
                                      </Button>
                                    </div>
                                  ) : (
                                    <div
                                      className={cn(
                                        "pt-1 text-[11px] font-medium",
                                        b.decision === "approved"
                                          ? "text-emerald-400"
                                          : "text-red-400"
                                      )}
                                    >
                                      {b.decision === "approved"
                                        ? "✅ 已批准执行"
                                        : "⛔ 已拒绝执行"}
                                    </div>
                                  )}
                                </div>
                              </div>
                            )
                          }
                          // 工具块：阶段性地折叠在它发生的那句话下面
                          const toolOpen =
                            b.status === "running" ? true : !!expanded[b.id]
                          const dur =
                            b.startedAt != null && b.finishedAt != null
                              ? fmtDur(b.finishedAt - b.startedAt)
                              : null
                          return (
                            <div
                              key={b.id}
                              className={cn(
                                "overflow-hidden rounded-xl",
                                toolOpen
                                  ? "border border-white/[0.06] bg-sidebar/60"
                                  : "self-start border-0 bg-transparent"
                              )}
                            >
                              <button
                                type="button"
                                onClick={() =>
                                  setExpanded((e) => ({
                                    ...e,
                                    [b.id]: !e[b.id],
                                  }))
                                }
                                className="flex w-full items-center gap-1.5 px-3 py-2 text-left text-[11px] font-medium tracking-wide text-cyan/80 transition-colors hover:text-cyan"
                              >
                                <ChevronDown
                                  className={cn(
                                    "size-3.5 transition-transform",
                                    !toolOpen && "-rotate-90"
                                  )}
                                />
                                <Wrench className="size-3.5 text-cyan/70" />
                                <span>执行 {b.tool}</span>
                                <span className="text-cyan/55">
                                  · {b.status === "done" ? "已完成" : "执行中…"}
                                </span>
                                {dur && (
                                  <span className="ml-auto text-cyan/70">
                                    用时 {dur}
                                  </span>
                                )}
                                {b.status === "running" && !dur && (
                                  <span className="ml-auto flex items-center gap-1 text-cyan/70">
                                    <Loader2 className="size-3 animate-spin" />
                                    执行中…
                                  </span>
                                )}
                              </button>
                              {toolOpen && (
                                <div className="flex flex-col gap-1.5 px-3 pb-2.5">
                                  <div className="rounded-lg border border-white/[0.06] bg-sidebar/40 px-2.5 py-1.5">
                                    <div className="flex items-center gap-2 text-xs">
                                      {b.status === "running" ? (
                                        <Loader2 className="size-3.5 animate-spin text-cyan" />
                                      ) : (
                                        <Wrench className="size-3.5 text-cyan/70" />
                                      )}
                                      <span className="font-medium text-foreground/90">
                                        {b.tool}
                                      </span>
                                      {b.status === "running" ? (
                                        <span className="ml-auto text-[10px] text-cyan/80">
                                          执行中…
                                        </span>
                                      ) : (
                                        <Check className="ml-auto size-3.5 text-emerald-400" />
                                      )}
                                    </div>
                                    {b.args && (
                                      <pre className="mt-1 whitespace-pre-wrap break-words font-mono text-[11px] text-muted-foreground">
                                        参数：{b.args}
                                      </pre>
                                    )}
                                    {b.result && (
                                      <pre className="mt-1 whitespace-pre-wrap break-words font-mono text-[11px] text-muted-foreground/90">
                                        结果：{b.result}
                                      </pre>
                                    )}
                                  </div>
                                </div>
                              )}
                            </div>
                          )
                        })}
                      </div>
                    )}
                  </div>
                )}

                {/* 时间 + 复制：置于内容下方（气泡之后） */}
                <div
                  className={cn(
                    "flex items-center gap-1.5 px-1 text-[10px] text-muted-foreground/70",
                    m.role === "user" && "flex-row-reverse"
                  )}
                >
                  <span>{fmtTime(m.ts)}</span>
                  <button
                    type="button"
                    title="复制内容"
                    onClick={() => copyText(m.id, textOf(m))}
                    className="flex size-4 items-center justify-center rounded transition-colors hover:text-cyan"
                  >
                    {copiedId === m.id ? (
                      <Check className="size-3 text-emerald-400" />
                    ) : (
                      <Copy className="size-3" />
                    )}
                  </button>
                </div>
              </div>
            </div>
          )
        })}
      </div>

      {/* 待发送附件条 + 超限提示 */}
      {(attachments.length > 0 || attachErr) && (
        <div className="mx-auto w-full max-w-3xl px-3 pt-2">
          {attachErr && (
            <div className="mb-1.5 rounded-lg border border-amber-500/30 bg-amber-500/10 px-3 py-1.5 text-xs text-amber-300">
              {attachErr}
            </div>
          )}
          {attachments.length > 0 && (
            <div className="flex flex-wrap items-center gap-2">
              {attachments.map((a) => (
                <div
                  key={a.id}
                  className="group relative flex items-center gap-2 rounded-xl border border-white/10 bg-sidebar/60 py-1.5 pl-2 pr-7"
                  title={`${a.name} · ${humanBytes(a.size)}`}
                >
                  {a.thumb ? (
                    <img
                      src={a.thumb}
                      alt={a.name}
                      className="size-8 shrink-0 rounded-md object-cover"
                    />
                  ) : (
                    <span className="text-base leading-none">
                      {attachIcon(a.mime, a.name)}
                    </span>
                  )}
                  <span className="flex flex-col leading-tight">
                    <span className="max-w-[150px] truncate text-xs text-foreground">
                      {a.name}
                    </span>
                    <span className="text-[10px] text-muted-foreground">
                      {humanBytes(a.size)}
                    </span>
                  </span>
                  <button
                    onClick={() => removeAttach(a.id)}
                    className="absolute right-1 top-1/2 -translate-y-1/2 rounded-full p-1 text-muted-foreground transition-colors hover:bg-white/10 hover:text-foreground"
                    aria-label={`移除 ${a.name}`}
                    title="移除"
                  >
                    <X className="size-3" />
                  </button>
                </div>
              ))}
              <span className="text-[10px] text-muted-foreground">
                {attachments.length}/{MAX_ATTACH_FILES} · 合计{" "}
                {humanBytes(attachments.reduce((s, a) => s + a.size, 0))}
              </span>
            </div>
          )}
        </div>
      )}

      {/* 连接状态灯：始终可见，第一时间告知后端是否在线 */}
      <div className="mx-auto mb-1.5 flex w-full max-w-3xl items-center gap-2 px-1 font-mono text-[11px]">
        <span
          className={cn(
            "inline-block size-1.5 rounded-full",
            backend === "online"
              ? "bg-[var(--cyan)] shadow-[0_0_6px_rgba(127,220,255,0.7)]"
              : backend === "offline"
              ? "bg-[var(--danger)]"
              : "bg-[var(--dim)] animate-pulse"
          )}
        />
        <span
          className={
            backend === "online"
              ? "text-[var(--cyan)]"
              : backend === "offline"
              ? "text-[var(--danger)]"
              : "text-[var(--dim)]"
          }
        >
          {backend === "online" ? "后端在线" : backend === "offline" ? "后端未连接" : "连接中…"}
        </span>
        <span className="text-[var(--dim)]">·</span>
        <span className="text-[var(--dim)]">
          {backend === "offline"
            ? "请先启动 LUMU：python run.py"
            : "Enter 发送 · Shift+Enter 换行 · 拖拽/粘贴文件"}
        </span>
      </div>

      {backend === "offline" ? (
        <div className="mx-auto flex w-full max-w-3xl items-center gap-3 rounded-xl border border-[rgba(255,107,107,0.35)] bg-[rgba(255,107,107,0.06)] px-4 py-3 text-sm text-[var(--danger)]">
          <span className="inline-block size-2 shrink-0 rounded-full bg-[var(--danger)]" />
          后端未连接，无法发送。请在本机终端运行{" "}
          <code className="mx-1 rounded bg-black/30 px-1.5 py-0.5 font-mono text-[var(--amber)]">
            python run.py
          </code>{" "}
          启动 LUMU 服务。
        </div>
      ) : (
        <div className="mx-auto flex w-full max-w-3xl items-end gap-2 rounded-xl border border-[rgba(127,220,255,0.14)] bg-[var(--panel2)] px-3 py-2 transition-shadow focus-within:border-[rgba(127,220,255,0.5)] focus-within:shadow-[0_0_0_3px_rgba(127,220,255,0.10)]">
          <input
            ref={fileInputRef}
            type="file"
            multiple
            className="hidden"
            onChange={(e) => {
              addFiles(Array.from(e.target.files || []))
              e.target.value = "" // 允许重复选同一个文件
            }}
          />
          <Button
            size="icon"
            variant="ghost"
            className="size-10 shrink-0 rounded-full"
            onClick={() => fileInputRef.current?.click()}
            disabled={streaming}
            aria-label="上传附件"
            title="上传附件（图片 / 文档 / 代码，也可直接拖拽或粘贴）"
          >
            <Paperclip className="size-4" />
          </Button>
          {sttAvailable && (
            <Button
              size="icon"
              variant={recording ? "destructive" : "ghost"}
              className="size-10 shrink-0 rounded-full"
              onClick={toggleRecord}
              aria-label={recording ? "停止录音" : "语音输入"}
              title={recording ? `停止录音 · ${recSeconds}s` : "语音输入（语音转文字）"}
            >
              {recording ? <Square className="size-4" /> : <Mic className="size-4" />}
            </Button>
          )}
          {recording && (
            <span className="flex shrink-0 items-center gap-1.5 self-center text-xs text-red-400">
              <span className="inline-block size-2 animate-pulse rounded-full bg-red-500" />
              录音中 {recSeconds}s
            </span>
          )}
          <span className="select-none self-center pb-1 font-mono text-lg leading-none text-[var(--cyan)]">
            ›
          </span>
          <textarea
            ref={textRef}
            value={input}
            onChange={(e) => {
              setInput(e.target.value)
              autoSize(e.target)
            }}
            onKeyDown={(e) => {
              if (
                e.key === "Enter" &&
                !e.shiftKey &&
                !e.nativeEvent.isComposing &&
                e.keyCode !== 229
              ) {
                e.preventDefault()
                send()
              }
            }}
            onPaste={(e) => {
              // 支持直接粘贴截图 / 复制的文件
              const items = Array.from(e.clipboardData?.items || [])
              const picked = items
                .filter((i) => i.kind === "file")
                .map((i) => i.getAsFile())
                .filter((f): f is File => !!f)
              if (picked.length) {
                e.preventDefault()
                addFiles(picked)
              }
            }}
            placeholder="给 LUMU 下指令…（Enter 发送）"
            className="max-h-[136px] min-h-[40px] flex-1 resize-none bg-transparent px-1 py-2.5 font-mono text-sm text-[var(--text)] outline-none placeholder:text-[var(--dim)]"
            rows={1}
          />
          {streaming ? (
            <Button
              size="icon"
              variant="ghost"
              className="size-10 shrink-0 rounded-full text-[var(--danger)] hover:bg-[rgba(255,107,107,0.12)]"
              onClick={stop}
              aria-label="停止生成"
              title="停止生成"
            >
              <Square className="size-4" />
            </Button>
          ) : (
            <Button
              size="icon"
              className="size-10 shrink-0 rounded-full bg-primary text-primary-foreground hover:bg-primary/90"
              onClick={send}
              disabled={!input.trim() && attachments.length === 0}
              aria-label="发送"
            >
              <Send className="size-4" />
            </Button>
          )}
        </div>
      )}
    </div>
  )
}
