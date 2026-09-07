import { useState } from "react";

import type { IdeaGrade, NotificationConfig, TelegramChat } from "@/api/notifications";
import { SectionCard } from "@/components/SectionCard";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  useDetectTelegramChats,
  useNotificationConfig,
  useNotificationLog,
  useSendTestNotification,
  useSetNotificationConfig,
} from "@/hooks/useNotifications";
import { cn } from "@/lib/utils";

type Draft = Pick<
  NotificationConfig,
  | "telegram_chat_id"
  | "notify_new_ideas"
  | "notify_idea_outcomes"
  | "notify_paper_fills"
  | "notify_daily_summary"
  | "idea_min_grade"
>;

const draftOf = (c: NotificationConfig): Draft => ({
  telegram_chat_id: c.telegram_chat_id,
  notify_new_ideas: c.notify_new_ideas,
  notify_idea_outcomes: c.notify_idea_outcomes,
  notify_paper_fills: c.notify_paper_fills,
  notify_daily_summary: c.notify_daily_summary,
  idea_min_grade: c.idea_min_grade,
});

function Check({
  checked,
  onChange,
  label,
  hint,
}: {
  checked: boolean;
  onChange: (v: boolean) => void;
  label: string;
  hint?: string;
}) {
  return (
    <label className="flex cursor-pointer items-start gap-2 text-sm text-fg">
      <input
        type="checkbox"
        checked={checked}
        onChange={(e) => onChange(e.target.checked)}
        className="mt-0.5 h-4 w-4 rounded border-line-strong accent-accent"
      />
      <span>
        {label}
        {hint && <span className="block text-[11px] text-fg-faint">{hint}</span>}
      </span>
    </label>
  );
}

const STATUS_VARIANT: Record<string, "default" | "success" | "warning" | "destructive"> = {
  sent: "success",
  pending: "default",
  skipped: "warning",
  failed: "destructive",
};

export function NotificationsPanel() {
  const { data: st } = useNotificationConfig();
  const save = useSetNotificationConfig();
  const test = useSendTestNotification();
  const detect = useDetectTelegramChats();
  const { data: log } = useNotificationLog();

  const [draft, setDraft] = useState<Draft | null>(null);
  const [syncedFrom, setSyncedFrom] = useState<string | null>(null);
  const [chats, setChats] = useState<TelegramChat[] | null>(null);

  const cfgKey = st ? JSON.stringify(st.config) : null;
  if (st && cfgKey !== syncedFrom) {
    setSyncedFrom(cfgKey);
    setDraft(draftOf(st.config));
  }

  if (!st || !draft) {
    return <p className="py-10 text-center text-sm text-fg-faint">Loading notification settings…</p>;
  }

  const cfg = st.config;
  const dirty = JSON.stringify(draft) !== JSON.stringify(draftOf(cfg));
  const set = <K extends keyof Draft>(k: K, v: Draft[K]) =>
    setDraft((d) => (d ? { ...d, [k]: v } : d));

  return (
    <div className="flex flex-col gap-4">
      {/* connection status */}
      <div className="rounded-lg border border-line bg-surface px-4 py-3">
        <div className="flex flex-wrap items-center gap-2">
          <Badge variant={st.connected ? "success" : st.token_present ? "warning" : "destructive"}>
            {st.connected ? "Connected" : st.token_present ? "Not linked" : "No bot token"}
          </Badge>
          {st.bot_username && <span className="text-sm text-fg">@{st.bot_username}</span>}
          {cfg.telegram_chat_id && (
            <span className="text-sm text-fg-muted">→ chat {cfg.telegram_chat_id}</span>
          )}
        </div>
        {!st.token_present && (
          <p className="mt-2 text-[13px] text-fg-muted">
            Create a bot with <span className="font-medium">@BotFather</span> on Telegram, then set{" "}
            <code className="text-fg">TELEGRAM_BOT_TOKEN</code> in the backend{" "}
            <code className="text-fg">.env</code> and restart the backend.
          </p>
        )}
        {st.bot_error && (
          <p className="mt-2 text-[13px] text-neg">Telegram: {st.bot_error}</p>
        )}
      </div>

      <SectionCard
        title="Telegram notifications"
        actions={
          <div className="flex items-center gap-2">
            <Badge variant={cfg.enabled ? "success" : "default"}>{cfg.enabled ? "ON" : "OFF"}</Badge>
            <button
              type="button"
              onClick={() => save.mutate({ enabled: !cfg.enabled })}
              disabled={save.isPending || !st.token_present}
              className="rounded px-2 py-0.5 text-[11px] font-medium text-accent hover:bg-accent-soft disabled:opacity-40"
            >
              {cfg.enabled ? "Turn off" : "Turn on"}
            </button>
          </div>
        }
      >
        <div className="flex flex-col gap-5">
          {/* chat id */}
          <div className="flex flex-col gap-2">
            <Label>Telegram chat</Label>
            <div className="flex flex-wrap items-center gap-2">
              <Input
                className="max-w-[16rem]"
                placeholder="chat id, e.g. 12345678"
                value={draft.telegram_chat_id ?? ""}
                onChange={(e) => set("telegram_chat_id", e.target.value || null)}
              />
              <Button
                size="sm"
                variant="outline"
                disabled={detect.isPending || !st.token_present}
                onClick={() =>
                  detect.mutate(undefined, { onSuccess: (rows) => setChats(rows) })
                }
              >
                {detect.isPending ? "Detecting…" : "Detect chat"}
              </Button>
            </div>
            {chats != null && (
              <div className="rounded-md border border-line bg-surface p-2 text-sm">
                {chats.length === 0 ? (
                  <p className="text-fg-faint">
                    No chats found. Send your bot a message on Telegram, then try again.
                  </p>
                ) : (
                  <ul className="flex flex-col gap-1">
                    {chats.map((c) => (
                      <li key={c.chat_id}>
                        <button
                          type="button"
                          onClick={() => set("telegram_chat_id", c.chat_id)}
                          className="w-full rounded px-2 py-1 text-left hover:bg-elevated"
                        >
                          <span className="font-medium text-fg">{c.chat_title}</span>{" "}
                          <span className="text-fg-faint">
                            {c.chat_type} · {c.chat_id}
                          </span>
                        </button>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            )}
          </div>

          {/* categories */}
          <div className="flex flex-col gap-3 border-t border-line pt-4">
            <Label>What to send</Label>
            <Check
              checked={draft.notify_new_ideas}
              onChange={(v) => set("notify_new_ideas", v)}
              label="New scanner recommendations"
              hint="Each new LIVE idea as it fires, filtered by the grade below."
            />
            <Check
              checked={draft.notify_idea_outcomes}
              onChange={(v) => set("notify_idea_outcomes", v)}
              label="Idea outcomes"
              hint="When a tracked idea resolves: target, stop, neutral or invalidated."
            />
            <Check
              checked={draft.notify_paper_fills}
              onChange={(v) => set("notify_paper_fills", v)}
              label="Paper account fills"
              hint="Every paper order fill — manual, auto-trade, strategy, basket, square-off."
            />
            <Check
              checked={draft.notify_daily_summary}
              onChange={(v) => set("notify_daily_summary", v)}
              label="Daily paper summary"
              hint="One wrap-up after 15:35 IST: net worth, day P&L, fills, scanner results."
            />
          </div>

          {/* grade */}
          <div className="flex flex-col gap-1 border-t border-line pt-4">
            <Label>Push ideas graded</Label>
            <select
              value={draft.idea_min_grade}
              onChange={(e) => set("idea_min_grade", e.target.value as IdeaGrade)}
              className="h-9 max-w-[12rem] rounded-md border border-line-strong bg-surface px-2 text-sm text-fg"
            >
              <option value="A">A only</option>
              <option value="B">A &amp; B</option>
              <option value="C">A, B &amp; C</option>
            </select>
          </div>

          <div className="flex flex-wrap items-center gap-2 border-t border-line pt-4">
            <Button size="sm" disabled={!dirty || save.isPending} onClick={() => save.mutate(draft)}>
              Save
            </Button>
            {dirty && (
              <Button size="sm" variant="ghost" onClick={() => setDraft(draftOf(cfg))}>
                Reset
              </Button>
            )}
            <Button
              size="sm"
              variant="outline"
              disabled={test.isPending || !st.connected}
              onClick={() => test.mutate()}
            >
              {test.isPending ? "Sending…" : "Send test message"}
            </Button>
            {test.data && (
              <span className={cn("text-xs", test.data.ok ? "text-pos" : "text-neg")}>
                {test.data.ok ? "Sent" : `Failed: ${test.data.error ?? test.data.status}`}
              </span>
            )}
          </div>
        </div>
      </SectionCard>

      {log && log.length > 0 && (
        <SectionCard title="Recent deliveries">
          <ul className="flex flex-col divide-y divide-line text-sm">
            {log.map((it) => (
              <li key={it.id} className="flex items-center justify-between gap-3 py-1.5">
                <span className="flex items-center gap-2">
                  <Badge variant={STATUS_VARIANT[it.status] ?? "default"}>{it.status}</Badge>
                  <span className="text-fg-muted">{it.kind}</span>
                  <span className="text-fg">{it.title}</span>
                </span>
                <span className="shrink-0 text-[11px] text-fg-faint">
                  {it.created_at ? new Date(it.created_at).toLocaleString() : ""}
                  {it.last_error ? ` · ${it.last_error}` : ""}
                </span>
              </li>
            ))}
          </ul>
        </SectionCard>
      )}
    </div>
  );
}
