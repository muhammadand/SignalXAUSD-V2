import math

# ─────────────────────────────────────────────────────────────────────────────
# INDICATOR UTILITIES (still used for chart rendering in state_manager)
# ─────────────────────────────────────────────────────────────────────────────

def calculate_vwap(candles):
    """Calculate Intraday VWAP for the given candles."""
    if not candles:
        return []
    out = [{"epoch": c["epoch"], "value": c["close"]} for c in candles]
    cum_tp_vol = 0.0
    cum_vol = 0.0
    for i, c in enumerate(candles):
        tp = (c["high"] + c["low"] + c["close"]) / 3.0
        vol = float(c.get("volume", c.get("count", 1.0)))
        if vol <= 0:
            vol = 1.0
        cum_tp_vol += tp * vol
        cum_vol += vol
        out[i]["value"] = cum_tp_vol / cum_vol if cum_vol > 0 else tp
    return out


def calculate_ema(candles, period):
    """Calculate Exponential Moving Average."""
    if len(candles) < period:
        return [{"epoch": c["epoch"], "value": c["close"]} for c in candles]
    multiplier = 2.0 / (period + 1)
    sma = sum(c["close"] for c in candles[:period]) / period
    out = [{"epoch": candles[i]["epoch"], "value": candles[i]["close"]} for i in range(len(candles))]
    out[period - 1]["value"] = sma
    for i in range(period, len(candles)):
        prev_ema = out[i - 1]["value"] or candles[i]["close"]
        out[i]["value"] = (candles[i]["close"] - prev_ema) * multiplier + prev_ema
    return out


def calculate_rsi(candles, period=14):
    """Calculate RSI using Wilder smoothing."""
    if len(candles) < period + 1:
        return [{"epoch": c["epoch"], "value": 50.0} for c in candles]
    out = [{"epoch": c["epoch"], "value": 50.0} for c in candles]
    deltas = [candles[i]["close"] - candles[i - 1]["close"] for i in range(1, len(candles))]
    avg_gain = sum(d for d in deltas[:period] if d > 0) / period
    avg_loss = sum(-d for d in deltas[:period] if d < 0) / period
    rs = avg_gain / avg_loss if avg_loss > 0 else 100.0
    out[period]["value"] = 100.0 - (100.0 / (1.0 + rs))
    for i in range(period + 1, len(candles)):
        d = deltas[i - 1]
        avg_gain = (avg_gain * (period - 1) + max(d, 0)) / period
        avg_loss = (avg_loss * (period - 1) + max(-d, 0)) / period
        rs = avg_gain / avg_loss if avg_loss > 0 else 100.0
        out[i]["value"] = 100.0 - (100.0 / (1.0 + rs))
    return out


def calculate_atr(candles, period=14):
    """Calculate Average True Range."""
    if len(candles) < period + 1:
        return [{"epoch": c["epoch"], "value": 0.1} for c in candles]
    out = [{"epoch": c["epoch"], "value": 0.1} for c in candles]
    tr_list = [candles[0]["high"] - candles[0]["low"]]
    for i in range(1, len(candles)):
        tr = max(
            candles[i]["high"] - candles[i]["low"],
            abs(candles[i]["high"] - candles[i - 1]["close"]),
            abs(candles[i]["low"]  - candles[i - 1]["close"])
        )
        tr_list.append(tr)
    atr = sum(tr_list[:period]) / period
    out[period - 1]["value"] = atr
    for i in range(period, len(candles)):
        prev = out[i - 1]["value"] or tr_list[i]
        atr = (prev * (period - 1) + tr_list[i]) / period
        out[i]["value"] = atr
    return out


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def find_swing_high(candles, lookback=5):
    """Find local swing highs within a lookback window.
    A swing high is a candle whose high is greater than the 'lookback' candles on both sides.
    """
    highs = []
    for i in range(lookback, len(candles) - lookback):
        c_high = candles[i]["high"]
        left  = all(candles[j]["high"] < c_high for j in range(i - lookback, i))
        right = all(candles[j]["high"] < c_high for j in range(i + 1, i + lookback + 1))
        if left and right:
            highs.append({"index": i, "price": c_high, "epoch": candles[i]["epoch"]})
    return highs


def find_swing_low(candles, lookback=5):
    """Find local swing lows within a lookback window."""
    lows = []
    for i in range(lookback, len(candles) - lookback):
        c_low = candles[i]["low"]
        left  = all(candles[j]["low"] > c_low for j in range(i - lookback, i))
        right = all(candles[j]["low"] > c_low for j in range(i + 1, i + lookback + 1))
        if left and right:
            lows.append({"index": i, "price": c_low, "epoch": candles[i]["epoch"]})
    return lows


# ─────────────────────────────────────────────────────────────────────────────
# MAIN STRATEGY: SFP + CHoCH Scalper
# ─────────────────────────────────────────────────────────────────────────────

class EMARsiStrategy:
    """
    SFP (Swing Failure Pattern) + CHoCH (Change of Character) Scalper.

    Phase flow:
      SCANNING
        → SFP_DETECTED (when price sweeps a key swing high/low but closes back inside)
        → ENTRY_TRIGGERED (when a CHoCH candle close confirms structural reversal)
      ACTIVE (position open)
    """

    SWING_LOOKBACK     = 4     # bars on each side to qualify a swing point
    SWING_SEARCH_BACK  = 50    # how many closed candles to search for key swing levels
    CHOCH_MAX_BARS     = 15    # max bars to wait for CHoCH before invalidation
    ATR_PERIOD         = 14    # for SL sizing
    SL_ATR_MULTIPLIER  = 0.5   # tight SL: half ATR beyond the wick
    TP_RR              = 2.0   # risk-to-reward ratio

    def __init__(self, ema_fast=9, ema_slow=21, rsi_period=14, atr_period=14):
        # Keep signature compatible with state_manager instantiation
        self.ema_fast   = ema_fast
        self.ema_slow   = ema_slow
        self.rsi_period = rsi_period
        self.atr_period = atr_period
        self.reset_state()

    def reset_state(self):
        self.phase           = "SCANNING"
        self.direction       = None      # "BUY" | "SELL"
        self.candle_pattern  = "None"

        # SFP metadata
        self.sfp_sweep_level = 0.0      # price level that was swept
        self.sfp_wick_tip    = 0.0      # the actual wick extreme (SL anchor)
        self.sfp_epoch       = None     # epoch of the SFP candle
        self.choch_level     = 0.0      # structural break level to trigger entry
        self.bars_since_sfp  = 0        # candle counter since SFP detected

        # Swing levels exposed for UI boxes
        self.box_high        = 0.0
        self.box_low         = 0.0

    # ------------------------------------------------------------------
    def analyze(self, candles_m1):
        """Main entry point called every tick on the M1 array."""
        min_len = self.SWING_SEARCH_BACK + self.SWING_LOOKBACK + 5
        if len(candles_m1) < min_len:
            return {"status": "WAITING_DATA",
                    "reason": f"Collecting candles… ({len(candles_m1)}/{min_len})"}

        if self.phase == "ACTIVE":
            return {"status": "ACTIVE_TRADE", "reason": "SFP+CHoCH trade is active."}

        # Use only confirmed closed candles (exclude index -1 which is live)
        closed = candles_m1[:-1]
        current_price = candles_m1[-1]["close"]

        if self.phase == "SCANNING":
            return self._scan_for_sfp(closed, current_price)

        if self.phase == "SFP_DETECTED":
            return self._wait_for_choch(closed, current_price)

        return {"status": "UNKNOWN", "reason": "Unknown strategy state."}

    # ------------------------------------------------------------------
    def _scan_for_sfp(self, closed, current_price):
        """
        Detect a Swing Failure Pattern on the most recently closed candle.
        SFP conditions:
          • Price wicks beyond a key swing high/low (formed at least SWING_LOOKBACK bars ago).
          • The candle CLOSES back inside the range (wick only, no close beyond).
        """
        search_window = closed[-self.SWING_SEARCH_BACK:]

        # Use the second-to-last candle (index -2 relative to full closed) as candidate SFP candle
        sfp_candle   = closed[-2]
        prev_candle  = closed[-3]

        # Determine ATR for later SL sizing (from the search window)
        atr_data = calculate_atr(search_window, self.ATR_PERIOD)
        atr_val  = atr_data[-1]["value"] if atr_data else 0.5

        # ── Bearish SFP: wick sweeps a swing HIGH but close is below that swing high ──
        swing_highs = find_swing_high(search_window[:-2], lookback=self.SWING_LOOKBACK)
        if swing_highs:
            # Key level = the HIGHEST swing high found
            key_swing_high = max(sh["price"] for sh in swing_highs)
            if (sfp_candle["high"] > key_swing_high          # wick broke above
                    and sfp_candle["close"] < key_swing_high # close back inside
                    and sfp_candle["close"] < sfp_candle["open"]):  # candle is bearish
                # CHoCH target = most recent local swing LOW (lower high boundary)
                swing_lows = find_swing_low(search_window[:-2], lookback=self.SWING_LOOKBACK)
                if swing_lows:
                    # CHoCH trigger = break below the last swing low before the SFP
                    choch_level = swing_lows[-1]["price"]

                    self.phase          = "SFP_DETECTED"
                    self.direction      = "SELL"
                    self.sfp_sweep_level= key_swing_high
                    self.sfp_wick_tip   = sfp_candle["high"]
                    self.sfp_epoch      = sfp_candle["epoch"]
                    self.choch_level    = choch_level
                    self.bars_since_sfp = 0
                    self.candle_pattern = "Bearish SFP"
                    self.box_high       = key_swing_high
                    self.box_low        = choch_level

                    return {
                        "status": "SFP_DETECTED",
                        "direction": "SELL",
                        "candle_pattern": "Bearish SFP",
                        "reason": (f"Bearish SFP: Wick swept swing high {key_swing_high:.2f}. "
                                   f"Waiting CHoCH break below {choch_level:.2f}."),
                        "box_high": key_swing_high,
                        "box_low": choch_level,
                        "manipulation_epoch": sfp_candle["epoch"]
                    }

        # ── Bullish SFP: wick sweeps a swing LOW but close is above that swing low ──
        swing_lows = find_swing_low(search_window[:-2], lookback=self.SWING_LOOKBACK)
        if swing_lows:
            key_swing_low = min(sl["price"] for sl in swing_lows)
            if (sfp_candle["low"] < key_swing_low             # wick broke below
                    and sfp_candle["close"] > key_swing_low   # close back inside
                    and sfp_candle["close"] > sfp_candle["open"]):  # candle is bullish
                swing_highs = find_swing_high(search_window[:-2], lookback=self.SWING_LOOKBACK)
                if swing_highs:
                    choch_level = swing_highs[-1]["price"]

                    self.phase          = "SFP_DETECTED"
                    self.direction      = "BUY"
                    self.sfp_sweep_level= key_swing_low
                    self.sfp_wick_tip   = sfp_candle["low"]
                    self.sfp_epoch      = sfp_candle["epoch"]
                    self.choch_level    = choch_level
                    self.bars_since_sfp = 0
                    self.candle_pattern = "Bullish SFP"
                    self.box_high       = choch_level
                    self.box_low        = key_swing_low

                    return {
                        "status": "SFP_DETECTED",
                        "direction": "BUY",
                        "candle_pattern": "Bullish SFP",
                        "reason": (f"Bullish SFP: Wick swept swing low {key_swing_low:.2f}. "
                                   f"Waiting CHoCH break above {choch_level:.2f}."),
                        "box_high": choch_level,
                        "box_low": key_swing_low,
                        "manipulation_epoch": sfp_candle["epoch"]
                    }

        # Calculate ATR and EMA for status message
        ema9_data  = calculate_ema(closed[-30:], self.ema_fast)
        ema21_data = calculate_ema(closed[-30:], self.ema_slow)
        ema9_val   = ema9_data[-1]["value"] if ema9_data else current_price
        ema21_val  = ema21_data[-1]["value"] if ema21_data else current_price

        return {
            "status": "SCANNING_SFP",
            "reason": (f"Scanning SFP… EMA9:{ema9_val:.2f} EMA21:{ema21_val:.2f} "
                       f"ATR:{atr_val:.2f}"),
            "box_high": self.box_high or None,
            "box_low":  self.box_low  or None
        }

    # ------------------------------------------------------------------
    def _wait_for_choch(self, closed, current_price):
        """
        Wait for a CHoCH (Change of Character) candle CLOSE to confirm the SFP reversal.
        CHoCH = a candle that closes beyond self.choch_level in the direction of trade.
        Invalidation conditions:
          • Price closes beyond the SFP wick tip (initial liquidity target blown)
          • Too many bars have elapsed without CHoCH
        """
        self.bars_since_sfp += 1

        atr_data = calculate_atr(closed[-20:], self.ATR_PERIOD)
        atr_val  = atr_data[-1]["value"] if atr_data else 0.5

        conf_candle = closed[-1]  # latest confirmed closed bar

        # ── Invalidation: SFP wick tip violated (stop would have been hit) ──
        if self.direction == "BUY" and conf_candle["low"] < self.sfp_wick_tip:
            self.reset_state()
            return {"status": "RESET",
                    "reason": "SFP BUY invalidated: price broke below the manipulation wick tip."}
        if self.direction == "SELL" and conf_candle["high"] > self.sfp_wick_tip:
            self.reset_state()
            return {"status": "RESET",
                    "reason": "SFP SELL invalidated: price broke above the manipulation wick tip."}

        # ── Invalidation: too many bars without CHoCH ──
        if self.bars_since_sfp > self.CHOCH_MAX_BARS:
            self.reset_state()
            return {"status": "RESET",
                    "reason": f"CHoCH not confirmed within {self.CHOCH_MAX_BARS} bars. Resetting."}

        # ── CHoCH confirmed ──
        choch_triggered = False
        if self.direction == "BUY" and conf_candle["close"] > self.choch_level:
            choch_triggered = True
        elif self.direction == "SELL" and conf_candle["close"] < self.choch_level:
            choch_triggered = True

        if choch_triggered:
            entry_price = current_price
            risk        = abs(entry_price - self.sfp_wick_tip) + (self.SL_ATR_MULTIPLIER * atr_val)

            if self.direction == "BUY":
                sl = self.sfp_wick_tip - (self.SL_ATR_MULTIPLIER * atr_val)
                tp = entry_price + (risk * self.TP_RR)
            else:
                sl = self.sfp_wick_tip + (self.SL_ATR_MULTIPLIER * atr_val)
                tp = entry_price - (risk * self.TP_RR)

            # Ensure minimum 1:1.5 RR
            reward = abs(tp - entry_price)
            if reward < 1.5 * risk:
                if self.direction == "BUY":
                    tp = entry_price + 1.5 * risk
                else:
                    tp = entry_price - 1.5 * risk

            self.phase = "ACTIVE"
            return {
                "status": "ENTRY_TRIGGERED",
                "direction": self.direction,
                "entry": round(entry_price, 3),
                "sl":    round(sl, 3),
                "tp":    round(tp, 3),
                "rsi":   50.0,   # placeholder; RSI not used for entry in SFP+CHoCH
                "pattern": "SFP+CHoCH Scalper",
                "candle_pattern": self.candle_pattern,
                "reason": (f"CHoCH confirmed ({self.bars_since_sfp} bars after SFP). "
                           f"Entry on {self.direction} structure break above {self.choch_level:.2f}. "
                           f"SL={sl:.2f} (below SFP wick), TP={tp:.2f} (1:{self.TP_RR} RR)."),
                "box_high": self.box_high,
                "box_low":  self.box_low,
                "manipulation_epoch": self.sfp_epoch
            }

        return {
            "status": "WAITING_CHOCH",
            "direction": self.direction,
            "reason": (f"{self.candle_pattern} detected. "
                       f"Waiting CHoCH break {'above' if self.direction == 'BUY' else 'below'} "
                       f"{self.choch_level:.2f} (bar {self.bars_since_sfp}/{self.CHOCH_MAX_BARS})."),
            "box_high": self.box_high,
            "box_low":  self.box_low,
            "manipulation_epoch": self.sfp_epoch
        }
