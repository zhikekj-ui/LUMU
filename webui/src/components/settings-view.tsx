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
  setProviderBaseUrl,
  fetchChannelsConfig,
  saveChannelsConfig,
  fetchAccess,
  setAccess,
  type AppConfig,
  type Provider,
  type ChannelDef,
  type AccessState,
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
  const [baseUrls, setBaseUrls] = React.useState<Record<string, string>>({})
  const [baseUrlMsg, setBaseUrlMsg] = React.useState<string | null>(null)
  const [keyMsg, setKeyMsg] = React.useState<string | null>(null)

  // 渠道接入
  const [channels, setChannels] = React.useState<ChannelDef[]>([])
  const [drafts, setDrafts] = React.useState<Record<string, Record<string, string>>>({})
  const [chSaving, setChSaving] = React.useState<string | null>(null)

  // 访问与分享（小白开关：本机 / 对外分享）
  const [access, setAccessState] = React.useState<AccessState | null>(null)
  const [accessLoading, setAccessLoading] = React.useState(true)
  const [accessBusy, setAccessBusy] = React.useState(false)

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
      setSelProvider(c.model_preference?.provider ?? "")
      setSelModel(c.model_preference?.model ?? "")
      setBaseUrls(Object.fromEntries(p.providers.map((x: any) => [x.name, x.active_base_url || ""])))
      setChannels(ch.channels)
    } finally {
      setLoading(false)
    }
  }, [])

  // 访问与分享：读取当前模式（定义在 useEffect 之前，避免 TDZ 崩溃）
  const loadAccess = React.useCallback(async () => {
    setAccessLoading(true)
    try {
      setAccessState(await fetchAccess())
    } catch (e: any) {
      toast.error("读取访问设置失败：" + String(e?.message || e))
    } finally {
      setAccessLoading(false)
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

  React.useEffect(() => {
    loadAccess()
  }, [loadAccess])

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
      await load() // 刷新配置，模型区立即出现该供应商，无需手动刷新页面
      setSelProvider((prev) => prev || name) // 若还没选中供应商，自动选中刚配好的这家
    } catch (e: any) {
      setKeyMsg("更新失败：" + String(e?.message || e))
    }
  }

  // 自定义 Base URL（OpenAI 兼容）：例如把 openai 供应商指向中转/自建网关
  const onSetBaseUrl = async (name: string) => {
    const v = (baseUrls[name] ?? "").trim()
    try {
      await setProviderBaseUrl(name, v)
      setBaseUrlMsg(
        v ? "已更新 " + name + " 的 Base URL：" + v : "已清除 " + name + " 的自定义 Base URL（恢复默认）"
      )
      setTimeout(() => setBaseUrlMsg(null), 2500)
      await load()
    } catch (e: any) {
      setBaseUrlMsg("更新失败：" + String(e?.message || e))
    }
  }

  // 访问与分享：读取 + 切换模式 + 复制 + 重新生成口令
  const accessMode = access?.mode ?? "local"
  const copyLink = async () => {
    const link = access?.share_link || ""
    try {
      await navigator.clipboard.writeText(link)
      toast.success("分享链接已复制")
    } catch {
      toast.error("复制失败，请手动选择链接复制")
    }
  }
  const onAccess = async (action: "enable" | "rotate" | "disable") => {
    setAccessBusy(true)
    try {
      if (action === "rotate") {
        const r = await setAccess("rotate")
        setAccessState((s) => (s ? { ...s, share_link: r.share_link ?? s.share_link } : s))
        toast.success("已重新生成口令，旧链接已失效")
      } else {
        await setAccess(action)
        await loadAccess()
        toast.success(action === "enable" ? "已开启对外分享，链接已生成" : "已切回仅本机")
      }
    } catch (e: any) {
      toast.error(String(e?.message || e))
    } finally {
      setAccessBusy(false)
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
            {configured.length === 0 && (
              <p className="rounded-md border border-dashed border-border bg-white/5 px-3 py-2 text-sm text-muted-foreground">
                还没有配置任何供应商密钥。先在下方的「供应商 API Key」填入一个密钥并保存，这里就能选择模型了。
              </p>
            )}
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
            <div key={p.name} className="rounded-lg border border-border bg-white/[0.03] p-3 space-y-2.5">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <span className="text-sm font-medium">{p.display_name}</span>
                <Badge
                  variant="outline"
                  className={
                    "font-mono text-xs " +
                    (p.api_key_configured ? "border-emerald-500/40 text-emerald-300" : "")
                  }
                >
                  <IconKey className="mr-1 size-3" />
                  {p.api_key_configured ? (p.api_key_preview || "已配置") : "未配置"}
                </Badge>
              </div>
              <div className="flex flex-wrap items-center gap-2">
                <Input
                  placeholder="输入新的 API Key"
                  value={keys[p.name] || ""}
                  onChange={(e) => setKeys((s) => ({ ...s, [p.name]: e.target.value }))}
                  className="max-w-xs flex-1"
                />
                <Button size="sm" variant="outline" onClick={() => onSetKey(p.name)} disabled={!keys[p.name]}>
                  更新
                </Button>
              </div>
              <div className="flex flex-wrap items-center gap-2">
                <Input
                  placeholder="Base URL（OpenAI 兼容，留空用默认）"
                  value={baseUrls[p.name] ?? ""}
                  onChange={(e) => setBaseUrls((s) => ({ ...s, [p.name]: e.target.value }))}
                  className="max-w-md flex-1 font-mono text-xs"
                />
                <Button size="sm" variant="outline" onClick={() => onSetBaseUrl(p.name)}>
                  保存地址
                </Button>
              </div>
              {p.active_base_url && (
                <p className="text-[11px] leading-relaxed text-muted-foreground/70">
                  当前生效地址：{p.active_base_url}
                </p>
              )}
            </div>
          ))}
          {baseUrlMsg && (
            <div className="rounded-md border border-border bg-white/5 px-3 py-2 text-sm text-foreground/90">
              {baseUrlMsg}
            </div>
          )}
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

      {/* 访问与分享（小白开关：本机 / 对外分享） */}
      <div className="space-y-3">
        <div className="flex items-center gap-2">
          <IconBroadcast className="size-4 text-[#7fdcff]" />
          <h2 className="font-display text-lg font-semibold tracking-tight">访问与分享</h2>
        </div>
        <p className="text-sm text-muted-foreground">
          决定谁能打开这个 LUMU 实例。默认仅本机、免口令；想分享给别人时打开「对外分享」，系统会自动生成一条带口令的链接，复制发给他即可，无需任何配置。
        </p>
        <Card>
          <CardContent className="space-y-4 pt-6">
            <div className="inline-flex rounded-lg border border-border p-1">
              <button
                type="button"
                onClick={() => onAccess("disable")}
                disabled={accessBusy || !!access?.exposed}
                className={`rounded-md px-4 py-1.5 text-sm transition-colors ${
                  accessMode === "local"
                    ? "bg-[#7fdcff]/15 font-medium text-[#7fdcff]"
                    : "text-muted-foreground hover:text-foreground"
                }`}
              >
                仅本机（免口令）
              </button>
              <button
                type="button"
                onClick={() => onAccess("enable")}
                disabled={accessBusy}
                className={`rounded-md px-4 py-1.5 text-sm transition-colors ${
                  accessMode === "share"
                    ? "bg-[#7fdcff]/15 font-medium text-[#7fdcff]"
                    : "text-muted-foreground hover:text-foreground"
                }`}
              >
                对外分享（自动口令）
              </button>
            </div>

            {accessLoading ? (
              <Skeleton className="h-10 w-full" />
            ) : accessMode === "share" ? (
              <>
                <div className="flex flex-wrap items-center gap-2">
                  <Input
                    readOnly
                    value={access?.share_link || ""}
                    className="max-w-xl font-mono text-xs"
                  />
                  <Button size="sm" variant="outline" onClick={copyLink}>
                    复制链接
                  </Button>
                </div>
                <p className="text-[11px] leading-relaxed text-muted-foreground/70">
                  链接里已包含口令，发给谁、谁就能进。若担心泄露，点下面的「重新生成口令」，旧链接立刻失效。
                </p>
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => onAccess("rotate")}
                  disabled={accessBusy}
                >
                  <IconKey className="mr-1 size-4" />
                  重新生成口令
                </Button>
              </>
            ) : (
              <p className="text-sm text-muted-foreground">
                只有这台设备能打开，外人无法访问，无需口令。要把 LUMU 分享给其他人，请切到「对外分享」。
              </p>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  )
}
