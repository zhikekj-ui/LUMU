"use client"

import * as React from "react"
import {
  IconUpload,
  IconTrash,
  IconRefresh,
  IconBrain,
  IconTags,
  IconLink,
} from "@tabler/icons-react"
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
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { Skeleton } from "@/components/ui/skeleton"
import {
  fetchKB,
  fetchKBStats,
  fetchKBGraph,
  uploadKBDoc,
  deleteKBDoc,
  type KBDocument,
  type KBStats,
  type KBGraphNode,
} from "@/lib/lumu"

const CAT_COLORS: Record<string, string> = {}
const PALETTE = ["#7fdcff", "#ffb454", "#a78bfa", "#34d399", "#f472b6", "#60a5fa"]
function catColor(cat: string) {
  if (!CAT_COLORS[cat]) CAT_COLORS[cat] = PALETTE[Object.keys(CAT_COLORS).length % PALETTE.length]
  return CAT_COLORS[cat]
}

export function KnowledgeView() {
  const [docs, setDocs] = React.useState<KBDocument[]>([])
  const [stats, setStats] = React.useState<KBStats | null>(null)
  const [cats, setCats] = React.useState<{ category: string; count: number }[]>([])
  const [graph, setGraph] = React.useState<KBGraphNode[]>([])
  const [loading, setLoading] = React.useState(true)
  const [err, setErr] = React.useState<string | null>(null)
  const [q, setQ] = React.useState("")
  const [pendingDel, setPendingDel] = React.useState<string | null>(null)
  const [uploading, setUploading] = React.useState(false)
  const [msg, setMsg] = React.useState<string | null>(null)
  const [showGraph, setShowGraph] = React.useState(false)
  const fileRef = React.useRef<HTMLInputElement>(null)

  const load = React.useCallback(async () => {
    setLoading(true)
    setErr(null)
    try {
      const [kb, st, g] = await Promise.all([
        fetchKB("work"),
        fetchKBStats("work"),
        fetchKBGraph("work").catch(() => ({ nodes: [] })),
      ])
      setDocs(kb.documents)
      setStats(st.stats)
      setCats(st.categories)
      setGraph(g.nodes || [])
    } catch (e: any) {
      setErr(String(e?.message || e))
    } finally {
      setLoading(false)
    }
  }, [])

  React.useEffect(() => {
    load()
  }, [load])

  const onUpload = async (file: File) => {
    setUploading(true)
    setMsg(null)
    try {
      await uploadKBDoc("work", file)
      setMsg(`已存入资料库：${file.name}`)
      await load()
    } catch (e: any) {
      setMsg("上传失败：" + String(e?.message || e))
    } finally {
      setUploading(false)
    }
  }

  const onDelete = async (id: string) => {
    try {
      await deleteKBDoc(id)
      setPendingDel(null)
      await load()
    } catch (e: any) {
      setMsg("删除失败：" + String(e?.message || e))
    }
  }

  const filtered = q
    ? docs.filter(
        (d) =>
          d.title.toLowerCase().includes(q.toLowerCase()) ||
          (d.tags || "").toLowerCase().includes(q.toLowerCase()) ||
          (d.category || "").toLowerCase().includes(q.toLowerCase())
      )
    : docs

  // 图谱投影
  const W = 640,
    H = 360
  const xs = graph.map((n) => n.x)
  const ys = graph.map((n) => n.y)
  const minX = Math.min(...xs, -1),
    maxX = Math.max(...xs, 1)
  const minY = Math.min(...ys, -1),
    maxY = Math.max(...ys, 1)
  const px = (x: number) => 40 + ((x - minX) / (maxX - minX || 1)) * (W - 80)
  const py = (y: number) => 40 + ((y - minY) / (maxY - minY || 1)) * (H - 80)

  return (
    <div className="space-y-5 p-4 md:p-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="font-display text-2xl font-semibold tracking-tight">资料库</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            LUMU 长期知识库 —— 跨会话沉淀的策略、经验与事实，由 agent 自动学习并检索。
          </p>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" size="sm" onClick={load} disabled={loading}>
            <IconRefresh className="size-4" /> 刷新
          </Button>
          <Button size="sm" onClick={() => fileRef.current?.click()} disabled={uploading}>
            <IconUpload className="size-4" /> {uploading ? "上传中…" : "存入文档"}
          </Button>
          <input
            ref={fileRef}
            type="file"
            className="hidden"
            onChange={(e) => {
              const f = e.target.files?.[0]
              if (f) onUpload(f)
              e.target.value = ""
            }}
          />
        </div>
      </div>

      {msg && (
        <div className="rounded-md border border-border bg-white/5 px-3 py-2 text-sm text-foreground/90">
          {msg}
        </div>
      )}

      {/* 概览指标 */}
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <StatTile icon={IconBrain} label="知识条目" value={stats?.total_entries ?? "—"} />
        <StatTile icon={IconTags} label="分类数" value={stats?.categories ?? "—"} />
        <StatTile icon={IconLink} label="有来源" value={stats?.entries_with_source ?? "—"} />
        <StatTile icon={IconBrain} label="本次载入" value={docs.length} />
      </div>

      {/* 分类分布 */}
      {cats.length > 0 && (
        <div className="flex flex-wrap gap-2">
          {cats.map((c) => (
            <Badge
              key={c.category}
              variant="outline"
              className="border-border bg-white/5 px-3 py-1"
              style={{ color: catColor(c.category) }}
            >
              {c.category} · {c.count}
            </Badge>
          ))}
        </div>
      )}

      <Card>
        <CardHeader className="flex-row items-center justify-between gap-3 space-y-0">
          <div>
            <CardTitle className="text-base">知识条目</CardTitle>
            <CardDescription>共 {docs.length} 条（按标题 / 标签 / 分类筛选）</CardDescription>
          </div>
          <Input
            placeholder="搜索标题 / 标签 / 分类…"
            value={q}
            onChange={(e) => setQ(e.target.value)}
            className="max-w-xs"
          />
        </CardHeader>
        <CardContent>
          {loading ? (
            <div className="space-y-2">
              {[0, 1, 2, 3].map((i) => (
                <Skeleton key={i} className="h-10 w-full" />
              ))}
            </div>
          ) : filtered.length === 0 ? (
            <p className="py-8 text-center text-sm text-muted-foreground">
              {err ? "加载失败：" + err : "暂无知识条目"}
            </p>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>标题</TableHead>
                  <TableHead className="w-28">分类</TableHead>
                  <TableHead className="w-44">标签</TableHead>
                  <TableHead className="w-36">来源</TableHead>
                  <TableHead className="w-32">更新时间</TableHead>
                  <TableHead className="w-20 text-right">操作</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {filtered.slice(0, 60).map((d) => (
                  <TableRow key={d.id}>
                    <TableCell className="font-medium">{d.title}</TableCell>
                    <TableCell>
                      <Badge variant="secondary" style={{ color: catColor(d.category) }}>
                        {d.category}
                      </Badge>
                    </TableCell>
                    <TableCell className="max-w-[180px] truncate text-xs text-muted-foreground" title={d.tags}>
                      {d.tags || "—"}
                    </TableCell>
                    <TableCell className="text-xs text-muted-foreground">{d.source}</TableCell>
                    <TableCell className="text-xs text-muted-foreground">{d.updated_at}</TableCell>
                    <TableCell className="text-right">
                      {pendingDel === d.id ? (
                        <span className="inline-flex gap-1">
                          <Button size="xs" variant="destructive" onClick={() => onDelete(d.id)}>
                            确认
                          </Button>
                          <Button size="xs" variant="ghost" onClick={() => setPendingDel(null)}>
                            取消
                          </Button>
                        </span>
                      ) : (
                        <Button
                          size="icon"
                          variant="ghost"
                          className="size-7"
                          title="删除"
                          onClick={() => setPendingDel(d.id)}
                        >
                          <IconTrash className="size-4 text-muted-foreground hover:text-red-400" />
                        </Button>
                      )}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      {/* 知识图谱 */}
      <Card>
        <CardHeader className="flex-row items-center justify-between gap-3 space-y-0">
          <div>
            <CardTitle className="text-base">关系图谱</CardTitle>
            <CardDescription>基于向量坐标的真实知识节点分布（{graph.length} 个节点）</CardDescription>
          </div>
          <Button variant="outline" size="sm" onClick={() => setShowGraph((s) => !s)}>
            {showGraph ? "收起" : "展开"}
          </Button>
        </CardHeader>
        {showGraph && graph.length > 0 && (
          <CardContent>
            <svg viewBox={`0 0 ${W} ${H}`} className="w-full rounded-md bg-white/[0.02]">
              {graph.slice(0, 120).map((n) => (
                <g key={n.id}>
                  <circle
                    cx={px(n.x)}
                    cy={py(n.y)}
                    r={3 + Math.min(8, n.importance * 3)}
                    fill={catColor(n.category)}
                    fillOpacity={0.55}
                    stroke={catColor(n.category)}
                  />
                  <text
                    x={px(n.x)}
                    y={py(n.y) - 8}
                    fontSize={9}
                    fill="currentColor"
                    className="fill-foreground/60"
                    textAnchor="middle"
                  >
                    {n.label.length > 12 ? n.label.slice(0, 12) + "…" : n.label}
                  </text>
                </g>
              ))}
            </svg>
          </CardContent>
        )}
      </Card>
    </div>
  )
}

function StatTile({
  icon: Icon,
  label,
  value,
}: {
  icon: React.ComponentType<{ className?: string }>
  label: string
  value: React.ReactNode
}) {
  return (
    <Card>
      <CardContent className="flex items-center gap-3 p-4">
        <div className="flex size-10 items-center justify-center rounded-lg bg-white/10 text-[#7fdcff]">
          <Icon className="size-5" />
        </div>
        <div>
          <div className="text-xl font-semibold leading-none">{value}</div>
          <div className="mt-1 text-xs text-muted-foreground">{label}</div>
        </div>
      </CardContent>
    </Card>
  )
}
