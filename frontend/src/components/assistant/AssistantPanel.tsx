import { useEffect, useRef, useState } from "react";
import { Sparkles, X } from "lucide-react";

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

export function AssistantPanel({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { data: status } = useAssistantStatus();
  const { data: suggestions = [] } = useAssistantSuggestions();
  const chat = useAssistantChat();
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [draft, setDraft] = useState("");
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [messages, chat.isPending]);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  function send(text: string) {
    const q = text.trim();
    if (!q || chat.isPending) return;
    const next: ChatMessage[] = [...messages, { role: "user", content: q }];
    setMessages(next);
    setDraft("");
    chat.mutate(next, {
      onSuccess: (r) => setMessages((m) => [...m, { role: "assistant", content: r.reply }]),
      onError: () =>
        setMessages((m) => [
          ...m,
          { role: "assistant", content: "Sorry — that request failed. Try again in a moment." },
        ]),
    });
  }

  return (
    <>
      <div
        className={cn(
          "fixed inset-0 z-[60] bg-black/40 backdrop-blur-[2px] transition-opacity",
          open ? "opacity-100" : "pointer-events-none opacity-0",
        )}
        onClick={onClose}
      />
      <aside
        className={cn(
          "fixed right-0 top-0 z-[61] flex h-full w-full max-w-[440px] flex-col border-l border-line bg-surface shadow-2xl transition-transform duration-300",
          open ? "translate-x-0" : "translate-x-full",
        )}
      >
        <header className="flex items-center justify-between border-b border-line px-4 py-3">
          <div className="flex items-center gap-2">
            <span className="flex h-7 w-7 items-center justify-center rounded-lg bg-gradient-to-br from-accent to-accent-strong text-accent-fg">
              <Sparkles className="h-4 w-4" />
            </span>
            <div>
              <p className="font-display text-sm font-semibold text-fg">Research assistant</p>
              <p className="max-w-[260px] truncate text-[11px] text-fg-faint">
                {status?.available
                  ? `${status.provider} · ${status.model}`
                  : "Not configured"}
              </p>
            </div>
          </div>
          <button type="button" onClick={onClose} className="rounded-md p-1 text-fg-muted hover:bg-elevated">
            <X className="h-4 w-4" />
          </button>
        </header>

        <div ref={scrollRef} className="flex-1 overflow-y-auto px-4 py-4">
          {!status?.available && (
            <div className="rounded-md border border-amber-400/40 bg-amber-400/10 p-3 text-xs text-amber-500">
              {status?.reason ?? "The assistant is not configured yet."}
            </div>
          )}

          {messages.length === 0 && status?.available && (
            <div className="flex flex-col gap-3">
              <p className="text-sm text-fg-muted">
                Ask about long-horizon stock or sector prospects. Answers are grounded in the
                platform's fundamentals, sector data and the engine's live signals.
              </p>
              <div className="flex flex-col gap-1.5">
                {suggestions.map((s) => (
                  <button
                    key={s}
                    type="button"
                    onClick={() => send(s)}
                    className="hover-lift rounded-lg border border-line bg-surface px-3 py-2 text-left text-[13px] text-fg-muted hover:text-fg"
                  >
                    {s}
                  </button>
                ))}
              </div>
            </div>
          )}

          <div className="flex flex-col gap-3">
            {messages.map((m, i) => (
              <div
                key={i}
                className={cn(
                  "max-w-[92%] rounded-2xl px-3.5 py-2.5 text-[13px]",
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
          className="border-t border-line p-3"
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
              disabled={!status?.available || chat.isPending}
              placeholder="Ask about a stock or sector…"
              className="min-h-[38px] flex-1 resize-none rounded-lg border border-line-strong bg-bg px-3 py-2 text-[13px] text-fg placeholder:text-fg-faint focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent disabled:opacity-50"
            />
            <Button
              type="submit"
              size="sm"
              disabled={!status?.available || chat.isPending || !draft.trim()}
            >
              Send
            </Button>
          </div>
          <p className="mt-1.5 text-[10px] text-fg-faint">
            Not investment advice. The assistant can be wrong — verify before acting.
          </p>
        </form>
      </aside>
    </>
  );
}

/** Header trigger for the assistant — lives in the top nav so it doesn't
 *  collide with dev-tool floating widgets in the bottom-right corner. */
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
