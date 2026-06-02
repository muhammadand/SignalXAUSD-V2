import os
import json
import asyncio
import threading
from dotenv import load_dotenv
from flask import Flask, render_template, jsonify

from state_manager import state

load_dotenv()

DERIV_WS_URL = os.getenv("DERIV_WS_URL")
SYMBOL = os.getenv("SYMBOL", "frxXAUUSD")

TIMEFRAME_MAP = {
    60:    "M1",
    300:   "M5",
    900:   "M15",
    3600:  "H1",
    14400: "H4"
}

MAX_COUNT = {
    "M1": 200,
    "M5": 200,
    "M15": 200,
    "H1": 200,
    "H4": 100
}

import websockets

async def deriv_ws_loop():
    print(f"CONNECTING TO DERIV WEBSOCKET FOR SYMBOL: {SYMBOL}...")
    while True:
        try:
            async with websockets.connect(DERIV_WS_URL) as ws:
                print("CONNECTED TO DERIV WEBSOCKET SUCCESSFUL")

                # Subscribe to live ticks
                await ws.send(json.dumps({"ticks": SYMBOL, "subscribe": 1}))

                # Subscribe candles for each timeframe
                for granularity, count in [(60, 200), (300, 200), (900, 200), (3600, 200), (14400, 100)]:
                    await ws.send(json.dumps({
                        "ticks_history": SYMBOL,
                        "style": "candles",
                        "granularity": granularity,
                        "subscribe": 1,
                        "count": count,
                        "end": "latest"
                    }))

                async for message in ws:
                    data = json.loads(message)

                    # --- Initial historical candle batch ---
                    if "candles" in data:
                        req = data.get("echo_req", {})
                        granularity = req.get("granularity", 0)
                        tf = TIMEFRAME_MAP.get(granularity)
                        if tf:
                            parsed = []
                            for c in data["candles"]:
                                parsed.append({
                                    "open":  float(c["open"]),
                                    "high":  float(c["high"]),
                                    "low":   float(c["low"]),
                                    "close": float(c["close"]),
                                    "epoch": int(c["epoch"]),
                                    "is_bullish": float(c["close"]) >= float(c["open"])
                                })
                            state.set_candles(tf, parsed)

                    # --- Live tick feed ---
                    elif "tick" in data:
                        state.update_price(float(data["tick"]["quote"]))

                    # --- Real-time OHLC bar update ---
                    elif "ohlc" in data:
                        ohlc = data["ohlc"]
                        tf = TIMEFRAME_MAP.get(int(ohlc["granularity"]))
                        if tf:
                            epoch = int(ohlc["open_time"])
                            new_candle = {
                                "open":  float(ohlc["open"]),
                                "high":  float(ohlc["high"]),
                                "low":   float(ohlc["low"]),
                                "close": float(ohlc["close"]),
                                "epoch": epoch,
                                "is_bullish": float(ohlc["close"]) >= float(ohlc["open"])
                            }
                            attr = f"candles_{tf.lower()}"
                            candles = list(getattr(state, attr, []))
                            if candles:
                                if candles[-1]["epoch"] == epoch:
                                    candles[-1] = new_candle
                                elif epoch > candles[-1]["epoch"]:
                                    candles.append(new_candle)
                            else:
                                candles.append(new_candle)

                            mc = MAX_COUNT.get(tf, 200)
                            if len(candles) > mc:
                                candles.pop(0)
                            state.set_candles(tf, candles)

        except Exception as e:
            print(f"WebSocket error: {e}. Reconnecting in 5s...")
            await asyncio.sleep(5)


def start_deriv_client():
    def run():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(deriv_ws_loop())
    threading.Thread(target=run, daemon=True).start()


app = Flask(__name__)

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/api/state")
def get_state():
    return jsonify(state.get_serializable_state())


if __name__ == "__main__":
    start_deriv_client()
    print("--------------------------------------------------")
    print("TCINVEST PRO WEB STATION  →  http://127.0.0.1:5001")
    print("--------------------------------------------------")
    app.run(host="127.0.0.1", port=5001, debug=False)