// Money / number formatting. Indian convention: lakh (1e5) and crore (1e7)
// grouping, ₹ prefix, comma-separated (en-IN locale).

const EN_IN = "en-IN";

/** Plain comma-grouped number, no currency symbol. */
export function num(v: number | null | undefined, digits = 2): string {
  if (v == null || !Number.isFinite(v)) return "–";
  return v.toLocaleString(EN_IN, { maximumFractionDigits: digits });
}

/** Full rupee value, comma-grouped: ₹12,34,567. */
export function inr(v: number | null | undefined, digits = 0): string {
  if (v == null || !Number.isFinite(v)) return "–";
  const neg = v < 0;
  const s = Math.abs(v).toLocaleString(EN_IN, { maximumFractionDigits: digits });
  return `${neg ? "-" : ""}₹${s}`;
}

/** Compact rupee value for tight spots: ₹1.23 Cr / ₹4.56 L / ₹7,890. */
export function inrCompact(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return "–";
  const neg = v < 0;
  const a = Math.abs(v);
  let body: string;
  if (a >= 1e7) body = `${(a / 1e7).toLocaleString(EN_IN, { maximumFractionDigits: 2 })} Cr`;
  else if (a >= 1e5) body = `${(a / 1e5).toLocaleString(EN_IN, { maximumFractionDigits: 2 })} L`;
  else body = a.toLocaleString(EN_IN, { maximumFractionDigits: 0 });
  return `${neg ? "-" : ""}₹${body}`;
}

/** Compact plain count: 1.2Cr / 3.4L / 5,678 (for volume / OI). */
export function countCompact(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return "–";
  const a = Math.abs(v);
  if (a >= 1e7) return `${(v / 1e7).toFixed(2)}Cr`;
  if (a >= 1e5) return `${(v / 1e5).toFixed(2)}L`;
  return v.toLocaleString(EN_IN);
}

/** Signed percent: +1.23% / -0.45%. */
export function pctSigned(v: number | null | undefined, digits = 2): string {
  if (v == null || !Number.isFinite(v)) return "–";
  return `${v >= 0 ? "+" : ""}${v.toFixed(digits)}%`;
}
