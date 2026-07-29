import React, { useState, useEffect, useRef } from 'react'
import {
  SettingOutlined, FolderOutlined, FolderOpenOutlined, GlobalOutlined,
  BulbOutlined, ToolOutlined, DatabaseOutlined, UserOutlined,
  BookOutlined, PlusOutlined, SendOutlined, CheckOutlined, DeleteOutlined,
  PaperClipOutlined, AudioOutlined, CloseOutlined, CopyOutlined, ReloadOutlined,
  LikeOutlined, DislikeOutlined
} from '@ant-design/icons'
import { Image, message, Tooltip, Steps, Modal, Input, Button, Tag, Empty, Spin } from 'antd'
import MemoryLifeform from './components/MemoryLifeform.jsx'
import SettingsDrawer from './components/SettingsDrawer.jsx'
import KbUploadModal from './components/KbUploadModal.jsx'
import * as api from './api.js'

const ICONS = {
  SettingOutlined, FolderOutlined, FolderOpenOutlined, GlobalOutlined,
  BulbOutlined, ToolOutlined, DatabaseOutlined, UserOutlined,
  BookOutlined, PlusOutlined, SendOutlined, CheckOutlined
}
function Ic({ name, ...rest }) {
  const C = ICONS[name]
  return C ? <C {...rest} /> : null
}

// 首次上手引导：示例开场板块已按用户要求移除（保持引导精简，不预置开场话术）

// ---------- 本地持久化（刷新不丢页面/会话/进行中内容） ----------
function safeGet(k) { try { return localStorage.getItem(k) } catch (_) { return null } }

// ---------- 模型回复「重点差异化」轻量 Markdown 渲染 ----------
function inlineMd(s) {
  const parts = s.split(/(\*\*[^*]+\*\*|`[^`]+`)/g)
  return parts.map((p, i) => {
    if (/^\*\*[^*]+\*\*$/.test(p)) return <strong key={i} className="lm-md-strong">{p.slice(2, -2)}</strong>
    if (/^`[^`]+`$/.test(p)) return <code key={i} className="lm-md-code">{p.slice(1, -1)}</code>
    return p
  })
}
function renderRich(text) {
  if (!text) return null
  const lines = text.split('\n')
  const out = []
  let inCode = false, codeBuf = [], listBuf = []
  const flushList = () => {
    if (listBuf.length) {
      out.push(<ul key={'ul' + out.length} className="lm-md-ul">{listBuf.map((t, i) => <li key={i}>{inlineMd(t)}</li>)}</ul>)
      listBuf = []
    }
  }
  for (const raw of lines) {
    if (raw.trim().startsWith('```')) {
      if (inCode) { out.push(<pre key={'pre' + out.length} className="lm-md-pre">{codeBuf.join('\n')}</pre>); codeBuf = []; inCode = false }
      else { flushList(); inCode = true }
      continue
    }
    if (inCode) { codeBuf.push(raw); continue }
    if (/^\s*[-*]\s+/.test(raw)) { listBuf.push(raw.replace(/^\s*[-*]\s+/, '')); continue }
    flushList()
    const h = raw.match(/^(#{1,4})\s+(.*)$/)
    if (h) { out.push(<div key={'h' + out.length} className={'lm-md-h h' + h[1].length}>{inlineMd(h[2])}</div>); continue }
    if (/^>\s+/.test(raw)) { out.push(<blockquote key={'q' + out.length} className="lm-md-quote">{inlineMd(raw.replace(/^>\s+/, ''))}</blockquote>); continue }
    if (raw.trim() === '') { out.push(<br key={'br' + out.length} />); continue }
    out.push(<p key={'p' + out.length} className="lm-md-p">{inlineMd(raw)}</p>)
  }
  flushList()
  if (inCode) out.push(<pre key={'pre' + out.length} className="lm-md-pre">{codeBuf.join('\n')}</pre>)
  return out
}

// ---------- 技能市场视图：浏览 / 安装 / 发布 ----------
function MarketView() {
  const [list, setList] = useState([])
  const [loading, setLoading] = useState(false)
  const [installing, setInstalling] = useState(null)
  const [publishOpen, setPublishOpen] = useState(false)
  const [form, setForm] = useState({ name: '', description: '', triggers: '', content: '' })
  const [publishing, setPublishing] = useState(false)

  async function load() {
    setLoading(true)
    const d = await api.fetchMarket()
    setList(d)
    setLoading(false)
  }
  useEffect(() => { load() }, [])

  async function doInstall(s) {
    setInstalling(s.name)
    const r = await api.installMarket(s.name)
    setInstalling(null)
    if (r && r.ok) {
      message.success(r.already ? `「${s.name}」此前已安装` : `已安装「${s.name}」，对话中即可热加载生效`)
      load()
    } else {
      message.error('安装失败：' + ((r && r.error) || '未知错误'))
    }
  }

  async function doPublish() {
    if (!form.name.trim() || !form.content.trim()) { message.warning('请填写技能名与正文'); return }
    setPublishing(true)
    const r = await api.publishMarket(form)
    setPublishing(false)
    if (r && r.ok) {
      message.success(`已发布「${r.published}」到技能市场`)
      setPublishOpen(false)
      setForm({ name: '', description: '', triggers: '', content: '' })
      load()
    } else {
      message.error('发布失败：' + ((r && r.error) || '未知错误'))
    }
  }

  return (
    <div className="lm-capwrap">
      <div className="lm-panel" style={{ padding: '14px 18px', marginBottom: 18, display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 16, flexWrap: 'wrap' }}>
        <div>
          <h3 style={{ fontSize: 16 }}>技能市场</h3>
          <div className="desc">一键安装内置 / 社区技能包，安装后随对话热加载生效；你也可以把自己的经验沉淀成技能包发布出来，被模型在对话中调用。</div>
        </div>
        <Button type="primary" icon={<PlusOutlined />} onClick={() => setPublishOpen(true)}>发布技能</Button>
      </div>
      <Spin spinning={loading}>
        {list.length === 0 ? (
          <Empty description="技能市场暂无上架技能" style={{ marginTop: 60 }} />
        ) : (
          <div className="lm-market-grid">
            {list.map(s => (
              <div className="lm-panel lm-cap-card lm-market-card" key={s.name}>
                <div className="lm-market-head">
                  <span className="lm-market-name">{s.name}</span>
                  {s.installed ? <Tag color="green">已安装</Tag> : <Tag>未安装</Tag>}
                </div>
                <div className="lm-market-desc">{s.description || '（暂无描述）'}</div>
                <div className="lm-market-foot">
                  {s.installed ? (
                    <Button size="small" disabled>已安装</Button>
                  ) : (
                    <Button type="primary" size="small" loading={installing === s.name} icon={<CheckOutlined />} onClick={() => doInstall(s)}>安装</Button>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}
      </Spin>
      <Modal
        title="发布技能包"
        open={publishOpen}
        onCancel={() => setPublishOpen(false)}
        onOk={doPublish}
        confirmLoading={publishing}
        okText="发布"
        width={580}
      >
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12, marginTop: 8 }}>
          <div>
            <div className="lm-field-label">技能名（字母 / 数字 / - / _）</div>
            <Input value={form.name} onChange={e => setForm(f => ({ ...f, name: e.target.value }))} placeholder="例如 my-data-tool" maxLength={40} />
          </div>
          <div>
            <div className="lm-field-label">一句话描述</div>
            <Input value={form.description} onChange={e => setForm(f => ({ ...f, description: e.target.value }))} placeholder="这个技能包能帮 LUMU 做什么" maxLength={80} />
          </div>
          <div>
            <div className="lm-field-label">触发词（逗号分隔，可选）</div>
            <Input value={form.triggers} onChange={e => setForm(f => ({ ...f, triggers: e.target.value }))} placeholder="例如 重启,部署,日志" />
          </div>
          <div>
            <div className="lm-field-label">技能正文（Markdown，将作为指令注入模型）</div>
            <Input.TextArea rows={8} value={form.content} onChange={e => setForm(f => ({ ...f, content: e.target.value }))} placeholder={'# 技能正文\n1. 第一步……\n2. 第二步……'} />
          </div>
        </div>
      </Modal>
    </div>
  )
}

function App() {
  const [view, setView] = useState(() => safeGet('lumu_view') || 'work') // work | cap
  const [space, setSpace] = useState(() => safeGet('lumu_space') || 'work') // 空间隔离：work | personal
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [messages, setMessages] = useState(() => {
    const sid = safeGet('lumu_session')
    if (sid) { const c = safeGet('lumu_conv_' + sid); if (c) { try { return JSON.parse(c).map(m => ({ ...m, streaming: false })) } catch (_) {} } }
    return []
  })
  const [draft, setDraft] = useState('')
  const [thinking, setThinking] = useState(false)
  const [streaming, setStreaming] = useState(false) // 是否正在流式输出
  const [modelStatus, setModelStatus] = useState({ name: 'LUMU', online: false })
  const [sessions, setSessions] = useState([])
  const [sessionId, setSessionId] = useState(() => safeGet('lumu_session') || null)
  const [deletingId, setDeletingId] = useState(null)
  const [chatTitle, setChatTitle] = useState('与 LUMU 对话')
  const [stats, setStats] = useState({ memory: 0, skill: 0, knowledge: 0 })
  const [todayMemories, setTodayMemories] = useState([])
  const [memPage, setMemPage] = useState(0)
  const [timelineData, setTimelineData] = useState([])
  const [toolsets, setToolsets] = useState({ total: 0, sets: [] })
  const [skills, setSkills] = useState([])
  const [skillsCount, setSkillsCount] = useState(0)
  const [kbDocs, setKbDocs] = useState([])
  const [kbStats, setKbStats] = useState({})
  const [kbUploading, setKbUploading] = useState(false)
  const [kbModalOpen, setKbModalOpen] = useState(false)
  const [kbFile, setKbFile] = useState(null)
  const [modelMenuOpen, setModelMenuOpen] = useState(false)
  const [providersList, setProvidersList] = useState([])
  const [switching, setSwitching] = useState(false)
  // 文件附件 / 语音输入
  const [pendingFiles, setPendingFiles] = useState([]) // [{uid, name, mime, data(base64), isImage}]
  const [recording, setRecording] = useState(false)
  const [speechSupported, setSpeechSupported] = useState(true)
  const memRef = useRef(null)
  const fileRef = useRef(null)
  const recognitionRef = useRef(null)
  const attachRef = useRef(null) // 通用文件上传：隐藏 file input，由工具栏图标按钮触发
  const baseTextRef = useRef('') // 语音开始前输入框已有文字，识别结果在其后追加（不覆盖）
  const firstSpace = useRef(true)
  const sendRef = useRef(null)
  const transcriptRef = useRef('')
  const msgsRef = useRef(null)
  const [atBottom, setAtBottom] = useState(true)
  // 长任务进度可视化：plan=步骤清单，planRound=当前进行到第几步（>step数表示全部完成）
  const [planSteps, setPlanSteps] = useState([])
  const [planRound, setPlanRound] = useState(0)
  const [profilePrefs, setProfilePrefs] = useState([])

  function refreshModelStatus() {
    api.fetchModelStatus().then(d => {
      setModelStatus(d)
      setSkillsCount(d.skills || 0)
    })
  }

  // 初始化：拉取与空间无关的全局数据
  useEffect(() => {
    refreshModelStatus()
    api.fetchProviders().then(setProvidersList) // 用于判断当前模型是否支持看图
    api.fetchToolsets().then(setToolsets)
    api.fetchTimeline().then(setTimelineData)
  }, [])

  // 持久化：刷新后停留在原页面/会话，且保留进行中的内容
  useEffect(() => { try { localStorage.setItem('lumu_view', view) } catch (_) {} }, [view])
  useEffect(() => { try { localStorage.setItem('lumu_space', space) } catch (_) {} }, [space])
  useEffect(() => {
    try { if (sessionId) localStorage.setItem('lumu_session', sessionId); else localStorage.removeItem('lumu_session') } catch (_) {}
  }, [sessionId])
  useEffect(() => {
    try { if (sessionId && messages.length) localStorage.setItem('lumu_conv_' + sessionId, JSON.stringify(messages)) } catch (_) {}
  }, [messages, sessionId])
  // 自动跟随：只有用户停在底部（atBottom）时才贴底；用户上滑看历史时视角固定不动
  useEffect(() => {
    if (atBottom) scrollToBottom()
  }, [messages, atBottom])
  // 挂载时：若恢复了会话但没有缓存消息，从后端拉历史
  useEffect(() => {
    if (sessionId && messages.length === 0) openSession({ id: sessionId, title: chatTitle })
    // eslint-disable-next-line
  }, [])

  // 顶栏模型选择：每次打开都拉最新列表（勾选启用变化即时生效）
  async function toggleModelMenu() {
    if (!modelMenuOpen) {
      const ps = await api.fetchProviders()
      setProvidersList(ps)
    }
    setModelMenuOpen(o => !o)
  }
  async function pickModel(providerName, modelName) {
    if (switching) return
    setSwitching(true)
    const ok = await api.switchModel(providerName, modelName)
    setSwitching(false)
    if (ok) {
      setModelMenuOpen(false)
      refreshModelStatus()
    } else {
      window.alert('切换失败：该提供商可能未配置 API Key，请到设置里先保存密钥')
    }
  }

  // 空间切换：只拉该空间的会话列表、记忆、技能与知识库（不自动建新会话）
  useEffect(() => {
    if (firstSpace.current) {
      // 首次挂载：保留从 localStorage 恢复的会话/消息，不清空
      firstSpace.current = false
    } else {
      setSessionId(null) // 用户主动切换空间才清空，回到空开场
      setMessages([])
      setChatTitle('与 LUMU 对话')
    }
    api.fetchSessions(space).then(setSessions)
    api.fetchMemory(space).then(d => {
      setStats(s => ({ ...s, memory: d.stats.memory, knowledge: d.stats.knowledge }))
      setTodayMemories(d.todayMemories)
    })
    loadSkills(space)
    loadKb(space)
    loadProfile(space)
  }, [space])

  // 进入「记忆与能力」页时，加载当前空间的技能库与知识库
  useEffect(() => {
    if (view === 'cap') {
      loadKb(space)
      loadSkills(space)
    }
  }, [view, space])

  async function loadKb(space) {
    const d = await api.fetchKbDocuments(space)
    setKbDocs(d.documents || [])
    setKbStats(d.stats || {})
  }
  async function loadSkills(space) {
    const list = await api.fetchSkills(space)
    setSkills(list)
    setSkillsCount(list.length)
  }
  async function loadProfile(space) {
    const prefs = await api.fetchProfile(space)
    setProfilePrefs(prefs)
  }

  const onMemScroll = () => {
    const el = memRef.current
    if (el) setMemPage(Math.round(el.scrollLeft / el.clientWidth))
  }
  // 每页 3 条：最新在前，旧的被推到后续页
  const MEM_PAGE = 3
  const memPages = []
  for (let i = 0; i < todayMemories.length; i += MEM_PAGE) {
    memPages.push(todayMemories.slice(i, i + MEM_PAGE))
  }

  // 流式执行核心：复用给「发送」与「重新生成」
  // files: 通用文件附件数组（[{name, mime, data}]），可为 null
  async function streamInto(botId, text, sid, files) {
    setThinking(true)
    setStreaming(true)
    const finish = () => {
      setMessages(m => m.map(x => x.id === botId ? { ...x, streaming: false } : x))
      setThinking(false)
      setStreaming(false)
      api.fetchSessions(space).then(setSessions)
    }
    try {
      await api.streamChat(text, sid, space, files, {
        onSession: id => { if (id) setSessionId(id) },
        onToken: delta => setMessages(m => m.map(x => x.id === botId ? { ...x, text: x.text + delta } : x)),
        onToolStart: name => setMessages(m => m.map(x => x.id === botId ? { ...x, tools: [...x.tools, { name, ok: false, running: true }] } : x)),
        onToolResult: name => setMessages(m => m.map(x => x.id === botId ? { ...x, tools: x.tools.map(t => (t.name === name && t.running) ? { ...t, ok: true, running: false } : t) } : x)),
        onDone: () => setPlanRound(999),
        onVisionWarning: (content) => {
          if (!content) return
          message.warning('图片未能被识别：' + content)
          setMessages(m => [...m, { id: 'warn_' + Date.now(), role: 'system', text: content }])
        },
        onPlan: (steps) => { setPlanSteps(Array.isArray(steps) ? steps : []); setPlanRound(0) },
        onProgress: (ev) => { if (ev && ev.round) setPlanRound(ev.round) },
        onError: err => setMessages(m => m.map(x => x.id === botId ? { ...x, text: (x.text || '') + '\n\n[出错了] ' + err, streaming: false } : x))
      })
    } catch (e) {
      // 流式失败：退回非流式
      try {
        const reply = await api.sendChat(text, sid, space, files)
        if (reply.sessionId) setSessionId(reply.sessionId)
        setMessages(m => m.map(x => x.id === botId ? { ...x, text: reply.text, tools: reply.tools, streaming: false } : x))
      } catch (e2) {
        setMessages(m => m.map(x => x.id === botId ? { ...x, text: '连接后端失败：' + e2.message, streaming: false } : x))
      }
    }
    finish()
  }
  async function send(textOverride) {
    const text = (textOverride ?? draft).trim()
    const files = pendingFiles.length ? pendingFiles : null
    if (!text && !files) return
    if (thinking || streaming) return
    // 多模态调度：只要附了图片且配了任意视觉模型，后端会自动路由理解（用户无感）；仅当完全没配视觉模型时温和提示
    if (files && files.some(f => f.isImage)) {
      const hasVisionProvider = providersList.some(p => p.supports_vision && p.api_key_configured)
      if (!hasVisionProvider) {
        message.info('当前未配置支持视觉的模型，图片可能无法被理解。到设置配置豆包 / GLM / 通义千问 / OpenAI 后即可自动看图')
      }
    }
    // 没有活动会话时，按当前空间新建一个（不提前自动建，让用户自己决定何时开始）
    let sid = sessionId
    if (!sid) {
      sid = await api.createSession(space)
      setSessionId(sid)
    }
    const botId = 'bot_' + Date.now()
    setMessages(m => [...m, { id: 'u_' + Date.now(), role: 'user', text: text || '(文件)', files: files || undefined }])
    setMessages(m => [...m, { id: botId, role: 'bot', text: '', tools: [], streaming: true }])
    setDraft('')
    setPendingFiles([])
    setPlanSteps([])
    setPlanRound(0)
    setChatTitle((text || (files && files.some(f => f.isImage) ? '图片消息' : '文件消息')).slice(0, 24))
    await streamInto(botId, text, sid, files)
  }
  // 复制气泡文字（兼容非 HTTPS / 旧浏览器）
  function copyBubble(text) {
    const t = (text || '').trim()
    if (!t) return
    const done = () => message.success('已复制到剪贴板')
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(t).then(done).catch(() => fallbackCopy(t, done))
    } else fallbackCopy(t, done)
  }
  function fallbackCopy(t, done) {
    try {
      const ta = document.createElement('textarea')
      ta.value = t
      ta.style.position = 'fixed'
      ta.style.opacity = '0'
      document.body.appendChild(ta)
      ta.select()
      document.execCommand('copy')
      document.body.removeChild(ta)
      done()
    } catch (_) {
      message.error('复制失败，请手动选择文字复制')
    }
  }
  // 重新生成：以当前 bot 之前最后一条用户消息为输入，替换当前 bot 回复
  async function regenerate(idx) {
    if (thinking || streaming) return
    let prompt = ''
    for (let k = idx - 1; k >= 0; k--) {
      if (messages[k] && messages[k].role === 'user') { prompt = messages[k].text || ''; break }
    }
    if (!prompt) return
    setMessages(m => m.slice(0, idx)) // 移除当前 bot 及其之后的消息
    let sid = sessionId
    if (!sid) { sid = await api.createSession(space); setSessionId(sid) }
    const botId = 'bot_' + Date.now()
    setMessages(m => [...m, { id: botId, role: 'bot', text: '', tools: [], streaming: true }])
    await streamInto(botId, prompt, sid, null)
  }
  // 赞 / 踩：更新本地状态并上报后端（后端落到语义记忆，引导智能体进化）
  async function handleFeedback(idx, rating) {
    const m = messages[idx]
    if (!m || m.role !== 'bot') return
    const next = m.feedback === rating ? null : rating // 再次点击同一项 = 取消
    let prompt = ''
    for (let k = idx - 1; k >= 0; k--) {
      if (messages[k] && messages[k].role === 'user') { prompt = messages[k].text || ''; break }
    }
    setMessages(ms => ms.map((x, i) => i === idx ? { ...x, feedback: next } : x))
    try {
      await api.sendFeedback({
        sessionId,
        messageIndex: idx,
        feedback: next || '',
        message: m.text || '',
        prompt,
        space,
      })
    } catch (_) { /* 本地状态已更新，上报失败不影响界面 */ }
  }
  function scrollToBottom() {
    const el = msgsRef.current
    if (el) el.scrollTop = el.scrollHeight
  }
  function onMsgsScroll() {
    const el = msgsRef.current
    if (!el) return
    const dist = el.scrollHeight - el.scrollTop - el.clientHeight
    setAtBottom(dist < 80)
  }
  sendRef.current = send

  // 移除某个待发送文件附件
  function removeFile(uid) {
    setPendingFiles(prev => prev.filter(f => f.uid !== uid))
  }

  // 通用文件上传：由工具栏图标按钮触发隐藏 file input，选中后读成 base64（图片/文档/压缩包等任意类型）
  function handlePickFiles(e) {
    const input = e.target
    const picked = Array.from(input.files || [])
    input.value = '' // 立即重置，允许重复选同一文件
    const room = 5 - pendingFiles.length
    if (room <= 0) { message.warning('最多同时附 5 个文件'); return }
    let added = 0
    for (const file of picked) {
      if (added >= room) { message.warning('最多同时附 5 个文件'); break }
      if (file.size > 15 * 1024 * 1024) { message.warning('单个文件需小于 15MB：' + file.name); continue }
      const reader = new FileReader()
      const uid = 'f_' + Date.now() + '_' + added
      reader.onload = () => {
        const result = reader.result || '' // data URL: data:<mime>;base64,<raw>
        const comma = result.indexOf(',')
        const raw = comma >= 0 ? result.slice(comma + 1) : result
        const mime = file.type || 'application/octet-stream'
        setPendingFiles(prev => prev.length < 5 ? [...prev, { uid, name: file.name, mime, data: raw, isImage: mime.startsWith('image/') }] : prev)
      }
      reader.readAsDataURL(file)
      added++
    }
  }

  // ---------- 语音输入：浏览器原生 SpeechRecognition（zh-CN），说完自动转写给模型 ----------
  useEffect(() => {
    const SR = window.SpeechRecognition || window.webkitSpeechRecognition
    if (!SR) { setSpeechSupported(false); return }
    const rec = new SR()
    rec.lang = 'zh-CN'
    rec.continuous = true
    rec.interimResults = true
    rec.onstart = () => setRecording(true)
    rec.onresult = (ev) => {
      let interim = ''
      let finalTxt = ''
      for (let i = 0; i < ev.results.length; i++) {
        const r = ev.results[i]
        if (r.isFinal) finalTxt += r[0].transcript
        else interim += r[0].transcript
      }
      // 重新计算已定稿文本（而非累加），避免同一段 final 被反复追加导致“你好你好你好”
      transcriptRef.current = finalTxt
      setDraft((baseTextRef.current + finalTxt + interim).trim())
    }
    rec.onend = () => {
      setRecording(false)
      // 关闭语音 = 仅停止收音；识别到的文字保留在输入框，由唯一的“发送”按钮发送，绝不自动发送
    }
    rec.onerror = (e) => {
      setRecording(false)
      message.error('语音识别出错（' + (e && e.error ? e.error : '未知') + '）：请确认已授权麦克风，并使用 Chrome / Edge')
    }
    recognitionRef.current = rec
    return () => { try { rec.stop() } catch (_) {} }
  }, [])
  function toggleSpeech() {
    const rec = recognitionRef.current
    if (!rec) { message.warning('当前浏览器不支持语音输入，建议用 Chrome / Edge'); return }
    if (recording) {
      try { rec.stop() } catch (_) {}
    } else {
      baseTextRef.current = (draft || '').trim() // 以当前输入框文字为基底，识别结果追加其后
      try { rec.start() } catch (_) {}
    }
  }

  async function newChat() {
    const id = await api.createSession(space)
    setSessionId(id)
    setMessages([])
    setChatTitle('与 LUMU 对话')
  }

  async function openSession(s) {
    setChatTitle(s.title)
    setSessionId(s.id)
    const msgs = await api.fetchSessionHistory(s.id)
    setMessages(msgs)
  }

  async function handleDeleteSession(s) {
    if (deletingId) return // 防重复点击
    setDeletingId(s.id)
    try {
      const res = await api.deleteSession(s.id)
      if (!res.ok) {
        window.alert('删除失败，原因：' + (res.error || '未知错误') + '\n\n（若为“网络错误/连接失败”，请确认后端地址是否正确，并强制刷新 Ctrl/Cmd+Shift+R）')
        return
      }
      setSessions(list => list.filter(x => x.id !== s.id))
      if (sessionId === s.id) {
        setSessionId(null)
        setMessages([])
        setChatTitle('与 LUMU 对话')
      }
    } finally {
      setDeletingId(null)
    }
  }

  async function onKbFile(e) {
    const f = e.target.files && e.target.files[0]
    if (!f) return
    // 打开解析过场弹窗，由弹窗完成上传、解析、入库与动效
    setKbFile(f)
    setKbModalOpen(true)
    e.target.value = ''
  }
  async function onKbDone() {
    // 弹窗结束后刷新知识库列表
    await loadKb(space)
  }
  async function handleDeleteKb(id) {
    if (!await api.deleteKbDocument(id, space)) window.alert('删除失败')
    else loadKb(space)
  }
  async function handleDeleteSkill(name) {
    if (!await api.deleteSkill(name)) window.alert('删除失败')
    else loadSkills(space)
  }

  const lastTools = [...messages].reverse().find(m => m.role === 'bot' && m.tools && m.tools.length)?.tools || []
  const chatSub = lastTools.length
    ? `本次已用到 ${lastTools.length} 个工具`
    : 'LUMU 正在记住你的偏好'

  return (
    <div className="lm-app">
      {/* 顶栏 */}
      <header className="lm-top">
        <div className="lm-brand">
          <svg className="lm-sprout" viewBox="0 0 24 24" width="24" height="24" aria-hidden="true">
            {/* 破土生长的新芽：茎 + 双叶 + 土点 */}
            <path d="M12 21v-8" stroke="#059669" strokeWidth="1.8" strokeLinecap="round" fill="none" />
            <path d="M12 13 C 12 9, 8.5 6.5, 4.5 6.5 C 4.5 10.5, 8 13.2, 12 13 Z" fill="#34d399" />
            <path d="M12 13 C 12 8.5, 15.5 5, 20 5 C 20 9.8, 16.2 13.4, 12 13 Z" fill="#059669" />
            <circle cx="7.5" cy="21.4" r="1" fill="#a7f3d0" />
            <circle cx="16.5" cy="21.4" r="1" fill="#a7f3d0" />
          </svg>
          <div>LUMU<small>记忆生命体</small></div>
        </div>
        <div className="lm-tabs">
          <button className={'lm-tab' + (view === 'work' ? ' active' : '')} onClick={() => setView('work')}>工作台</button>
          <button className={'lm-tab' + (view === 'cap' ? ' active' : '')} onClick={() => setView('cap')}>记忆与能力</button>
          <button className={'lm-tab' + (view === 'market' ? ' active' : '')} onClick={() => setView('market')}>技能市场</button>
        </div>
        <div className="lm-spacer" />
        <div className="lm-model-wrap">
          <button className="lm-pill lm-pill-btn" onClick={toggleModelMenu} title="点击切换模型">
            <span className="on" /> {modelStatus.name} · {modelStatus.online ? '在线' : '离线'} <span className="caret">▾</span>
          </button>
          {modelMenuOpen && (
            <>
              <div className="lm-model-mask" onClick={() => setModelMenuOpen(false)} />
              <div className="lm-model-pop">
                {providersList.length === 0 && <div className="lm-model-empty">加载中…</div>}
                {(() => {
                  // 只显示已配置密钥的提供商；模型优先用用户勾选启用的列表
                  const configured = providersList.filter(p => p.api_key_configured)
                  if (providersList.length > 0 && configured.length === 0) {
                    return <div className="lm-model-empty">还没有配置任何提供商密钥，请到设置里保存密钥并勾选模型</div>
                  }
                  return configured.map(p => {
                    const models = (p.enabled_models && p.enabled_models.length) ? p.enabled_models : (p.models || [])
                    return (
                      <div key={p.name} className="lm-model-group">
                        <div className="lm-model-gh">{p.display_name || p.name}</div>
                        {models.map(m => {
                          const active = p.name === modelStatus.provider && m === modelStatus.name
                          return (
                            <div key={m}
                              className={'lm-model-item' + (active ? ' cur' : '') + (switching ? ' busy' : '')}
                              onClick={() => !active && pickModel(p.name, m)}>
                              {m}{active ? ' ✓' : ''}
                            </div>
                          )
                        })}
                      </div>
                    )
                  })
                })()}
              </div>
            </>
          )}
        </div>
        <button className="lm-gear" style={{ border: '1px solid #e6e6e6', borderRadius: 10, padding: '7px 12px' }} onClick={() => setSettingsOpen(true)} aria-label="设置"><SettingOutlined /></button>
      </header>

      {/* 左侧栏 */}
      <aside className="lm-rail">
        <div className="lm-new" onClick={newChat}><PlusOutlined /> 新对话</div>
        <div className="lm-h4">最近</div>
        {sessions.length === 0 && <div className="lm-sess" style={{ color: '#b0b0b0' }}>暂无会话</div>}
        {sessions.map(s => (
          <div key={s.id} className={'lm-sess' + (s.id === sessionId ? ' active' : '')} onClick={() => openSession(s)}>
            <span className="lm-sess-title">{s.title}</span>
            <span className="lm-sess-del" title="删除对话" onClick={(e) => { e.stopPropagation(); handleDeleteSession(s) }}><DeleteOutlined /></span>
          </div>
        ))}
        <div className="lm-h4">空间</div>
        <button className={'lm-sess' + (space === 'work' ? ' active' : '')} onClick={() => setSpace('work')}><Ic name="FolderOutlined" /> 工作</button>
        <button className={'lm-sess' + (space === 'personal' ? ' active' : '')} onClick={() => setSpace('personal')}><Ic name="UserOutlined" /> 个人</button>
      </aside>

      {/* 中间：工作台对话 */}
      {view === 'work' && (
        <section className="lm-main">
          <div className="lm-chat-head">
            <div className="t">{chatTitle}</div>
            <div className="s">{chatSub}</div>
          </div>
          <div className="lm-msgs" ref={msgsRef} onScroll={onMsgsScroll}>
            {messages.length === 0 && (() => {
              const modelConfigured = (providersList || []).filter(p => p && p.api_key_configured).length > 0
              return (
              <div className="lm-starters">
                <div className="lm-starters-cap">欢迎使用 LUMU</div>
                <div className="lm-guide-sub">你的本地 AI 助手 —— 能真去干活，并越用越懂你。</div>

                <div className="lm-guide">
                  <div className={'lm-step' + (modelConfigured ? ' done' : '')}>
                    <div className="lm-step-no">{modelConfigured ? '✓' : '1'}</div>
                    <div className="lm-step-bd">
                      <div className="lm-step-t">连接你的模型</div>
                      <div className="lm-step-d">{modelConfigured ? '模型已就绪，可以直接对话。' : '首次使用请先填一个模型 API Key（如 DeepSeek / OpenAI）。'}</div>
                      {!modelConfigured && <Button type="primary" size="small" onClick={() => setSettingsOpen(true)} style={{ marginTop: 6 }}>去设置</Button>}
                    </div>
                  </div>

                  <div className="lm-step">
                    <div className="lm-step-no">2</div>
                    <div className="lm-step-bd">
                      <div className="lm-step-t">选一个空间</div>
                      <div className="lm-step-d">工作空间处理任务，个人空间记你的生活。当前在<Button type="link" size="small" onClick={() => setSpace('work')} style={{ padding: '0 4px' }}>工作</Button>/<Button type="link" size="small" onClick={() => setSpace('personal')} style={{ padding: '0 4px' }}>个人</Button>，点一下即可切换。</div>
                    </div>
                  </div>

                  <div className="lm-step">
                    <div className="lm-step-no">3</div>
                    <div className="lm-step-bd">
                      <div className="lm-step-t">开始对话</div>
                      <div className="lm-step-d">在下方输入框直接说你想做的事，LUMU 会真去干活。</div>
                    </div>
                  </div>
                </div>
              </div>
              )
            })()}
            {messages.map((m, i) => {
              if (m.role === 'system') {
                return (
                  <div key={m.id || i} className="lm-msg system">
                    <div className="lm-bubble warn"><span className="lm-warn-ic">⚠</span> {m.text}</div>
                  </div>
                )
              }
              return (
              <div key={m.id || i} className={'lm-msg ' + m.role}>
                <div className={'lm-av ' + (m.role === 'bot' ? 'bot' : 'me')}>{m.role === 'bot' ? 'L' : '我'}</div>
                <div>
                  {m.files && m.files.length > 0 && (
                    <div className="lm-msg-imgs">
                      {m.files.some(f => f.isImage) && (
                        <Image.PreviewGroup>
                          {m.files.filter(f => f.isImage).map((f, ii) => (
                            <Image key={ii} src={'data:' + f.mime + ';base64,' + f.data} width={110} height={110} style={{ objectFit: 'cover', borderRadius: 10 }} />
                          ))}
                        </Image.PreviewGroup>
                      )}
                      {m.files.some(f => !f.isImage) && (
                        <div className="lm-msg-files">
                          {m.files.filter(f => !f.isImage).map((f, ii) => (
                            <span key={ii} className="lm-file-chip"><PaperClipOutlined /> {f.name}</span>
                          ))}
                        </div>
                      )}
                    </div>
                  )}
                  {/* 完成后：工具在气泡上方；流式输出中：工具在气泡下方 */}
                  {m.tools && m.tools.length > 0 && !m.streaming && (
                    <div className="lm-tools">
                      {m.tools.map((t, ti) => (
                        <span key={ti} className={'lm-chip' + (t.ok ? ' ok' : '')}>{t.name} {t.ok && <span className="ok"><CheckOutlined /></span>}</span>
                      ))}
                    </div>
                  )}
                  <div className="lm-bubble">
                    {m.role === 'bot' ? renderRich(m.text) : m.text}
                    {m.streaming && <span className="lm-cursor" />}
                  </div>
                  {m.role === 'bot' && m.streaming && planSteps.length > 0 && (
                    <div style={{ margin: '10px 0 6px', background: '#f0fdf4', border: '1px solid #bbf7d0', borderRadius: 10, padding: '10px 12px' }}>
                      <div style={{ fontSize: 12, color: '#059669', marginBottom: 6, fontWeight: 500 }}>执行进度</div>
                      <Steps
                        size="small"
                        current={Math.max(0, Math.min(planRound, planSteps.length) - 1)}
                        items={planSteps.map((s) => ({ title: s.replace(/[`*]/g, '').slice(0, 42) }))}
                      />
                    </div>
                  )}
                  {m.role === 'bot' && !m.streaming && (
                    <div className="lm-msg-actions">
                      <Tooltip title="复制内容">
                        <button className="lm-act" onClick={() => copyBubble(m.text)} aria-label="复制"><CopyOutlined /></button>
                      </Tooltip>
                      <Tooltip title="重新生成这条回复">
                        <button className="lm-act" onClick={() => regenerate(i)} aria-label="重新生成"><ReloadOutlined /></button>
                      </Tooltip>
                      <Tooltip title="认可这条回复（帮助智能体进化）">
                        <button className={'lm-act' + (m.feedback === 'like' ? ' on like' : '')} onClick={() => handleFeedback(i, 'like')} aria-label="赞"><LikeOutlined /></button>
                      </Tooltip>
                      <Tooltip title="不认可这条回复（帮助智能体改进）">
                        <button className={'lm-act' + (m.feedback === 'dislike' ? ' on dislike' : '')} onClick={() => handleFeedback(i, 'dislike')} aria-label="踩"><DislikeOutlined /></button>
                      </Tooltip>
                    </div>
                  )}
                  {m.tools && m.tools.length > 0 && m.streaming && (
                    <div className="lm-tools streaming">
                      {m.tools.map((t, ti) => (
                        <span key={ti} className={'lm-chip' + (t.running ? ' running' : t.ok ? ' ok' : '')}>
                          {t.name} {t.running ? '…' : t.ok ? <span className="ok"><CheckOutlined /></span> : ''}
                        </span>
                      ))}
                    </div>
                  )}
                </div>
              </div>
            )})}
            {thinking && !messages.some(m => m.streaming) && (
              <div className="lm-think"><span className="b" /><span className="b" /><span className="b" /> LUMU 正在理解并写入记忆…</div>
            )}
          </div>
          {!atBottom && (
            <button className="lm-tobottom" onClick={() => { scrollToBottom(); setAtBottom(true) }} aria-label="回到最新消息">↓ 回到底部</button>
          )}
          <div className="lm-composer">
            {recording && (
              <div className="lm-voice-live">
                <span className="dot" /> 正在聆听… {draft ? '“' + draft + '”' : '请说话'}
              </div>
            )}
            {pendingFiles.length > 0 && (
              <div className="lm-attach-preview">
                {pendingFiles.map(f => (
                  <div key={f.uid} className={'lm-attach-thumb' + (f.isImage ? '' : ' file')}>
                    {f.isImage ? (
                      <img src={'data:' + f.mime + ';base64,' + f.data} alt={f.name} />
                    ) : (
                      <span className="lm-attach-ic"><PaperClipOutlined /></span>
                    )}
                    <span className="lm-attach-name" title={f.name}>{f.name}</span>
                    <button className="lm-attach-x" onClick={() => removeFile(f.uid)} aria-label="移除"><CloseOutlined /></button>
                  </div>
                ))}
              </div>
            )}
            <div className="lm-box">
              <Input.TextArea
                className="lm-input"
                value={draft}
                autoSize={{ minRows: 1, maxRows: 5 }}
                variant="borderless"
                placeholder="让 LUMU 帮你做点什么…（它能读文件、上网、跑命令、记东西）"
                onChange={e => setDraft(e.target.value)}
                onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send() } }}
              />
              <Tooltip title="上传文件（图片 / 文档 / 压缩包等，最多 5 个，单个 ≤15MB）">
                <button
                  className="lm-icon-btn"
                  onClick={() => attachRef.current?.click()}
                  aria-label="上传文件"
                >
                  <PaperClipOutlined />
                </button>
              </Tooltip>
              <input
                ref={attachRef}
                type="file"
                accept="*"
                multiple
                style={{ display: 'none' }}
                onChange={handlePickFiles}
              />
              <Tooltip title={speechSupported ? '语音输入（中文）' : '当前浏览器不支持语音输入，建议用 Chrome / Edge'}>
                <button
                  className={'lm-icon-btn' + (recording ? ' on' : '')}
                  onClick={toggleSpeech}
                  aria-label="语音输入"
                >
                  <AudioOutlined className={recording ? 'lm-pulse' : ''} />
                </button>
              </Tooltip>
              <button className="lm-send" onClick={() => send()} aria-label="发送"><SendOutlined /></button>
            </div>
          </div>
        </section>
      )}

      {/* 右侧：记忆生命体（仅工作台显示） */}
      {view === 'work' && (
        <aside className="lm-side">
          <h3><span className="lm-live" /> 记忆生命体</h3>
          <div className="lm-orb-wrap">
            <MemoryLifeform dark />
          </div>
          <div className="lm-stats">
            <div className="lm-stat"><b>{stats.memory}</b><span>记忆</span></div>
            <div className="lm-stat"><b>{skillsCount}</b><span>技能</span></div>
            <div className="lm-stat"><b>{stats.knowledge}</b><span>知识</span></div>
          </div>
          <h3>你这个人（LUMU 记得的偏好）</h3>
          <div style={{ background: '#f0fdf4', border: '1px solid #bbf7d0', borderRadius: 10, padding: '10px 12px', marginBottom: 14 }}>
            {profilePrefs.length === 0 ? (
              <div style={{ fontSize: 12, color: '#94a3b8' }}>还没有记住你的偏好，多聊几句它就懂你了</div>
            ) : (
              profilePrefs.map((p, i) => (
                <div key={i} style={{ fontSize: 12.5, color: '#334155', lineHeight: 1.9 }}>· {p.content}</div>
              ))
            )}
          </div>
          <h3>今天 LUMU 记住了</h3>
          <div className="lm-mem-pages" ref={memRef} onScroll={onMemScroll}>
            {memPages.map((page, pi) => (
              <div className="lm-mem-page" key={pi}>
                {page.map((m, i) => (
                  <div className="lm-mem" key={i}>
                    <span className={'tag ' + m.cls}>{m.type}</span>
                    <div className="txt">{m.text}<small>{m.meta}</small></div>
                  </div>
                ))}
              </div>
            ))}
          </div>
          {memPages.length > 1 && (
            <div className="lm-mem-dots">
              {memPages.map((_, pi) => (
                <span key={pi} className={'dot' + (pi === memPage ? ' on' : '')} />
              ))}
            </div>
          )}
        </aside>
      )}

      {/* 记忆与能力视图 */}
      {view === 'cap' && (
        <div className="lm-capwrap">
          <div className="lm-panel" style={{ padding: '14px 18px', marginBottom: 18 }}>
            <h3 style={{ fontSize: 16 }}>记忆与能力中心</h3>
            <div className="desc">这里能看到 LUMU 真正“长”成了什么样子——它记住了你什么、学会了什么、能帮你做哪些事。这是 LUMU 区别于普通助手的核心。</div>
          </div>
          <div className="lm-cap-cols">
            <div className="lm-cap-col">
              <div className="lm-panel lm-cap-card">
                <h3>记忆生命体</h3>
                <div className="desc">持续生长的智能体象征——它随你与 LUMU 的每一次互动不断累积与进化。</div>
                <div className="lm-orb-wrap" style={{ height: 280 }}>
                  <MemoryLifeform dark />
                </div>
              </div>
              <div className="lm-panel lm-cap-card">
                <h3>能力（工具集）</h3>
                <div className="desc">LUMU 真实内置 {toolsets.total} 项工具，覆盖 {toolsets.sets.length} 个能力域。</div>
                {toolsets.sets.length === 0 && <div className="lm-empty">暂无能力数据</div>}
                <div className="lm-tags lm-card-body">
                  {toolsets.sets.map(c => (
                    <span className="lm-tag" key={c.name} title={c.desc}>{c.label}</span>
                  ))}
                </div>
              </div>
              <div className="lm-panel lm-cap-card">
                <h3>知识库（{kbStats.total_entries ?? 0}）</h3>
                <div className="desc">上传文档（txt / md / pdf / docx），LUMU 会记住内容并在对话中检索问答。</div>
                <div className="lm-kb-actions">
                  <button className="lm-btn" disabled={kbModalOpen} onClick={() => fileRef.current && fileRef.current.click()}>{kbModalOpen ? '解析中…' : '上传文档'}</button>
                  <input ref={fileRef} type="file" accept=".txt,.md,.pdf,.docx" style={{ display: 'none' }} onChange={onKbFile} />
                </div>
                {kbDocs.length === 0 && <div className="lm-empty">知识库还是空的，上传一份资料试试</div>}
                {kbDocs.length > 0 && (
                  <div className="lm-list-body">
                    {kbDocs.map(d => (
                      <div className="lm-skill" key={d.id}>
                        <div className="bar" />
                        <div className="info">
                          <div className="nm">{d.title || d.source}</div>
                          <div className="ds">{d.category}{Array.isArray(d.tags) && d.tags.length ? ' · ' + d.tags.join(',') : ''}</div>
                        </div>
                        <div className="del" title="删除文档" onClick={() => handleDeleteKb(d.id)}><DeleteOutlined /></div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>
            <div className="lm-cap-col">
              <div className="lm-panel lm-cap-card">
                <h3>成长时间线</h3>
                <div className="desc">来自 LUMU 真实的对话记录。</div>
                {timelineData.length === 0 ? (
                  <div className="lm-empty">暂无活动记录</div>
                ) : (
                  <div className="lm-tl-body">
                    {timelineData.map((t, i) => (
                      <div key={i} className="lm-tl">
                        <div className="bar" />
                        <div className="c"><div className="d">{t.meta}</div><div className="t"><b>{t.who}</b> {t.text}</div></div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
              <div className="lm-panel lm-cap-card">
                <h3>技能库（{skills.length}）</h3>
                <div className="desc">LUMU 已内置可复用的技能流程；对话中学会的新技能也会沉淀到这里。</div>
                {skills.length === 0 && <div className="lm-empty">暂无技能</div>}
                {skills.length > 0 && (
                  <div className="lm-list-body">
                    {skills.map(s => (
                      <div className="lm-skill" key={s.name}>
                        <div className="bar" />
                        <div className="info">
                          <div className="nm">{s.name}</div>
                          <div className="ds">{s.description}</div>
                          {s.tags && <div className="tg">#{s.tags}</div>}
                        </div>
                        <div className="del" title="删除技能" onClick={() => handleDeleteSkill(s.name)}><DeleteOutlined /></div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>
          </div>
        </div>
      )}

      {/* 技能市场视图 */}
      {view === 'market' && <MarketView />}

      <SettingsDrawer open={settingsOpen} onClose={() => setSettingsOpen(false)} onModelChanged={refreshModelStatus} />

      <KbUploadModal
        open={kbModalOpen}
        file={kbFile}
        space={space}
        onClose={() => { setKbModalOpen(false); setKbFile(null) }}
        onDone={onKbDone}
      />
    </div>
  )
}

export default App
