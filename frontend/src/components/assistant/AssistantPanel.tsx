import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Maximize2, Sparkles, X } from "lucide-react";

import type { ChatMessage } from "@/api/assistant";
import { Button } from "@/components/ui/button";
import {
  useAssistantChat,
  useAssistantStatus,
  useAssistantSuggestions,
} from "@/hooks/useAssistant";
import { cn } from "@/lib/utils";

/* --- a very small markdown renderer (headings / bold / bullets / paras) --- */
function inline(s: string) {
  return s.split(/(\*\*[^*]+\*\*|`[^`]+`)/g).map((p, i) => {
    if (p.startsWith("**") && p.endsWith("**"))
      return (
        <strong key={i} className="font-semibold text-fg">
          {p.slice(2, -2)}
        </strong>
      );
    if (p.startsWith("`") && p.endsWith("`"))
      return (
        <code key={i} className="rounded bg-elevated px-1 py-0.5 text-[12px]">
          {p.slice(1, -1)}
        </code>
      );
    return <span key={i}>{p}</span>;
  });
}

function Markdown({ text }: { text: string }) {
  const lines = text.split("\n");
  const out: React.ReactNode[] = [];
  let list: string[] = [];
  const flush = () => {
    if (list.length) {
      out.push(
        <ul key={`l${out.length}`} className="my-1.5 list-disc space-y-1 pl-5">
          {list.map((li, i) => (
            <li key={i}>{inline(li)}</li>
          ))}
        </ul>,
      );
      list = [];
    }
  };
  for (const raw of lines) {
    const l = raw.trimEnd();
    if (/^#{1,4}\s/.test(l)) {
      flush();
      out.push(
        <p key={`h${out.length}`} className="mt-2.5 font-display text-sm font-semibold text-fg">
          {inline(l.replace(/^#{1,4}\s/, ""))}
        </p>,
      );
    } else if (/^[-*]\s+/.test(l)) {
      list.push(l.replace(/^[-*]\s+/, ""));
    } else if (l === "") {
      flush();
    } else {
      flush();
      out.push(
        <p key={`p${out.length}`} className="my-1.5 leading-relaxed">
          {inline(l)}
        </p>,
      );
    }
  }
  flush();
  return <div className="text-[13px] text-fg-muted">{out}</div>;
}

function errText(e: unknown): string {
  const d = (e as { response?: { data?: { message?: string; detail?: string } } })?.response?.data;
  return d?.message ?? d?.detail ?? "The request failed — check that the AI provider is running.";
}

/** The chat itself — reused by the slide-over panel and the full page. */
export function AssistantChat({ compact = false }: { compact?: boolean }) {
  const { data: status } = useAssistantStatus();
  const { data: suggestions = [] } = useAssistantSuggestions();
  const chat = useAssistantChat();
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [draft, setDraft] = useState("");
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [messages, chat.isPending]);

  const canSend = !!status?.configured && !chat.isPending;

  function send(text: string) {
    const q = text.trim();
    if (!q || chat.isPending) return;
    const next: ChatMessage[] = [...messages, { role: "user", content: q }];
    setMessages(next);
    setDraft("");
    chat.mutate(next, {
      onSuccess: (r) => setMessages((m) => [...m, { role: "assistant", content: r.reply }]),
      onError: (e) =>
        setMessages((m) => [...m, { role: "assistant", content: `⚠️ ${errText(e)}` }]),
    });
  }

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div ref={scrollRef} className={cn("flex-1 overflow-y-auto", compact ? "px-4 py-4" : "px-1 py-4")}>
        {status && !status.available && (
          <div className="mb-3 rounded-md border border-amber-400/40 bg-amber-400/10 p-3 text-xs text-amber-600 dark:text-amber-400">
            {status.reason ?? "The assistant provider isn't reachable right now."}
            {status.configured && (
              <span className="mt-1 block text-amber-600/80 dark:text-amber-400/80">
                You can still type a message and retry once it's up.
              </span>
            )}
          </div>
        )}

        {messages.length === 0 && (
          <div className="flex flex-col gap-3">
            <p className="text-sm text-fg-muted">
              Ask about long-horizon stock or sector prospects. Answers are grounded in the
              platform's fundamentals, sector data and the engine's live signals.
            </p>
            {status?.configured && suggestions.length > 0 && (
              <div className="flex flex-col gap-1.5">
                {suggestions.map((s) => (
                  <button
                    key={s}
                    type="button"
                    onClick={() => send(s)}
                    disabled={!canSend}
                    className="hover-lift rounded-lg border border-line bg-surface px-3 py-2 text-left text-[13px] text-fg-muted hover:text-fg disabled:opacity-50"
                  >
                    {s}
                  </button>
                ))}
              </div>
            )}
          </div>
        )}

        <div className="flex flex-col gap-3">
          {messages.map((m, i) => (
            <div
              key={i}
              className={cn(
                "rounded-2xl px-3.5 py-2.5 text-[13px]",
                compact ? "max-w-[92%]" : "max-w-[720px]",
                m.role === "user"
                  ? "self-end bg-accent-soft text-fg"
                  : "self-start border border-line bg-elevated/40",
              )}
            >
              {m.role === "user" ? m.content : <Markdown text={m.content} />}
            </div>
          ))}
          {chat.isPending && (
            <div className="self-start rounded-2xl border border-line bg-elevated/40 px-3.5 py-2.5 text-[13px] text-fg-faint">
              <span className="inline-flex gap-1">
                <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-fg-faint [animation-delay:-0.2s]" />
                <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-fg-faint [animation-delay:-0.1s]" />
                <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-fg-faint" />
              </span>
            </div>
          )}
        </div>
      </div>

      <form
        className={cn("border-t border-line pt-3", compact ? "px-4 pb-3" : "px-1 pb-1")}
        onSubmit={(e) => {
          e.preventDefault();
          send(draft);
        }}
      >
        <div className="flex items-end gap-2">
          <textarea
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                send(draft);
              }
            }}
            rows={2}
            disabled={!canSend}
            placeholder={status?.configured ? "Ask about a stock or sector…" : "Assistant not configured"}
            className="min-h-[38px] flex-1 resize-none rounded-lg border border-line-strong bg-bg px-3 py-2 text-[13px] text-fg placeholder:text-fg-faint focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent disabled:opacity-50"
          />
          <Button type="submit" size="sm" disabled={!canSend || !draft.trim()}>
            Send
          </Button>
        </div>
        <p className="mt-1.5 text-[10px] text-fg-faint">
          Not investment advice. The assistant can be wrong — verify before acting.
        </p>
      </form>
    </div>
  );
}

export function AssistantPanel({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { data: status, refetch: refetchStatus } = useAssistantStatus();
  const nav = useNavigate();

  useEffect(() => {
    if (open) void refetchStatus();
  }, [open, refetchStatus]);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  return (
    <>
      {/* transparent click-away — no dark veil, the page stays readable */}
      {open && <div className="fixed inset-0 z-[60]" onClick={onClose} />}
      <aside
        className={cn(
          "fixed right-0 top-0 z-[61] flex h-full w-full max-w-[400px] flex-col border-l border-line-strong bg-surface shadow-2xl transition-transform duration-300",
          open ? "translate-x-0" : "pointer-events-none translate-x-full",
        )}
        aria-hidden={!open}
      >
        <header className="flex items-center justify-between border-b border-line px-4 py-3">
          <div className="flex items-center gap-2">
            <span className="flex h-7 w-7 items-center justify-center rounded-lg bg-gradient-to-br from-accent to-accent-strong text-accent-fg">
              <Sparkles className="h-4 w-4" />
            </span>
            <div>
              <p className="font-display text-sm font-semibold text-fg">Research assistant</p>
              <p className="max-w-[240px] truncate text-[11px] text-fg-faint">
                {status?.configured ? status.model : "Not configured"}
                {status && !status.available && status.configured ? " · offline" : ""}
              </p>
            </div>
          </div>
          <div className="flex items-center gap-1">
            <button
              type="button"
              onClick={() => {
                onClose();
                nav("/assistant");
              }}
              title="Open as full page"
              className="rounded-md p-1 text-fg-muted hover:bg-elevated"
            >
              <Maximize2 className="h-4 w-4" />
            </button>
            <button
              type="button"
              onClick={onClose}
              className="rounded-md p-1 text-fg-muted hover:bg-elevated"
            >
              <X className="h-4 w-4" />
            </button>
          </div>
        </header>

        <div className="min-h-0 flex-1">
          <AssistantChat compact />
        </div>
      </aside>
    </>
  );
}

/** Header trigger for the assistant — lives in the top nav. */
export function AssistantHeaderButton() {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        aria-label="Open the research assistant"
        className="flex items-center gap-1.5 rounded-md border border-accent/40 bg-accent-soft px-2.5 py-1.5 text-xs font-semibold text-accent transition-colors hover:bg-accent/15"
      >
        <Sparkles className="h-3.5 w-3.5" />
        <span className="hidden sm:inline">Ask AI</span>
      </button>
      <AssistantPanel open={open} onClose={() => setOpen(false)} />
    </>
  );
}
