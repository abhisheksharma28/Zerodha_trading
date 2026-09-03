import { Plus, Trash2 } from "lucide-react";

import type { Sleeve, Weighting } from "@/api/baskets";
import { InstrumentSearch } from "@/components/InstrumentSearch";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";

const WEIGHTINGS: { value: Weighting; label: string; hint: string }[] = [
  { value: "equal", label: "Equal", hint: "same weight to every held name" },
  { value: "inverse_vol", label: "Inverse-vol", hint: "calmer names get more weight" },
  { value: "momentum_weighted", label: "Momentum", hint: "stronger names get more weight" },
];

export function emptySleeve(n: number): Sleeve {
  return {
    id: `sleeve-${n}`,
    name: n === 1 ? "Equity core" : `Sleeve ${n}`,
    weight_pct: 0,
    weighting: "equal",
    members: [],
    rule: { type: "none", lookback: 126, top_k: 5, trend_ma: 200, min_roc_pct: 0 },
  };
}

/** Members are stored here as "NSE:SYMBOL" refs for InstrumentSearch; the
 *  backend strips the exchange. */
export function SleeveEditor({
  sleeves,
  onChange,
}: {
  sleeves: Sleeve[];
  onChange: (next: Sleeve[]) => void;
}) {
  const total = sleeves.reduce((s, sl) => s + (Number(sl.weight_pct) || 0), 0);

  const patch = (i: number, p: Partial<Sleeve>) =>
    onChange(sleeves.map((sl, idx) => (idx === i ? { ...sl, ...p } : sl)));
  const patchRule = (i: number, p: Partial<Sleeve["rule"]>) =>
    onChange(
      sleeves.map((sl, idx) => (idx === i ? { ...sl, rule: { ...sl.rule, ...p } } : sl)),
    );

  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center justify-between">
        <p className="text-xs text-fg-faint">
          Sleeve weights must add to 100%.{" "}
          <span
            className={cn(
              "font-semibold tabular-nums",
              Math.abs(total - 100) < 0.5 ? "text-pos" : "text-neg",
            )}
          >
            {total.toFixed(1)}%
          </span>
        </p>
        <Button
          size="sm"
          variant="outline"
          type="button"
          onClick={() => onChange([...sleeves, emptySleeve(sleeves.length + 1)])}
        >
          <Plus className="mr-1 h-3.5 w-3.5" /> Add sleeve
        </Button>
      </div>

      {sleeves.map((sl, i) => (
        <div key={i} className="rounded-lg border border-line bg-bg/40 p-3">
          <div className="flex flex-wrap items-end gap-3">
            <label className="flex flex-col gap-1">
              <span className="text-[10px] uppercase tracking-wide text-fg-faint">Sleeve name</span>
              <Input
                className="h-8 w-44"
                value={sl.name}
                onChange={(e) => patch(i, { name: e.target.value })}
              />
            </label>
            <label className="flex flex-col gap-1">
              <span className="text-[10px] uppercase tracking-wide text-fg-faint">Weight %</span>
              <Input
                type="number"
                className="h-8 w-24 tabular-nums"
                value={sl.weight_pct}
                min={0}
                max={100}
                onChange={(e) => patch(i, { weight_pct: Number(e.target.value) })}
              />
            </label>
            <label className="flex flex-col gap-1">
              <span className="text-[10px] uppercase tracking-wide text-fg-faint">Weighting</span>
              <select
                className="h-8 rounded-md border border-line bg-surface px-2 text-sm"
                value={sl.weighting}
                onChange={(e) => patch(i, { weighting: e.target.value as Weighting })}
              >
                {WEIGHTINGS.map((w) => (
                  <option key={w.value} value={w.value}>
                    {w.label}
                  </option>
                ))}
              </select>
            </label>
            {sleeves.length > 1 && (
              <Button
                size="sm"
                variant="ghost"
                type="button"
                className="ml-auto text-neg"
                onClick={() => onChange(sleeves.filter((_, idx) => idx !== i))}
              >
                <Trash2 className="h-4 w-4" />
              </Button>
            )}
          </div>

          <div className="mt-3">
            <span className="text-[10px] uppercase tracking-wide text-fg-faint">
              Members ({sl.members.length})
            </span>
            <div className="mt-1">
              <InstrumentSearch
                value={sl.members}
                onChange={(next) => patch(i, { members: next })}
              />
            </div>
          </div>

          <div className="mt-3 flex flex-wrap items-end gap-3">
            <label className="flex flex-col gap-1">
              <span className="text-[10px] uppercase tracking-wide text-fg-faint">Rotation rule</span>
              <select
                className="h-8 rounded-md border border-line bg-surface px-2 text-sm"
                value={sl.rule.type}
                onChange={(e) =>
                  patchRule(i, { type: e.target.value as Sleeve["rule"]["type"] })
                }
              >
                <option value="none">None — hold every member</option>
                <option value="momentum_top_k">Momentum top-K</option>
              </select>
            </label>
            {sl.rule.type === "momentum_top_k" && (
              <>
                <RuleNum
                  label="Lookback (bars)"
                  value={sl.rule.lookback}
                  onChange={(v) => patchRule(i, { lookback: v })}
                />
                <RuleNum
                  label="Hold top"
                  value={sl.rule.top_k}
                  onChange={(v) => patchRule(i, { top_k: v })}
                />
                <RuleNum
                  label="Trend MA (0 = off)"
                  value={sl.rule.trend_ma}
                  onChange={(v) => patchRule(i, { trend_ma: v })}
                />
                <RuleNum
                  label="Min ROC %"
                  value={sl.rule.min_roc_pct}
                  onChange={(v) => patchRule(i, { min_roc_pct: v })}
                />
              </>
            )}
          </div>
        </div>
      ))}
    </div>
  );
}

function RuleNum({
  label,
  value,
  onChange,
}: {
  label: string;
  value: number;
  onChange: (v: number) => void;
}) {
  return (
    <label className="flex flex-col gap-1">
      <span className="text-[10px] uppercase tracking-wide text-fg-faint">{label}</span>
      <Input
        type="number"
        className="h-8 w-28 tabular-nums"
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
      />
    </label>
  );
}
