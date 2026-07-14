import os
import random
from datetime import datetime
import threading
from strategy_amd import EMARsiStrategy, calculate_vwap, calculate_ema, calculate_rsi, calculate_atr
from tinydb import TinyDB
from ml_optimizer import ai_predictor, train_predictor_from_db

# Initialize TinyDB
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "db.json")
db = TinyDB(DB_PATH)
trades_table = db.table("trades")

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

        # EMA+RSI Strategy instance
        self.amd_strategy = EMARsiStrategy(ema_fast=9, ema_slow=21, rsi_period=14, atr_period=14)
        self.amd_info = {}

        # Signal & active trade
        self.signal_type  = None      # "BUY" | "SELL" | None
        self.signal_entry = 0.0
        self.signal_sl    = 0.0
        self.signal_tp    = 0.0
        self.signal_confidence = 0
        self.signal_reason = "Awaiting AMD analysis..."
        self.signal_pattern = "None"
        self.signal_candle_pattern = "None"
        self.signal_setup_key = "None"

        self.position_active = False
        self.position_entry  = 0.0
        self.position_size   = 0.10   # micro lot

        # Stats & history loaded from TinyDB
        all_trades = trades_table.all()
        all_trades.sort(key=lambda x: x.get("time", ""))
        
        self.trade_history = all_trades
        self.total_wins    = sum(1 for t in all_trades if t.get("result") == "WIN")
        self.total_losses  = sum(1 for t in all_trades if t.get("result") == "LOSS")

        self._analysis_cooldown = 0

        # Train ML model on startup
        train_predictor_from_db()

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

            if self._analysis_cooldown > 0:
                self._analysis_cooldown -= 1
                return

            if self.position_active:
                self._check_position(price)
            else:
                self._try_generate_signal()

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

            informative_reason = self._generate_pnl_reason(hit, self.signal_type, price)

            trade_record = {
                "time":   datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "type":   self.signal_type,
                "pattern": self.signal_pattern,
                "candle_pattern": self.signal_candle_pattern,
                "setup_key": self.signal_setup_key,
                "confidence": self.signal_confidence,
                "entry":  f"{self.position_entry:.2f}",
                "exit":   f"{price:.2f}",
                "pnl":    f"{pnl:+.2f}",
                "result": hit,
                "reason": informative_reason
            }

            # Save to TinyDB
            try:
                trades_table.insert(trade_record)
                # Retrain ML model with new data
                train_predictor_from_db()
            except Exception as e:
                print(f"Error saving to TinyDB: {e}")

            self.trade_history.append(trade_record)
            if len(self.trade_history) > 100:
                self.trade_history.pop(0)

            # Close position
            self.position_active = False
            self.signal_type     = None
            self.signal_entry    = 0.0
            self.signal_sl       = 0.0
            self.signal_tp       = 0.0
            self.signal_confidence = 0
            self.signal_reason   = f"Trade closed ({hit}). Re-analysing..."
            self.signal_pattern  = "None"
            self.signal_candle_pattern = "None"
            self.signal_setup_key = "None"
            
            # Reset AMD strategy state for the next trade
            self.amd_strategy.reset_state()
            self.amd_info = {}

            # Brief cooldown before next signal (reduced from 5 to 2 to be more aggressive)
            self._analysis_cooldown = 2

    def _generate_pnl_reason(self, hit, signal_type, exit_price):
        # Analyse the last 5 closed M1 candles to assess recent momentum
        recent_candles = self.candles_m1[-5:] if len(self.candles_m1) >= 5 else []
        bullish_count = sum(1 for c in recent_candles if c["close"] >= c["open"])
        bearish_count = len(recent_candles) - bullish_count
        candle_summary = f"{bullish_count} bullish, {bearish_count} bearish in the last 5 M1 candles"

        pattern = self.signal_candle_pattern or "SFP"
        pnl_val = (exit_price - self.position_entry) * 100 if signal_type == "BUY" else (self.position_entry - exit_price) * 100

        # Try to use AI analysis from Agent Router
        try:
            from ai_analyzer import generate_trade_outcome_reason
            ai_reason = generate_trade_outcome_reason(
                hit=hit,
                direction=signal_type,
                pattern=pattern,
                entry=self.position_entry,
                exit=exit_price,
                pnl=f"{pnl_val:+.2f}",
                recent_candles_summary=candle_summary
            )
            if ai_reason:
                return ai_reason
        except Exception as e:
            print(f"AI post-trade reason failed: {e}")

        # Fallback to templates if AI is not available
        if hit == "WIN":
            if signal_type == "BUY":
                reasons = [
                    f"TP Hit: {pattern} liquidity sweep executed perfectly. CHoCH confirmed structural shift; buyers absorbed sell-side liquidity and expanded to TP.",
                    f"TP Hit: Bullish SFP confirmed. Smart money swept stops below swing low, then aggressively reversed. Price expanded cleanly to target.",
                    f"TP Hit: Post-CHoCH momentum sustained. Buyers maintained control after the structure break, hitting the 1:2 RR target."
                ]
            else:
                reasons = [
                    f"TP Hit: {pattern} resistance fakeout confirmed. CHoCH broke previous higher-low, triggering cascading sell orders to TP.",
                    f"TP Hit: Bearish SFP completed. Sellers engineered a liquidity sweep above swing high then drove price aggressively to target.",
                    f"TP Hit: Post-CHoCH bearish momentum held. Sellers dominated after the structure break, reaching the 1:2 RR."
                ]
            return random.choice(reasons)
        else:  # LOSS
            if signal_type == "BUY":
                reasons = [
                    f"SL Hit: Double SFP — second liquidity sweep extended beyond the first wick tip, invalidating the bullish setup.",
                    f"SL Hit: CHoCH failed to hold. Buyers could not sustain the structure break; sellers regained control and breached the SFP wick.",
                    f"SL Hit: Macro bearish pressure overwhelmed the local SFP reversal signal."
                ]
                if bearish_count >= 4:
                    return f"SL Hit: Persistent bearish momentum (4/5 candles bearish) overpowered the {pattern} reversal. SFP wick tip violated."
            else:
                reasons = [
                    f"SL Hit: Double SFP — second liquidity sweep extended above the bearish SFP wick, invalidating the sell setup.",
                    f"SL Hit: CHoCH failed to hold. Sellers could not sustain the structure break; buyers reclaimed price above the SFP wick.",
                    f"SL Hit: Macro bullish pressure overwhelmed the local SFP reversal signal."
                ]
                if bullish_count >= 4:
                    return f"SL Hit: Persistent bullish momentum (4/5 candles bullish) overpowered the {pattern} reversal. SFP wick tip violated."
            return random.choice(reasons)

    # ------------------------------------------------------------------
    def _try_generate_signal(self):
        """Generate a signal using the SFP + CHoCH Scalper Strategy on M1."""
        if not self.candles_m1 or len(self.candles_m1) < 60:
            self.signal_reason = "Collecting M1 candle data for SFP scanner…"
            return

        analysis = self.amd_strategy.analyze(self.candles_m1)
        self.amd_info = analysis

        status = analysis.get("status")

        # Passthrough scanning / waiting states — just update the reason display
        if status in (
            "SCANNING_SFP", "SFP_DETECTED", "WAITING_CHOCH",
            "RESET", "WAITING_DATA"
        ):
            self.signal_reason = analysis.get("reason", "")
            return

        if status == "ENTRY_TRIGGERED":
            direction = analysis["direction"]
            candle_pat = analysis.get("candle_pattern", "None")

            # SFP-based setup keys for AI learning
            setup_key = f"{direction}_SFP_CHOCH_{candle_pat.replace(' ', '_').upper()}"
            self.signal_setup_key = setup_key

            setup_dict = {
                "pattern": analysis.get("pattern", "SFP+CHoCH Scalper"),
                "type": direction,
                "candle_pattern": candle_pat,
                "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }

            # Predict win probability using Naive Bayes ML model
            ml_prob = ai_predictor.predict_win_probability(setup_dict)
            win_rate = int(round(ml_prob * 100))

            # Filter out low-probability trades (< 40% chance of success - lowered from 50 to be more aggressive)
            if win_rate < 40:
                print(f"AI ML Optimizer Filtered Setup: {direction} ({analysis.get('pattern', 'SFP')}) with confidence {win_rate}%. Skipping trade.")
                self.signal_reason = f"Filtered by AI Optimizer: Low probability of success ({win_rate}%)."
                self.amd_strategy.reset_state()
                return

            self.signal_type           = direction
            self.signal_entry          = analysis["entry"]
            self.signal_sl             = analysis["sl"]
            self.signal_tp             = analysis["tp"]
            self.signal_confidence     = win_rate

            # Calculate current indicator values for AI analysis
            ema9_data  = calculate_ema(self.candles_m1, 9)
            ema21_data = calculate_ema(self.candles_m1, 21)
            rsi_data   = calculate_rsi(self.candles_m1, 14)
            atr_data   = calculate_atr(self.candles_m1, 14)

            ema9 = ema9_data[-1]["value"] if ema9_data else analysis["entry"]
            ema21 = ema21_data[-1]["value"] if ema21_data else analysis["entry"]
            rsi = rsi_data[-1]["value"] if rsi_data else 50.0
            atr = atr_data[-1]["value"] if atr_data else 1.0

            # Generate AI-powered entry rationale
            try:
                from ai_analyzer import generate_entry_reason
                self.signal_reason = generate_entry_reason(
                    direction=direction,
                    pattern=analysis.get("pattern", "SFP+CHoCH Scalper"),
                    candle_pattern=candle_pat,
                    entry_price=analysis["entry"],
                    sl=analysis["sl"],
                    tp=analysis["tp"],
                    ema9=ema9,
                    ema21=ema21,
                    rsi=rsi,
                    atr=atr
                )
            except Exception as e:
                print(f"AI entry reason generation failed: {e}")
                self.signal_reason = analysis["reason"]

            self.signal_pattern        = analysis.get("pattern", "SFP+CHoCH Scalper")
            self.signal_candle_pattern = candle_pat

            self.position_entry  = analysis["entry"]
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

            pnl_val = pnl_pct = 0.0
            if self.position_active and self.position_entry > 0 and price > 0:
                diff = (price - self.position_entry) if self.signal_type == "BUY" \
                       else (self.position_entry - price)
                pnl_val = diff * 100
                pnl_pct = (diff / self.position_entry) * 100

            total_closed = self.total_wins + self.total_losses
            win_rate = (self.total_wins / total_closed * 100) if total_closed > 0 else 0.0

            rr_ratio = 1.5
            if self.position_active and self.signal_sl != self.signal_entry:
                rr_ratio = round(abs(self.signal_tp - self.signal_entry) / abs(self.signal_entry - self.signal_sl), 1)

            res = {
                "last_price":     self.last_price,
                "tick_direction": self.tick_direction,
                "tick_color":     self.tick_color,
                "watchlist": [
                    {"symbol": "XAUUSD",  "price": f"{price:.2f}", "change": "+0.28%" if self.tick_direction == "▲" else "-0.15%", "direction": self.tick_direction, "color": self.tick_color},
                    {"symbol": "XAGUSD",  "price": f"{self.xagusd_price:.3f}", "change": "+0.12%" if self.tick_direction == "▲" else "-0.08%", "direction": "▲" if self.tick_direction == "▲" else "▼", "color": self.tick_color},
                    {"symbol": "DXY",     "price": f"{self.dxy_price:.2f}", "change": "-0.05%" if self.tick_direction == "▲" else "+0.08%", "direction": "▼" if self.tick_direction == "▲" else "▲", "color": "red" if self.tick_direction == "▲" else "green"},
                    {"symbol": "US10Y",   "price": f"{self.us10y_yield:.3f}%", "change": "0.00%", "direction": "■", "color": "white"}
                ],
                "candles_m1": self.candles_m1,
                "candles_m5": self.candles_m5,
                "candles_m15": self.candles_m15,
                "candles_h1": self.candles_h1,
                "candles_h4": self.candles_h4,
                "amd_info": self.amd_info,
                "market_trend": "SFP + CHoCH Scalper",
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

            # Calculate and inject indicators for all timeframes
            for tf in ["m1", "m5", "m15", "h1", "h4"]:
                candles = getattr(self, f"candles_{tf}", [])
                if candles:
                    res[f"vwap_{tf}"] = calculate_vwap(candles)
                    res[f"ema9_{tf}"] = calculate_ema(candles, 9)
                    res[f"ema21_{tf}"] = calculate_ema(candles, 21)
                    atr = calculate_atr(candles, 14)
                    res[f"atr_{tf}"] = atr[-1]["value"] if atr else None
                else:
                    res[f"vwap_{tf}"] = []
                    res[f"ema9_{tf}"] = []
                    res[f"ema21_{tf}"] = []
                    res[f"atr_{tf}"] = None

            return res

state = TradingStationState()
