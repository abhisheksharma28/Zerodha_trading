import { useState } from "react";

import type { AlgoConfig, AlgoStatus } from "@/api/paperAccount";
import { SectionCard } from "@/components/SectionCard";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { usePaperAlgo, useSetPaperAlgo } from "@/hooks/usePaperAccount";
import { inr } from "@/lib/format";
import { cn } from "@/lib/utils";

type Draft = Pick<
  AlgoConfig,
  | "min_grade"
  | "pct_per_trade"
  | "max_open_auto"
  | "daily_loss_stop_pct"
  | "cutoff_ist"
  | "allow_delivery"
  | "allow_intraday"
  | "allow_options"
  | "equity_product"
>;

const draftOf = (c: AlgoConfig): Draft => ({
  min_grade: c.min_grade,
  pct_per_trade: c.pct_per_trade,
  max_open_auto: c.max_open_auto,
  daily_loss_stop_pct: c.daily_loss_stop_pct,
  cutoff_ist: c.cutoff_ist,
  allow_delivery: c.allow_delivery,
  allow_intraday: c.allow_intraday,
  allow_options: c.allow_options,
  equity_product: c.equity_product,
});

function Field({ label, hint, children }: { label: string; hint?: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-1">
      <Label>{label}</Label>
      {children}
      {hint && <p className="text-[11px] text-fg-faint">{hint}</p>}
    </div>
  );
}

function Check({
  checked,
  onChange,
  label,
}: {
  checked: boolean;
  onChange: (v: boolean) => void;
  label: string;
}) {
  return (
    <label className="flex cursor-pointer items-center gap-2 text-sm text-fg">
      <input
        type="checkbox"
        checked={checked}
        onChange={(e) => onChange(e.target.checked)}
        className="h-4 w-4 rounded border-line-strong accent-accent"
      />
      {label}
    </label>
  );
}

export function AlgoPanel() {
  const { data: st } = usePaperAlgo();
  const save = useSetPaperAlgo();
  const [draft, setDraft] = useState<Draft | null>(null);
  const [syncedFrom, setSyncedFrom] = useState<string | null>(null);

  // adopt the server config as the draft baseline the first time it loads and
  // whenever it genuinely changes on the server (save, or a backend halt) —
  // a plain poll returns the same JSON and leaves in-progress edits alone.
  const cfgKey = st ? JSON.stringify(st.config) : null;
  if (st && cfgKey !== syncedFrom) {
    setSyncedFrom(cfgKey);
    setDraft(draftOf(st.config));
  }

  if (!st || !draft) {
    return <p className="py-10 text-center text-sm text-fg-faint">Loading auto-trade settings…</p>;
  }

  const cfg = st.config;
  const dirty = JSON.stringify(draft) !== JSON.stringify(draftOf(cfg));
  const set = <K extends keyof Draft>(k: K, v: Draft[K]) => setDraft((d) => (d ? { ...d, [k]: v } : d));

  return (
    <div className="flex flex-col gap-4">
      {/* status strip */}
      <div className="flex flex-wrap items-stretch rounded-lg border border-line bg-surface">
        <div className="min-w-[10rem] flex-1 border-r border-line px-4 py-3 last:border-0">
          <p className="text-[11px] uppercase tracking-wide text-fg-faint">Auto-trading</p>
          <div className="mt-1 flex items-center gap-2">
            <Badge variant={cfg.enabled ? "success" : "default"}>{cfg.enabled ? "ON" : "OFF"}</Badge>
            <button
              type="button"
              onClick={() => save.mutate({ enabled: !cfg.enabled })}
              disabled={save.isPending}
              className="rounded px-2 py-0.5 text-[11px] font-medium text-accent hover:bg-accent-soft"
            >
              {cfg.enabled ? "Turn off" : "Turn on"}
            </button>
          </div>
        </div>
        <div className="min-w-[8rem] flex-1 border-r border-line px-4 py-3 last:border-0">
          <p className="text-[11px] uppercase tracking-wide text-fg-faint">Open auto positions</p>
          <p className="mt-1 text-lg font-semibold tabular-nums">
            {st.open_auto_positions}
            <span className="text-sm text-fg-faint"> / {st.max_open_auto}</span>
          </p>
        </div>
        <div className="min-w-[8rem] flex-1 border-r border-line px-4 py-3 last:border-0">
          <p className="text-[11px] uppercase tracking-wide text-fg-faint">Auto P&L today</p>
          <p
            className={cn(
              "mt-1 text-lg font-semibold tabular-nums",
              st.today_realized_pnl > 0 ? "text-pos" : st.today_realized_pnl < 0 ? "text-neg" : "text-fg-muted",
            )}
          >
            {inr(st.today_realized_pnl)}
          </p>
        </div>
      </div>

      {st.halted && cfg.halted_reason && (
        <div className="rounded-md border border-neg/40 bg-neg/10 px-3 py-2 text-sm text-neg">
          Auto-trading halted for today — {cfg.halted_reason}. It resumes tomorrow, or turn it off and
          on again to clear the halt.
        </div>
      )}

      <SectionCard
        title="Auto-trade rules"
        actions={
          <div className="flex items-center gap-2">
            {dirty && <span className="text-[11px] text-fg-faint">unsaved changes</span>}
            <Button
              size="sm"
              disabled={!dirty || save.isPending}
              onClick={() => save.mutate(draft)}
            >
              Save rules
            </Button>
            {dirty && (
              <Button size="sm" variant="ghost" onClick={() => setDraft(draftOf(cfg))}>
                Reset
              </Button>
            )}
          </div>
        }
      >
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
          <Field label="Minimum grade" hint="Only ideas at this grade or better are auto-taken.">
            <select
              value={draft.min_grade}
              onChange={(e) => set("min_grade", e.target.value as Draft["min_grade"])}
              className="h-9 rounded-md border border-line-strong bg-surface px-2 text-sm text-fg"
            >
              <option value="A">A only</option>
              <option value="B">A & B</option>
              <option value="C">A, B & C</option>
            </select>
          </Field>

          <Field label="% of net worth per trade" hint="Position size for each auto trade.">
            <Input
              type="number"
              step="0.5"
              min={0.1}
              max={25}
              value={draft.pct_per_trade}
              onChange={(e) => set("pct_per_trade", Number(e.target.value))}
            />
          </Field>

          <Field label="Max open auto positions" hint="New auto trades pause at this many open.">
            <Input
              type="number"
              min={1}
              max={50}
              value={draft.max_open_auto}
              onChange={(e) => set("max_open_auto", Number(e.target.value))}
            />
          </Field>

          <Field label="Daily loss stop (%)" hint="Halts new auto trades for the day when auto P&L drops this far.">
            <Input
              type="number"
              step="0.5"
              min={0.5}
              max={100}
              value={draft.daily_loss_stop_pct}
              onChange={(e) => set("daily_loss_stop_pct", Number(e.target.value))}
            />
          </Field>

          <Field label="No new trades after (IST)" hint="Cut-off time for opening fresh auto trades.">
            <Input
              type="time"
              value={draft.cutoff_ist}
              onChange={(e) => set("cutoff_ist", e.target.value)}
            />
          </Field>

          <Field label="Equity delivery product" hint="Product used for long delivery ideas.">
            <select
              value={draft.equity_product}
              onChange={(e) => set("equity_product", e.target.value as Draft["equity_product"])}
              className="h-9 rounded-md border border-line-strong bg-surface px-2 text-sm text-fg"
            >
              <option value="CNC">CNC (hold)</option>
              <option value="MIS">MIS (intraday)</option>
            </select>
          </Field>
        </div>

        <div className="mt-4 flex flex-wrap gap-x-6 gap-y-2 border-t border-line pt-3">
          <Check checked={draft.allow_delivery} onChange={(v) => set("allow_delivery", v)} label="Take delivery ideas" />
          <Check checked={draft.allow_intraday} onChange={(v) => set("allow_intraday", v)} label="Take intraday ideas" />
          <Check checked={draft.allow_options} onChange={(v) => set("allow_options", v)} label="Take option ideas (defined-risk spreads)" />
        </div>

        <p className="mt-3 text-[11px] text-fg-faint">
          When on, every LIVE idea from the Trading Ideas engine that clears these rules is placed in
          this paper account, tagged <span className="font-medium">AUTO</span>, with a protective
          stop. Auto positions are squared off when the source idea expires.
        </p>
      </SectionCard>
    </div>
  );
}

export function AlgoPill({ status }: { status?: AlgoStatus }) {
  const save = useSetPaperAlgo();
  const on = status?.config.enabled ?? false;
  return (
    <button
      type="button"
      onClick={() => save.mutate({ enabled: !on })}
      disabled={!status || save.isPending}
      className={cn(
        "flex items-center gap-1.5 rounded-md border px-2.5 py-1.5 text-xs font-semibold transition-colors",
        on
          ? "border-pos/40 bg-pos/10 text-pos"
          : "border-line-strong text-fg-muted hover:bg-elevated",
      )}
      title="Toggle auto-trading of engine ideas in this paper account"
    >
      <span className={cn("h-2 w-2 rounded-full", on ? "bg-pos" : "bg-line-strong")} />
      Algo {on ? "ON" : "OFF"}
      {on && status && status.halted && <span className="text-neg">· halted</span>}
    </button>
  );
}
