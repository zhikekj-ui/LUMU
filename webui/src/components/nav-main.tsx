"use client"

import * as React from "react"
import {
  IconMessageCircle,
  IconPlus,
  IconTrash,
  IconChevronDown,
  IconDashboard,
  IconListDetails,
  IconMoodSmile,
  type Icon,
} from "@tabler/icons-react"

import { Button } from "@/components/ui/button"
import { cn } from "@/lib/utils"
import {
  SidebarGroup,
  SidebarGroupContent,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
} from "@/components/ui/sidebar"
import { useConversations } from "@/components/conversations"

export type View =
  | "chat"
  | "dashboard"
  | "lifecycle"
  | "knowledge"
  | "search"
  | "reports"
  | "settings"
  | "help"
  | "feedback"

// 通用「视图切换」侧栏按钮（供文档组 / 次级导航复用，避免重复样板）
export function NavViewButton({
  title,
  view,
  icon: IconC,
  active,
  onSelect,
}: {
  title: string
  view: View
  icon: Icon
  active: boolean
  onSelect: (v: View) => void
}) {
  return (
    <SidebarMenuItem>
      <SidebarMenuButton
        tooltip={title}
        isActive={active}
        onClick={() => onSelect(view)}
      >
        <IconC />
        <span className="font-normal">{title}</span>
      </SidebarMenuButton>
    </SidebarMenuItem>
  )
}

export function NavMain({
  view,
  onSelectView,
}: {
  view: View
  onSelectView: (v: View) => void
}) {
  const {
    conversations,
    activeId,
    createConversation,
    selectConversation,
    deleteConversation,
  } = useConversations()
  const [open, setOpen] = React.useState(false)

  const items: { title: string; view: View; icon: Icon }[] = [
    { title: "仪表盘", view: "dashboard", icon: IconDashboard },
    { title: "生命周期", view: "lifecycle", icon: IconListDetails },
  ]

  return (
    <SidebarGroup>
      <SidebarGroupContent className="flex flex-col gap-2">
        <SidebarMenu>
          <SidebarMenuItem className="flex flex-col gap-1">
            {/* 对话按钮：可折叠，展开显示对话记录 + 新对话 */}
            <SidebarMenuButton
              tooltip="对话"
              isActive={view === "chat"}
              onClick={() => {
                setOpen((o) => !o)
                onSelectView("chat")
              }}
              className={cn(
                "min-w-8 duration-200 ease-linear",
                view === "chat"
                  ? "bg-primary text-primary-foreground hover:bg-primary/90 hover:text-primary-foreground"
                  : "bg-primary text-primary-foreground hover:bg-primary/90 hover:text-primary-foreground"
              )}
            >
              <IconMessageCircle />
              <span>对话</span>
              <IconChevronDown
                className={cn("ml-auto size-4 transition-transform", open && "rotate-180")}
              />
            </SidebarMenuButton>

            {open && (
              <div className="ml-3 flex flex-col gap-0.5 border-l border-white/10 pl-2">
                {/* 新对话按钮置顶：位于历史对话列表上方 */}
                <Button
                  size="sm"
                  variant="outline"
                  className="mb-0.5 w-full justify-start gap-1.5"
                  onClick={() => {
                    createConversation()
                    setOpen(true)
                    onSelectView("chat")
                  }}
                >
                  <IconPlus className="size-4" />
                  新对话
                </Button>
                {conversations.map((c) => (
                  <div
                    key={c.id}
                    className={cn(
                      "group flex items-center gap-1 rounded px-1.5 py-1 text-xs transition-colors",
                      c.id === activeId
                        ? "bg-white/10 text-foreground"
                        : "border border-transparent text-muted-foreground hover:bg-white/5 hover:text-foreground"
                    )}
                  >
                    <button
                      type="button"
                      className="flex-1 truncate text-left"
                      onClick={() => {
                        selectConversation(c.id)
                        onSelectView("chat")
                      }}
                      title={c.title}
                    >
                      {c.title || "新对话"}
                    </button>
                    <button
                      type="button"
                      className="shrink-0 opacity-0 transition-opacity group-hover:opacity-100"
                      title="删除对话"
                      onClick={(e) => {
                        e.stopPropagation()
                        deleteConversation(c.id)
                      }}
                    >
                      <IconTrash className="size-3.5 text-muted-foreground hover:text-red-400" />
                    </button>
                  </div>
                ))}
              </div>
            )}
          </SidebarMenuItem>
        </SidebarMenu>

        {/* 仪表盘 / 生命周期：真实可切换视图 */}
        <SidebarMenu>
          {items.map((item) => (
            <SidebarMenuItem key={item.view}>
              <SidebarMenuButton
                tooltip={item.title}
                isActive={view === item.view}
                onClick={() => onSelectView(item.view)}
              >
                <item.icon />
                <span className="font-normal">{item.title}</span>
              </SidebarMenuButton>
            </SidebarMenuItem>
          ))}
        </SidebarMenu>
      </SidebarGroupContent>
    </SidebarGroup>
  )
}
