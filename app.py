
import json
import urllib.request
from flask import Flask, jsonify, render_template

app = Flask(__name__)


# ==================================
# 1. BINANCE BTCUSDT DATA
# ==================================

def get_candles(interval):
    url = (
        "https://data-api.binance.vision/api/v3/klines"
        f"?symbol=BTCUSDT&interval={interval}&limit=100"
    )

    request = urllib.request.Request(
        url,
        headers={"User-Agent": "BTC-AI-Server"}
    )

    with urllib.request.urlopen(request, timeout=15) as response:
        raw_data = json.loads(response.read().decode())

    return [
        {
            "time": candle[0],
            "open": float(candle[1]),
            "high": float(candle[2]),
            "low": float(candle[3]),
            "close": float(candle[4]),
            "volume": float(candle[5])
        }
        for candle in raw_data[:-1]
    ]


def get_market_data():
    return {
        "symbol": "BTCUSDT",
        "exchange": "BINANCE",
        "timeframes": {
            "M15": get_candles("15m"),
            "H1": get_candles("1h"),
            "H4": get_candles("4h")
        }
    }


# ==================================
# 2. EMA CALCULATION
# ==================================

def calculate_ema(values, period):
    if len(values) < period:
        return None

    ema = sum(values[:period]) / period
    multiplier = 2 / (period + 1)

    for price in values[period:]:
        ema = (
            price * multiplier
            + ema * (1 - multiplier)
        )

    return ema


# ==================================
# 3. RSI CALCULATION
# ==================================

def calculate_rsi(values, period=14):
    if len(values) <= period:
        return None

    changes = [
        values[i] - values[i - 1]
        for i in range(1, len(values))
    ]

    recent = changes[-period:]

    gains = [x for x in recent if x > 0]
    losses = [-x for x in recent if x < 0]

    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period

    if avg_loss == 0:
        return 100.0 if avg_gain > 0 else 50.0

    rs = avg_gain / avg_loss

    return 100 - (100 / (1 + rs))

# ==================================
# 4. MARKET STRUCTURE ANALYSIS
# ==================================

def analyze_structure(candles):
    highs = [c["high"] for c in candles]
    lows = [c["low"] for c in candles]
    closes = [c["close"] for c in candles]

    swing_highs = []
    swing_lows = []

    # Detect confirmed swing points
    for i in range(2, len(candles) - 2):

        if (
            highs[i] > highs[i - 1]
            and highs[i] > highs[i - 2]
            and highs[i] > highs[i + 1]
            and highs[i] > highs[i + 2]
        ):
            swing_highs.append({
                "index": i,
                "price": highs[i]
            })

        if (
            lows[i] < lows[i - 1]
            and lows[i] < lows[i - 2]
            and lows[i] < lows[i + 1]
            and lows[i] < lows[i + 2]
        ):
            swing_lows.append({
                "index": i,
                "price": lows[i]
            })

    last_high = swing_highs[-1] if swing_highs else None
    previous_high = (
        swing_highs[-2] if len(swing_highs) >= 2 else None
    )

    last_low = swing_lows[-1] if swing_lows else None
    previous_low = (
        swing_lows[-2] if len(swing_lows) >= 2 else None
    )

    # High structure
    if last_high and previous_high:
        high_structure = (
            "HH"
            if last_high["price"] > previous_high["price"]
            else "LH"
        )
    else:
        high_structure = "INSUFFICIENT_DATA"

    # Low structure
    if last_low and previous_low:
        low_structure = (
            "HL"
            if last_low["price"] > previous_low["price"]
            else "LL"
        )
    else:
        low_structure = "INSUFFICIENT_DATA"

    current_price = closes[-1]

    # Break of Structure
    if last_high and current_price > last_high["price"]:
        bos = "BULLISH_BOS"

    elif last_low and current_price < last_low["price"]:
        bos = "BEARISH_BOS"

    else:
        bos = "NO_CONFIRMED_BOS"

    return {
        "swing_high": (
            round(last_high["price"], 2) if last_high else None
        ),
        "previous_swing_high": (
            round(previous_high["price"], 2)
            if previous_high else None
        ),
        "swing_low": (
            round(last_low["price"], 2) if last_low else None
        ),
        "previous_swing_low": (
            round(previous_low["price"], 2)
            if previous_low else None
        ),
        "high_structure": high_structure,
        "low_structure": low_structure,
        "bos": bos
    }


# ==================================
# 5. TIMEFRAME ANALYSIS
# ==================================

def analyze_timeframe(candles):
    closes = [c["close"] for c in candles]

    ema20 = calculate_ema(closes, 20)
    ema50 = calculate_ema(closes, 50)
    rsi = calculate_rsi(closes)

    price = closes[-1]

    if ema20 is None or ema50 is None or rsi is None:
        raise ValueError("Not enough candle data")

    if price > ema20 > ema50:
        trend = "BULLISH"

    elif price < ema20 < ema50:
        trend = "BEARISH"

    else:
        trend = "NEUTRAL"

    return {
        "price": round(price, 2),
        "ema20": round(ema20, 2),
        "ema50": round(ema50, 2),
        "rsi14": round(rsi, 2),
        "trend": trend,
        "market_structure": analyze_structure(candles)
    }
# ==================================
# 6. COMPLETE MARKET ANALYSIS
# ==================================
def analyze_market(data):
    h4 = data["timeframes"]["H4"]
    h1 = data["timeframes"]["H1"]
    m15 = data["timeframes"]["M15"]

    entry = m15["price"]
    structure = m15["market_structure"]

    h4_trend = h4["trend"]
    h1_trend = h1["trend"]
    m15_trend = m15["trend"]
    bos = structure["bos"]

    signal = "WAIT"
    stop_loss = None
    take_profit = None
    reason = "Belum ada confirmation yang lengkap."

    if (
        h4_trend == "BULLISH"
        and h1_trend == "BULLISH"
        and m15_trend == "BULLISH"
        and bos == "BULLISH_BOS"
    ):
        swing_low = structure["swing_low"]

        if swing_low < entry:
            signal = "LONG"
            stop_loss = swing_low
            take_profit = entry + (entry - stop_loss) * 2
            reason = "Semua timeframe bullish dan M15 mengesahkan bullish BOS."

    elif (
        h4_trend == "BEARISH"
        and h1_trend == "BEARISH"
        and m15_trend == "BEARISH"
        and bos == "BEARISH_BOS"
    ):
        swing_high = structure["swing_high"]

        if swing_high > entry:
            signal = "SHORT"
            stop_loss = swing_high
            take_profit = entry - (stop_loss - entry) * 2
            reason = "Semua timeframe bearish dan M15 mengesahkan bearish BOS."

    return {
        "decision": signal,
        "exchange": data["exchange"],
        "symbol": data["symbol"],
        "entry": entry if signal != "WAIT" else None,
        "stop_loss": stop_loss,
        "take_profit": take_profit,
        "risk_reward": "1:2" if signal != "WAIT" else None,
        "signal_reason": reason,
        "timeframes": data["timeframes"],
        "note": "Analisis teknikal sahaja. Tiada order sebenar dihantar."
    } 


@app.route("/btc-data", methods=["GET"])
def btc_data():
    try:
        return jsonify(get_market_data()), 200

    except Exception as error:
        return jsonify({
            "status": "error",
            "message": str(error)
        }), 502


@app.route("/btc-analysis", methods=["GET"])
def btc_analysis():
    try:
        data = get_market_data()
        result = analyze_market(data)

        return jsonify(result), 200

    except Exception as error:
        return jsonify({
            "status": "error",
            "message": str(error)
        }), 502
