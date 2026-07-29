// 数据接入层 —— 真实对接 LUMU 后端（前端由服务器 api/static 同域提供，无需跨域/鉴权）
// 后端接口：GET /api/health、GET /api/sessions、POST /api/sessions、
//           POST /api/chat、GET /api/memory/unified、GET /api/skills
// 任何请求失败都平滑降级到示例数据，保证界面不空白、可演示。

const BASE = ''

// ---------- 示例降级数据（仅在网络/后端异常时使用） ----------
const SAMPLE = {
  modelStatus: { name: 'deepseek-v4-flash', online: false },
  sessions: [
    { id: 's1', title: '把昨天的数据整理成表', mem: 3, active: true },
    { id: 's2', title: '帮我写一份产品周报', mem: 0 },
    { id: 's3', title: '查一下竞品的公开资料', mem: 1 }
  ],
  stats: { memory: 44, skill: 0, knowledge: 12 },
  todayMemories: [
    { type: '偏好', cls: 'k', text: '表格默认「地区在前、月份在后」', meta: '刚刚 · 来自对话' },
    { type: '待办', cls: '', text: '下周要交季度复盘', meta: '刚刚 · 来自对话' },
    { type: '知识', cls: 'k', text: '销售数据在 ~/data，约 300 行', meta: '本次 · 来自文件' },
    { type: '偏好', cls: 'k', text: '汇报先看结论、再展开细节', meta: '今天 · 来自对话' },
    { type: '知识', cls: 'k', text: '你常用 Excel 做周报模板', meta: '今天 · 来自文件' }
  ]
}

async function getJSON(url) {
  const r = await fetch(BASE + url, { headers: { Accept: 'application/json' } })
  if (!r.ok) throw new Error(url + ' -> ' + r.status)
  return r.json()
}

// 模型/在线状态（同时带回真实的能力域与计数）
export async function fetchModelStatus() {
  try {
    const d = await getJSON('/api/health')
    return {
      name: d.model || 'unknown',
      online: d.status === 'ok',
      provider: d.provider,
      tools: d.tools ?? 0,
      toolsets: Array.isArray(d.toolsets) ? d.toolsets : [],
      skills: d.skills ?? 0,
      memories: d.memories ?? 0
    }
  } catch (e) {
    return { ...SAMPLE.modelStatus, online: false }
  }
}

// 会话列表（可按空间过滤）
export async function fetchSessions(space) {
  try {
    const url = '/api/sessions' + (space ? ('?space=' + encodeURIComponent(space)) : '')
    const d = await getJSON(url)
    if (!Array.isArray(d) || d.length === 0) return []
    return d.map(s => ({ id: s.id, title: s.preview || '新对话' }))
  } catch (e) {
    return SAMPLE.sessions
  }
}

// 新建会话，返回 id（按空间创建）
export async function createSession(space) {
  try {
    const url = BASE + '/api/sessions' + (space ? ('?space=' + encodeURIComponent(space)) : '')
    const r = await fetch(url, { method: 'POST' })
    const j = await r.json()
    return j.id
  } catch (e) {
    return 'local-' + Date.now()
  }
}

// 拉取某个会话的历史消息（{role, content}）
export async function fetchSessionHistory(id) {
  try {
    const d = await getJSON('/api/sessions/' + id)
    const msgs = (d.messages || [])
      .filter(m => m.role === 'user' || m.role === 'assistant')
      .map(m => ({ role: m.role === 'assistant' ? 'bot' : 'user', text: m.content || '' }))
    return msgs
  } catch (e) {
    return []
  }
}

// 删除会话，返回 { ok, error }
export async function deleteSession(id) {
  try {
    const r = await fetch(BASE + '/api/sessions/' + id, { method: 'DELETE' })
    if (!r.ok) {
      let detail = ''
      try { const j = await r.json(); if (j && j.detail) detail = '：' + j.detail } catch (e) {}
      throw new Error('后端返回 ' + r.status + detail)
    }
    const j = await r.json()
    return { ok: j.ok === true }
  } catch (e) {
    // 网络层错误（跨域/断网/旧包缓存连不到后端）会落到这里
    const msg = e && e.message ? e.message : '未知网络错误'
    return { ok: false, error: msg }
  }
}

// 发消息，返回 {sessionId, text, tools:[{name, ok}]}
// files: 可选，通用文件附件数组 [{name, mime, data}]（data 为 data URL 或 base64）
export async function sendChat(message, sessionId, space, files) {
  const body = { message, session_id: sessionId || null, space: space || 'work' }
  if (files && files.length) body.files = files
  const r = await fetch(BASE + '/api/chat', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body)
  })
  if (!r.ok) throw new Error('聊天请求失败 (' + r.status + ')')
  const d = await r.json()
  const tools = Array.isArray(d.tool_calls)
    ? d.tool_calls.map(t => ({ name: t.tool || t.name || '工具', ok: true }))
    : []
  return { sessionId: d.session_id, text: d.content || '', tools }
}

// 流式发送：解析 SSE（data: {...}）逐事件回调
// cb: { onSession, onToken, onToolStart, onToolResult, onDone, onError }
// files: 可选，通用文件附件数组 [{name, mime, data}]
export async function streamChat(message, sessionId, space, files, cb) {
  const body = { message, session_id: sessionId || null, space: space || 'work' }
  if (files && files.length) body.files = files
  const r = await fetch(BASE + '/api/chat/stream', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body)
  })
  if (!r.ok) throw new Error('流式请求失败 (' + r.status + ')')
  const reader = r.body.getReader()
  const decoder = new TextDecoder()
  let buf = ''
  const dispatch = (ev) => {
    switch (ev.type) {
      case 'session': cb.onSession && cb.onSession(ev.session_id); break
      case 'token': cb.onToken && cb.onToken(ev.content || ''); break
      case 'tool_start': cb.onToolStart && cb.onToolStart(ev.tool); break
      case 'tool_result': cb.onToolResult && cb.onToolResult(ev.tool); break
      case 'done': cb.onDone && cb.onDone(); break
      case 'vision_warning': cb.onVisionWarning && cb.onVisionWarning(ev.content || ''); break
      case 'plan': cb.onPlan && cb.onPlan(ev.steps || []); break
      case 'progress': cb.onProgress && cb.onProgress(ev); break
      case 'error': cb.onError && cb.onError(ev.content || '未知错误'); break
      default: break
    }
  }
  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buf += decoder.decode(value, { stream: true })
    let idx
    while ((idx = buf.indexOf('\n\n')) !== -1) {
      const chunk = buf.slice(0, idx)
      buf = buf.slice(idx + 2)
      const line = chunk.split('\n').find(l => l.startsWith('data: '))
      if (!line) continue
      const payload = line.slice(6).trim()
      if (!payload) continue
      try { dispatch(JSON.parse(payload)) } catch (_) { /* 忽略非 JSON 行 */ }
    }
  }
  if (buf.trim()) {
    const line = buf.split('\n').find(l => l.startsWith('data: '))
    if (line) { try { dispatch(JSON.parse(line.slice(6).trim())) } catch (_) {} }
  }
}

function mapCategory(cat) {
  const m = {
    preference: '偏好', pref: '偏好',
    consolidated: '已整理',
    interaction: '互动',
    general: '记录',
    project: '项目',
    knowledge: '知识', know: '知识',
    todo: '待办', task: '待办',
    about_you: '关于你', you: '关于你',
    skill: '技能'
  }
  return m[cat] || (cat || '记忆')
}
function mapKind(cat) {
  const c = cat || ''
  if (/pref|consol/.test(c)) return 'pref'
  if (/you|about|project|interaction/.test(c)) return 'you'
  if (/skill/.test(c)) return 'skill'
  return 'know'
}
// 友好时间：以数据里最新日期为“今天”基准，避免服务器/浏览器时区错位
function fmtMeta(created_at, refDate) {
  const s = created_at || ''
  const date = s.slice(0, 10)
  const time = s.slice(11, 16)
  if (!date) return '来自记忆'
  if (date === refDate) return '今天 ' + (time || '')
  return date.slice(5) + (time ? ' ' + time : '') // MM-DD HH:MM
}

// 记忆总览：统计 + 今日/近期记忆 + 生命体节点（按空间过滤）
export async function fetchMemory(space) {
  try {
    const url = '/api/memory/unified' + (space ? ('?space=' + encodeURIComponent(space)) : '')
    const d = await getJSON(url)
    const mems = Array.isArray(d.memories) ? d.memories : []
    const total = d.total ?? mems.length
    // 以数据里最新日期作为“今天”基准（created_at 无时区，避免 UTC/本地错位）
    const dates = mems.map(m => (m.created_at || '').slice(0, 10)).filter(Boolean).sort()
    const refDate = dates[dates.length - 1] || new Date().toISOString().slice(0, 10)
    // 按内容去重，避免“同一句话被存了 N 份副本”刷屏
    const dedup = (arr) => {
      const seen = new Set()
      return arr.filter(m => {
        const c = (m.content || '').trim()
        if (seen.has(c)) return false
        seen.add(c)
        return true
      })
    }
    let picked = dedup(mems.filter(m => (m.created_at || '').slice(0, 10) === refDate))
    if (picked.length === 0) picked = dedup(mems)
    picked = picked.slice(0, 12)
    const todayMemories = picked.map(m => {
      const type = mapCategory(m.category)
      return {
        type,
        cls: type === '知识' ? 'k' : '',
        text: (m.content || '').slice(0, 60),
        meta: fmtMeta(m.created_at, refDate)
      }
    })
    // 知识类：knowledge / general / project / consolidated 都算“沉淀下来的认知”
    const knowledge = mems.filter(m => /know|general|project|consol/.test(m.category || '')).length
    return {
      stats: { memory: total, skill: 0, knowledge },
      todayMemories: todayMemories.length ? todayMemories : SAMPLE.todayMemories
    }
  } catch (e) {
    return { stats: SAMPLE.stats, todayMemories: SAMPLE.todayMemories }
  }
}

export async function fetchSkillsCount() {
  try {
    const d = await getJSON('/api/skills')
    return Array.isArray(d) ? d.length : 0
  } catch (e) {
    return 0
  }
}

// ---------- 真实能力域（工具集） ----------
// 后端 /api/health 返回真实 toolset 列表，这里做中文名 + 描述映射
const TOOLSET_LABELS = {
  tts_stt: '语音 (TTS/STT)', observability: '可观测性', provider: '模型提供商',
  search: '联网搜索', browser: '浏览器', orchestration: '多智能体编排',
  system: '系统状态', checkpoint: '检查点', vision: '视觉/图像',
  cron: '定时任务', sandbox: '沙箱', adaptive: '自适应', reasoning: '推理',
  security: '安全', knowledge: '知识库', file: '文件', session: '会话',
  api: 'API 调用', terminal: '终端命令', memory: '记忆',
  hitl: '人工确认', rag: '检索增强 (RAG)', skills: '技能',
  visualization: '可视化', events: '事件', learning: '学习'
}
const TOOLSET_DESC = {
  tts_stt: '语音合成与识别', observability: '运行轨迹与监控', provider: '切换/路由大模型',
  search: '联网检索资料', browser: '打开网页、截图、提取', orchestration: '派子任务并行干',
  system: '读取系统状态', checkpoint: '断点续跑', vision: '看图理解',
  cron: '定时自动跑', sandbox: '隔离执行代码', adaptive: '按场景调整策略', reasoning: '多步推理',
  security: '敏感操作防护', knowledge: '知识库问答', file: '读写与管理文件', session: '多会话管理',
  api: '调用外部接口', terminal: '跑本地命令', memory: '记住并整理你',
  hitl: '危险操作先问你', rag: '私有资料检索增强', skills: '安装扩展技能',
  visualization: '记忆可视化', events: '事件总线', learning: '从对话中学习'
}

// 真实能力域：总数 + 24 个工具域
export async function fetchToolsets() {
  try {
    const d = await getJSON('/api/health')
    const names = Array.isArray(d.toolsets) ? d.toolsets : []
    return {
      total: d.tools ?? 0,
      sets: names.map(name => ({
        name,
        label: TOOLSET_LABELS[name] || name,
        desc: TOOLSET_DESC[name] || ''
      }))
    }
  } catch (e) {
    return { total: 0, sets: [] }
  }
}

// 友好时间：以数据里最新日期为“今天”基准（时间串无时区）
function fmtTs(ts, refDate) {
  const s = ts || ''
  const date = s.slice(0, 10)
  const time = s.slice(11, 16)
  if (!date) return ''
  if (refDate && date === refDate) return '今天 ' + (time || '')
  return date.slice(5) + (time ? ' ' + time : '')
}

// 真实成长时间线：来自 /api/timeline 的真实对话事件
export async function fetchTimeline() {
  try {
    const d = await getJSON('/api/timeline?limit=80')
    const evs = Array.isArray(d.events) ? d.events : []
    if (evs.length === 0) return []
    const dates = evs.map(e => (e.ts || '').slice(0, 10)).filter(Boolean).sort()
    const refDate = dates[dates.length - 1] || ''
    const KIND = { user: '你', assistant: 'LUMU', tool: '工具' }
    return evs.slice(0, 14).map(e => ({
      kind: e.kind,
      who: KIND[e.kind] || e.kind,
      text: (e.text || '').slice(0, 60),
      meta: fmtTs(e.ts, refDate)
    }))
  } catch (e) {
    return []
  }
}

// 用户长期偏好画像：复用 /api/memory/unified 全部记忆，过滤偏好/关于你类
export async function fetchProfile(space) {
  try {
    const url = '/api/memory/unified' + (space ? ('?space=' + encodeURIComponent(space)) : '')
    const d = await getJSON(url)
    const mems = Array.isArray(d.memories) ? d.memories : []
    const prefs = mems.filter(m => /pref|about_you|you|consol/.test(m.category || '')).slice(0, 12)
    return prefs.map(m => ({ content: (m.content || '').slice(0, 50), category: m.category || '' }))
  } catch (e) {
    return []
  }
}

// ---------- 配置接口（设置面板） ----------
export async function fetchConfigParams() {
  try { return await getJSON('/api/config/params') } catch (e) { return { temperature: 0.7, top_p: 0.9 } }
}
export async function saveConfigParams(temperature, top_p) {
  try {
    const r = await fetch(BASE + '/api/config/params', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ temperature, top_p }) })
    return r.ok
  } catch (e) { return false }
}
export async function fetchSystemPrompt() {
  try { const d = await getJSON('/api/config/system-prompt'); return d.system_prompt || '' } catch (e) { return '' }
}
export async function saveSystemPrompt(text) {
  try {
    const r = await fetch(BASE + '/api/config/system-prompt', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ system_prompt: text }) })
    return r.ok
  } catch (e) { return false }
}
export async function fetchProviders() {
  try { const d = await getJSON('/api/config/providers'); return d.providers || [] } catch (e) { return [] }
}
export async function saveProviderKey(name, key) {
  try {
    const r = await fetch(BASE + '/api/config/provider/' + encodeURIComponent(name) + '/key', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ api_key: key }) })
    return r.ok
  } catch (e) { return false }
}
export async function saveProviderBaseUrl(name, baseUrl) {
  try {
    const r = await fetch(BASE + '/api/config/provider/' + encodeURIComponent(name) + '/base-url', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ base_url: baseUrl || '' }) })
    return r.ok
  } catch (e) { return false }
}
export async function detectProviderModels(name) {
  // 用已配置密钥调提供商接口，自动识别该令牌下真实可用的模型
  try { return await getJSON('/api/config/providers/' + encodeURIComponent(name) + '/models') } catch (e) { return { detected: false, models: [], enabled_models: [] } }
}
export async function saveEnabledModels(name, models) {
  try {
    const r = await fetch(BASE + '/api/config/providers/' + encodeURIComponent(name) + '/enabled-models', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ models }) })
    return r.ok
  } catch (e) { return false }
}
export async function switchModel(provider, model) {
  try {
    const r = await fetch(BASE + '/api/config/model', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ provider, model }) })
    return r.ok
  } catch (e) { return false }
}
export async function fetchTts() {
  try { return await getJSON('/api/config/tts') } catch (e) { return {} }
}
export async function saveTts(provider, mimo_api_key) {
  try {
    const r = await fetch(BASE + '/api/config/tts', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ provider, mimo_api_key }) })
    return r.ok
  } catch (e) { return false }
}
export async function fetchStt() {
  try { return await getJSON('/api/config/stt') } catch (e) { return {} }
}
export async function fetchEmbedding() {
  try { return await getJSON('/api/config/embedding') } catch (e) { return {} }
}
export async function saveEmbedding(base_url, model, api_key) {
  try {
    const r = await fetch(BASE + '/api/config/embedding', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ base_url, model, api_key }) })
    return r.ok
  } catch (e) { return false }
}

// ---------- 知识库管理 ----------
export async function fetchKbDocuments(space) {
  try {
    const url = '/api/kb/documents' + (space ? ('?space=' + encodeURIComponent(space)) : '')
    const d = await getJSON(url)
    return { documents: d.documents || [], stats: d.stats || {} }
  } catch (e) { return { documents: [], stats: {} } }
}
export async function uploadKbDocument(file, space) {
  try {
    const fd = new FormData()
    fd.append('file', file)
    if (space) fd.append('space', space)
    const r = await fetch(BASE + '/api/kb/documents' + (space ? ('?space=' + encodeURIComponent(space)) : ''), { method: 'POST', body: fd })
    if (!r.ok) {
      let detail = ''
      try { const j = await r.json(); if (j && j.detail) detail = j.detail } catch (e) {}
      return { status: 'error', message: detail || ('HTTP ' + r.status) }
    }
    return await r.json()  // {status, filename, chars, chunks, entries}
  } catch (e) { return { status: 'error', message: e.message || '网络错误' } }
}
export async function deleteKbDocument(id, space) {
  try {
    const r = await fetch(BASE + '/api/kb/documents/' + encodeURIComponent(id) + (space ? ('?space=' + encodeURIComponent(space)) : ''), { method: 'DELETE' })
    return r.ok
  } catch (e) { return false }
}

// ---------- 技能库 ----------
export async function fetchSkills(tag, space) {
  try {
    const params = []
    if (tag) params.push('tag=' + encodeURIComponent(tag))
    if (space) params.push('space=' + encodeURIComponent(space))
    const qs = params.length ? ('?' + params.join('&')) : ''
    const d = await getJSON('/api/skills' + qs)
    return Array.isArray(d) ? d : []
  } catch (e) { return [] }
}
export async function deleteSkill(name) {
  try {
    const r = await fetch(BASE + '/api/skills/' + encodeURIComponent(name), { method: 'DELETE' })
    return r.ok
  } catch (e) { return false }
}
// 赞 / 踩：记录用户对某条回复的认可或不认可，落到后端记忆系统（有助于智能体进化）
export async function sendFeedback({ sessionId, messageIndex, feedback, message, prompt, space }) {
  const r = await fetch(BASE + '/api/feedback', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      session_id: sessionId || '',
      message_index: messageIndex ?? -1,
      feedback: feedback || '',
      message: message || '',
      prompt: prompt || '',
      space: space || '',
    }),
  })
  if (!r.ok) throw new Error('feedback ' + r.status)
  return r.json()
}

// ---------- 技能市场 ----------
// 浏览上架的技能包（含是否已安装）
export async function fetchMarket() {
  try {
    const d = await getJSON('/api/market/skills')
    return Array.isArray(d) ? d : []
  } catch (e) { return [] }
}
// 一键安装技能包到用户技能库（热加载生效）
export async function installMarket(name) {
  try {
    const r = await fetch(BASE + '/api/market/install', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name })
    })
    if (!r.ok) throw new Error('HTTP ' + r.status)
    return await r.json() // {ok, installed|already}
  } catch (e) { return { ok: false, error: e.message } }
}
// 发布新技能包：按真实 SKILL.md 格式落盘到 packs/，立即可被浏览与安装
export async function publishMarket({ name, description, content, triggers }) {
  try {
    const r = await fetch(BASE + '/api/market/publish', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name, description, content, triggers })
    })
    if (!r.ok) throw new Error('HTTP ' + r.status)
    return await r.json() // {ok, published} 或 {ok:false, error}
  } catch (e) { return { ok: false, error: e.message } }
}
