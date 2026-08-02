"use client"

import * as React from "react"
import {
  IconDeviceFloppy,
  IconKey,
  IconCheck,
  IconBrandTelegram,
  IconBrandDiscord,
  IconWebhook,
  IconBrandWechat,
  IconBrandMessenger,
  IconBrandSlack,
  IconBroadcast,
} from "@tabler/icons-react"
import { toast } from "sonner"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { Skeleton } from "@/components/ui/skeleton"
import {
  fetchConfig,
  fetchProviders,
  saveSystemPrompt,
  switchModel,
  saveParams,
  setProviderKey,
  fetchChannelsConfig,
  saveChannelsConfig,
  type AppConfig,
  type Provider,
  type ChannelDef,
} from "@/lib/lumu"

export function SettingsView() {
  const [cfg, setCfg] = React.useState<AppConfig | null>(null)
  const [providers, setProviders] = React.useState<Provider[]>([])
  const [loading, setLoading] = React.useState(true)
  const [sp, setSp] = React.useState("")
  const [spSaved, setSpSaved] = React.useState(false)
  const [temp, setTemp] = React.useState(0.7)
  const [topP, setTopP] = React.useState(0.9)
  const [paramsSaved, setParamsSaved] = React.useState(false)
  const [selProvider, setSelProvider] = React.useState("")
  const [selModel, setSelModel] = React.useState("")
  const [keys, setKeys] = React.useState<Record<string, string>>({})
  const [keyMsg, setKeyMsg] = React.useState<string | null>(null)

  // 渠道接入
  const [channels, setChannels] = React.useState<ChannelDef[]>([])
  const [drafts, setDrafts] = React.useState<Record<string, Record<string, string>>>({})
  const [chSaving, setChSaving] = React.useState<string | null>(null)

  const load = React.useCallback(async () => {
    setLoading(true)
    try {
      const [c, p, ch] = await Promise.all([
        fetchConfig(),
        fetchProviders(),
        fetchChannelsConfig().catch(() => ({ channels: [] })),
      ])
      setCfg(c)
      setProviders(p.providers)
      setSp(c.system_prompt || "")
      setTemp(c.provider_overrides?.temperature ?? 0.7)
      setTopP(c.provider_overrides?.top_p ?? 0.9)
      setSelProvider(c.model_preference.provider)
      setSelModel(c.model_preference.model)
      setChannels(ch.channels)
    } finally {
      setLoading(false)
    }
  }, [])

  const channelIcon: Record<string, React.ComponentType<{ className?: string }>> = {
    telegram: IconBrandTelegram,
    discord: IconBrandDiscord,
    webhook: IconWebhook,
    wecom: IconBrandWechat,
    feishu: IconBrandMessenger,
    dingtalk: IconBrandSlack,
  }

  const setField = (chKey: string, fKey: string, val: string) => {
    setDrafts((s) => ({ ...s, [chKey]: { ...(s[chKey] || {}), [fKey]: val } }))
  }

  const onSaveChannel = async (ch: ChannelDef) => {
    const draft = drafts[ch.key] || {}
    const payload: Record<string, string> = {}
    for (const [k, v] of Object.entries(draft)) {
      if (v && v.trim() !== "") payload[k] = v.trim()
    }
    if (Object.keys(payload).length === 0) {
      toast.error("没有需要保存的改动")
      return
    }
    setChSaving(ch.key)
    try {
      await saveChannelsConfig({ [ch.key]: payload })
      toast.success(`已保存「${ch.name}」配置，正在热重载渠道`)
      const fresh = await fetchChannelsConfig()
      setChannels(fresh.channels)
      setDrafts((s) => ({ ...s, [ch.key]: {} }))
    } catch (e: any) {
      toast.error("保存失败：" + String(e?.message || e))
    } finally {
      setChSaving(null)
    }
  }

  React.useEffect(() => {
    load()
  }, [load])

  const configured = providers.filter((p) => p.api_key_configured)
  const curProvider = providers.find((p) => p.name === selProvider)
  const modelOptions = curProvider
    ? Array.from(new Set([...curProvider.enabled_models, ...curProvider.models]))
    : []

  const onSwitch = async () => {
    try {
      await switchModel(selProvider, selModel)
      setKeyMsg("模型已切换为 " + selModel)
    } catch (e: any) {
      setKeyMsg("切换失败：" + String(e?.message || e))
    }
  }

  const onSaveSP = async () => {
    try {
      await saveSystemPrompt(sp)
      setSpSaved(true)
      setTimeout(() => setSpSaved(false), 2000)
    } catch (e: any) {
      setKeyMsg("保存失败：" + String(e?.message || e))
    }
  }

  const onSaveParams = async () => {
    try {
      await saveParams({ temperature: temp, top_p: topP })
      setParamsSaved(true)
      setTimeout(() => setParamsSaved(false), 2000)
    } catch (e: any) {
      setKeyMsg("保存失败：" + String(e?.message || e))
    }
  }

  const onSetKey = async (name: string) => {
    const k = keys[name]
    if (!k) return
    try {
      await setProviderKey(name, k)
      setKeyMsg("已更新 " + name + " 的 API Key")
      setKeys((s) => ({ ...s, [name]: "" }))
    } catch (e: any) {
      setKeyMsg("更新失败：" + String(e?.message || e))
    }
  }

  if (loading) {
    return (
      <div className="space-y-4 p-6">
        <Skeleton className="h-8 w-40" />
        <Skeleton className="h-64 w-full" />
      </div>
    )
  }

  return (
    <div className="space-y-5 p-4 md:p-6">
      <div>
        <h1 className="font-display text-2xl font-semibold tracking-tight">设置</h1>
        <p className="mt-1 text-sm text-muted-foreground">模型、系统提示词、采样参数与供应商密钥。</p>
      </div>

      {keyMsg && (
        <div className="rounded-md border border-border bg-white/5 px-3 py-2 text-sm text-foreground/90">
          {keyMsg}
        </div>
      )}

      <div className="grid gap-4 lg:grid-cols-2">
        {/* 模型 */}
        <Card>
          <CardHeader>
            <CardTitle className="text-base">当前模型</CardTitle>
            <CardDescription>仅显示已配置 API Key 的供应商</CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="space-y-1.5">
              <Label>供应商</Label>
              <Select value={selProvider} onValueChange={setSelProvider}>
                <SelectTrigger>
                  <SelectValue placeholder="选择供应商" />
                </SelectTrigger>
                <SelectContent>
                  {configured.map((p) => (
                    <SelectItem key={p.name} value={p.name}>
                      {p.display_name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-1.5">
              <Label>模型</Label>
              <Select value={selModel} onValueChange={setSelModel}>
                <SelectTrigger>
                  <SelectValue placeholder="选择模型" />
                </SelectTrigger>
                <SelectContent>
                  {modelOptions.map((m) => (
                    <SelectItem key={m} value={m}>
                      {m}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <Button size="sm" onClick={onSwitch}>
              切换模型
            </Button>
          </CardContent>
        </Card>

        {/* 采样参数 */}
        <Card>
          <CardHeader>
            <CardTitle className="text-base">采样参数</CardTitle>
            <CardDescription>影响生成随机性与多样性</CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="space-y-1.5">
              <Label>Temperature：{temp}</Label>
              <Input
                type="range"
                min={0}
                max={2}
                step={0.1}
                value={temp}
                onChange={(e) => setTemp(parseFloat(e.target.value))}
              />
            </div>
            <div className="space-y-1.5">
              <Label>Top P：{topP}</Label>
              <Input
                type="range"
                min={0}
                max={1}
                step={0.05}
                value={topP}
                onChange={(e) => setTopP(parseFloat(e.target.value))}
              />
            </div>
            <Button size="sm" onClick={onSaveParams}>
              {paramsSaved ? <IconCheck className="mr-1 size-4" /> : <IconDeviceFloppy className="mr-1 size-4" />}
              保存参数
            </Button>
          </CardContent>
        </Card>
      </div>

      {/* 系统提示词 */}
      <Card>
        <CardHeader className="flex-row items-center justify-between gap-3 space-y-0">
          <div>
            <CardTitle className="text-base">系统提示词</CardTitle>
            <CardDescription>LUMU 的本体身份与行为准则（{sp.length} 字）</CardDescription>
          </div>
          <Button size="sm" onClick={onSaveSP}>
            {spSaved ? <IconCheck className="mr-1 size-4" /> : <IconDeviceFloppy className="mr-1 size-4" />}
            保存
          </Button>
        </CardHeader>
        <CardContent>
          <textarea
            value={sp}
            onChange={(e) => setSp(e.target.value)}
            className="h-48 w-full resize-none rounded-md border border-border bg-transparent p-3 text-sm outline-none focus:border-[#7fdcff]/50"
          />
        </CardContent>
      </Card>

      {/* 供应商密钥 */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">供应商 API Key</CardTitle>
          <CardDescription>密钥以掩码显示，输入新值后点击更新</CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          {providers.map((p) => (
            <div key={p.name} className="flex flex-wrap items-center gap-2">
              <span className="w-36 text-sm font-medium">{p.display_name}</span>
              <Badge variant="outline" className="font-mono text-xs">
                <IconKey className="mr-1 size-3" />
                {p.api_key_configured ? p.api_key : "未配置"}
              </Badge>
              <Input
                placeholder="输入新的 API Key"
                value={keys[p.name] || ""}
                onChange={(e) => setKeys((s) => ({ ...s, [p.name]: e.target.value }))}
                className="max-w-xs"
              />
              <Button size="sm" variant="outline" onClick={() => onSetKey(p.name)} disabled={!keys[p.name]}>
                更新
              </Button>
            </div>
          ))}
        </CardContent>
      </Card>

      {/* 语音配置 */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">语音合成 / 识别</CardTitle>
          <CardDescription>当前状态</CardDescription>
        </CardHeader>
        <CardContent className="flex flex-wrap gap-3">
          <Badge variant="secondary">TTS：{cfg?.tts.default_provider}</Badge>
          <Badge variant="secondary">STT：{cfg?.stt.default_provider}</Badge>
        </CardContent>
      </Card>

      {/* 渠道接入（个人市场切入点） */}
      <div className="space-y-3">
        <div className="flex items-center gap-2">
          <IconBroadcast className="size-4 text-[#7fdcff]" />
          <h2 className="font-display text-lg font-semibold tracking-tight">渠道接入</h2>
        </div>
        <p className="text-sm text-muted-foreground">
          把 LUMU 接进你常用的聊天工具，随时随地用自然语言使唤它。填好凭据后点「保存并启用」，服务会热重载，无需重启。
        </p>

        <div className="grid gap-4 lg:grid-cols-2">
          {channels.map((ch) => {
            const Icon = channelIcon[ch.key] || IconBroadcast
            return (
              <Card key={ch.key}>
                <CardHeader className="flex-row items-start justify-between gap-3 space-y-0">
                  <div className="flex items-center gap-3">
                    <div className="flex size-9 items-center justify-center rounded-lg border border-border bg-white/5">
                      <Icon className="size-5 text-[#7fdcff]" />
                    </div>
                    <div>
                      <CardTitle className="text-base">{ch.name}</CardTitle>
                      <CardDescription className="mt-0.5 max-w-[260px]">
                        {ch.desc}
                      </CardDescription>
                    </div>
                  </div>
                  {ch.enabled ? (
                    <Badge className="border-[#34d399]/40 bg-[#34d399]/10 text-[#34d399]">
                      已连接
                    </Badge>
                  ) : (
                    <Badge variant="outline" className="text-muted-foreground">
                      未启用
                    </Badge>
                  )}
                </CardHeader>
                <CardContent className="space-y-3">
                  {ch.fields.map((f) => (
                    <div key={f.key} className="space-y-1">
                      <div className="flex items-center gap-2">
                        <Label className="text-xs">{f.label}</Label>
                        {f.secret && f.set && (
                          <Badge variant="secondary" className="text-[10px] text-[#34d399]">
                            已配置
                          </Badge>
                        )}
                      </div>
                      <Input
                        type={f.secret ? "password" : "text"}
                        value={drafts[ch.key]?.[f.key] ?? ""}
                        onChange={(e) => setField(ch.key, f.key, e.target.value)}
                        placeholder={
                          f.secret && f.set ? "已配置，留空则不修改" : f.label
                        }
                        autoComplete="off"
                      />
                    </div>
                  ))}
                  <p className="text-[11px] leading-relaxed text-muted-foreground/70">
                    {ch.doc}
                  </p>
                  <div className="flex justify-end">
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={() => onSaveChannel(ch)}
                      disabled={chSaving === ch.key}
                    >
                      {chSaving === ch.key ? "保存中…" : "保存并启用"}
                    </Button>
                  </div>
                </CardContent>
              </Card>
            )
          })}
        </div>
      </div>
    </div>
  )
}
