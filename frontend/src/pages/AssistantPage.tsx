import { Sparkles } from "lucide-react";

import { AssistantChat } from "@/components/assistant/AssistantPanel";
import { PageHeader } from "@/components/PageHeader";
import { useAssistantStatus } from "@/hooks/useAssistant";

export default function AssistantPage() {
  const { data: status } = useAssistantStatus();
  return (
    <div className="mx-auto flex h-[calc(100vh-11rem)] max-w-3xl flex-col gap-4">
      <PageHeader
        title="Research assistant"
        subtitle={
          status?.configured
            ? `${status.provider} · ${status.model}${status.available ? "" : " · offline"}`
            : "Not configured — set an AI provider in the backend .env"
        }
        actions={
          <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-gradient-to-br from-accent to-accent-strong text-accent-fg">
            <Sparkles className="h-4 w-4" />
          </span>
        }
      />
      <div className="min-h-0 flex-1 rounded-lg border border-line bg-surface p-4">
        <AssistantChat />
      </div>
    </div>
  );
}
