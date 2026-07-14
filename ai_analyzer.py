import os
import json
import urllib.request
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

API_KEY = os.getenv("AGENTROUTER_API_KEY")
BASE_URL = os.getenv("AGENTROUTER_BASE_URL", "https://agentrouter.org/v1")
MODEL = os.getenv("AGENTROUTER_MODEL", "gpt-4o-mini")

def call_agentrouter_ai(system_prompt, user_prompt, max_tokens=120):
    """
    Call Agent Router API using standard library urllib to avoid extra dependencies.
    """
    if not API_KEY:
        print("AGENTROUTER_API_KEY is not set. Skipping AI generation.")
        return None

    url = f"{BASE_URL.rstrip('/')}/chat/completions"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {API_KEY}"
    }
    
    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
        "temperature": 0.7,
        "max_tokens": max_tokens
    }
    
    try:
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers=headers, method="POST")
        
        # 8-second timeout to ensure it doesn't freeze the trading loop
        with urllib.request.urlopen(req, timeout=8) as response:
            res_data = json.loads(response.read().decode("utf-8"))
            return res_data["choices"][0]["message"]["content"].strip()
    except Exception as e:
        print(f"Agent Router AI API Error: {e}")
        return None

def generate_entry_reason(direction, pattern, candle_pattern, entry_price, sl, tp, ema9, ema21, rsi, atr):
    """
    Generate professional, AI-powered reason for entering a trade.
    """
    system_prompt = (
        "You are an expert XAUUSD (Gold) trading analyst and algorithmic signal generator. "
        "Write a 1-sentence professional entry rationale. Do NOT use markdown. Keep it under 40 words."
    )
    
    user_prompt = (
        f"Generate an entry rationale for a XAUUSD {direction} trade. "
        f"Strategy: {pattern} ({candle_pattern}). "
        f"Entry price: {entry_price}, SL: {sl}, TP: {tp}. "
        f"Indicators: EMA9={ema9:.2f}, EMA21={ema21:.2f}, RSI={rsi:.1f}, ATR={atr:.2f}."
    )
    
    result = call_agentrouter_ai(system_prompt, user_prompt, max_tokens=100)
    if result:
        return f"AI Analysis: {result}"
    
    # Fallback if AI fails
    return f"{pattern} ({candle_pattern}) triggered {direction} entry. SL={sl:.2f}, TP={tp:.2f}."

def generate_trade_outcome_reason(hit, direction, pattern, entry, exit, pnl, recent_candles_summary):
    """
    Generate professional, AI-powered reason explaining why a trade hit TP (WIN) or SL (LOSS).
    """
    system_prompt = (
        "You are an expert XAUUSD (Gold) post-trade analyst. "
        "Explain the outcome of the trade in exactly 1-2 sentences. Focus on price action and market momentum. "
        "Do NOT use markdown. Keep it under 45 words."
    )
    
    user_prompt = (
        f"Explain why a XAUUSD {direction} trade using {pattern} hit {hit} (WIN/LOSS). "
        f"Entry price: {entry}, Exit price: {exit}, PnL: {pnl}. "
        f"Recent candle direction history: {recent_candles_summary}."
    )
    
    result = call_agentrouter_ai(system_prompt, user_prompt, max_tokens=120)
    if result:
        return f"{hit} Hit: {result}"
    
    # Fallback if AI fails
    if hit == "WIN":
        return f"TP Hit: {pattern} targets executed cleanly as market momentum favored the trade."
    else:
        return f"SL Hit: Market momentum reversed against the setup, invalidating the structure."
