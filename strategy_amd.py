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

    SWING_LOOKBACK     = 2     # bars on each side to qualify a swing point
    SWING_SEARCH_BACK  = 50    # how many closed candles to search for key swing levels
    CHOCH_MAX_BARS     = 15    # max bars to wait for CHoCH before invalidation
    ATR_PERIOD         = 14    # for SL sizing
    SL_ATR_MULTIPLIER  = 1.2   # wider SL to reduce premature stop outs
    TP_RR              = 0.6   # risk-to-reward ratio for higher win rate

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
            # Check the last 3 swing highs (most recent first) for a sweep
            for sh in reversed(swing_highs[-3:]):
                level = sh["price"]
                if (sfp_candle["high"] > level                     # wick broke above
                        and sfp_candle["close"] < level            # close back inside
                        and sfp_candle["close"] < sfp_candle["open"]): # bearish candle
                    
                    # For aggressive entry, CHoCH level is the low of the SFP candle itself
                    choch_level = sfp_candle["low"]

                    self.phase          = "SFP_DETECTED"
                    self.direction      = "SELL"
                    self.sfp_sweep_level= level
                    self.sfp_wick_tip   = sfp_candle["high"]
                    self.sfp_epoch      = sfp_candle["epoch"]
                    self.choch_level    = choch_level
                    self.bars_since_sfp = 0
                    self.candle_pattern = "Bearish SFP"
                    self.box_high       = level
                    self.box_low        = choch_level

                    return {
                        "status": "SFP_DETECTED",
                        "direction": "SELL",
                        "candle_pattern": "Bearish SFP",
                        "reason": (f"Bearish SFP: Wick swept swing high {level:.2f}. "
                                   f"Waiting aggressive break below SFP low {choch_level:.2f}."),
                        "box_high": level,
                        "box_low": choch_level,
                        "manipulation_epoch": sfp_candle["epoch"]
                    }

        # ── Bullish SFP: wick sweeps a swing LOW but close is above that swing low ──
        swing_lows = find_swing_low(search_window[:-2], lookback=self.SWING_LOOKBACK)
        if swing_lows:
            # Check the last 3 swing lows (most recent first) for a sweep
            for sl in reversed(swing_lows[-3:]):
                level = sl["price"]
                if (sfp_candle["low"] < level                      # wick broke below
                        and sfp_candle["close"] > level            # close back inside
                        and sfp_candle["close"] > sfp_candle["open"]): # bullish candle
                    
                    # For aggressive entry, CHoCH level is the high of the SFP candle itself
                    choch_level = sfp_candle["high"]

                    self.phase          = "SFP_DETECTED"
                    self.direction      = "BUY"
                    self.sfp_sweep_level= level
                    self.sfp_wick_tip   = sfp_candle["low"]
                    self.sfp_epoch      = sfp_candle["epoch"]
                    self.choch_level    = choch_level
                    self.bars_since_sfp = 0
                    self.candle_pattern = "Bullish SFP"
                    self.box_high       = choch_level
                    self.box_low        = level

                    return {
                        "status": "SFP_DETECTED",
                        "direction": "BUY",
                        "candle_pattern": "Bullish SFP",
                        "reason": (f"Bullish SFP: Wick swept swing low {level:.2f}. "
                                   f"Waiting aggressive break above SFP high {choch_level:.2f}."),
                        "box_high": choch_level,
                        "box_low": level,
                        "manipulation_epoch": sfp_candle["epoch"]
                    }

        # Calculate indicators for alternative strategies
        ema9_data  = calculate_ema(search_window, self.ema_fast)
        ema21_data = calculate_ema(search_window, self.ema_slow)
        rsi_data   = calculate_rsi(search_window, self.rsi_period)

        ema9_val   = ema9_data[-1]["value"] if ema9_data else current_price
        ema21_val  = ema21_data[-1]["value"] if ema21_data else current_price
        rsi_val    = rsi_data[-1]["value"] if rsi_data else 50.0

        # --- 2. EMA Crossover Strategy ---
        if len(ema9_data) >= 3 and len(ema21_data) >= 3:
            ema_cross_up = (ema9_data[-1]["value"] > ema21_data[-1]["value"] 
                            and ema9_data[-2]["value"] <= ema21_data[-2]["value"]
                            and closed[-1]["close"] > closed[-1]["open"]) # bullish confirmation
            ema_cross_down = (ema9_data[-1]["value"] < ema21_data[-1]["value"] 
                              and ema9_data[-2]["value"] >= ema21_data[-2]["value"]
                              and closed[-1]["close"] < closed[-1]["open"]) # bearish confirmation

            if ema_cross_up:
                entry_price = current_price
                risk = self.SL_ATR_MULTIPLIER * atr_val
                sl = entry_price - risk
                tp = entry_price + (risk * self.TP_RR)
                self.phase = "ACTIVE"
                self.direction = "BUY"
                self.sfp_wick_tip = sl
                return {
                    "status": "ENTRY_TRIGGERED",
                    "direction": "BUY",
                    "entry": round(entry_price, 3),
                    "sl":    round(sl, 3),
                    "tp":    round(tp, 3),
                    "rsi":   round(rsi_val, 2),
                    "pattern": "EMA Crossover",
                    "candle_pattern": "Bullish Cross",
                    "reason": f"Bullish EMA Crossover: EMA9 ({ema9_val:.2f}) crossed above EMA21 ({ema21_val:.2f}). Entering BUY. SL={sl:.2f}, TP={tp:.2f} (1:{self.TP_RR} RR).",
                    "box_high": None,
                    "box_low":  None,
                    "manipulation_epoch": closed[-1]["epoch"]
                }

            if ema_cross_down:
                entry_price = current_price
                risk = self.SL_ATR_MULTIPLIER * atr_val
                sl = entry_price + risk
                tp = entry_price - (risk * self.TP_RR)
                self.phase = "ACTIVE"
                self.direction = "SELL"
                self.sfp_wick_tip = sl
                return {
                    "status": "ENTRY_TRIGGERED",
                    "direction": "SELL",
                    "entry": round(entry_price, 3),
                    "sl":    round(sl, 3),
                    "tp":    round(tp, 3),
                    "rsi":   round(rsi_val, 2),
                    "pattern": "EMA Crossover",
                    "candle_pattern": "Bearish Cross",
                    "reason": f"Bearish EMA Crossover: EMA9 ({ema9_val:.2f}) crossed below EMA21 ({ema21_val:.2f}). Entering SELL. SL={sl:.2f}, TP={tp:.2f} (1:{self.TP_RR} RR).",
                    "box_high": None,
                    "box_low":  None,
                    "manipulation_epoch": closed[-1]["epoch"]
                }

        # --- 3. RSI Mean Reversion Strategy ---
        if len(rsi_data) >= 4:
            rsi_oversold = any(r["value"] < 30 for r in rsi_data[-4:-1]) and rsi_data[-1]["value"] >= 30
            rsi_overbought = any(r["value"] > 70 for r in rsi_data[-4:-1]) and rsi_data[-1]["value"] <= 70

            if rsi_oversold:
                entry_price = current_price
                risk = self.SL_ATR_MULTIPLIER * atr_val
                sl = entry_price - risk
                tp = entry_price + (risk * self.TP_RR)
                self.phase = "ACTIVE"
                self.direction = "BUY"
                self.sfp_wick_tip = sl
                return {
                    "status": "ENTRY_TRIGGERED",
                    "direction": "BUY",
                    "entry": round(entry_price, 3),
                    "sl":    round(sl, 3),
                    "tp":    round(tp, 3),
                    "rsi":   round(rsi_val, 2),
                    "pattern": "RSI Reversal",
                    "candle_pattern": "RSI Oversold",
                    "reason": f"RSI Oversold Reversal (RSI={rsi_val:.1f}). Entering BUY. SL={sl:.2f}, TP={tp:.2f} (1:{self.TP_RR} RR).",
                    "box_high": None,
                    "box_low":  None,
                    "manipulation_epoch": closed[-1]["epoch"]
                }

            if rsi_overbought:
                entry_price = current_price
                risk = self.SL_ATR_MULTIPLIER * atr_val
                sl = entry_price + risk
                tp = entry_price - (risk * self.TP_RR)
                self.phase = "ACTIVE"
                self.direction = "SELL"
                self.sfp_wick_tip = sl
                return {
                    "status": "ENTRY_TRIGGERED",
                    "direction": "SELL",
                    "entry": round(entry_price, 3),
                    "sl":    round(sl, 3),
                    "tp":    round(tp, 3),
                    "rsi":   round(rsi_val, 2),
                    "pattern": "RSI Reversal",
                    "candle_pattern": "RSI Overbought",
                    "reason": f"RSI Overbought Reversal (RSI={rsi_val:.1f}). Entering SELL. SL={sl:.2f}, TP={tp:.2f} (1:{self.TP_RR} RR).",
                    "box_high": None,
                    "box_low":  None,
                    "manipulation_epoch": closed[-1]["epoch"]
                }

        return {
            "status": "SCANNING_SFP",
            "reason": (f"Scanning (SFP/EMA/RSI)… EMA9:{ema9_val:.2f} EMA21:{ema21_val:.2f} "
                       f"RSI:{rsi_val:.1f} ATR:{atr_val:.2f}"),
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

            # Ensure minimum 1:0.5 RR
            reward = abs(tp - entry_price)
            if reward < 0.5 * risk:
                if self.direction == "BUY":
                    tp = entry_price + 0.5 * risk
                else:
                    tp = entry_price - 0.5 * risk

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
