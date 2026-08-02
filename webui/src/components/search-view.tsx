"use client"

import * as React from "react"
import {
  IconSearch,
  IconBrain,
  IconMessageCircle,
  IconStack,
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
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { Skeleton } from "@/components/ui/skeleton"
import {
  fetchMemorySearch,
  fetchSessions,
  fetchSkillsSearch,
  type MemoryHit,
  type SessionHit,
} from "@/lib/lumu"

export function SearchView() {
  const [q, setQ] = React.useState("")
  const [run, setRun] = React.useState("")
  const [mem, setMem] = React.useState<MemoryHit[]>([])
  const [sess, setSess] = React.useState<SessionHit[]>([])
  const [skills, setSkills] = React.useState<any[]>([])
  const [loading, setLoading] = React.useState(false)
  const [err, setErr] = React.useState<string | null>(null)

  const doSearch = React.useCallback(async () => {
    const query = q.trim()
    if (!query) return
    setRun(query)
    setLoading(true)
    setErr(null)
    try {
      // 各来源独立容错：单源失败不影响其余结果展示
      const [m, s, sk] = await Promise.all([
        fetchMemorySearch(query, 20).catch(() => []),
        fetchSessions("work").catch(() => []),
        fetchSkillsSearch(query).catch(() => []),
      ])
      // 会话按预览命中过滤
      const hitSess = s.filter(
        (x) => x.preview?.toLowerCase().includes(query.toLowerCase())
      )
      setMem(m)
      setSess(hitSess)
      setSkills(sk)
    } catch (e: any) {
      setErr(String(e?.message || e))
    } finally {
      setLoading(false)
    }
  }, [q])

  return (
    <div className="space-y-5 p-4 md:p-6">
      <div>
        <h1 className="font-display text-2xl font-semibold tracking-tight">搜索</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          跨记忆、历史会话与技能统一检索。输入关键词即时查找 LUMU 掌握的一切。
        </p>
      </div>

      <div className="flex gap-2">
        <Input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="搜索关键词，如：模型、前端、用户偏好…"
          onKeyDown={(e) => e.key === "Enter" && doSearch()}
          className="max-w-xl"
        />
        <Button onClick={doSearch} disabled={loading || !q.trim()}>
          <IconSearch className="size-4" /> 搜索
        </Button>
      </div>

      {!run ? (
        <p className="py-16 text-center text-sm text-muted-foreground">输入关键词开始检索</p>
      ) : loading ? (
        <div className="space-y-2">
          {[0, 1, 2].map((i) => (
            <Skeleton key={i} className="h-12 w-full" />
          ))}
        </div>
      ) : err ? (
        <p className="text-sm text-red-400">检索失败：{err}</p>
      ) : (
        <Tabs defaultValue="memory">
          <TabsList>
            <TabsTrigger value="memory">
              <IconBrain className="mr-1 size-4" /> 记忆 {mem.length}
            </TabsTrigger>
            <TabsTrigger value="session">
              <IconMessageCircle className="mr-1 size-4" /> 会话 {sess.length}
            </TabsTrigger>
            <TabsTrigger value="skill">
              <IconStack className="mr-1 size-4" /> 技能 {skills.length}
            </TabsTrigger>
          </TabsList>

          <TabsContent value="memory">
            <Card>
              <CardHeader>
                <CardTitle className="text-base">记忆命中</CardTitle>
                <CardDescription>来自长期记忆库（关键词：{run}）</CardDescription>
              </CardHeader>
              <CardContent className="space-y-2">
                {mem.length === 0 && <Empty />}
                {mem.map((m, i) => (
                  <div key={i} className="rounded-md border border-border bg-white/5 p-3">
                    <div className="mb-1 flex items-center gap-2">
                      <Badge variant="secondary">{m.category}</Badge>
                      <span className="font-mono text-xs text-muted-foreground">{m.key}</span>
                    </div>
                    <p className="text-sm text-foreground/90">{m.content}</p>
                  </div>
                ))}
              </CardContent>
            </Card>
          </TabsContent>

          <TabsContent value="session">
            <Card>
              <CardHeader>
                <CardTitle className="text-base">历史会话命中</CardTitle>
                <CardDescription>预览中包含关键词的会话</CardDescription>
              </CardHeader>
              <CardContent className="space-y-2">
                {sess.length === 0 && <Empty />}
                {sess.map((s) => (
                  <div key={s.id} className="rounded-md border border-border bg-white/5 p-3">
                    <div className="mb-1 flex items-center justify-between">
                      <span className="font-mono text-xs text-muted-foreground">{s.id}</span>
                      <Badge variant="outline">{s.message_count} 条消息</Badge>
                    </div>
                    <p className="line-clamp-2 text-sm text-foreground/90">{s.preview}</p>
                  </div>
                ))}
              </CardContent>
            </Card>
          </TabsContent>

          <TabsContent value="skill">
            <Card>
              <CardHeader>
                <CardTitle className="text-base">技能命中</CardTitle>
                <CardDescription>名称 / 描述匹配的技能</CardDescription>
              </CardHeader>
              <CardContent className="space-y-2">
                {skills.length === 0 && <Empty />}
                {skills.map((s, i) => (
                  <div key={i} className="rounded-md border border-border bg-white/5 p-3">
                    <div className="mb-1 font-medium">{s.name || s.skill_name || "未命名技能"}</div>
                    <p className="text-sm text-foreground/80">{s.description || ""}</p>
                  </div>
                ))}
              </CardContent>
            </Card>
          </TabsContent>
        </Tabs>
      )}
    </div>
  )
}

function Empty() {
  return <p className="py-8 text-center text-sm text-muted-foreground">无匹配结果</p>
}
