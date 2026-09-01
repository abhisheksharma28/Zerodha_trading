# Zerodha Kite Connect API — Research Notes

Source of truth: official docs at https://kite.trade/docs/connect/v3/, the Kite Connect developer
forum (https://kite.trade/forum), and Zerodha's support portal (https://support.zerodha.com). Last
verified 2026-09-01. Kite Connect is versioned (`v3`); always re-check the live docs before relying
on anything here for production trading, since rate limits and regulatory requirements have changed
more than once in 2024-2026 and will keep changing.

This document is the design source of truth for `backend/app/brokers/zerodha/*`. Anywhere the API
has a hard limitation, the platform is designed around it rather than assuming it away — see
"Design implications" at the end of each section.

---

## 1. Authentication & login flow

Kite Connect uses a three-legged OAuth-like flow. There is no username/password grant available to
the API directly — a human must complete login (including 2FA/TOTP) in a browser.

1. **App registration**: Register an app at developers.kite.trade to get an `api_key` and
   `api_secret`. A registered **redirect URL** receives the login callback.
2. **Login redirect**: Send the user to
   `https://kite.zerodha.com/connect/login?v=3&api_key=<api_key>`. The user logs in with their
   Zerodha credentials + 2FA TOTP (2FA is mandatory on the account).
3. **Request token**: On success, Zerodha redirects to the app's redirect URL with a `request_token`
   query parameter (and `action=login`, `status=success`). This token is short-lived and single-use.
4. **Token exchange**: `POST /session/token` with `api_key`, `request_token`, and a `checksum` =
   `SHA-256(api_key + request_token + api_secret)`. Response contains the `access_token` (plus
   `public_token`, `refresh_token` field is not usable for silent refresh — see below).
5. **Using the token**: Every subsequent REST call sends header `Authorization: token
   <api_key>:<access_token>` and `X-Kite-Version: 3`.
6. **Expiry**: The `access_token` is valid until **6 AM IST the next day** (a SEBI/exchange
   regulatory requirement, not a rolling TTL) — or earlier if invalidated via `DELETE
   /session/token` or a master logout from Kite Web. **There is no refresh-token flow that avoids
   human login** — a human (or a stored, automated TOTP secret) must complete the browser login
   again every trading day.
7. **api_secret handling**: Zerodha explicitly warns the `api_secret` must never be embedded in a
   mobile/desktop client — it must stay server-side. For a single-user local platform, the secret
   lives only in the backend's `.env`, never in the frontend bundle.

**Design implications**
- The daily-expiry design means **live/paper trading requires a same-day re-auth step** every
  trading morning before market open. The backend exposes `GET /api/v1/broker/login-url` and
  `POST /api/v1/broker/session` (accepts the `request_token` the user pastes back after completing
  login in a browser) — there is no way to fully automate this away without storing the user's
  Zerodha password/TOTP secret, which this platform does **not** do by default.
- `access_token` is stored encrypted at rest (see `core/security.py`), scoped per broker profile,
  and never returned to the frontend in API responses (the frontend only ever learns "connected /
  not connected" + expiry time).
- All broker calls funnel through a single `KiteSession` object that raises a typed
  `BrokerAuthExpiredError` on a `403`/`TokenException`, which the execution layer maps to "pause
  live/paper deployments and alert" rather than silently retrying with stale credentials.

---

## 2. REST API surface used by this platform

Base URL: `https://api.kite.trade`. All docs at `https://kite.trade/docs/connect/v3/<section>/`.

| Area | Endpoints | Notes |
|---|---|---|
| User | `GET /user/profile`, `GET /user/margins` | Profile + funds/margins per segment |
| Orders | `POST/PUT/DELETE /orders/:variety`, `GET /orders`, `GET /orders/:order_id`, `GET /trades` | Core order lifecycle |
| GTT | `POST/PUT/DELETE /gtt/triggers`, `GET /gtt/triggers` | Good-till-triggered conditional orders |
| Portfolio | `GET /portfolio/positions`, `GET /portfolio/holdings` | Live positions/holdings snapshot |
| Margins | `POST /margins/orders`, `POST /margins/basket`, `POST /charges/orders` | Pre-trade margin & charge estimation |
| Market quotes | `GET /quote`, `GET /quote/ohlc`, `GET /quote/ltp` | Snapshot quotes, rate-limited to 1 req/s |
| Historical data | `GET /instruments/historical/:instrument_token/:interval` | Candle history for backtesting |
| Instruments | `GET /instruments`, `GET /instruments/:exchange` | Full instrument dump (CSV), refresh daily |
| WebSocket | `wss://ws.kite.trade` | Live ticks + order postbacks |

### Orders
- Required fields: `tradingsymbol`, `exchange`, `transaction_type` (BUY/SELL), `order_type`
  (MARKET/LIMIT/SL/SL-M), `quantity`, `product` (CNC/MIS/NRML/MTF), `validity` (DAY/IOC/TTL).
- Varieties: `regular`, `amo` (after-market), `co` (cover order), `iceberg`, `auction`.
- Exchanges/segments: NSE, BSE (equity), NFO, BFO (F&O), CDS, BCD (currency), MCX (commodity).
- Status lifecycle: `PUT ORDER REQ RECEIVED` → RMS validation → `OPEN`/`VALIDATION PENDING` →
  exchange ack → `COMPLETE` / `REJECTED` / `CANCELLED`. Also `MODIFY PENDING`,
  `CANCEL PENDING`, `TRIGGER PENDING` (for SL/GTT).
- Max **25 modifications per order** (exchange-enforced).
- **Market protection is now mandatory** on MARKET and SL-M orders (see §4) — the platform always
  sets an explicit protection value, never `0`.

### Historical data (backtesting data source)
- Intervals: `minute, 3minute, 5minute, 10minute, 15minute, 30minute, 60minute, day`.
- Response rows: `[timestamp, open, high, low, close, volume]` (+ `oi` as a 7th field if
  `oi=1` and the instrument supports open interest).
- `continuous=1` stitches expired NFO/MCX futures contracts into one continuous series — needed for
  multi-year futures backtests.
- No documented hard cap on total range, but in practice large minute-level pulls must be chunked
  (see rate limits) and the platform should cache pulled candles locally rather than re-fetching.

**Design implications**
- The `market_data/` module treats Kite historical data as a **cache-through source**, not a live
  dependency: pulled candles land in Postgres (or a columnar store later) keyed by
  `(instrument_token, interval)`, so backtests never re-hit the API for already-fetched ranges and
  the platform still functions (for backtesting) if Kite is down or the data plan lapses.
- Because live quotes/candles require the paid "Connect" data plan (₹500/month, see §6), the
  platform must degrade gracefully — backtesting on already-cached data keeps working even if the
  live data subscription is off; only sim/paper/live deployments that need live ticks require it.

---

## 3. WebSocket streaming

- Endpoint: `wss://ws.kite.trade?api_key=<key>&access_token=<token>`.
- **Up to 3 WebSocket connections per API key**, each subscribing to **up to 3000 instruments**.
- Subscribe/unsubscribe/set-mode via small JSON control messages, e.g.
  `{"a": "subscribe", "v": [408065, 884737]}`.
- Modes: `ltp` (8 bytes/packet — LTP only), `quote` (44 bytes — OHLC+volume, no depth), `full`
  (184 bytes — adds 5-level market depth). Ticks arrive as a single binary frame containing one or
  more concatenated packets; a 1-byte heartbeat is sent periodically to keep idle connections alive.
- **Order updates (postbacks) are pushed on the same WebSocket** as JSON text frames
  (`{"type": "order", "data": {...}}`), in addition to (optionally) HTTP postback webhooks — so a
  single persistent connection carries both market data and the user's own order-state changes.
- No documented automatic reconnect from Zerodha's client — the consumer is responsible for
  detecting a dropped socket and reconnecting with backoff, then re-subscribing.

**Design implications**
- `market_data/kite_ws.py` owns exactly one long-lived WebSocket per broker session (a singleton
  per process, not per-strategy), fans ticks out internally (Redis pub/sub) to however many
  strategies are running — this respects the 3-connection ceiling even if dozens of strategies are
  deployed simultaneously, and keeps the 3000-instrument budget centrally managed rather than each
  strategy subscribing independently.
- The same fan-out pipe delivers order postbacks to `execution/` so fills are reflected in
  positions/trade logs within the same event loop that updates strategy state — no separate polling
  of `GET /orders` in the hot path (that endpoint is reserved for reconciliation/audit, run on a
  slower timer).
- Reconnection is handled by a supervisor with exponential backoff + jitter; on reconnect it
  re-subscribes all previously-subscribed tokens and immediately reconciles positions/orders via
  REST to close any gap the socket drop may have caused, before resuming strategy signal
  processing.

---

## 4. Rate limits & order-flow constraints

| Call type | Limit |
|---|---|
| Quote (`/quote*`) | 1 request/second |
| Historical candles | 3 requests/second |
| Order placement/modification/cancellation | 10 requests/second, **400 orders/minute**, **5,000 orders/day** per user/API key |
| All other REST endpoints | 10 requests/second |
| Order modifications | 25 per order (lifetime) |
| WebSocket connections | 3 per API key, 3000 instruments per connection |

A `429` is returned when a limit is exceeded; `TokenException`/`403` means the session expired and
needs a fresh login. Full exception taxonomy: `TokenException`, `UserException`, `OrderException`,
`InputException`, `MarginException`, `HoldingException`, `NetworkException`, `DataException`,
`GeneralException`.

**Regulatory constraints layered on top (SEBI/NSE algo-trading circular, in force since 1 Apr
2026):**
- **Static IP mandatory for order placement.** Only order endpoints are IP-restricted — quotes,
  historical data, portfolio, and the WebSocket feed are reachable from any IP. Up to 2 IPs
  (primary + backup) can be registered per developer profile, and the exchange allows only **one
  change per calendar week** — so IP changes cannot be part of any deploy automation; they're a
  manual, rare, deliberate action.
- **10 orders/second is now an exchange-enforced ceiling**, not just an API courtesy limit.
  Consistently exceeding it requires formally registering the strategy with the exchange (auditor
  certificate + strategy write-up + risk-management write-up, filed through the broker) — well out
  of scope for a personal single-user platform, so the platform's own risk layer enforces an
  internal ceiling *below* 10/s and treats approaching it as a risk-limit breach, not a scaling
  problem to solve later.
- **Market protection is mandatory** on MARKET and SL-M orders; an order with protection `0` is
  rejected outright. The platform always computes and sends an explicit protection value (`-1` for
  exchange-automatic protection, unless a specific percentage is configured).
- Market orders are disallowed on the commodity (MCX) segment.

**Design implications**
- `core/config.py` requires `ZERODHA_STATIC_IP` to be documented in `.env.example` with a comment
  explaining it must match whatever is registered on developers.kite.trade — the app does **not**
  attempt to auto-detect or auto-register it.
- `risk/` implements a token-bucket limiter *tighter* than Kite's own (configurable, default well
  under 10 orders/s and under 400/min) so the platform fails safe internally before ever tripping
  the exchange-level cap or needing exchange registration.
- `brokers/zerodha/order_builder.py` is the single place order payloads are constructed; it refuses
  to build a MARKET/SL-M payload without an explicit protection value, so no code path can produce
  a protection-`0` order.
- All broker HTTP calls go through a shared client wrapper with per-endpoint-class rate limiting
  (quote/historical/order buckets are independent) and automatic, capped, jittered retry only on
  `429`/`5xx` — never on `4xx` order rejections, which are terminal and surfaced to the audit log.

---

## 5. Instruments, margins, positions, holdings

- `GET /instruments` (and `/instruments/:exchange`) returns a large CSV dump of every tradable
  instrument (token, symbol, name, expiry, strike, lot size, tick size, segment). This changes
  daily (new expiries, symbol changes) and is **not paginated or delta** — the whole file is
  re-downloaded and diffed. The platform refreshes this once daily (pre-market) into Postgres and
  strategies/backtests always resolve symbols through that local table, never by hardcoding tokens.
- `POST /margins/orders` and `/margins/basket` give pre-trade margin requirements (including
  spread/hedge benefits for baskets) — the execution layer calls these before submitting live
  orders as a pre-trade risk check, independent of the strategy's own sizing logic.
- `GET /portfolio/positions` / `/holdings` and `GET /user/margins` are the source of truth for what
  the broker thinks the account holds; the platform reconciles its internal ledger against these on
  a timer (and after every reconnect) rather than trusting its own fill bookkeeping alone.

---

## 6. Pricing / plan requirements

- **Personal (free)**: order/GTT/alert management, margin computation, portfolio — no real-time or
  historical market data.
- **Connect (₹500/month per app)**: adds WebSocket live data and historical candle API access.
  Required for anything beyond backtesting on already-cached data (i.e. required for sim/paper/live
  modes that need live prices).
- A startup/no-cost tier exists by direct arrangement with Zerodha for consumer products — not
  applicable to a personal single-user tool.

**Design implication**: `docs/ZERODHA_API_NOTES.md` (this file) and `.env.example` call out that the
**Connect** plan is a hard prerequisite for Simulation/Paper/Live modes; Backtesting mode can run
entirely offline against cached historical data pulled once while the subscription is active.

---

## 7. Summary of hard constraints this platform is designed around

1. **No silent daily re-auth** → explicit "reconnect broker" step surfaced in the UI every trading
   day; deployments in paper/live mode auto-pause (never auto-resume unattended) when the session
   expires.
2. **Static IP, manual & rate-limited to change weekly** → never dynamically managed by the app;
   documented as an operator runbook step.
3. **10 orders/sec exchange ceiling, no auto-registration path assumed** → internal limiter set
   below the exchange limit; breaches are a risk event, not a queue-and-retry event.
4. **Market protection mandatory** → enforced at the order-builder level, not just documented.
5. **3 WebSocket connections / 3000 instruments each, per API key** → a single shared, fanned-out
   market-data connection per broker session rather than per-strategy sockets.
6. **Historical data is a metered, paid resource** → cached locally, backtests never depend on live
   API availability.
7. **This is a regulated, audited activity** (algo registration thresholds, order records) → every
   order/signal/config change is captured in the immutable audit/changelog from day one (see
   `audit/` and `changelog/` modules), so the platform could support a future exchange-registration
   filing without retrofitting logging.

Sources:
- [Kite Connect API docs](https://kite.trade/docs/connect/v3/)
- [Authentication & login flow](https://kite.trade/docs/connect/v3/user/)
- [Exceptions & rate limits](https://kite.trade/docs/connect/v3/exceptions/)
- [Orders API](https://kite.trade/docs/connect/v3/orders/)
- [Historical data API](https://kite.trade/docs/connect/v3/historical/)
- [WebSocket streaming API](https://kite.trade/docs/connect/v3/websocket/)
- [Margins API](https://kite.trade/docs/connect/v3/margins/)
- [Static IP requirement](https://support.zerodha.com/category/trading-and-markets/general-kite/kite-api/articles/static-ip)
- [Kite API pricing](https://support.zerodha.com/category/trading-and-markets/general-kite/kite-api/articles/what-are-the-charges-for-kite-apis)
- [Preparing to comply with SEBI's retail algo rules (static IP, rate limits, order types)](https://kite.trade/forum/discussion/15912/preparing-to-comply-with-sebis-retail-algo-rules-static-ip-ratelimits-order-types)
- [Notes on the NSE circular prescribing operating procedures for API usage](https://kite.trade/forum/discussion/15350/notes-on-the-nse-circular-prescribing-operating-procedures-for-api-usage)
