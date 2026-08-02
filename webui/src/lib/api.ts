const BASE = '/api'

async function req(path: string, opts: RequestInit = {}) {
  const r = await fetch(BASE + path, {
    ...opts,
    headers: { 'Content-Type': 'application/json', ...(opts.headers || {}) }
  })
  if (!r.ok) throw new Error('HTTP ' + r.status)
  return r
}

export async function listSessions(space = 'work') {
  const r = await req(`/sessions?space=${space}`)
  return r.json()
}
export async function createSession(space = 'work') {
  const r = await req(`/sessions?space=${space}`, { method: 'POST' })
  return r.json()
}
export async function deleteSession(id: string) {
  await req(`/sessions/${id}`, { method: 'DELETE' })
}
export async function getSession(id: string) {
  const r = await req(`/sessions/${id}`)
  return r.json()
}
export async function health() {
  const r = await req(`/health`)
  return r.json()
}

export async function chatStream(
  body: any,
  signal: AbortSignal,
  onEvent: (e: any) => void
) {
  const r = await fetch(BASE + '/chat/stream', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
    signal
  })
  const reader = r.body!.getReader()
  const dec = new TextDecoder()
  let buf = ''
  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buf += dec.decode(value, { stream: true })
    let idx
    while ((idx = buf.indexOf('\n\n')) >= 0) {
      const chunk = buf.slice(0, idx)
      buf = buf.slice(idx + 2)
      chunk.split('\n').forEach((line) => {
        if (line.startsWith('data: ')) {
          try {
            onEvent(JSON.parse(line.slice(6)))
          } catch (e) {}
        }
      })
    }
  }
}
