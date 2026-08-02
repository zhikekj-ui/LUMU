import * as React from "react"

// 文件元信息（与后端 /api/files/{id} 对应；id 为纯 UUID，不带扩展名）
export interface FileMeta {
  id: string
  name: string
  mime: string
  size?: number
}

// 对话中的文件块（conversation.tsx 持久化用，随对话一起存 localStorage，刷新不丢）
export interface FileBlock {
  type: "file"
  id: string
  file: FileMeta
}

// —— 文件卡片：辅助 + 全局灯箱/下载 ——
export function humanSize(n: number): string {
  n = n || 0
  if (n < 1024) return n + " B"
  if (n < 1024 * 1024) return (n / 1024).toFixed(1) + " KB"
  return (n / 1024 / 1024).toFixed(1) + " MB"
}
export function typeLabel(m: string): string {
  if (!m) return "文件"
  if (m.indexOf("image") === 0) return "图片"
  if (m.indexOf("video") === 0) return "视频"
  if (m.indexOf("audio") === 0) return "音频"
  if (m.indexOf("pdf") > -1) return "PDF"
  return "文件"
}
export function iconFor(m: string): string {
  if (!m) return "📎"
  if (m.indexOf("image") === 0) return "🖼"
  if (m.indexOf("video") === 0) return "🎬"
  if (m.indexOf("audio") === 0) return "🔊"
  if (m.indexOf("pdf") > -1) return "📄"
  return "📎"
}

// 全局灯箱（点击图片/视频放大），单例挂在 body，点空白/Esc 关闭
export function openLumuLightbox(url: string, mime: string, name: string) {
  let lb = document.getElementById("lumu-lightbox") as HTMLDivElement | null
  if (!lb) {
    lb = document.createElement("div")
    lb.id = "lumu-lightbox"
    lb.style.cssText =
      "position:fixed;inset:0;z-index:9999;display:none;align-items:center;justify-content:center;" +
      "background:rgba(3,6,12,.86);opacity:0;transition:opacity .18s ease;backdrop-filter:blur(4px);"
    document.body.appendChild(lb)
    lb.addEventListener("click", (e) => {
      const t = e.target as HTMLElement
      if (t === lb || t.dataset.lbClose === "1") closeLumuLightbox()
    })
    // 仅注册一次 Esc 关闭
    if (!document.getElementById("lumu-lightbox-kd")) {
      const kd = document.createElement("div")
      kd.id = "lumu-lightbox-kd"
      document.addEventListener("keydown", (e) => {
        if (e.key === "Escape") {
          const cur = document.getElementById("lumu-lightbox")
          if (cur && cur.style.display !== "none") closeLumuLightbox()
        }
      })
    }
  }
  lb.innerHTML = ""
  const stage = document.createElement("div")
  stage.style.cssText =
    "max-width:92vw;max-height:92vh;display:flex;align-items:center;justify-content:center;"
  let media: HTMLImageElement | HTMLVideoElement
  if (mime.indexOf("video") === 0) {
    media = document.createElement("video")
    media.src = url
    ;(media as HTMLVideoElement).controls = true
    ;(media as HTMLVideoElement).autoplay = true
    media.style.cssText =
      "max-width:92vw;max-height:92vh;border-radius:10px;box-shadow:0 20px 60px rgba(0,0,0,.5);"
  } else {
    media = document.createElement("img")
    media.src = url
    media.style.cssText =
      "max-width:92vw;max-height:92vh;border-radius:10px;box-shadow:0 20px 60px rgba(0,0,0,.5);"
  }
  media.addEventListener("contextmenu", (e) => {
    e.preventDefault()
    showLumuDownload(e, url, name)
  })
  stage.appendChild(media)
  lb.appendChild(stage)
  lb.style.display = "flex"
  requestAnimationFrame(() => {
    lb!.style.opacity = "1"
  })
}
export function closeLumuLightbox() {
  const lb = document.getElementById("lumu-lightbox")
  if (!lb) return
  lb.style.opacity = "0"
  setTimeout(() => {
    lb.style.display = "none"
    lb.innerHTML = ""
  }, 180)
}
export function showLumuDownload(e: MouseEvent, url: string, name: string) {
  const old = document.getElementById("lumu-dl-btn")
  if (old) old.remove()
  const btn = document.createElement("button")
  btn.id = "lumu-dl-btn"
  btn.textContent = "⤓ 下载"
  btn.style.cssText =
    "position:fixed;z-index:10000;padding:8px 14px;border-radius:8px;cursor:pointer;" +
    "border:1px solid rgba(127,220,255,.5);background:rgba(10,16,26,.94);color:#7fdcff;" +
    "font:13px/1 system-ui;box-shadow:0 6px 20px rgba(0,0,0,.4);"
  btn.style.left = e.clientX + 8 + "px"
  btn.style.top = e.clientY + 8 + "px"
  btn.addEventListener("click", (ev) => {
    ev.stopPropagation()
    const a = document.createElement("a")
    a.href = url
    a.download = name || ""
    a.rel = "noopener"
    document.body.appendChild(a)
    a.click()
    a.remove()
    btn.remove()
  })
  document.body.appendChild(btn)
  setTimeout(() => {
    if (btn.parentNode) btn.remove()
  }, 4000)
}

// 文件卡片组件：图片/视频/音频/文档，hover 轻微放大、点击灯箱、右键下载
export function FileCard({ block }: { block: FileBlock }) {
  const f = block.file
  const mime = f.mime || ""
  const url = "/api/files/" + f.id
  const isImage = mime.indexOf("image") === 0
  const isVideo = mime.indexOf("video") === 0
  const isAudio = mime.indexOf("audio") === 0
  const [failed, setFailed] = React.useState(false)
  return (
    <div className="lumu-file-msg overflow-hidden rounded-xl border border-white/[0.06] bg-sidebar/40">
      <div className="flex items-center gap-2 px-3 py-2 opacity-65 transition-opacity">
        <span className="text-[15px]">{iconFor(mime)}</span>
        <div className="min-w-0 flex-1">
          <div className="truncate text-[13px] text-cyan/90">{f.name}</div>
          <div className="text-[11px] text-muted-foreground">
            {(f.size && f.size > 0 ? humanSize(f.size) : "未知大小")} · {typeLabel(mime)}
          </div>
        </div>
      </div>
      <div
        className="lumu-file-wrap relative overflow-hidden"
        onClick={() => {
          if (isImage || isVideo) openLumuLightbox(url, mime, f.name)
        }}
        onContextMenu={(e) => {
          e.preventDefault()
          showLumuDownload(e.nativeEvent, url, f.name)
        }}
      >
        {isImage && (
          <img
            src={url}
            loading="lazy"
            draggable={false}
            className="block w-full max-h-[340px] cursor-zoom-in object-cover transition-transform duration-300"
            onMouseEnter={(e) => (e.currentTarget.style.transform = "scale(1.05)")}
            onMouseLeave={(e) => (e.currentTarget.style.transform = "scale(1)")}
            onError={() => setFailed(true)}
          />
        )}
        {isVideo && (
          <video
            src={url}
            preload="metadata"
            muted
            playsInline
            className="block w-full max-h-[340px] cursor-zoom-in object-cover transition-transform duration-300"
            onMouseEnter={(e) => (e.currentTarget.style.transform = "scale(1.05)")}
            onMouseLeave={(e) => (e.currentTarget.style.transform = "scale(1)")}
            onError={() => setFailed(true)}
          />
        )}
        {isAudio && (
          <audio
            controls
            preload="metadata"
            src={url}
            className="w-full"
            onContextMenu={(e) => e.preventDefault()}
            onError={() => setFailed(true)}
          />
        )}
        {!isImage && !isVideo && !isAudio && (
          <div className="px-4 py-4 text-center text-[13px] text-muted-foreground">
            📄 {f.name}
          </div>
        )}
        {failed && (
          <div className="absolute inset-0 flex items-center justify-center bg-background/80 text-[13px] text-muted-foreground">
            ⚠ 文件已失效或已清理
          </div>
        )}
      </div>
    </div>
  )
}

// —— 给 MarkdownBlock 用：把文本中的内部文件链接 [label](/api/files/fid) 拆成段 ——
// 这样 LUMU 以 markdown 文本形式推送的文件，也能渲染成真实 FileCard，而非普通 <a>。
const MIME_MAP: Record<string, string> = {
  mp3: "audio/mpeg", wav: "audio/wav", m4a: "audio/mp4", ogg: "audio/ogg", flac: "audio/flac",
  png: "image/png", jpg: "image/jpeg", jpeg: "image/jpeg", gif: "image/gif", webp: "image/webp",
  mp4: "video/mp4", webm: "video/webm", mov: "video/quicktime",
  pdf: "application/pdf", txt: "text/plain", md: "text/markdown", csv: "text/csv",
  doc: "application/msword", docx: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
  xls: "application/vnd.ms-excel", xlsx: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
  json: "application/json", zip: "application/zip",
}
function guessMimeFromName(name: string): string {
  const ext = (name.split(".").pop() || "").toLowerCase()
  return MIME_MAP[ext] || ""
}
const FILE_LINK = /\[([^\]]*)\]\(([^)\s]+)\)/g
const FID = /\/api\/files\/([A-Za-z0-9_\-]+)(?:\.[A-Za-z0-9]+)?(?:\?[^)]*)?$/i
const NAME = /([\w\u4e00-\u9fa5\-.]+\.(?:mp3|wav|m4a|ogg|flac|png|jpe?g|gif|webp|mp4|webm|mov|pdf|docx?|xlsx?|pptx?|txt|md|csv|json|zip))/i

export function splitFileLinks(
  src: string
): Array<{ kind: "md"; text: string } | { kind: "file"; file: FileMeta }> {
  const out: Array<{ kind: "md"; text: string } | { kind: "file"; file: FileMeta }> = []
  if (!src) return out
  let last = 0
  let m: RegExpExecArray | null
  FILE_LINK.lastIndex = 0
  while ((m = FILE_LINK.exec(src))) {
    const label = m[1]
    const url = m[2].trim()
    const fm = FID.exec(url)
    if (!fm) continue // 非内部文件链接，留给 markdown 正常渲染为 <a>
    const fid = fm[1]
    const nm = NAME.exec(label)
    const name = nm ? nm[1] : label.trim()
    const mime = guessMimeFromName(name)
    if (m.index > last) out.push({ kind: "md", text: src.slice(last, m.index) })
    out.push({ kind: "file", file: { id: fid, name, mime } })
    last = FILE_LINK.lastIndex
  }
  if (last < src.length) out.push({ kind: "md", text: src.slice(last) })
  return out
}
