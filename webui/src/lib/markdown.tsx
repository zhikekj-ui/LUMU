import { useEffect, useRef, useMemo } from 'react'
import hljs from 'highlight.js/lib/core'
import python from 'highlight.js/lib/languages/python'
import json from 'highlight.js/lib/languages/json'
import bash from 'highlight.js/lib/languages/bash'
import javascript from 'highlight.js/lib/languages/javascript'
import typescript from 'highlight.js/lib/languages/typescript'
import xml from 'highlight.js/lib/languages/xml'
import css from 'highlight.js/lib/languages/css'
import { sanitizeModelText, esc } from './sanitize'
import { FileCard, splitFileLinks } from '@/components/file-card'

hljs.registerLanguage('python', python)
hljs.registerLanguage('json', json)
hljs.registerLanguage('bash', bash)
hljs.registerLanguage('shell', bash)
hljs.registerLanguage('sh', bash)
hljs.registerLanguage('javascript', javascript)
hljs.registerLanguage('js', javascript)
hljs.registerLanguage('typescript', typescript)
hljs.registerLanguage('ts', typescript)
hljs.registerLanguage('html', xml)
hljs.registerLanguage('xml', xml)
hljs.registerLanguage('css', css)

export function renderMarkdown(src: string, sanitize: boolean): string {
  if (src == null) return ''
  const parts = String(src).split(/```/)
  let html = ''
  parts.forEach((part, i) => {
    if (i % 2 === 1) {
      const nl = part.indexOf('\n')
      const lang = nl > 0 ? part.slice(0, nl).trim() : ''
      const code = nl > 0 ? part.slice(nl + 1) : part
      html +=
        '<div class="codewrap"><div class="codehead"><span class="lang">' +
        (lang || 'code') +
        '</span><button class="copy" type="button">复制</button></div><pre><code class="language-' +
        (lang || '') +
        '">' +
        esc(code.replace(/\n$/, '')) +
        '</code></pre></div>'
    } else {
      const seg = sanitize ? sanitizeModelText(part) : part
      seg.split(/\n{2,}/).forEach((p) => {
        if (!p.trim()) return
        html += '<p>' + p.replace(/\n/g, '<br>') + '</p>'
      })
    }
  })
  return html
}

export function MarkdownBlock({ content, sanitize }: { content: string; sanitize: boolean }) {
  const ref = useRef<HTMLDivElement>(null)
  // 把文本里的内部文件链接 [label](/api/files/fid) 拆出来，渲染成真实 FileCard
  const segs = useMemo(() => splitFileLinks(content), [content])
  useEffect(() => {
    const el = ref.current
    if (!el) return
    el.querySelectorAll('.codewrap code').forEach((c) => {
      const ce = c as HTMLElement
      try {
        if (!ce.dataset.hl) {
          hljs.highlightElement(ce)
          ce.dataset.hl = '1'
        }
      } catch (e) {}
    })
    el.querySelectorAll('.copy').forEach((btn) => {
      btn.addEventListener('click', () => {
        const code = (btn.closest('.codewrap')?.querySelector('code')?.textContent) || ''
        navigator.clipboard.writeText(code).then(() => {
          btn.textContent = '已复制'
          setTimeout(() => (btn.textContent = '复制'), 1200)
        })
      })
    })
  }, [content, segs])
  return (
    <div className="typeset typeset-chat" ref={ref}>
      {segs.map((seg, i) =>
        seg.kind === "file" ? (
          <FileCard key={"f" + i} block={{ type: "file", id: seg.file.id, file: seg.file }} />
        ) : (
          <div key={"m" + i} dangerouslySetInnerHTML={{ __html: renderMarkdown(seg.text, sanitize) }} />
        )
      )}
    </div>
  )
}
