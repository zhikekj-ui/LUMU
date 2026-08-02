"use client"

import * as React from "react"
import {
  IconMoodSmile,
  IconStar,
  IconSend,
} from "@tabler/icons-react"
import { toast } from "sonner"

import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import {
  submitFeedback,
  type FeedbackCategory,
} from "@/lib/lumu"

const CATS: { key: FeedbackCategory; label: string }[] = [
  { key: "suggest", label: "建议" },
  { key: "bug", label: "问题/Bug" },
  { key: "praise", label: "好评" },
  { key: "question", label: "咨询" },
]

export function FeedbackView() {
  const [category, setCategory] = React.useState<FeedbackCategory>("suggest")
  const [rating, setRating] = React.useState(0)
  const [content, setContent] = React.useState("")
  const [feature, setFeature] = React.useState("")
  const [contact, setContact] = React.useState("")
  const [submitting, setSubmitting] = React.useState(false)

  const onSubmit = async () => {
    const text = content.trim()
    if (!text) {
      toast.error("请先填写反馈内容")
      return
    }
    setSubmitting(true)
    try {
      await submitFeedback({
        category,
        rating,
        content: text,
        feature: feature.trim() || undefined,
        page: "webui/feedback",
        contact: contact.trim() || undefined,
      })
      toast.success("感谢反馈，我们已收到！")
      setContent("")
      setRating(0)
      setFeature("")
      setContact("")
    } catch (e: any) {
      toast.error(e?.message || "提交失败，请稍后重试")
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="flex flex-1 flex-col gap-6 p-4 md:p-6">
      {/* 页头 */}
      <div className="flex items-start gap-3">
        <div className="flex size-10 items-center justify-center rounded-lg border border-border bg-white/5">
          <IconMoodSmile className="size-5 text-[#7fdcff]" />
        </div>
        <div>
          <h1 className="text-xl font-semibold tracking-tight">用户反馈</h1>
          <p className="text-sm text-muted-foreground">
            你的每条反馈都会进入产品迭代闭环——这是 LUMU 先服务个人、再用真实需求打磨 B 端能力的起点。
          </p>
        </div>
      </div>

      {/* 提交反馈 */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">提交反馈</CardTitle>
          <CardDescription>无论是吐槽、建议还是想提的需求，都欢迎告诉我们。</CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-4">
          {/* 类型选择 */}
          <div className="flex flex-wrap gap-2">
            {CATS.map((c) => (
              <button
                key={c.key}
                type="button"
                onClick={() => setCategory(c.key)}
                className={
                  "rounded-full border px-3 py-1 text-sm transition-colors " +
                  (category === c.key
                    ? "border-[#7fdcff] bg-[#7fdcff]/10 text-[#7fdcff]"
                    : "border-border text-muted-foreground hover:bg-white/5")
                }
              >
                {c.label}
              </button>
            ))}
          </div>

          {/* 评分 */}
          <div className="flex items-center gap-2">
            <span className="text-sm text-muted-foreground">满意度</span>
            <div className="flex gap-1">
              {[1, 2, 3, 4, 5].map((n) => (
                <button
                  key={n}
                  type="button"
                  onClick={() => setRating(n)}
                  aria-label={`${n} 星`}
                >
                  <IconStar
                    className={
                      "size-5 transition-colors " +
                      (n <= rating
                        ? "fill-[#ffb454] text-[#ffb454]"
                        : "text-muted-foreground/40 hover:text-[#ffb454]/60")
                    }
                  />
                </button>
              ))}
            </div>
            {rating > 0 && (
              <span className="text-xs text-[#ffb454]">{rating} / 5</span>
            )}
          </div>

          {/* 内容 */}
          <textarea
            value={content}
            onChange={(e) => setContent(e.target.value)}
            rows={4}
            maxLength={2000}
            placeholder="说说你的想法…（必填）"
            className="w-full resize-y rounded-md border border-border bg-white/5 px-3 py-2 text-sm text-foreground outline-none placeholder:text-muted-foreground/50 focus:border-[#7fdcff]/50"
          />

          {/* 可选字段 */}
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <input
              value={feature}
              onChange={(e) => setFeature(e.target.value)}
              placeholder="相关功能（可选）"
              className="rounded-md border border-border bg-white/5 px-3 py-2 text-sm text-foreground outline-none placeholder:text-muted-foreground/50 focus:border-[#7fdcff]/50"
            />
            <input
              value={contact}
              onChange={(e) => setContact(e.target.value)}
              placeholder="联系方式（可选，便于回访）"
              className="rounded-md border border-border bg-white/5 px-3 py-2 text-sm text-foreground outline-none placeholder:text-muted-foreground/50 focus:border-[#7fdcff]/50"
            />
          </div>

          <div className="flex justify-end">
            <Button size="sm" onClick={onSubmit} disabled={submitting}>
              <IconSend className="size-4" />
              {submitting ? "提交中…" : "提交反馈"}
            </Button>
          </div>
        </CardContent>
      </Card>
    </div>
  )
}
