import React, { useEffect, useRef, useState } from 'react'
import { Modal, Steps, Progress, Button, Typography } from 'antd'
import {
  FileTextOutlined, FilePdfOutlined, FileWordOutlined,
  CheckCircleTwoTone, CloseCircleTwoTone, LoadingOutlined
} from '@ant-design/icons'
import * as api from '../api.js'

const { Step } = Steps
const { Text, Paragraph } = Typography

// 每个阶段进度条逼近的上限（营造分阶段推进的过场感）
const STEP_CAP = [35, 70, 100, 100]
const wait = (ms) => new Promise((r) => setTimeout(r, ms))

function fileIcon(name) {
  const ext = (name.split('.').pop() || '').toLowerCase()
  if (ext === 'pdf') return <FilePdfOutlined style={{ color: '#e11d48' }} />
  if (ext === 'docx') return <FileWordOutlined style={{ color: '#2563eb' }} />
  return <FileTextOutlined style={{ color: '#059669' }} />
}

function fmtSize(bytes) {
  if (!bytes && bytes !== 0) return ''
  if (bytes < 1024) return bytes + ' B'
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB'
  return (bytes / 1024 / 1024).toFixed(1) + ' MB'
}

const STAGE_HINT = [
  '正在上传文档到 LUMU 本地知识库…',
  '正在逐页识别文字、抽取正文（pdf / docx / txt / md）…',
  '正在把内容按语义拆分成多条知识并写入记忆…',
  '全部完成'
]

export default function KbUploadModal({ open, file, space, onClose, onDone }) {
  const [cur, setCur] = useState(0)
  const [pct, setPct] = useState(0)
  const [stat, setStat] = useState(null)
  const [err, setErr] = useState('')
  const pctRef = useRef(0)
  const timerRef = useRef(null)
  const ranRef = useRef(false)

  // 进度条：持续向当前阶段的上限逼近，制造平滑过场
  useEffect(() => {
    if (!open) return
    timerRef.current = setInterval(() => {
      const cap = STEP_CAP[cur] ?? 100
      pctRef.current += Math.max(1, (cap - pctRef.current) * 0.12)
      if (pctRef.current > cap) pctRef.current = cap
      setPct(Math.min(99, Math.round(pctRef.current)))
    }, 80)
    return () => { if (timerRef.current) clearInterval(timerRef.current) }
  }, [open, cur])

  // 主流程：上传 → 解析 → 入库，分阶段推进步骤
  useEffect(() => {
    if (!open || !file || ranRef.current) return
    ranRef.current = true
    setCur(0); setPct(0); pctRef.current = 0; setStat(null); setErr('')

    ;(async () => {
      try {
        const res = await api.uploadKbDocument(file, space)
        setCur(1); await wait(320)            // 解析中
        setCur(2); await wait(320)            // 入库中
        if (res && (res.status === 'ok' || res.status === 'empty')) {
          setStat(res); setCur(3)
        } else {
          setErr((res && res.message) || '解析失败，请重试')
          setCur(3)
        }
      } catch (e) {
        setErr(e.message || '上传失败，请检查网络后重试')
        setCur(3)
      } finally {
        pctRef.current = 100; setPct(100)
      }
    })()

    return () => { ranRef.current = false }
  }, [open, file])

  const done = cur === 3
  const ok = done && stat && (stat.status === 'ok' || stat.status === 'empty')
  const isEmpty = done && stat && stat.status === 'empty'

  function handleClose() {
    if (onDone) onDone(stat)
    onClose()
  }

  return (
    <Modal
      open={open}
      onCancel={done ? handleClose : undefined}
      footer={done ? (
        <Button type="primary" onClick={handleClose}>
          {ok ? '完成' : '关闭'}
        </Button>
      ) : (
        <Button type="default" disabled>处理中…</Button>
      )}
      closable={done}
      maskClosable={done}
      destroyOnClose
      title="文档解析入库"
      width={460}
    >
      <div className="kb-up">
        {file && (
          <div className="kb-up-file">
            <span className="kb-up-ic">{fileIcon(file.name)}</span>
            <div className="kb-up-meta">
              <div className="nm">{file.name}</div>
              <div className="sz">{fmtSize(file.size)}</div>
            </div>
          </div>
        )}

        <Steps
          direction="vertical"
          size="small"
          current={cur}
          status={err ? 'error' : 'process'}
          className="kb-up-steps"
        >
          <Step title="上传文档" description="安全传到 LUMU 本地" />
          <Step title="识别解析" description="抽取正文文字" />
          <Step title="拆分入库" description="按语义写入知识库" />
          <Step title="完成" description="可在「记忆与能力」查看" />
        </Steps>

        <div className="kb-up-prog">
          <Progress
            percent={pct}
            status={err ? 'exception' : ok ? 'success' : 'active'}
            strokeColor={{ from: '#10b981', to: '#059669' }}
          />
          <div className={'kb-up-hint' + (err ? ' err' : '')}>
            {err ? <CloseCircleTwoTone twoToneColor="#e11d48" /> : done && ok ? <CheckCircleTwoTone twoToneColor="#059669" /> : <LoadingOutlined />}
            <span>{err ? err : STAGE_HINT[cur]}</span>
          </div>
        </div>

        {ok && (
          <div className="kb-up-res">
            {isEmpty ? (
              <Paragraph style={{ margin: 0, color: '#b45309' }}>
                文档已处理，但未解析出可读文字（可能是扫描件图片 PDF 或空文件）。建议提供可复制文字的版本。
              </Paragraph>
            ) : (
              <div className="kb-up-stats">
                <div className="st"><b>{stat.chars.toLocaleString()}</b><span>识别字符</span></div>
                <div className="st"><b>{stat.chunks}</b><span>拆分段数</span></div>
                <div className="st"><b>{stat.entries}</b><span>入库条数</span></div>
              </div>
            )}
            <Text type="secondary" style={{ fontSize: 12 }}>
              已写入空间「{space === 'personal' ? '个人' : '工作'}」，对话时可被检索问答。
            </Text>
          </div>
        )}
      </div>
    </Modal>
  )
}
