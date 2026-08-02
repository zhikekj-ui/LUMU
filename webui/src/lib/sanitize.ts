export function sanitizeLive(s: string): string {
  if (!s) return ''
  s = s.replace(/[\u0000-\u0008\u000B\u000C\u000E-\u001F\u007F\u200B-\u200D\uFEFF\uFE0F]/g, '')
  s = s.replace(
    /[\u{1F000}-\u{1FAFF}\u{2600}-\u{27BF}\u{2B00}-\u{2BFF}\u{2190}-\u{21FF}\u{2300}-\u{23FF}\u{2460}-\u{24FF}\u{25A0}-\u{25FF}\u{2900}-\u{297F}\u{1F1E6}-\u{1F1FF}\u{1F900}-\u{1F9FF}\u{1FA70}-\u{1FAFF}]/gu,
    ''
  )
  return s
}

export function sanitizeModelText(s: string): string {
  if (!s) return ''
  s = sanitizeLive(s)
  s = s.replace(/\*\*(.+?)\*\*/g, '$1')
  s = s.replace(/\*(.+?)\*/g, '$1')
  s = s.replace(/__(.+?)__/g, '$1')
  s = s.replace(/_(.+?)_/g, '$1')
  s = s.replace(/(^|[\s(])[*_]+([\s).,!?;:，。！？；：]|$)/g, '$1$2')
  return s
}

export function esc(s: string): string {
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
}

export function fmtTime(ts: number): string {
  const d = new Date(ts)
  return d.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
}
