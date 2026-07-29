import React, { useEffect, useState } from 'react'
import * as api from '../api.js'

// 真实配置抽屉：模型/提供商、推理参数、系统提示词、TTS、Embedding。
// 全部接后端 /api/config/*，不含记忆/能力（那些在工作台与「记忆与能力」页）。
export default function SettingsDrawer({ open, onClose, onModelChanged }) {
  const [tab, setTab] = useState('model')
  const [providers, setProviders] = useState([])
  const [provider, setProvider] = useState('')
  const [apiKey, setApiKey] = useState('')
  const [baseUrl, setBaseUrl] = useState('')
  const [detected, setDetected] = useState({ loading: false, ok: false, reason: '', models: [] })
  const [checked, setChecked] = useState([])   // 勾选启用的模型
  const [curStatus, setCurStatus] = useState({ provider: '', name: '' })
  const [temperature, setTemperature] = useState(0.7)
  const [topP, setTopP] = useState(0.9)
  const [sysPrompt, setSysPrompt] = useState('')
  const [ttsProvider, setTtsProvider] = useState('')
  const [ttsKey, setTtsKey] = useState('')
  const [embUrl, setEmbUrl] = useState('')
  const [embModel, setEmbModel] = useState('')
  const [embKey, setEmbKey] = useState('')
  const [msg, setMsg] = useState('')
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    if (!open) return
    setMsg('')
    Promise.all([
      api.fetchProviders(),
      api.fetchConfigParams(),
      api.fetchSystemPrompt(),
      api.fetchTts(),
      api.fetchEmbedding(),
      api.fetchModelStatus(),
    ]).then(([ps, p, sp, tts, emb, st]) => {
      setProviders(ps)
      setCurStatus({ provider: st.provider || '', name: st.name || '' })
      // 预选后端当前真实使用的 provider（而不是写死第一个）
      const cur = ps.find(x => x.name === st.provider)
      const initial = cur || ps[0]
      if (initial) selectProvider(initial.name, ps)
      setTemperature(p.temperature ?? 0.7)
      setTopP(p.top_p ?? 0.9)
      setSysPrompt(sp || '')
      setTtsProvider(tts.provider || '')
      setTtsKey(tts.mimo_api_key || '')
      setEmbUrl(emb.base_url || '')
      setEmbModel(emb.model || '')
      setEmbKey(emb.api_key ? '********' : '')
    }).catch(() => setMsg('读取配置失败，后端可能未连接'))
  }, [open])

  // 选中提供商：若已配密钥则自动识别其令牌下的真实模型列表
  async function selectProvider(name, list) {
    const ps = list || providers
    const p = ps.find(x => x.name === name)
    setProvider(name)
    setApiKey('')
    setBaseUrl(p?.active_base_url || '')
    setChecked(p?.enabled_models?.length ? p.enabled_models : [])
    if (!p) return
    if (!p.api_key_configured) {
      setDetected({ loading: false, ok: false, reason: '未配置 API Key，保存密钥后自动识别', models: [] })
      return
    }
    setDetected({ loading: true, ok: false, reason: '', models: [] })
    const d = await api.detectProviderModels(name)
    setDetected({ loading: false, ok: !!d.detected, reason: d.reason || '', models: d.models || [] })
    // 默认勾选：已保存的启用列表 > 当前在用模型 > 空
    const saved = (d.enabled_models && d.enabled_models.length) ? d.enabled_models : (p.enabled_models || [])
    if (saved.length) setChecked(saved.filter(m => (d.models || []).includes(m) || !d.detected))
  }

  function toggleModel(m) {
    setChecked(c => c.includes(m) ? c.filter(x => x !== m) : [...c, m])
  }

  // 保存勾选启用的模型
  async function saveChecked() {
    setBusy(true); setMsg('')
    const ok = await api.saveEnabledModels(provider, checked)
    setMsg(ok ? `已启用 ${checked.length} 个模型 ✓（顶栏模型菜单即时生效）` : '保存失败')
    if (ok) {
      const ps = await api.fetchProviders(); setProviders(ps)
      if (onModelChanged) onModelChanged()
    }
    setBusy(false)
  }

  // 切换当前使用的模型（从勾选列表中点选）
  async function useModel(m) {
    setBusy(true); setMsg('')
    const ok = await api.switchModel(provider, m)
    setMsg(ok ? `已切换到 ${provider} / ${m} ✓` : '切换失败')
    if (ok) { setCurStatus({ provider, name: m }); if (onModelChanged) onModelChanged() }
    setBusy(false)
  }

  async function saveParams() {
    setBusy(true); setMsg('')
    const ok = await api.saveConfigParams(Number(temperature), Number(topP))
    setMsg(ok ? '参数已保存 ✓' : '保存失败')
    setBusy(false)
  }
  async function savePrompt() {
    setBusy(true); setMsg('')
    const ok = await api.saveSystemPrompt(sysPrompt)
    setMsg(ok ? '系统提示词已保存 ✓' : '保存失败')
    setBusy(false)
  }
  async function saveKey() {
    setBusy(true); setMsg('')
    const ok = await api.saveProviderKey(provider, apiKey)
    setMsg(ok ? 'API Key 已保存 ✓ 正在自动识别可用模型…' : '保存失败')
    setBusy(false)
    if (ok) {
      const ps = await api.fetchProviders(); setProviders(ps)
      await selectProvider(provider, ps) // 保存密钥后立即自动识别模型
    }
  }
  async function saveBaseUrl() {
    setBusy(true); setMsg('')
    const ok = await api.saveProviderBaseUrl(provider, baseUrl.trim())
    setMsg(ok ? 'Base URL 已保存 ✓（该提供商将指向此地址）' : '保存失败')
    setBusy(false)
    if (ok) {
      const ps = await api.fetchProviders(); setProviders(ps)
      await selectProvider(provider, ps)
    }
  }
  async function saveTts() {
    setBusy(true); setMsg('')
    const ok = await api.saveTts(ttsProvider, ttsKey)
    setMsg(ok ? '语音配置已保存 ✓' : '保存失败')
    setBusy(false)
  }
  async function saveEmb() {
    setBusy(true); setMsg('')
    const ok = await api.saveEmbedding(embUrl, embModel, embKey === '********' ? '' : embKey)
    setMsg(ok ? '嵌入配置已保存 ✓' : '保存失败')
    setBusy(false)
  }

  if (!open) return null
  const TABS = [['model', '模型/提供商'], ['params', '推理参数'], ['prompt', '系统提示词'], ['tts', '语音'], ['emb', '嵌入']]
  return (
    <div className="lm-drawer-mask" onClick={onClose}>
      <div className="lm-drawer" onClick={e => e.stopPropagation()}>
        <div className="lm-drawer-head">
          <b>设置</b>
          <button className="lm-x" onClick={onClose} aria-label="关闭">×</button>
        </div>
        <div className="lm-drawer-tabs">
          {TABS.map(([k, v]) => (
            <button key={k} className={'lm-dtab' + (tab === k ? ' on' : '')} onClick={() => setTab(k)}>{v}</button>
          ))}
        </div>
        <div className="lm-drawer-body">
          {tab === 'model' && (
            <div className="lm-form">
              <label>提供商</label>
              <select value={provider} onChange={e => selectProvider(e.target.value)}>
                {providers.map(p => <option key={p.name} value={p.name}>{p.display_name || p.name}{p.api_key_configured ? ' ·已配置' : ' ·未配密钥'}</option>)}
              </select>
              <label>API Key（{provider}）</label>
              <input value={apiKey} placeholder={providers.find(p => p.name === provider)?.api_key_preview || '粘贴该提供商的 API Key'} onChange={e => setApiKey(e.target.value)} />
              <button className="lm-btn" disabled={busy || !apiKey.trim()} onClick={saveKey}>保存密钥并自动识别模型</button>

              <label style={{ marginTop: 14 }}>Base URL（可选，连硅基流动等 OpenAI 兼容服务时填写）</label>
              <input value={baseUrl} placeholder="https://api.siliconflow.cn/v1 （留空用默认）" onChange={e => setBaseUrl(e.target.value)} />
              <button className="lm-btn" disabled={busy} onClick={saveBaseUrl}>保存 Base URL</button>

              <label style={{ marginTop: 14 }}>可用模型{detected.loading ? '（识别中…）' : detected.ok ? `（已自动识别 ${detected.models.length} 个，勾选启用）` : detected.reason ? `（${detected.reason}）` : ''}</label>
              {detected.loading && <div className="lm-empty">正在读取该令牌下的模型列表…</div>}
              {!detected.loading && detected.models.length > 0 && (
                <div className="lm-model-checks">
                  {detected.models.map(m => (
                    <label key={m} className={'lm-check' + (checked.includes(m) ? ' on' : '')}>
                      <input type="checkbox" checked={checked.includes(m)} onChange={() => toggleModel(m)} />
                      <span className="nm">{m}</span>
                      {curStatus.provider === provider && curStatus.name === m && <span className="cur">当前在用</span>}
                      {checked.includes(m) && <button className="lm-mini-btn" disabled={busy} onClick={e => { e.preventDefault(); useModel(m) }}>使用</button>}
                    </label>
                  ))}
                </div>
              )}
              {!detected.loading && detected.models.length > 0 && (
                <button className="lm-btn" disabled={busy || checked.length === 0} onClick={saveChecked}>保存启用的 {checked.length} 个模型</button>
              )}
              {!detected.loading && detected.models.length === 0 && (
                <div className="lm-empty">保存密钥后会自动读取该令牌下真实可用的模型</div>
              )}
            </div>
          )}
          {tab === 'params' && (
            <div className="lm-form">
              <label>温度 temperature：{temperature}</label>
              <input type="range" min="0" max="1" step="0.05" value={temperature} onChange={e => setTemperature(e.target.value)} />
              <label>top_p：{topP}</label>
              <input type="range" min="0" max="1" step="0.05" value={topP} onChange={e => setTopP(e.target.value)} />
              <button className="lm-btn" disabled={busy} onClick={saveParams}>保存参数</button>
            </div>
          )}
          {tab === 'prompt' && (
            <div className="lm-form">
              <label>系统提示词（写在每次对话最前面，定义 LUMU 的默认身份与边界）</label>
              <textarea rows={10} value={sysPrompt} onChange={e => setSysPrompt(e.target.value)} />
              <button className="lm-btn" disabled={busy} onClick={savePrompt}>保存提示词</button>
            </div>
          )}
          {tab === 'tts' && (
            <div className="lm-form">
              <label>TTS 提供商</label>
              <input value={ttsProvider} placeholder="如 mimo / none" onChange={e => setTtsProvider(e.target.value)} />
              <label>API Key（留空则不修改）</label>
              <input value={ttsKey} placeholder="mimo API Key" onChange={e => setTtsKey(e.target.value)} />
              <button className="lm-btn" disabled={busy} onClick={saveTts}>保存语音配置</button>
            </div>
          )}
          {tab === 'emb' && (
            <div className="lm-form">
              <label>Embedding Base URL</label>
              <input value={embUrl} onChange={e => setEmbUrl(e.target.value)} />
              <label>Embedding 模型</label>
              <input value={embModel} onChange={e => setEmbModel(e.target.value)} />
              <label>API Key（留空则不修改）</label>
              <input value={embKey} onChange={e => setEmbKey(e.target.value)} />
              <button className="lm-btn" disabled={busy} onClick={saveEmb}>保存嵌入配置</button>
            </div>
          )}
          {msg && <div className="lm-save-msg">{msg}</div>}
        </div>
      </div>
    </div>
  )
}
