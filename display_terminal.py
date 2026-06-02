import os
import sys
import math
import random
import re
import shutil
from datetime import datetime

# =====================================================================
# SYSTEM & COLOR SETTINGS (ANSI)
# =====================================================================
class Color:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    
    # Bloomberg / TCInvest Color Palette
    AMBER = "\033[38;5;214m"      # Headers / Gold details
    CYAN = "\033[36m"             # Tickers / Labels
    WHITE = "\033[37m"            # Normal values
    GRAY = "\033[90m"             # Borders / Grid lines
    
    # Trend colors
    GREEN = "\033[32m"            # Bullish / Profits
    RED = "\033[31m"              # Bearish / Losses
    BG_GREEN = "\033[42m\033[30m" # Green background with black text
    BG_RED = "\033[41m\033[37m"   # Red background with white text

    @staticmethod
    def paint(text, color_code):
        return f"{color_code}{text}{Color.RESET}"

# =====================================================================
# ANSI STRIPPER FOR PERFECT ALIGNMENT MATHEMATICS
# =====================================================================
def strip_ansi(text):
    """Strips all ANSI escape codes perfectly using regex to ensure accurate text length calculations."""
    ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
    return ansi_escape.sub('', text)

# =====================================================================
# LIVE TRADING STATION STATE MANAGER
# =====================================================================
class TradingStationState:
    def __init__(self, ticks_per_candle=5, max_candles=150):
        self.ticks_per_candle = ticks_per_candle
        self.max_candles = max_candles
        
        # Market Data
        self.last_price = None
        self.prev_price = None
        self.tick_direction = "■"
        self.tick_color = Color.WHITE
        
        # Candles & Volume History
        self.candles = []
        self.current_candle = None
        
        # Correlations (simulated on gold movements for realistic display)
        self.xagusd_price = 28.45
        self.dxy_price = 104.20
        self.us10y_yield = 4.35
        
        # Trading Signal details
        self.signal_type = "BUY"
        self.signal_entry = 0.0
        self.signal_sl = 0.0
        self.signal_tp = 0.0
        self.signal_confidence = 88
        
        # Active Position portfolio tracker
        self.position_size = 0.50  # Lots
        self.position_active = True

    def update_market_feeds(self, price):
        if price is None:
            return
        
        self.prev_price = self.last_price
        self.last_price = price
        
        if self.prev_price is not None:
            if price > self.prev_price:
                self.tick_direction = "▲"
                self.tick_color = Color.GREEN
                self.xagusd_price += round(random.uniform(0.001, 0.005), 3)
                self.dxy_price -= round(random.uniform(0.001, 0.003), 2)
            elif price < self.prev_price:
                self.tick_direction = "▼"
                self.tick_color = Color.RED
                self.xagusd_price -= round(random.uniform(0.001, 0.005), 3)
                self.dxy_price += round(random.uniform(0.001, 0.003), 2)
            else:
                self.tick_direction = "■"
                self.tick_color = Color.WHITE
        
        sim_volume = random.randint(120, 850)
        if self.current_candle is None:
            self.current_candle = {
                "open": price,
                "high": price,
                "low": price,
                "close": price,
                "volume": sim_volume,
                "ticks_count": 1
            }
        else:
            self.current_candle["high"] = max(self.current_candle["high"], price)
            self.current_candle["low"] = min(self.current_candle["low"], price)
            self.current_candle["close"] = price
            self.current_candle["volume"] += sim_volume
            self.current_candle["ticks_count"] += 1
            
        if self.current_candle["ticks_count"] >= self.ticks_per_candle:
            self.current_candle["is_bullish"] = self.current_candle["close"] >= self.current_candle["open"]
            self.candles.append(self.current_candle)
            if len(self.candles) > self.max_candles:
                self.candles.pop(0)
            self.current_candle = None
            
        if self.signal_entry == 0.0 or abs(self.signal_entry - price) > 30.0:
            self.generate_simulated_signal(price)

    def get_all_visible_candles(self):
        visible = list(self.candles)
        if self.current_candle:
            temp_c = dict(self.current_candle)
            temp_c["is_bullish"] = temp_c["close"] >= temp_c["open"]
            visible.append(temp_c)
        return visible

    def generate_simulated_signal(self, price):
        self.signal_entry = round(price - 0.15, 2)
        self.signal_sl = round(price - 4.50, 2)
        self.signal_tp = round(price + 9.00, 2)
        self.signal_confidence = random.randint(82, 94)
        self.signal_type = "BUY" if random.random() > 0.4 else "SELL"

state = TradingStationState(ticks_per_candle=5, max_candles=150)

# =====================================================================
# CANDLESTICK DRAWING ENGINE (DYNAMICALLY DIMENSIONED)
# =====================================================================
def get_candlestick_rows(candles, width=20, height=9):
    """Generates ASCII candlestick chart rows scaled dynamically to given width and height."""
    if width <= 0 or height <= 0:
        return []
        
    if len(candles) > width:
        display_candles = candles[-width:]
    else:
        display_candles = [None] * (width - len(candles)) + candles
        
    valid_candles = [c for c in candles if c is not None]
    if not valid_candles:
        return [f"{' ' * (10 + width * 2)}"] * height
        
    min_val = min(c["low"] for c in valid_candles)
    max_val = max(c["high"] for c in valid_candles)
    val_range = max_val - min_val
    if val_range == 0:
        val_range = 1.0

    grid = [[" " for _ in range(width)] for _ in range(height)]
    grid_colors = [[None for _ in range(width)] for _ in range(height)]
    
    def val_to_y(val):
        y = int(((val - min_val) / val_range) * (height - 1))
        return max(0, min(height - 1, y))

    for col, c in enumerate(display_candles):
        if c is None:
            continue
            
        color = Color.GREEN if c["is_bullish"] else Color.RED
        y_open = val_to_y(c["open"])
        y_close = val_to_y(c["close"])
        y_high = val_to_y(c["high"])
        y_low = val_to_y(c["low"])
        
        y_body_min = min(y_open, y_close)
        y_body_max = max(y_open, y_close)
        
        # Wick
        for y in range(y_low, y_high + 1):
            grid[y][col] = "│"
            grid_colors[y][col] = color
            
        # Body
        if y_body_min == y_body_max:
            grid[y_body_min][col] = "█"
            grid_colors[y_body_min][col] = color
        else:
            for y in range(y_body_min, y_body_max + 1):
                grid[y][col] = "█"
                grid_colors[y][col] = color

    rows = []
    for r in range(height - 1, -1, -1):
        price_val = min_val + (r * (val_range / (height - 1)))
        label = f"{price_val:8.2f} │"
        
        row_cells = []
        for col in range(width):
            char = grid[r][col]
            color = grid_colors[r][col]
            if color is not None:
                row_cells.append(Color.paint(char, color))
            else:
                row_cells.append("." if (r % 2 == 0 and col % 4 == 0) else " ")
                
        # Space-separated expanded candles
        expanded = "".join(f"{c} " for c in row_cells)
        rows.append(Color.paint(label, Color.CYAN) + expanded)
        
    return rows

# =====================================================================
# TERMINAL RENDERING & FLICKER CONTROL
# =====================================================================
# =====================================================================
# HIGH-IMPACT ECONOMIC CALENDAR VOLATILITY TRACKER
# =====================================================================
class EconomicCalendar:
    def __init__(self):
        # Dynamically set starting time for relative countdown simulation
        self.init_time = datetime.now()
        # Real-time high impact events affecting Gold
        self.events = [
            {"name": "US Core CPI (YoY)", "offset_minutes": 15, "forecast": "BULLISH", "volatility": "VERY HIGH"},
            {"name": "US Non-Farm Payrolls (NFP)", "offset_minutes": 45, "forecast": "BEARISH", "volatility": "CRITICAL"},
            {"name": "FOMC Interest Rate Decision", "offset_minutes": 120, "forecast": "BULLISH", "volatility": "CRITICAL"},
            {"name": "US GDP Growth Rate (QoQ)", "offset_minutes": 240, "forecast": "BULLISH", "volatility": "HIGH"},
            {"name": "Initial Jobless Claims", "offset_minutes": 480, "forecast": "BEARISH", "volatility": "HIGH"}
        ]

    def get_upcoming_events(self):
        import datetime as dt
        now = datetime.now()
        upcoming = []
        for e in self.events:
            event_time = self.init_time + dt.timedelta(minutes=e["offset_minutes"])
            
            # Reschedule if the event has passed by more than 1 minute to keep stopwatch always alive
            if now > event_time + dt.timedelta(minutes=1):
                e["offset_minutes"] += 600
                event_time = self.init_time + dt.timedelta(minutes=e["offset_minutes"])
                
            diff = event_time - now
            total_seconds = int(diff.total_seconds())
            
            if total_seconds < 0:
                countdown_str = "RELEASING..." 
            else:
                hours = total_seconds // 3600
                minutes = (total_seconds % 3600) // 60
                seconds = total_seconds % 60
                countdown_str = f"{hours:02d}h {minutes:02d}m {seconds:02d}s"
                
            upcoming.append({
                "name": e["name"],
                "time": event_time.strftime("%H:%M:%S"),
                "countdown": countdown_str,
                "forecast": e["forecast"],
                "volatility": e["volatility"]
            })
        return upcoming


# =====================================================================
# MAIN RENDERING DASHBOARD
# =====================================================================
class TerminalDashboard:
    def __init__(self, state_manager):
        self.state = state_manager
        self.last_width = 0
        self.last_height = 0
        self.active_timeframe = "H1"  # Default timeframe display
        self.calendar = EconomicCalendar()  # Dynamic economic calendar

    def get_dimensions(self):
        """Fetches active terminal size with reliable default overrides."""
        cols, rows = shutil.get_terminal_size(fallback=(100, 30))
        # Enforce minimum workable terminal size for clean aesthetic mapping
        width = max(80, cols)
        height = max(24, rows)
        return width, height

    def reset_cursor(self):
        """Moves terminal cursor to top-left to render over previous frame smoothly without flickering."""
        sys.stdout.write("\033[H")
        sys.stdout.flush()

    def clear_screen(self):
        """Performs absolute screen clear. Best used when terminal resizes to wipe stale remnants."""
        sys.stdout.write("\033[2J\033[H")
        sys.stdout.flush()

    def check_keypress(self):
        """Poles stdin non-blockingly to intercept live timeframe toggle inputs (1 for H1, 4 for H4)."""
        try:
            import select
            import termios
            import tty
            if sys.stdin.isatty():
                fd = sys.stdin.fileno()
                old_settings = termios.tcgetattr(fd)
                try:
                    tty.setraw(fd)
                    rlist, _, _ = select.select([sys.stdin], [], [], 0)
                    if rlist:
                        char = sys.stdin.read(1)
                        if char == '1':
                            self.active_timeframe = "H1"
                        elif char == '4':
                            self.active_timeframe = "H4"
                finally:
                    termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
        except Exception:
            pass

    def draw_line(self, content, max_w, alignment="left"):
        """Formats and prints a single terminal row perfectly padded to fit the boundary."""
        raw_len = len(strip_ansi(content))
        if raw_len > max_w:
            truncated = content
            while len(strip_ansi(truncated)) > max_w - 3:
                truncated = truncated[:-1]
            content = truncated + "..."
            raw_len = len(strip_ansi(content))

        padding = max_w - raw_len
        if alignment == "left":
            print(f"{content}{' ' * padding}")
        elif alignment == "right":
            print(f"{' ' * padding}{content}")
        else:  # Center
            left_pad = padding // 2
            right_pad = padding - left_pad
            print(f"{' ' * left_pad}{content}{' ' * right_pad}")

    def render_view(self, price, h1, h4):
        # Update tick state
        self.state.update_market_feeds(price)
        
        # Non-blockingly check keyboard toggle selection
        self.check_keypress()
        
        w_total, h_total = self.get_dimensions()
        
        # Trigger full screen clear if size changes to prevent overlapping text ghosts
        if w_total != self.last_width or h_total != self.last_height:
            self.clear_screen()
            self.last_width = w_total
            self.last_height = h_total
        else:
            self.reset_cursor()

        # Dynamic Grid Layout Width Setup (Borders & Dividers count: 4 chars)
        w_left = 23
        w_right = 26
        w_center = max(30, w_total - w_left - w_right - 4)
        w_inner = w_left + w_center + w_right + 2 # Inner content inside outer left/right borders
        
        # Border definitions
        border_outer_top = Color.paint("┌" + "─" * (w_inner) + "┐", Color.GRAY)
        border_top = Color.paint("┌" + "─" * w_left + "┬" + "─" * w_center + "┬" + "─" * w_right + "┐", Color.GRAY)
        border_mid = Color.paint("├" + "─" * w_left + "┼" + "─" * w_center + "┼" + "─" * w_right + "┤", Color.GRAY)
        border_divider = Color.paint("├" + "─" * w_inner + "┤", Color.GRAY)
        border_bottom = Color.paint("└" + "─" * w_inner + "┘", Color.GRAY)

        # -----------------------------------------------------------------
        # ROW 1: HEADER PANEL
        # -----------------------------------------------------------------
        time_str = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
        title = Color.paint(" TCINVEST PRO STATION [GOLD] ", Color.BOLD + Color.AMBER)
        account_info = Color.paint(" Account: ACTIVE ", Color.CYAN)
        time_display = Color.paint(f" {time_str} ", Color.GRAY)
        
        h_inner = f" {title} │ {account_info} │ {time_display}"
        h_inner_len = len(strip_ansi(h_inner))
        h_spacer = " " * max(0, w_inner - h_inner_len)
        
        print(border_outer_top)
        print(f"│{h_inner}{h_spacer}│")
        print(border_top)

        # -----------------------------------------------------------------
        # ROW 2: SIDE-BY-SIDE PANELS (WATCHLIST, CHART, ORDER STATION)
        # -----------------------------------------------------------------
        left_lines = []
        center_lines = []
        right_lines = []

        # --- A. LEFT PANEL: WATCHLIST ---
        left_lines.append(Color.paint("  WATCHLIST / INDEX  ", Color.BOLD + Color.AMBER))
        left_lines.append(Color.paint(" ─────────────────── ", Color.GRAY))
        
        curr_gold = self.state.last_price if self.state.last_price else 0.0
        gold_change = "+0.28%" if self.state.tick_direction == "▲" else "-0.15%"
        gold_color = Color.GREEN if self.state.tick_direction == "▲" else Color.RED
        left_lines.append(f" {Color.paint('XAUUSD', Color.CYAN):<8} {Color.paint(f'{curr_gold:.2f}', Color.WHITE):>8} {Color.paint(self.state.tick_direction, self.state.tick_color)}")
        left_lines.append(f" {Color.paint('  % Chg', Color.GRAY):<8} {Color.paint(gold_change, gold_color):>8}")
        left_lines.append(Color.paint(" ─────────────────── ", Color.GRAY))
        
        left_lines.append(f" {Color.paint('XAGUSD', Color.CYAN):<8} {Color.paint(f'{self.state.xagusd_price:.3f}', Color.WHITE):>8} {Color.paint('▲' if self.state.tick_direction == '▲' else '▼', Color.GREEN if self.state.tick_direction == '▲' else Color.RED)}")
        left_lines.append(f" {Color.paint('DXY', Color.CYAN):<8} {Color.paint(f'{self.state.dxy_price:.2f}', Color.WHITE):>8} {Color.paint('▼' if self.state.tick_direction == '▲' else '▲', Color.RED if self.state.tick_direction == '▲' else Color.GREEN)}")
        left_lines.append(f" {Color.paint('US10Y', Color.CYAN):<8} {Color.paint(f'{self.state.us10y_yield:.3f}%', Color.WHITE):>8} {Color.paint('■', Color.WHITE)}")
        left_lines.append(Color.paint(" ─────────────────── ", Color.GRAY))
        left_lines.append(Color.paint(" Feed Status: ONLINE ", Color.GREEN))

        # --- B. CENTER PANEL: LIVE SPOT GOLD CHART ---
        chart_cols = max(5, (w_center - 11) // 2)
        chart_height = max(7, h_total - 24)  # Give slightly more room for the calendar below
        
        # Pick dynamic candle feed
        active_feed = h1 if self.active_timeframe == "H1" else h4
        
        # If dynamic websocket feed is still empty/connecting, fallback to simulated ticker history
        if not active_feed:
            active_feed = self.state.get_all_visible_candles()
            source_info = "SIMULATED"
        else:
            source_info = "LIVE"
            
        chart_rows = get_candlestick_rows(active_feed, width=chart_cols, height=chart_height)
        
        tf_label = Color.paint(f" {self.active_timeframe} ({source_info}) ", Color.BOLD + Color.AMBER)
        control_hint = Color.paint(" [Press 1:H1 | 4:H4] ", Color.GRAY)
        
        header_text = f"  GOLD {tf_label}{control_hint}"
        header_len = len(strip_ansi(header_text))
        h_spacer = " " * max(0, w_center - header_len)
        
        center_lines.append(f"{header_text}{h_spacer}")
        for r_line in chart_rows:
            center_lines.append(r_line)

        # --- C. RIGHT PANEL: ORDER ENTRY & ALERTS ---
        action = self.state.signal_type
        badge = Color.paint(f" {action} ", Color.BOLD + (Color.BG_GREEN if action == "BUY" else Color.BG_RED))
        
        right_lines.append(Color.paint("  ORDERENTRY / ALERTS  ", Color.BOLD + Color.AMBER))
        right_lines.append(Color.paint(" ─────────────────────── ", Color.GRAY))
        right_lines.append(f" {Color.paint('ACTION:', Color.CYAN):<12} {badge}")
        right_lines.append(f" {Color.paint('ENTRY:', Color.CYAN):<12} {Color.paint(f'{self.state.signal_entry:.2f}', Color.WHITE)}")
        right_lines.append(f" {Color.paint('SL:', Color.CYAN):<12} {Color.paint(f'{self.state.signal_sl:.2f}', Color.RED)}")
        right_lines.append(f" {Color.paint('TP:', Color.CYAN):<12} {Color.paint(f'{self.state.signal_tp:.2f}', Color.GREEN)}")
        
        filled = int(self.state.signal_confidence / 10)
        conf_bar = Color.paint("█" * filled, Color.GREEN if action == "BUY" else Color.RED) + Color.paint("░" * (10 - filled), Color.GRAY)
        right_lines.append(f" {Color.paint('CONFIDENCE:', Color.CYAN):<12} {self.state.signal_confidence}%")
        right_lines.append(f" [{conf_bar}]")
        right_lines.append(Color.paint(" ─────────────────────── ", Color.GRAY))
        right_lines.append(f" {Color.paint('EXEC:', Color.CYAN):<12} {Color.paint('AUTO-ON', Color.GREEN)}")

        # Equalize panel row heights perfectly based on the maximum lines generated
        num_rows = max(len(left_lines), len(center_lines), len(right_lines))
        while len(left_lines) < num_rows:
            left_lines.append("")
        while len(center_lines) < num_rows:
            center_lines.append("")
        while len(right_lines) < num_rows:
            right_lines.append("")

        # Render rows side-by-side with dynamic padding alignment
        for i in range(num_rows):
            l_col = left_lines[i]
            c_col = center_lines[i]
            r_col = right_lines[i]
            
            l_len = len(strip_ansi(l_col))
            c_len = len(strip_ansi(c_col))
            r_len = len(strip_ansi(r_col))
            
            l_pad = " " * max(0, w_left - l_len)
            c_pad = " " * max(0, w_center - c_len)
            r_pad = " " * max(0, w_right - r_len)
            
            print(f"│{l_col}{l_pad}│{c_col}{c_pad}│{r_col}{r_pad}│")

        print(border_mid)

        # -----------------------------------------------------------------
        # ROW 3: TIMEFRAME MONITOR (H1 & H4 ANALYSIS)
        # -----------------------------------------------------------------
        def format_candle(tf_name, candle_data):
            if not candle_data:
                return Color.paint(f"  [{tf_name}] Awaiting websocket feed data...", Color.GRAY)
            
            c = candle_data[-1] if isinstance(candle_data, list) else candle_data
            
            op = c.get("open", 0.0)
            hi = c.get("high", 0.0)
            lo = c.get("low", 0.0)
            cl = c.get("close", 0.0)
            
            trend = "BULLISH ▲" if cl >= op else "BEARISH ▼"
            trend_color = Color.GREEN if cl >= op else Color.RED
            
            o_str = f"O: {Color.paint(f'{op:.2f}', Color.WHITE)}"
            h_str = f"H: {Color.paint(f'{hi:.2f}', Color.GREEN)}"
            l_str = f"L: {Color.paint(f'{lo:.2f}', Color.RED)}"
            c_str = f"C: {Color.paint(f'{cl:.2f}', Color.WHITE)}"
            trend_str = Color.paint(trend, trend_color)
            
            return f" [{Color.paint(tf_name, Color.CYAN)}]  {o_str}  │  {h_str}  │  {l_str}  │  {c_str}  │  ST: {trend_str}"

        h1_view = format_candle("H1", h1)
        h4_view = format_candle("H4", h4)
        
        for view in [h1_view, h4_view]:
            view_len = len(strip_ansi(view))
            spacer = " " * max(0, w_inner - view_len)
            print(f"│{view}{spacer}│")

        print(border_divider)

        # -----------------------------------------------------------------
        # ROW 4: PORTFOLIO & POSITION DESK
        # -----------------------------------------------------------------
        pos_title = Color.paint(" ACTIVE PORTFOLIO & POSITION MANAGER ", Color.BOLD + Color.AMBER)
        pos_title_len = len(strip_ansi(pos_title))
        p_title_spacer = " " * max(0, w_inner - pos_title_len)
        print(f"│{pos_title}{p_title_spacer}│")
        
        # Table Headers
        headers = f"  {'SYMBOL':<10} {'TYPE':<6} {'LOTS':<6} {'ENTRY':<10} {'MARKET':<10} {'PNL ($)':<12} {'RETURN (%)':<12} {'STATUS':<8}"
        headers_len = len(strip_ansi(headers))
        h_spacer = " " * max(0, w_inner - headers_len)
        print(f"│{Color.paint(headers, Color.CYAN)}{h_spacer}│")
        
        if self.state.position_active:
            pos_entry = self.state.signal_entry
            pnl_val = 0.0
            pnl_pct = 0.0
            
            if pos_entry > 0:
                pip_diff = curr_gold - pos_entry
                pnl_val = pip_diff * 50.0  # 0.50 Lots equivalent leverage
                pnl_pct = (pip_diff / pos_entry) * 100.0
                
            pnl_color = Color.GREEN if pnl_val >= 0 else Color.RED
            p_val_str = f"${pnl_val:+.2f}"
            p_pct_str = f"{pnl_pct:+.3f}%"
            
            # Position Data Formatting Row
            pos_row = f"  {Color.paint('XAUUSD', Color.WHITE):<19} {Color.paint('BUY', Color.GREEN):<15} {Color.paint('0.50', Color.WHITE):<15} {pos_entry:<10.2f} {curr_gold:<10.2f} {Color.paint(f'{p_val_str:<12}', pnl_color)} {Color.paint(f'{p_pct_str:<12}', pnl_color)} {Color.paint('ACTIVE', Color.GREEN):<17}"
            pos_len = len(strip_ansi(pos_row))
            pad = " " * max(0, w_inner - pos_len)
            print(f"│{pos_row}{pad}│")
        else:
            empty_msg = "  No active positions found for XAUUSD."
            empty_msg_len = len(empty_msg)
            pad = " " * max(0, w_inner - empty_msg_len)
            print(f"│{Color.paint(empty_msg, Color.GRAY)}{pad}│")
            
        print(border_divider)

        # -----------------------------------------------------------------
        # ROW 5: UPCOMING ECONOMIC CALENDAR & GOLD VOLATILITY DESK
        # -----------------------------------------------------------------
        cal_title = Color.paint(" UPCOMING HIGH-IMPACT ECONOMIC CALENDAR (XAU/USD IMPACT) ", Color.BOLD + Color.AMBER)
        cal_title_len = len(strip_ansi(cal_title))
        cal_title_spacer = " " * max(0, w_inner - cal_title_len)
        print(f"│{cal_title}{cal_title_spacer}│")
        
        # Calendar Headers (dynamically aligned)
        cal_headers = f"  {'ECONOMIC EVENT':<30} {'RELEASE TIME':<14} {'COUNTDOWN (STOPWATCH)':<24} {'GOLD FORECAST':<16} {'VOLATILITY':<12}"
        cal_headers_len = len(strip_ansi(cal_headers))
        cal_h_spacer = " " * max(0, w_inner - cal_headers_len)
        print(f"│{Color.paint(cal_headers, Color.CYAN)}{cal_h_spacer}│")
        
        # Draw dynamic events with real stopwatch countdowns!
        events = self.calendar.get_upcoming_events()
        for e in events:
            forecast_str = Color.paint("BULLISH ▲", Color.GREEN) if e["forecast"] == "BULLISH" else Color.paint("BEARISH ▼", Color.RED)
            vol_color = Color.RED if e["volatility"] in ["CRITICAL", "VERY HIGH"] else Color.AMBER
            vol_str = Color.paint(e["volatility"], Color.BOLD + vol_color)
            
            cal_row = f"  {Color.paint(e['name'], Color.WHITE):<39} {e['time']:<14} {Color.paint(e['countdown'], Color.CYAN):<33} {forecast_str:<25} {vol_str:<21}"
            cal_len = len(strip_ansi(cal_row))
            cal_pad = " " * max(0, w_inner - cal_len)
            print(f"│{cal_row}{cal_pad}│")

        print(border_bottom)
        sys.stdout.flush()


# Instantiate singleton for rendering
dashboard = TerminalDashboard(state)


# =====================================================================
# PUBLIC EXPORTED ENTRYPOINT (PRESERVES original API compatibility)
# =====================================================================
def render(price, h1, h4):
    """Entrypoint function called by main.py to render the trading terminal layout."""
    dashboard.render_view(price, h1, h4)