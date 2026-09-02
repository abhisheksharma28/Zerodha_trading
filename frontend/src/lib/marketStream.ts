// Singleton browser <-> backend market-data WebSocket (`/ws/market`).
//
// Ref-counts symbol subscriptions across all components, auto-reconnects with
// backoff, and re-subscribes everything on reconnect. Components use the
// useLiveTick hook rather than touching this directly.

export interface DepthLevel {
  price: number;
  quantity: number;
  orders: number;
}

export interface LiveTick {
  type: "tick";
  token: number;
  symbol: string; // exchange-qualified, e.g. "NSE:RELIANCE"
  ltp: number | null;
  ohlc?: { open: number; high: number; low: number; close: number };
  volume?: number | null;
  avg_price?: number | null;
  buy_qty?: number | null;
  sell_qty?: number | null;
  oi?: number | null;
  depth?: { buy: DepthLevel[]; sell: DepthLevel[] };
  ts?: number | null;
}

export type StreamStatus = "idle" | "connecting" | "open" | "reconnecting";

type TickListener = (t: LiveTick) => void;

function wsUrl(): string {
  const explicit = import.meta.env.VITE_WS_BASE_URL as string | undefined;
  if (explicit) return `${explicit.replace(/\/$/, "")}/market`;
  const api =
    (import.meta.env.VITE_API_BASE_URL as string | undefined) ?? "http://localhost:8000/api/v1";
  return api.replace(/^http/, "ws").replace(/\/api\/v1\/?$/, "") + "/ws/market";
}

class MarketStream {
  private ws: WebSocket | null = null;
  private status: StreamStatus = "idle";
  private readonly tickListeners = new Map<string, Set<TickListener>>();
  private readonly statusListeners = new Set<() => void>();
  private outbox: string[] = [];
  private backoff = 1000;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;

  getStatus(): StreamStatus {
    return this.status;
  }

  onStatus(cb: () => void): () => void {
    this.statusListeners.add(cb);
    return () => this.statusListeners.delete(cb);
  }

  subscribe(symbol: string, listener: TickListener): () => void {
    let set = this.tickListeners.get(symbol);
    const isFirst = !set || set.size === 0;
    if (!set) {
      set = new Set();
      this.tickListeners.set(symbol, set);
    }
    set.add(listener);

    this.ensureConnected();
    if (isFirst) this.send({ type: "subscribe", symbols: [symbol] });

    return () => {
      const s = this.tickListeners.get(symbol);
      if (!s) return;
      s.delete(listener);
      if (s.size === 0) {
        this.tickListeners.delete(symbol);
        this.send({ type: "unsubscribe", symbols: [symbol] });
      }
    };
  }

  // --- internals ---

  private setStatus(s: StreamStatus) {
    this.status = s;
    for (const cb of this.statusListeners) cb();
  }

  private ensureConnected() {
    if (this.ws && (this.ws.readyState === WebSocket.OPEN || this.ws.readyState === WebSocket.CONNECTING))
      return;
    this.setStatus(this.status === "idle" ? "connecting" : "reconnecting");

    let ws: WebSocket;
    try {
      ws = new WebSocket(wsUrl());
    } catch {
      this.scheduleReconnect();
      return;
    }
    this.ws = ws;

    ws.onopen = () => {
      this.backoff = 1000;
      this.setStatus("open");
      const symbols = [...this.tickListeners.keys()];
      if (symbols.length) ws.send(JSON.stringify({ type: "subscribe", symbols }));
      for (const msg of this.outbox) ws.send(msg);
      this.outbox = [];
    };

    ws.onmessage = (ev) => {
      let msg: unknown;
      try {
        msg = JSON.parse(ev.data as string);
      } catch {
        return;
      }
      const m = msg as { type?: string; symbol?: string };
      if (m.type === "tick" && m.symbol) {
        const listeners = this.tickListeners.get(m.symbol);
        if (listeners) for (const l of listeners) l(msg as LiveTick);
      }
    };

    ws.onclose = () => {
      if (this.ws === ws) this.ws = null;
      if (this.tickListeners.size > 0) this.scheduleReconnect();
      else this.setStatus("idle");
    };
    ws.onerror = () => ws.close();
  }

  private scheduleReconnect() {
    if (this.reconnectTimer) return;
    this.setStatus("reconnecting");
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null;
      this.ensureConnected();
    }, this.backoff);
    this.backoff = Math.min(this.backoff * 2, 15000);
  }

  private send(obj: unknown) {
    const s = JSON.stringify(obj);
    if (this.ws && this.ws.readyState === WebSocket.OPEN) this.ws.send(s);
    else this.outbox.push(s);
  }
}

export const marketStream = new MarketStream();
