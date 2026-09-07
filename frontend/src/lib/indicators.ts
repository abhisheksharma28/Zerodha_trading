/** Pure, causal indicator maths for the charting screen. Each function takes
 *  the candle array and returns points aligned to candle `time`, skipping the
 *  warm-up region so lightweight-charts doesn't draw a leading flat line. */

export interface Candle {
  time: number;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}
export interface LinePoint {
  time: number;
  value: number;
}

export function sma(candles: Candle[], period: number): LinePoint[] {
  const out: LinePoint[] = [];
  let sum = 0;
  for (let i = 0; i < candles.length; i++) {
    sum += candles[i].close;
    if (i >= period) sum -= candles[i - period].close;
    if (i >= period - 1) out.push({ time: candles[i].time, value: sum / period });
  }
  return out;
}

export function ema(candles: Candle[], period: number): LinePoint[] {
  if (candles.length < period) return [];
  const k = 2 / (period + 1);
  const out: LinePoint[] = [];
  let prev = candles.slice(0, period).reduce((a, c) => a + c.close, 0) / period;
  out.push({ time: candles[period - 1].time, value: prev });
  for (let i = period; i < candles.length; i++) {
    prev = candles[i].close * k + prev * (1 - k);
    out.push({ time: candles[i].time, value: prev });
  }
  return out;
}

/** Rolling VWAP that resets at the start of each trading day (detected by a
 *  date change in the timestamp). Good enough for intraday charts. */
export function vwap(candles: Candle[]): LinePoint[] {
  const out: LinePoint[] = [];
  let day = "";
  let pv = 0;
  let vol = 0;
  for (const c of candles) {
    const d = new Date(c.time * 1000).toISOString().slice(0, 10);
    if (d !== day) {
      day = d;
      pv = 0;
      vol = 0;
    }
    const typical = (c.high + c.low + c.close) / 3;
    pv += typical * c.volume;
    vol += c.volume;
    if (vol > 0) out.push({ time: c.time, value: pv / vol });
  }
  return out;
}

export function bollinger(
  candles: Candle[],
  period = 20,
  mult = 2,
): { upper: LinePoint[]; middle: LinePoint[]; lower: LinePoint[] } {
  const upper: LinePoint[] = [];
  const middle: LinePoint[] = [];
  const lower: LinePoint[] = [];
  for (let i = period - 1; i < candles.length; i++) {
    const win = candles.slice(i - period + 1, i + 1).map((c) => c.close);
    const m = win.reduce((a, v) => a + v, 0) / period;
    const sd = Math.sqrt(win.reduce((a, v) => a + (v - m) ** 2, 0) / period);
    const t = candles[i].time;
    middle.push({ time: t, value: m });
    upper.push({ time: t, value: m + mult * sd });
    lower.push({ time: t, value: m - mult * sd });
  }
  return { upper, middle, lower };
}

export function rsi(candles: Candle[], period = 14): LinePoint[] {
  if (candles.length < period + 1) return [];
  const out: LinePoint[] = [];
  let gain = 0;
  let loss = 0;
  for (let i = 1; i <= period; i++) {
    const ch = candles[i].close - candles[i - 1].close;
    if (ch >= 0) gain += ch;
    else loss -= ch;
  }
  gain /= period;
  loss /= period;
  const push = (i: number) => {
    const rs = loss === 0 ? 100 : gain / loss;
    out.push({ time: candles[i].time, value: loss === 0 ? 100 : 100 - 100 / (1 + rs) });
  };
  push(period);
  for (let i = period + 1; i < candles.length; i++) {
    const ch = candles[i].close - candles[i - 1].close;
    gain = (gain * (period - 1) + Math.max(ch, 0)) / period;
    loss = (loss * (period - 1) + Math.max(-ch, 0)) / period;
    push(i);
  }
  return out;
}

export function macd(
  candles: Candle[],
  fast = 12,
  slow = 26,
  signal = 9,
): { macd: LinePoint[]; signal: LinePoint[]; hist: LinePoint[] } {
  const emaLine = (period: number) => {
    const k = 2 / (period + 1);
    const res: number[] = [];
    let prev = candles[0]?.close ?? 0;
    candles.forEach((c, i) => {
      prev = i === 0 ? c.close : c.close * k + prev * (1 - k);
      res.push(prev);
    });
    return res;
  };
  const f = emaLine(fast);
  const s = emaLine(slow);
  const macdArr = candles.map((c, i) => ({ time: c.time, value: f[i] - s[i] }));
  // signal = EMA of macd
  const k = 2 / (signal + 1);
  let prev = macdArr[0]?.value ?? 0;
  const sig = macdArr.map((p, i) => {
    prev = i === 0 ? p.value : p.value * k + prev * (1 - k);
    return { time: p.time, value: prev };
  });
  const hist = macdArr.map((p, i) => ({ time: p.time, value: p.value - sig[i].value }));
  const from = slow;
  return { macd: macdArr.slice(from), signal: sig.slice(from), hist: hist.slice(from) };
}

/** Standard (floor-trader) pivot points. Each level is derived from the
 *  PREVIOUS calendar period's high/low/close and held flat across every
 *  candle of the CURRENT period, so it steps once per period boundary.
 *  Candle `time` is the IST-shifted epoch the backend emits, so the UTC
 *  calendar accessors below bucket by the NSE trading day / week / month. */
export type PivotBasis = "D" | "W" | "M";

export interface PivotLevels {
  p: LinePoint[];
  r1: LinePoint[];
  r2: LinePoint[];
  r3: LinePoint[];
  s1: LinePoint[];
  s2: LinePoint[];
  s3: LinePoint[];
}

function pivotBucketKey(t: number, basis: PivotBasis): string {
  const d = new Date(t * 1000);
  const y = d.getUTCFullYear();
  if (basis === "M") return `${y}-${d.getUTCMonth()}`;
  if (basis === "W") {
    const dow = (d.getUTCDay() + 6) % 7; // Monday = 0
    return `w${Date.UTC(y, d.getUTCMonth(), d.getUTCDate() - dow)}`;
  }
  return `${y}-${d.getUTCMonth()}-${d.getUTCDate()}`;
}

export function pivotPoints(candles: Candle[], basis: PivotBasis = "D"): PivotLevels {
  const out: PivotLevels = { p: [], r1: [], r2: [], r3: [], s1: [], s2: [], s3: [] };
  if (candles.length === 0) return out;

  const buckets: Candle[][] = [];
  let key = "";
  for (const c of candles) {
    const k = pivotBucketKey(c.time, basis);
    if (k !== key) {
      buckets.push([]);
      key = k;
    }
    buckets[buckets.length - 1].push(c);
  }

  for (let i = 1; i < buckets.length; i++) {
    const prev = buckets[i - 1];
    const h = Math.max(...prev.map((c) => c.high));
    const l = Math.min(...prev.map((c) => c.low));
    const c = prev[prev.length - 1].close;
    const p = (h + l + c) / 3;
    const range = h - l;
    const lv = {
      p,
      r1: 2 * p - l,
      s1: 2 * p - h,
      r2: p + range,
      s2: p - range,
      r3: h + 2 * (p - l),
      s3: l - 2 * (h - p),
    };
    for (const bar of buckets[i]) {
      out.p.push({ time: bar.time, value: lv.p });
      out.r1.push({ time: bar.time, value: lv.r1 });
      out.r2.push({ time: bar.time, value: lv.r2 });
      out.r3.push({ time: bar.time, value: lv.r3 });
      out.s1.push({ time: bar.time, value: lv.s1 });
      out.s2.push({ time: bar.time, value: lv.s2 });
      out.s3.push({ time: bar.time, value: lv.s3 });
    }
  }
  return out;
}

export function atr(candles: Candle[], period = 14): LinePoint[] {
  if (candles.length < period + 1) return [];
  const tr: number[] = [];
  for (let i = 1; i < candles.length; i++) {
    const c = candles[i];
    const pc = candles[i - 1].close;
    tr.push(Math.max(c.high - c.low, Math.abs(c.high - pc), Math.abs(c.low - pc)));
  }
  const out: LinePoint[] = [];
  let a = tr.slice(0, period).reduce((x, v) => x + v, 0) / period;
  out.push({ time: candles[period].time, value: a });
  for (let i = period; i < tr.length; i++) {
    a = (a * (period - 1) + tr[i]) / period;
    out.push({ time: candles[i + 1].time, value: a });
  }
  return out;
}
