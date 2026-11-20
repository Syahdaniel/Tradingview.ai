
import json
import urllib.request
from flask import Flask, jsonify

app = Flask(__name__)

# ==================================
# 1. AMBIL DATA BTC DARIPADA BINANCE
# ==================================

def get_candles(interval):
    url = (
        "https://data-api.binance.vision/api/v3/klines"
        f"?symbol=BTCUSDT&interval={interval}&limit=100"
    )

    req = urllib.request.Request(
        url,
        headers={"User-Agent": "BTC-AI-Server"}
    )

    with urllib.request.urlopen(req, timeout=15) as response:
        candles = json.loads(response.read().decode())

    # Abaikan candle terakhir yang masih berjalan
    closed_candles = candles[:-1]

    return [
        {
            "time": candle[0],
            "open": float(candle[1]),
            "high": float(candle[2]),
            "low": float(candle[3]),
            "close": float(candle[4]),
            "volume": float(candle[5])
        }
        for candle in closed_candles
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

    ema_value = sum(values[:period]) / period
    multiplier = 2 / (period + 1)

    for price in values[period:]:
        ema_value = (
            price * multiplier
            + ema_value * (1 - multiplier)
        )

    return ema_value


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

    recent_changes = changes[-period:]

    gains = [
        change for change in recent_changes
        if change > 0
    ]

    losses = [
        abs(change) for change in recent_changes
        if change < 0
    ]

    average_gain = sum(gains) / period
    average_loss = sum(losses) / period

    if average_loss == 0:
        return 100.0 if average_gain > 0 else 50.0

    rs = average_gain / average_loss

    return 100 - (100 / (1 + rs))


# ==================================
# 4. ANALYZE EACH TIMEFRAME
# ==================================

def analyze_timeframe(candles):
    closes = [candle["close"] for candle in candles]

    ema20 = calculate_ema(closes, 20)
    ema50 = calculate_ema(closes, 50)
    rsi = calculate_rsi(closes)

    price = closes[-1]

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
        "last_closed_candle": candles[-1]["time"]
    }


# ==================================
# 5. MULTI-TIMEFRAME ANALYSIS
# ==================================

def analyze_market(data):
    timeframes = data["timeframes"]

    analysis = {
        timeframe: analyze_timeframe(candles)
        for timeframe, candles in timeframes.items()
    }

    h4 = analysis["H4"]
    h1 = analysis["H1"]
    m15 = analysis["M15"]

    if (
        h4["trend"] == "BULLISH"
        and h1["trend"] == "BULLISH"
        and m15["trend"] == "BULLISH"
        and 50 <= m15["rsi14"] < 70
    ):
        decision = "BULLISH_SETUP"

    elif (
        h4["trend"] == "BEARISH"
        and h1["trend"] == "BEARISH"
        and m15["trend"] == "BEARISH"
        and 30 < m15["rsi14"] <= 50
    ):
        decision = "BEARISH_SETUP"

    else:
        decision = "WAIT"

    return {
        "symbol": "BTCUSDT",
        "exchange": "BINANCE",
        "decision": decision,
        "timeframes": analysis,
        "note": (
            "Technical indicator analysis only. "
            "Not a guaranteed trading signal. "
            "No trades are executed."
        )
    }


# ==================================
# 6. SERVER ROUTES
# ==================================

@app.route("/", methods=["GET"])
def home():
    return "BTC AI Server is running!"


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
