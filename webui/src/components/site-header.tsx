import * as React from "react"
import { Button } from "@/components/ui/button"
import { Separator } from "@/components/ui/separator"
import { SidebarTrigger } from "@/components/ui/sidebar"
import { IconChevronDown, IconCheck } from "@tabler/icons-react"

type ProviderInfo = {
  name: string
  display_name: string
  enabled_models: string[]
}
type CurrentModel = { provider: string; model: string }

export function SiteHeader() {
  const [providers, setProviders] = React.useState<ProviderInfo[]>([])
  const [allProviders, setAllProviders] = React.useState<ProviderInfo[]>([])
  const [current, setCurrent] = React.useState<CurrentModel | null>(null)
  const [open, setOpen] = React.useState(false)
  const [switching, setSwitching] = React.useState(false)
  const wrapRef = React.useRef<HTMLDivElement>(null)

  // 点击外部关闭下拉
  React.useEffect(() => {
    function onDoc(e: MouseEvent) {
      if (wrapRef.current && !wrapRef.current.contains(e.target as Node)) {
        setOpen(false)
      }
    }
    document.addEventListener("mousedown", onDoc)
    return () => document.removeEventListener("mousedown", onDoc)
  }, [])

  const displayName = React.useCallback(
    (name: string) => {
      // 规范化内部计划/备用模式名（如 stepfun_plan → stepfun），如实显示厂商
      const base = name.replace(/_(plan|fallback|backup|备用)$/i, "")
      return allProviders.find((p) => p.name === base)?.display_name ?? name
    },
    [allProviders]
  )

  React.useEffect(() => {
    let alive = true
    Promise.all([
      fetch("/api/config/providers").then((r) => (r.ok ? r.json() : null)),
      fetch("/health").then((r) => (r.ok ? r.json() : null)),
    ])
      .then(([cfg, health]) => {
        if (!alive) return
        if (cfg?.providers) {
          setAllProviders(cfg.providers)
          setProviders(
            cfg.providers.filter(
              (p: ProviderInfo) =>
                Array.isArray(p.enabled_models) && p.enabled_models.length > 0
            )
          )
        }
        if (health?.provider) {
          setCurrent({ provider: health.provider, model: health.model })
        }
      })
      .catch(() => {})
    return () => {
      alive = false
    }
  }, [])

  async function switchTo(provider: string, model: string) {
    if (switching) return
    setSwitching(true)
    try {
      const res = await fetch("/api/config/model", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ provider, model }),
      })
      if (res.ok) {
        const h = await fetch("/health").then((r) => (r.ok ? r.json() : null))
        if (h?.provider) setCurrent({ provider: h.provider, model: h.model })
        else setCurrent({ provider, model })
      }
    } catch {
      /* 忽略网络异常 */
    } finally {
      setSwitching(false)
      setOpen(false)
    }
  }

  const currentLabel = current
    ? `${displayName(current.provider)} / ${current.model}`
    : "已配置的模型"

  return (
    <header className="flex h-(--header-height) shrink-0 items-center gap-2 transition-[width,height] ease-linear group-has-data-[collapsible=icon]/sidebar-wrapper:h-(--header-height)">
      <div className="flex w-full items-center gap-1 px-4 lg:gap-2 lg:px-6">
        <SidebarTrigger className="-ml-1" />
        <Separator
          orientation="vertical"
          className="mx-2 data-[orientation=vertical]:h-4"
        />
        {/* 模型切换下拉：使用相对定位，避免被 SidebarInset 的 transform 干扰 fixed 定位 */}
        <div className="relative" ref={wrapRef}>
          <Button
            variant="ghost"
            size="sm"
            className="h-8 gap-1 px-2 font-medium"
            onClick={() => setOpen((o) => !o)}
            disabled={switching}
            aria-haspopup="menu"
            aria-expanded={open}
          >
            <span>{currentLabel}</span>
            <IconChevronDown
              className={
                "size-4 opacity-60 transition-transform " +
                (open ? "rotate-180" : "")
              }
            />
          </Button>
          {open && (
            <div className="absolute left-0 top-full z-50 mt-1.5 w-64 rounded-lg border border-[rgba(127,220,255,0.16)] bg-[var(--panel2)] p-1.5 text-[var(--text)] shadow-2xl shadow-black/50">
              <div className="px-2 py-1.5 text-xs font-medium text-[var(--dim)]">
                已配置的模型
              </div>
              <div className="my-1 h-px bg-[rgba(127,220,255,0.14)]" />
              {providers.length === 0 && (
                <div className="px-2 py-1.5 text-sm text-muted-foreground">
                  暂无已启用模型
                </div>
              )}
              {providers.map((p, pi) => (
                <div key={p.name}>
                  {pi > 0 && (
                    <div className="my-1 h-px bg-[rgba(127,220,255,0.12)]" />
                  )}
                  <div className="px-2 pb-1 pt-1.5 text-[11px] font-semibold tracking-wide text-[var(--cyan)]">
                    {p.display_name}
                  </div>
                  {p.enabled_models.map((m) => {
                    const isCurrent =
                      current?.provider === p.name && current?.model === m
                    return (
                      <button
                        key={`${p.name}/${m}`}
                        type="button"
                        onClick={() => switchTo(p.name, m)}
                        className={
                          "flex w-full items-center justify-between rounded px-2 py-1.5 text-left text-sm transition-colors hover:bg-[rgba(255,255,255,0.06)] " +
                          (isCurrent
                            ? "text-[var(--amber)]"
                            : "text-[var(--text)]")
                        }
                      >
                        <span>{m}</span>
                        {isCurrent && (
                          <IconCheck className="size-4 text-[var(--amber)]" />
                        )}
                      </button>
                    )
                  })}
                </div>
              ))}
            </div>
          )}
        </div>
        <div className="ml-auto flex items-center gap-2">
          <Button variant="ghost" asChild size="sm" className="hidden sm:flex">
            <a
              href="https://lumux.cn"
              rel="noopener noreferrer"
              target="_blank"
              className="dark:text-foreground"
            >
              官网
            </a>
          </Button>
        </div>
      </div>
    </header>
  )
}
