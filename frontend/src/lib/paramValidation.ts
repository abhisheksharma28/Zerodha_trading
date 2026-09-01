import type { TemplateParamSpec } from "@/types/api";

type Schema = Record<string, TemplateParamSpec>;
type Values = Record<string, unknown>;

export function paramError(spec: TemplateParamSpec, value: unknown): string | null {
  if (spec.type === "integer" || spec.type === "number") {
    const n = Number(value);
    if (Number.isNaN(n)) return "must be a number";
    if (spec.type === "integer" && !Number.isInteger(n)) return "must be a whole number";
    if (spec.min != null && n < spec.min) return `min ${spec.min}`;
    if (spec.max != null && n > spec.max) return `max ${spec.max}`;
  }
  if (spec.type === "enum" && spec.choices && !spec.choices.includes(value)) {
    return "invalid choice";
  }
  return null;
}

export function schemaErrors(schema: Schema, values: Values): Record<string, string> {
  const out: Record<string, string> = {};
  for (const [name, spec] of Object.entries(schema)) {
    const err = paramError(spec, values[name] ?? spec.default);
    if (err) out[name] = err;
  }
  return out;
}
