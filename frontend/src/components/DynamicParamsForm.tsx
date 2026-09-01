import { Fragment } from "react";

import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { paramError } from "@/lib/paramValidation";
import type { TemplateParamSpec } from "@/types/api";

type Schema = Record<string, TemplateParamSpec>;
type Values = Record<string, unknown>;

const GROUP_ORDER = ["core", "sizing", "filter", "risk"] as const;
const GROUP_LABEL: Record<string, string> = {
  core: "Core",
  sizing: "Position sizing",
  filter: "Filters",
  risk: "Risk controls",
};

export function DynamicParamsForm({
  schema,
  values,
  onChange,
}: {
  schema: Schema;
  values: Values;
  onChange: (next: Values) => void;
}) {
  const set = (name: string, raw: unknown) => onChange({ ...values, [name]: raw });

  const byGroup: Record<string, [string, TemplateParamSpec][]> = {};
  for (const entry of Object.entries(schema)) {
    const g = entry[1].group ?? "core";
    (byGroup[g] ??= []).push(entry);
  }

  return (
    <div className="flex flex-col gap-6">
      {GROUP_ORDER.filter((g) => byGroup[g]?.length).map((group) => (
        <div key={group} className="flex flex-col gap-3">
          <p className="text-xs font-semibold uppercase tracking-wide text-fg-faint">
            {GROUP_LABEL[group] ?? group}
          </p>
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            {byGroup[group].map(([name, spec]) => {
              const value = values[name] ?? spec.default;
              const err = paramError(spec, value);
              return (
                <Fragment key={name}>
                  <div className="flex flex-col gap-1.5">
                    <Label htmlFor={name} className="text-xs">
                      {name}
                    </Label>
                    {spec.type === "boolean" ? (
                      <label className="flex items-center gap-2 text-sm text-fg-muted">
                        <input
                          id={name}
                          type="checkbox"
                          checked={Boolean(value)}
                          onChange={(e) => set(name, e.target.checked)}
                          className="h-4 w-4 rounded border-line-strong bg-surface"
                        />
                        enabled
                      </label>
                    ) : spec.type === "enum" ? (
                      <select
                        id={name}
                        value={String(value)}
                        onChange={(e) => set(name, e.target.value)}
                        className="h-9 rounded-md border border-line-strong bg-surface px-3 text-sm text-fg"
                      >
                        {spec.choices?.map((c) => (
                          <option key={String(c)} value={String(c)}>
                            {String(c)}
                          </option>
                        ))}
                      </select>
                    ) : (
                      <Input
                        id={name}
                        type={spec.type === "string" ? "text" : "number"}
                        value={String(value ?? "")}
                        step={spec.type === "integer" ? 1 : "any"}
                        onChange={(e) =>
                          set(
                            name,
                            spec.type === "string"
                              ? e.target.value
                              : e.target.value === ""
                                ? ""
                                : Number(e.target.value),
                          )
                        }
                        className={err ? "border-red-500/60" : undefined}
                      />
                    )}
                    <p className="text-[11px] leading-tight text-fg-faint">
                      {spec.description}
                      {spec.min != null || spec.max != null ? (
                        <span className="text-fg-faint">
                          {" "}
                          ({spec.min ?? "-∞"}–{spec.max ?? "∞"})
                        </span>
                      ) : null}
                    </p>
                    {err && <p className="text-[11px] text-red-400">{err}</p>}
                  </div>
                </Fragment>
              );
            })}
          </div>
        </div>
      ))}
    </div>
  );
}
