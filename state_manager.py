import random
from datetime import datetime, timedelta
import threading

# =====================================================================
# TECHNICAL INDICATORS (Pure Python, no deps)
# =====================================================================

def calculate_rsi(candles, period=14):
    """Wilder's RSI — returns list of {epoch, value}."""
    out = [{"epoch": c["epoch"], "value": 50.0} for c in candles]
    if len(candles) <= period:
        return out

    closes = [c["close"] for c in candles]
    changes = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    gains  = [max(d, 0) for d in changes]
    losses = [max(-d, 0) for d in changes]

    avg_g = sum(gains[:period]) / period
    avg_l = sum(losses[:period]) / period

    def rsi_from(ag, al):
        return 100.0 if al == 0 else 100.0 - 100.0 / (1.0 + ag / al)

    result = [{"epoch": candles[i]["epoch"], "value": 50.0} for i in range(period)]
    result.append({"epoch": candles[period]["epoch"], "value": rsi_from(avg_g, avg_l)})

    for i in range(period, len(changes)):
        avg_g = (avg_g * (period - 1) + gains[i]) / period
        avg_l = (avg_l * (period - 1) + losses[i]) / period
        result.append({"epoch": candles[i + 1]["epoch"], "value": rsi_from(avg_g, avg_l)})

    return result


def calculate_adx(candles, period=14):
    """Wilder's ADX — returns list of {epoch, value}."""
    out = [{"epoch": c["epoch"], "value": 20.0} for c in candles]
    if len(candles) <= period * 2:
        return out

    tr_list, pdm, mdm = [], [], []
    for i in range(1, len(candles)):
        h, l, pc = candles[i]["high"], candles[i]["low"], candles[i - 1]["close"]
        ph, pl = candles[i - 1]["high"], candles[i - 1]["low"]
        tr_list.append(max(h - l, abs(h - pc), abs(l - pc)))
        up, dn = h - ph, pl - l
        pdm.append(up if up > dn and up > 0 else 0.0)
        mdm.append(dn if dn > up and dn > 0 else 0.0)

    s_tr  = sum(tr_list[:period])
    s_pdm = sum(pdm[:period])
    s_mdm = sum(mdm[:period])

    dx_vals = []
    def _dx(spdm, smdm, str_):
        dip = 100 * spdm / str_ if str_ > 0 else 0
        dim = 100 * smdm / str_ if str_ > 0 else 0
        return 100 * abs(dip - dim) / (dip + dim) if (dip + dim) > 0 else 0

    dx_vals.append(_dx(s_pdm, s_mdm, s_tr))
    for i in range(period, len(tr_list)):
        s_tr  = s_tr  - s_tr  / period + tr_list[i]
        s_pdm = s_pdm - s_pdm / period + pdm[i]
        s_mdm = s_mdm - s_mdm / period + mdm[i]
        dx_vals.append(_dx(s_pdm, s_mdm, s_tr))

    if len(dx_vals) < period:
        return out

    adx_val = sum(dx_vals[:period]) / period
    result = [{"epoch": candles[i]["epoch"], "value": 20.0} for i in range(period)]
    result.append({"epoch": candles[period]["epoch"], "value": adx_val})
    for i in range(period, len(dx_vals)):
        adx_val = (adx_val * (period - 1) + dx_vals[i]) / period
        result.append({"epoch": candles[i + 1]["epoch"], "value": adx_val})

    while len(result) < len(candles):
        result.append({"epoch": candles[len(result)]["epoch"], "value": 20.0})

    return result


def get_trend(candles_h1, candles_h4):
    """
    Multi-timeframe trend detection using H1 + H4 last candle structure.
    Returns: "BUY", "SELL", or "NEUTRAL"
    """
    def _bias(candles):
        if len(candles) < 5:
            return "NEUTRAL"
        # Simple structure: compare last 5 candle highs & lows
        recent = candles[-5:]
        bullish = sum(1 for c in recent if c["is_bullish"])
        if bullish >= 4:
            return "BUY"
        elif bullish <= 1:
            return "SELL"
        return "NEUTRAL"

    h1_bias = _bias(candles_h1)
    h4_bias = _bias(candles_h4)

    if h1_bias == "BUY"  and h4_bias == "BUY":  return "BUY"
    if h1_bias == "SELL" and h4_bias == "SELL": return "SELL"
    # Partial alignment
    if h4_bias == "BUY":  return "BUY"
    if h4_bias == "SELL": return "SELL"
    return "NEUTRAL"


def check_m1_entry(candles_m1, rsi_vals, adx_vals, trend):
    """
    Entry filter on M1 using RSI + ADX + trend alignment.
    Returns: "BUY", "SELL", or None
    """
    if not candles_m1 or len(rsi_vals) < 2 or len(adx_vals) < 2:
        return None

    last_rsi = rsi_vals[-1]["value"]
    last_adx = adx_vals[-1]["value"]

    trend_strong = last_adx >= 20          # trend is meaningful
    momentum_buy  = last_rsi > 50 and last_rsi < 70   # not overbought
    momentum_sell = last_rsi < 50 and last_rsi > 30   # not oversold

    if trend == "BUY"  and trend_strong and momentum_buy:  return "BUY"
    if trend == "SELL" and trend_strong and momentum_sell: return "SELL"
    return None


# =====================================================================
# TRADING STATE MANAGER
# =====================================================================

class TradingStationState:
    def __init__(self):
        self.lock = threading.Lock()

        # Price feed
        self.last_price   = None
        self.prev_price   = None
        self.tick_direction = "■"
        self.tick_color    = "white"

        # OHLC candle histories
        self.candles_m1 = []
        self.candles_m5 = []
        self.candles_h1 = []
        self.candles_h4 = []

        # Simulated correlated assets
        self.xagusd_price = 28.450
        self.dxy_price    = 104.20
        self.us10y_yield  = 4.350

        # Signal & active trade
        self.signal_type  = None      # "BUY" | "SELL" | None
        self.signal_entry = 0.0
        self.signal_sl    = 0.0
        self.signal_tp    = 0.0
        self.signal_confidence = 0
        self.signal_reason = "Awaiting multi-TF analysis..."

        self.position_active = False
        self.position_entry  = 0.0
        self.position_size   = 0.10   # micro lot

        # Stats & history
        self.trade_history = []
        self.total_wins    = 0
        self.total_losses  = 0

        # Analysis lock: prevent re-signal immediately after a trade closes
        self._analysis_cooldown = 0

    # ------------------------------------------------------------------
    def update_price(self, price):
        with self.lock:
            if price is None:
                return
            self.prev_price = self.last_price
            self.last_price = price

            if self.prev_price is not None:
                if price > self.prev_price:
                    self.tick_direction = "▲"; self.tick_color = "green"
                    self.xagusd_price += round(random.uniform(0.001, 0.005), 3)
                    self.dxy_price    -= round(random.uniform(0.001, 0.003), 2)
                elif price < self.prev_price:
                    self.tick_direction = "▼"; self.tick_color = "red"
                    self.xagusd_price -= round(random.uniform(0.001, 0.005), 3)
                    self.dxy_price    += round(random.uniform(0.001, 0.003), 2)
                else:
                    self.tick_direction = "■"; self.tick_color = "white"

            # Cooldown counter
            if self._analysis_cooldown > 0:
                self._analysis_cooldown -= 1
                return

            if self.position_active:
                self._check_position(price)
            else:
                self._try_generate_signal(price)

    # ------------------------------------------------------------------
    def _check_position(self, price):
        """Monitor whether price hits SL or TP."""
        hit = None
        pnl = 0.0

        if self.signal_type == "BUY":
            if price >= self.signal_tp:
                hit = "WIN";  pnl = (self.signal_tp - self.position_entry) * 100
            elif price <= self.signal_sl:
                hit = "LOSS"; pnl = (self.signal_sl - self.position_entry) * 100
        else:  # SELL
            if price <= self.signal_tp:
                hit = "WIN";  pnl = (self.position_entry - self.signal_tp) * 100
            elif price >= self.signal_sl:
                hit = "LOSS"; pnl = (self.position_entry - self.signal_sl) * 100

        if hit:
            if hit == "WIN":
                self.total_wins += 1
            else:
                self.total_losses += 1

            self.trade_history.append({
                "time":   datetime.now().strftime("%H:%M:%S"),
                "type":   self.signal_type,
                "entry":  f"{self.position_entry:.2f}",
                "exit":   f"{price:.2f}",
                "pnl":    f"{pnl:+.2f}",
                "result": hit
            })
            if len(self.trade_history) > 15:
                self.trade_history.pop(0)

            # Close position — clear signal lines
            self.position_active = False
            self.signal_type     = None
            self.signal_entry    = 0.0
            self.signal_sl       = 0.0
            self.signal_tp       = 0.0
            self.signal_confidence = 0
            self.signal_reason   = f"Trade closed ({hit}). Re-analysing..."

            # Brief cooldown before next signal
            self._analysis_cooldown = 5

    # ------------------------------------------------------------------
    def _try_generate_signal(self, price):
        """Generate a signal using M1 entry + H1/H4 trend confirmation."""
        if not self.candles_m1 or len(self.candles_m1) < 30:
            self.signal_reason = "Waiting for M1 candle data..."
            return

        # Compute indicators on M1
        rsi_vals = calculate_rsi(self.candles_m1, 14)
        adx_vals = calculate_adx(self.candles_m1, 14)

        # Multi-TF trend
        trend = get_trend(self.candles_h1, self.candles_h4)

        if trend == "NEUTRAL":
            self.signal_reason = "H1/H4 trend: NEUTRAL — waiting for alignment..."
            return

        # M1 entry filter
        direction = check_m1_entry(self.candles_m1, rsi_vals, adx_vals, trend)
        if not direction:
            last_rsi = rsi_vals[-1]["value"] if rsi_vals else 50
            last_adx = adx_vals[-1]["value"] if adx_vals else 0
            self.signal_reason = (
                f"Waiting: M1 RSI={last_rsi:.1f}, ADX={last_adx:.1f}, "
                f"Trend={trend}"
            )
            return

        # Risk management — ATR-based SL/TP from M1
        if len(self.candles_m1) >= 14:
            atr = sum(
                c["high"] - c["low"]
                for c in self.candles_m1[-14:]
            ) / 14
        else:
            atr = 0.5

        sl_dist = max(round(atr * 1.5, 2), 0.30)
        tp_dist = sl_dist * 2.0   # RR 1:2

        if direction == "BUY":
            sl = round(price - sl_dist, 2)
            tp = round(price + tp_dist, 2)
        else:
            sl = round(price + sl_dist, 2)
            tp = round(price - tp_dist, 2)

        last_rsi = rsi_vals[-1]["value"] if rsi_vals else 50
        last_adx = adx_vals[-1]["value"] if adx_vals else 0
        conf = min(95, int(50 + last_adx * 0.8 + abs(last_rsi - 50) * 0.4))

        self.signal_type       = direction
        self.signal_entry      = round(price, 2)
        self.signal_sl         = sl
        self.signal_tp         = tp
        self.signal_confidence = conf
        self.signal_reason     = (
            f"{'H1+H4 Uptrend' if direction=='BUY' else 'H1+H4 Downtrend'} | "
            f"M1 RSI={last_rsi:.1f} | ADX={last_adx:.1f} | RR 1:2"
        )
        self.position_entry  = round(price, 2)
        self.position_active = True

    # ------------------------------------------------------------------
    def set_candles(self, tf, candles_list):
        with self.lock:
            attr = f"candles_{tf.lower()}"
            setattr(self, attr, list(candles_list))

    # ------------------------------------------------------------------
    def get_serializable_state(self, calendar_events):
        with self.lock:
            price = self.last_price or 0.0

            # Floating PnL
            pnl_val = pnl_pct = 0.0
            if self.position_active and self.position_entry > 0 and price > 0:
                diff = (price - self.position_entry) if self.signal_type == "BUY" \
                       else (self.position_entry - price)
                pnl_val = diff * 100
                pnl_pct = (diff / self.position_entry) * 100

            # Win rate
            total_closed = self.total_wins + self.total_losses
            win_rate = (self.total_wins / total_closed * 100) if total_closed > 0 else 0.0

            # Indicators (computed from live candle arrays)
            rsi_m1 = calculate_rsi(self.candles_m1)
            adx_m1 = calculate_adx(self.candles_m1)
            rsi_m5 = calculate_rsi(self.candles_m5)
            adx_m5 = calculate_adx(self.candles_m5)
            rsi_h1 = calculate_rsi(self.candles_h1)
            adx_h1 = calculate_adx(self.candles_h1)
            rsi_h4 = calculate_rsi(self.candles_h4)
            adx_h4 = calculate_adx(self.candles_h4)

            # Trend for display
            trend = get_trend(self.candles_h1, self.candles_h4)

            return {
                "last_price":     self.last_price,
                "tick_direction": self.tick_direction,
                "tick_color":     self.tick_color,

                "watchlist": [
                    {"symbol": "XAUUSD",  "price": f"{price:.2f}",
                     "change": "+0.28%" if self.tick_direction == "▲" else "-0.15%",
                     "direction": self.tick_direction, "color": self.tick_color},
                    {"symbol": "XAGUSD",  "price": f"{self.xagusd_price:.3f}",
                     "change": "+0.12%" if self.tick_direction == "▲" else "-0.08%",
                     "direction": "▲" if self.tick_direction == "▲" else "▼",
                     "color": self.tick_color},
                    {"symbol": "DXY",     "price": f"{self.dxy_price:.2f}",
                     "change": "-0.05%" if self.tick_direction == "▲" else "+0.08%",
                     "direction": "▼" if self.tick_direction == "▲" else "▲",
                     "color": "red" if self.tick_direction == "▲" else "green"},
                    {"symbol": "US10Y",   "price": f"{self.us10y_yield:.3f}%",
                     "change": "0.00%", "direction": "■", "color": "white"}
                ],

                "candles_m1": self.candles_m1,  "rsi_m1": rsi_m1, "adx_m1": adx_m1,
                "candles_m5": self.candles_m5,  "rsi_m5": rsi_m5, "adx_m5": adx_m5,
                "candles_h1": self.candles_h1,  "rsi_h1": rsi_h1, "adx_h1": adx_h1,
                "candles_h4": self.candles_h4,  "rsi_h4": rsi_h4, "adx_h4": adx_h4,

                "market_trend": trend,

                "signal": {
                    "active":      self.position_active,
                    "type":        self.signal_type or "NONE",
                    "entry":       f"{self.signal_entry:.2f}",
                    "sl":          f"{self.signal_sl:.2f}",
                    "tp":          f"{self.signal_tp:.2f}",
                    "confidence":  self.signal_confidence,
                    "reason":      self.signal_reason
                },

                "portfolio": {
                    "active":      self.position_active,
                    "size":        f"{self.position_size:.2f}",
                    "entry":       f"{self.position_entry:.2f}",
                    "market":      f"{price:.2f}",
                    "pnl":         f"{pnl_val:+.2f}",
                    "pnl_percent": f"{pnl_pct:+.3f}%",
                    "pnl_color":   "green" if pnl_val >= 0 else "red",
                    "status":      "ACTIVE" if self.position_active else "CLOSED"
                },

                "stats": {
                    "total_trades": total_closed,
                    "total_wins":   self.total_wins,
                    "total_losses": self.total_losses,
                    "win_rate":     f"{win_rate:.1f}%"
                },

                "trade_history": list(reversed(self.trade_history)),
                "calendar":      calendar_events
            }


# =====================================================================
# ECONOMIC CALENDAR
# =====================================================================

class EconomicCalendar:
    def __init__(self):
        self.init_time = datetime.now()
        self.events = [
            {"name": "US Core CPI (YoY)",          "offset_minutes": 15,  "forecast": "BULLISH", "volatility": "VERY HIGH"},
            {"name": "US Non-Farm Payrolls (NFP)",  "offset_minutes": 45,  "forecast": "BEARISH", "volatility": "CRITICAL"},
            {"name": "FOMC Interest Rate Decision", "offset_minutes": 120, "forecast": "BULLISH", "volatility": "CRITICAL"},
            {"name": "US GDP Growth Rate (QoQ)",    "offset_minutes": 240, "forecast": "BULLISH", "volatility": "HIGH"},
            {"name": "Initial Jobless Claims",      "offset_minutes": 480, "forecast": "BEARISH", "volatility": "HIGH"},
        ]

    def get_upcoming_events(self):
        now = datetime.now()
        result = []
        for e in self.events:
            et = self.init_time + timedelta(minutes=e["offset_minutes"])
            if now > et + timedelta(minutes=1):
                e["offset_minutes"] += 600
                et = self.init_time + timedelta(minutes=e["offset_minutes"])
            diff = int((et - now).total_seconds())
            if diff < 0:
                cd = "RELEASING..."
            else:
                cd = f"{diff//3600:02d}h {(diff%3600)//60:02d}m {diff%60:02d}s"
            result.append({
                "name": e["name"], "time": et.strftime("%H:%M:%S"),
                "countdown": cd, "forecast": e["forecast"], "volatility": e["volatility"]
            })
        return result


state    = TradingStationState()
calendar = EconomicCalendar()
