import { AppSidebar } from "@/components/app-sidebar"
import { SiteHeader } from "@/components/site-header"
import { Conversation } from "@/components/conversation"
import { ConversationsProvider } from "@/components/conversations"
import { DashboardView } from "@/components/dashboard-view"
import { LifecycleView } from "@/components/lifecycle-view"
import { KnowledgeView } from "@/components/knowledge-view"
import { SearchView } from "@/components/search-view"
import { ReportsView } from "@/components/reports-view"
import { SettingsView } from "@/components/settings-view"
import { HelpView } from "@/components/help-view"
import { FeedbackView } from "@/components/feedback-view"
import type { View } from "@/components/nav-main"
import { SidebarInset, SidebarProvider } from "@/components/ui/sidebar"
import * as React from "react"

export default function Page() {
  const [view, setView] = React.useState<View>("chat")

  return (
    <ConversationsProvider>
      <SidebarProvider
        className="h-svh overflow-hidden"
        style={
          {
            "--sidebar-width": "calc(var(--spacing) * 72)",
            "--header-height": "calc(var(--spacing) * 12)",
          } as React.CSSProperties
        }
      >
        <AppSidebar variant="inset" view={view} onSelectView={setView} />
        <SidebarInset>
          <SiteHeader />
          <div className="flex min-h-0 flex-1 flex-col overflow-y-auto">
            {view === "chat" && <Conversation />}
            {view === "dashboard" && <DashboardView onGoChat={() => setView("chat")} onGoLifecycle={() => setView("lifecycle")} />}
            {view === "lifecycle" && <LifecycleView onGoChat={() => setView("chat")} />}
            {view === "knowledge" && <KnowledgeView />}
            {view === "search" && <SearchView />}
            {view === "reports" && <ReportsView />}
            {view === "settings" && <SettingsView />}
            {view === "help" && <HelpView />}
            {view === "feedback" && <FeedbackView />}
          </div>
        </SidebarInset>
      </SidebarProvider>
    </ConversationsProvider>
  )
}
