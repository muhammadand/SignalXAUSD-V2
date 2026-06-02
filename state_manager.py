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


def calculate_ema(candles, period):
    """Exponential Moving Average (EMA) — returns list of {epoch, value}."""
    out = [{"epoch": c["epoch"], "value": c["close"]} for c in candles]
    if len(candles) < period:
        return out

    closes = [c["close"] for c in candles]
    sma = sum(closes[:period]) / period
    
    result = [{"epoch": candles[i]["epoch"], "value": closes[i]} for i in range(period - 1)]
    result.append({"epoch": candles[period - 1]["epoch"], "value": sma})
    
    k = 2.0 / (period + 1.0)
    current_ema = sma
    
    for i in range(period, len(candles)):
        current_ema = (closes[i] * k) + (current_ema * (1.0 - k))
        result.append({"epoch": candles[i]["epoch"], "value": current_ema})
        
    return result


def calculate_vwap(candles):
    """Intraday VWAP - resets cumulative sums on day boundary."""
    out = [{"epoch": c["epoch"], "value": c["close"]} for c in candles]
    if not candles:
        return out
        
    cum_tp_vol = 0.0
    cum_vol = 0.0
    last_date = None
    
    result = []
    for c in candles:
        epoch = c["epoch"]
        dt = datetime.fromtimestamp(epoch)
        curr_date = dt.date()
        
        if last_date is not None and curr_date != last_date:
            cum_tp_vol = 0.0
            cum_vol = 0.0
            
        last_date = curr_date
        
        tp = (c["high"] + c["low"] + c["close"]) / 3.0
        vol = float(c.get("volume", c.get("count", 1.0)))
        if vol <= 0:
            vol = 1.0
            
        cum_tp_vol += tp * vol
        cum_vol += vol
        
        vwap_val = cum_tp_vol / cum_vol if cum_vol > 0 else tp
        result.append({"epoch": epoch, "value": vwap_val})
        
    return result


def calculate_atr(candles, period=14):
    """Average True Range (ATR) — returns list of {epoch, value}."""
    out = [{"epoch": c["epoch"], "value": 0.1} for c in candles]
    if len(candles) < 2:
        return out

    tr_list = []
    for i in range(len(candles)):
        if i == 0:
            tr_list.append(candles[i]["high"] - candles[i]["low"])
        else:
            h, l, pc = candles[i]["high"], candles[i]["low"], candles[i - 1]["close"]
            tr_list.append(max(h - l, abs(h - pc), abs(l - pc)))

    if len(candles) <= period:
        return out

    atr_val = sum(tr_list[:period]) / period
    result = [{"epoch": candles[i]["epoch"], "value": 0.1} for i in range(period)]
    result.append({"epoch": candles[period]["epoch"], "value": atr_val})

    for i in range(period, len(tr_list) - 1):
        atr_val = (atr_val * (period - 1) + tr_list[i + 1]) / period
        result.append({"epoch": candles[i + 1]["epoch"], "value": atr_val})

    while len(result) < len(candles):
        result.append({"epoch": candles[len(result)]["epoch"], "value": atr_val})

    return result


def calculate_support_resistance(candles, window=15, num_levels=2):
    """Find key support & resistance levels based on local extrema in candle history."""
    if len(candles) < window * 2:
        return [], []

    highs = [c["high"] for c in candles]
    lows = [c["low"] for c in candles]

    res_levels = []
    sup_levels = []

    for i in range(window, len(candles) - window):
        curr_high = highs[i]
        curr_low = lows[i]

        if all(curr_high >= highs[j] for j in range(i - window, i + window + 1)):
            res_levels.append(curr_high)

        if all(curr_low <= lows[j] for j in range(i - window, i + window + 1)):
            sup_levels.append(curr_low)

    current_price = candles[-1]["close"]

    res_levels = sorted(list(set(round(r, 2) for r in res_levels)))
    sup_levels = sorted(list(set(round(s, 2) for s in sup_levels)))

    resistances = [r for r in res_levels if r > current_price]
    supports = [s for s in sup_levels if s < current_price]

    resistances = resistances[:num_levels]
    supports = supports[-num_levels:]

    return supports, resistances


def get_trend(candles_m15, candles_h1):
    """
    Multi-timeframe trend detection using M15 + H1 last candle structure.
    Returns: "BUY", "SELL", or "NEUTRAL"
    """
    def _bias(candles):
        if len(candles) < 5:
            return "NEUTRAL"
        recent = candles[-5:]
        bullish = sum(1 for c in recent if c["is_bullish"])
        if bullish >= 4:
            return "BUY"
        elif bullish <= 1:
            return "SELL"
        return "NEUTRAL"

    m15_bias = _bias(candles_m15)
    h1_bias = _bias(candles_h1)

    if m15_bias == "BUY" and h1_bias == "BUY":
        return "BUY"
    if m15_bias == "SELL" and h1_bias == "SELL":
        return "SELL"
    return "NEUTRAL"


def check_m1_entry(candles_m1, rsi_vals, adx_vals, ema9_vals, ema21_vals, vwap_vals, trend):
    """
    Entry filter on M1 using RSI + ADX + EMA Cross + VWAP + trend alignment.
    Returns: "BUY", "SELL", or None
    """
    if not candles_m1 or len(rsi_vals) < 2 or len(adx_vals) < 2 or len(ema9_vals) < 2 or len(ema21_vals) < 2 or len(vwap_vals) < 2:
        return None

    last_close = candles_m1[-1]["close"]
    last_rsi = rsi_vals[-1]["value"]
    last_adx = adx_vals[-1]["value"]
    last_ema9 = ema9_vals[-1]["value"]
    last_ema21 = ema21_vals[-1]["value"]
    last_vwap = vwap_vals[-1]["value"]

    trend_strong = last_adx >= 20          # trend is meaningful
    above_vwap = last_close > last_vwap
    below_vwap = last_close < last_vwap
    ema_bullish = last_ema9 > last_ema21
    ema_bearish = last_ema9 < last_ema21
    rsi_buy = last_rsi > 50 and last_rsi < 70
    rsi_sell = last_rsi < 50 and last_rsi > 30

    if trend == "BUY" and trend_strong and above_vwap and ema_bullish and rsi_buy:
        return "BUY"
    if trend == "SELL" and trend_strong and below_vwap and ema_bearish and rsi_sell:
        return "SELL"
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
        self.candles_m15 = []
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
        """Generate a signal using M1 entry + M15/H1 trend confirmation + ADX + VWAP + EMA + RSI."""
        if not self.candles_m1 or len(self.candles_m1) < 30:
            self.signal_reason = "Waiting for M1 candle data..."
            return

        if not self.candles_m15 or len(self.candles_m15) < 10:
            self.signal_reason = "Waiting for M15 candle data..."
            return

        if not self.candles_h1 or len(self.candles_h1) < 10:
            self.signal_reason = "Waiting for H1 candle data..."
            return

        # Compute indicators on M1
        rsi_vals = calculate_rsi(self.candles_m1, 14)
        adx_vals = calculate_adx(self.candles_m1, 14)
        ema9_vals = calculate_ema(self.candles_m1, 9)
        ema21_vals = calculate_ema(self.candles_m1, 21)
        vwap_vals = calculate_vwap(self.candles_m1)

        # Multi-TF trend (M15 and H1)
        trend = get_trend(self.candles_m15, self.candles_h1)

        if trend == "NEUTRAL":
            self.signal_reason = "M15/H1 trend: NEUTRAL (not aligned) — scanning..."
            return

        # M1 entry filter
        direction = check_m1_entry(self.candles_m1, rsi_vals, adx_vals, ema9_vals, ema21_vals, vwap_vals, trend)
        if not direction:
            last_rsi = rsi_vals[-1]["value"] if rsi_vals else 50
            last_adx = adx_vals[-1]["value"] if adx_vals else 0
            self.signal_reason = (
                f"Scanning: M1 RSI={last_rsi:.1f}, ADX={last_adx:.1f}, "
                f"Trend(M15/H1)={trend} | Waiting for VWAP/EMA/RSI triggers"
            )
            return

        # Risk management — ATR-based SL/TP from M1
        atr_vals = calculate_atr(self.candles_m1, 14)
        atr = atr_vals[-1]["value"] if atr_vals else 0.5
        if atr <= 0.01:
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
            f"{'M15+H1 Uptrend' if direction=='BUY' else 'M15+H1 Downtrend'} | "
            f"M1 RSI={last_rsi:.1f} | ADX={last_adx:.1f} | VWAP/EMA aligned | RR 1:2.0"
        )
        self.position_entry  = round(price, 2)
        self.position_active = True

    # ------------------------------------------------------------------
    def set_candles(self, tf, candles_list):
        with self.lock:
            attr = f"candles_{tf.lower()}"
            setattr(self, attr, list(candles_list))

    # ------------------------------------------------------------------
    def get_serializable_state(self):
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

            # Indicators & overlays (computed from live candle arrays)
            rsi_m1 = calculate_rsi(self.candles_m1)
            adx_m1 = calculate_adx(self.candles_m1)
            ema9_m1 = calculate_ema(self.candles_m1, 9)
            ema21_m1 = calculate_ema(self.candles_m1, 21)
            vwap_m1 = calculate_vwap(self.candles_m1)
            sup_m1, res_m1 = calculate_support_resistance(self.candles_m1)
            atr_m1_list = calculate_atr(self.candles_m1)
            atr_m1 = atr_m1_list[-1]["value"] if atr_m1_list else 0.0

            rsi_m5 = calculate_rsi(self.candles_m5)
            adx_m5 = calculate_adx(self.candles_m5)
            ema9_m5 = calculate_ema(self.candles_m5, 9)
            ema21_m5 = calculate_ema(self.candles_m5, 21)
            vwap_m5 = calculate_vwap(self.candles_m5)
            sup_m5, res_m5 = calculate_support_resistance(self.candles_m5)
            atr_m5_list = calculate_atr(self.candles_m5)
            atr_m5 = atr_m5_list[-1]["value"] if atr_m5_list else 0.0

            rsi_m15 = calculate_rsi(self.candles_m15)
            adx_m15 = calculate_adx(self.candles_m15)
            ema9_m15 = calculate_ema(self.candles_m15, 9)
            ema21_m15 = calculate_ema(self.candles_m15, 21)
            vwap_m15 = calculate_vwap(self.candles_m15)
            sup_m15, res_m15 = calculate_support_resistance(self.candles_m15)
            atr_m15_list = calculate_atr(self.candles_m15)
            atr_m15 = atr_m15_list[-1]["value"] if atr_m15_list else 0.0

            rsi_h1 = calculate_rsi(self.candles_h1)
            adx_h1 = calculate_adx(self.candles_h1)
            ema9_h1 = calculate_ema(self.candles_h1, 9)
            ema21_h1 = calculate_ema(self.candles_h1, 21)
            vwap_h1 = calculate_vwap(self.candles_h1)
            sup_h1, res_h1 = calculate_support_resistance(self.candles_h1)
            atr_h1_list = calculate_atr(self.candles_h1)
            atr_h1 = atr_h1_list[-1]["value"] if atr_h1_list else 0.0

            rsi_h4 = calculate_rsi(self.candles_h4)
            adx_h4 = calculate_adx(self.candles_h4)
            ema9_h4 = calculate_ema(self.candles_h4, 9)
            ema21_h4 = calculate_ema(self.candles_h4, 21)
            vwap_h4 = calculate_vwap(self.candles_h4)
            sup_h4, res_h4 = calculate_support_resistance(self.candles_h4)
            atr_h4_list = calculate_atr(self.candles_h4)
            atr_h4 = atr_h4_list[-1]["value"] if atr_h4_list else 0.0

            # Trend for display (M15 and H1)
            trend = get_trend(self.candles_m15, self.candles_h1)

            # Calculate active dynamic RR Ratio
            rr_ratio = 2.0
            if self.position_active and self.signal_sl != self.signal_entry:
                rr_ratio = round(abs(self.signal_tp - self.signal_entry) / abs(self.signal_entry - self.signal_sl), 1)

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

                "candles_m1": self.candles_m1,  "rsi_m1": rsi_m1, "adx_m1": adx_m1, "ema9_m1": ema9_m1, "ema21_m1": ema21_m1, "vwap_m1": vwap_m1, "sup_m1": sup_m1, "res_m1": res_m1, "atr_m1": atr_m1,
                "candles_m5": self.candles_m5,  "rsi_m5": rsi_m5, "adx_m5": adx_m5, "ema9_m5": ema9_m5, "ema21_m5": ema21_m5, "vwap_m5": vwap_m5, "sup_m5": sup_m5, "res_m5": res_m5, "atr_m5": atr_m5,
                "candles_m15": self.candles_m15, "rsi_m15": rsi_m15, "adx_m15": adx_m15, "ema9_m15": ema9_m15, "ema21_m15": ema21_m15, "vwap_m15": vwap_m15, "sup_m15": sup_m15, "res_m15": res_m15, "atr_m15": atr_m15,
                "candles_h1": self.candles_h1,  "rsi_h1": rsi_h1, "adx_h1": adx_h1, "ema9_h1": ema9_h1, "ema21_h1": ema21_h1, "vwap_h1": vwap_h1, "sup_h1": sup_h1, "res_h1": res_h1, "atr_h1": atr_h1,
                "candles_h4": self.candles_h4,  "rsi_h4": rsi_h4, "adx_h4": adx_h4, "ema9_h4": ema9_h4, "ema21_h4": ema21_h4, "vwap_h4": vwap_h4, "sup_h4": sup_h4, "res_h4": res_h4, "atr_h4": atr_h4,

                "market_trend": trend,
                "rr_ratio": rr_ratio,

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

                "trade_history": list(reversed(self.trade_history))
            }


state = TradingStationState()
