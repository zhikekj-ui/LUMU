"use client"

import * as React from "react"
import {
  IconDatabase,
  IconHelp,
  IconInnerShadowTop,
  IconMoodSmile,
  IconReport,
  IconSearch,
  IconSettings,
} from "@tabler/icons-react"

import { NavMain, NavViewButton, type View } from "@/components/nav-main"
import { Sidebar, SidebarContent, SidebarGroup, SidebarGroupContent, SidebarGroupLabel, SidebarHeader, SidebarMenu, SidebarMenuButton, SidebarMenuItem } from "@/components/ui/sidebar"

const data = {
  user: {
    name: "LUMU 用户",
    email: "本地实例",
    avatar: "/avatars/shadcn.jpg",
  },
  workspace: [
    { title: "资料库", view: "knowledge" as View, icon: IconDatabase },
    { title: "搜索", view: "search" as View, icon: IconSearch },
    { title: "报告", view: "reports" as View, icon: IconReport },
  ],
  navSecondary: [
    { title: "设置", view: "settings" as View, icon: IconSettings },
    { title: "用户反馈", view: "feedback" as View, icon: IconMoodSmile },
    { title: "获取帮助", view: "help" as View, icon: IconHelp },
  ],
}

export function AppSidebar({
  view,
  onSelectView,
  ...props
}: React.ComponentProps<typeof Sidebar> & {
  view: View
  onSelectView: (v: View) => void
}) {
  return (
    <Sidebar collapsible="offcanvas" {...props}>
      <SidebarHeader>
        <SidebarMenu>
          <SidebarMenuItem>
            <SidebarMenuButton
              asChild
              className="data-[slot=sidebar-menu-button]:p-1.5!"
            >
              <a href="#">
                <IconInnerShadowTop className="size-5!" />
                <span className="text-base font-semibold">LUMU</span>
              </a>
            </SidebarMenuButton>
          </SidebarMenuItem>
        </SidebarMenu>
      </SidebarHeader>
      <SidebarContent>
        <NavMain view={view} onSelectView={onSelectView} />
        <SidebarGroup>
          <SidebarGroupLabel>知识 &amp; 工具</SidebarGroupLabel>
          <SidebarGroupContent>
            <SidebarMenu>
              {data.workspace.map((item) => (
                <NavViewButton
                  key={item.view}
                  title={item.title}
                  view={item.view}
                  icon={item.icon}
                  active={view === item.view}
                  onSelect={onSelectView}
                />
              ))}
            </SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>
        <SidebarGroup className="mt-auto">
          <SidebarGroupContent>
            <SidebarMenu>
              {data.navSecondary.map((item) => (
                <NavViewButton
                  key={item.view}
                  title={item.title}
                  view={item.view}
                  icon={item.icon}
                  active={view === item.view}
                  onSelect={onSelectView}
                />
              ))}
            </SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>
      </SidebarContent>
    </Sidebar>
  )
}
