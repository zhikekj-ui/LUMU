import * as React from 'react'
import { Activity as ActivityIcon } from 'lucide-react'

import {
  Sidebar,
  SidebarContent,
  SidebarHeader,
} from '@/components/ui/sidebar'
import type { Activity } from '@/types'

interface Props {
  activities: Activity[]
}

export function ActivitySidebar({ activities }: Props) {
  return (
    <Sidebar
      side="right"
      collapsible="none"
      style={{ ['--sidebar-width' as any]: '19rem' }}
      className="hidden border-l border-sidebar-border lg:flex"
    >
      <SidebarHeader className="border-b border-sidebar-border px-3 py-3">
        <div className="flex items-center gap-2 text-sidebar-foreground">
          <ActivityIcon className="size-4 text-cyan" />
          <span className="font-mono text-xs uppercase tracking-[0.16em]">活动 · Activity</span>
        </div>
      </SidebarHeader>
      <SidebarContent className="scroll-thin gap-0 p-2">
        {activities.length === 0 && (
          <p className="px-2 py-3 text-xs text-muted-foreground">
            运行中的工具调用与进度会实时显示在这里。
          </p>
        )}
        {activities.map((a) => {
          const dot =
            a.status === 'ok'
              ? 'bg-emerald-400'
              : a.status === 'err'
              ? 'bg-destructive'
              : 'bg-cyan'
          return (
            <div
              key={a.id}
              className="mb-2 rounded-md border border-sidebar-border bg-sidebar-accent/30 p-2"
            >
              <div className="flex items-center gap-2 text-sidebar-foreground">
                <span className={`size-1.5 shrink-0 rounded-full ${dot}`} />
                <span className="font-mono text-[11px]">{a.action}</span>
                {a.status && (
                  <span className="ml-auto font-mono text-[9px] uppercase tracking-wider text-muted-foreground">
                    {a.status}
                  </span>
                )}
              </div>
              {a.detail && (
                <pre className="mt-1 max-h-28 overflow-auto whitespace-pre-wrap break-words font-mono text-[10px] leading-relaxed text-muted-foreground">
                  {a.detail}
                </pre>
              )}
            </div>
          )
        })}
      </SidebarContent>
    </Sidebar>
  )
}
