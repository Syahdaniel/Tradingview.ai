
import json
import urllib.request
import urllib.error
from flask import Flask, jsonify, render_template

app = Flask(__name__)

BINANCE_URL = "https://data-api.binance.vision/api/v3"


# ==============================
# GET BINANCE CANDLES
# ==============================

def get_candles(interval, limit=200):
    url = (
        f"{BINANCE_URL}/klines"
        f"?symbol=BTCUSDT&interval={interval}&limit={limit}"
    )

    request = urllib.request.Request(
        url,
        headers={"User-Agent": "BTC-Analyzer/1.0"}
    )

    with urllib.request.urlopen(request, timeout=15) as response:
        raw_data = json.loads(response.read().decode("utf-8"))

    # Abaikan candle yang masih sedang terbentuk
    closed_data = raw_data[:-1]

    candles = []

    for item in closed_data:
        candles.append({
            "time": int(item[0]),
            "open": float(item[1]),
            "high": float(item[2]),
            "low": float(item[3]),
            "close": float(item[4]),
            "volume": float(item[5])
        })

    if len(candles) < 60:
        raise ValueError("Data candle tidak mencukupi.")

    return candles


# ==============================
# GET MARKET DATA
# ==============================

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


# ==============================
# EMA
# ==============================

def calculate_ema(values, period):
    if len(values) < period:
        return None

    multiplier = 2 / (period + 1)

    ema = sum(values[:period]) / period

    for price in values[period:]:
        ema = (price * multiplier) + (ema * (1 - multiplier))

    return round(ema, 2)


# ==============================
# RSI
# ==============================

def calculate_rsi(values, period=14):
    if len(values) <= period:
        return None

    gains = []
    losses = []

    for i in range(1, len(values)):
        change = values[i] - values[i - 1]
        gains.append(max(change, 0))
        losses.append(max(-change, 0))

    average_gain = sum(gains[:period]) / period
    average_loss = sum(losses[:period]) / period

    for i in range(period, len(gains)):
        average_gain = (
            (average_gain * (period - 1)) + gains[i]
        ) / period

        average_loss = (
            (average_loss * (period - 1)) + losses[i]
        ) / period

    if average_loss == 0:
        return 100.0

    rs = average_gain / average_loss
    rsi = 100 - (100 / (1 + rs))

    return round(rsi, 2)


# ==============================
# MARKET STRUCTURE
# ==============================

def analyze_structure(candles):
    highs = []
    lows = []

    for i in range(2, len(candles) - 2):
        high = candles[i]["high"]
        low = candles[i]["low"]

        if (
            high > candles[i - 1]["high"]
            and high > candles[i - 2]["high"]
            and high > candles[i + 1]["high"]
            and high > candles[i + 2]["high"]
        ):
            highs.append(high)

        if (
            low < candles[i - 1]["low"]
            and low < candles[i - 2]["low"]
            and low < candles[i + 1]["low"]
            and low < candles[i + 2]["low"]
        ):
            lows.append(low)

    if len(highs) < 2 or len(lows) < 2:
        return {
            "high_structure": "UNKNOWN",
            "low_structure": "UNKNOWN",
            "swing_high": None,
            "swing_low": None,
            "previous_swing_high": None,
            "previous_swing_low": None,
            "bos": "NO_CONFIRMED_BOS"
        }

    previous_high = highs[-2]
    latest_high = highs[-1]

    previous_low = lows[-2]
    latest_low = lows[-1]

    high_structure = (
        "HH" if latest_high > previous_high else "LH"
    )

    low_structure = (
        "HL" if latest_low > previous_low else "LL"
    )

    last_close = candles[-1]["close"]

    if last_close > latest_high:
        bos = "BULLISH_BOS"
    elif last_close < latest_low:
        bos = "BEARISH_BOS"
    else:
        bos = "NO_CONFIRMED_BOS"

    return {
        "high_structure": high_structure,
        "low_structure": low_structure,
        "swing_high": latest_high,
        "swing_low": latest_low,
        "previous_swing_high": previous_high,
        "previous_swing_low": previous_low,
        "bos": bos
    }


# ==============================
# ANALYZE EACH TIMEFRAME
# ==============================

def analyze_timeframe(candles):
    closes = [candle["close"] for candle in candles]

    price = closes[-1]
    ema20 = calculate_ema(closes, 20)
    ema50 = calculate_ema(closes, 50)
    rsi = calculate_rsi(closes)

    if ema20 is None or ema50 is None:
        trend = "UNKNOWN"
    elif price > ema20 and ema20 > ema50:
        trend = "BULLISH"
    elif price < ema20 and ema20 < ema50:
        trend = "BEARISH"
    else:
        trend = "SIDEWAYS"

    return {
        "price": round(price, 2),
        "ema20": ema20,
        "ema50": ema50,
        "rsi14": rsi,
        "trend": trend,
        "market_structure": analyze_structure(candles)
    }


# ==============================
# LONG / SHORT SIGNAL ENGINE
# ==============================

def analyze_market(data):
    timeframes = data["timeframes"]

    h4 = timeframes["H4"]
    h1 = timeframes["H1"]
    m15 = timeframes["M15"]

    entry = m15["price"]
    structure = m15["market_structure"]

    signal = "WAIT"
    stop_loss = None
    take_profit = None

    reason = "Belum ada confirmation yang lengkap."

    if (
        h4["trend"] == "BULLISH"
        and h1["trend"] == "BULLISH"
        and m15["trend"] == "BULLISH"
        and structure["bos"] == "BULLISH_BOS"
    ):
        swing_low = structure["swing_low"]

        if swing_low is not None and swing_low < entry:
            signal = "LONG"
            stop_loss = round(swing_low, 2)
            take_profit = round(
                entry + ((entry - stop_loss) * 2), 2
            )
            reason = "Semua timeframe bullish dengan M15 bullish BOS."

    elif (
        h4["trend"] == "BEARISH"
        and h1["trend"] == "BEARISH"
        and m15["trend"] == "BEARISH"
        and structure["bos"] == "BEARISH_BOS"
    ):
        swing_high = structure["swing_high"]

        if swing_high is not None and swing_high > entry:
            signal = "SHORT"
            stop_loss = round(swing_high, 2)
            take_profit = round(
                entry - ((stop_loss - entry) * 2), 2
            )
            reason = "Semua timeframe bearish dengan M15 bearish BOS."

    return {
        "decision": signal,
        "exchange": data["exchange"],
        "symbol": data["symbol"],
        "entry": entry if signal != "WAIT" else None,
        "stop_loss": stop_loss,
        "take_profit": take_profit,
        "risk_reward": "1:2" if signal != "WAIT" else None,
        "signal_reason": reason,
        "timeframes": timeframes,
        "note": (
            "Analisis teknikal sahaja. "
            "Tiada order sebenar dihantar. "
            "Signal bukan jaminan keuntungan."
        )
    }


# ==============================
# DASHBOARD
# ==============================

@app.route("/", methods=["GET"])
def home():
    return render_template("index.html")


# ==============================
# BTC DATA API
# ==============================

@app.route("/btc-data", methods=["GET"])
def btc_data():
    try:
        data = get_market_data()

        result = {
            "symbol": data["symbol"],
            "exchange": data["exchange"],
            "timeframes": {
                name: analyze_timeframe(candles)
                for name, candles in data["timeframes"].items()
            }
        }

        return jsonify(result)

    except Exception as error:
        app.logger.exception("BTC data error")
        return jsonify({"error": str(error)}), 500


# ==============================
# BTC ANALYSIS API
# ==============================

@app.route("/btc-analysis", methods=["GET"])
def btc_analysis():
    try:
        data = get_market_data()

        analyzed_data = {
            "symbol": data["symbol"],
            "exchange": data["exchange"],
            "timeframes": {
                name: analyze_timeframe(candles)
                for name, candles in data["timeframes"].items()
            }
        }

        result = analyze_market(analyzed_data)

        return jsonify(result)

    except Exception as error:
        app.logger.exception("BTC analysis error")
        return jsonify({"error": str(error)}), 500


# ==============================
# LIVE BTC PRICE API
# ==============================

@app.route("/btc-price", methods=["GET"])
def btc_price():
    try:
        url = f"{BINANCE_URL}/ticker/price?symbol=BTCUSDT"

        request = urllib.request.Request(
            url,
            headers={"User-Agent": "BTC-Analyzer/1.0"}
        )

        with urllib.request.urlopen(request, timeout=10) as response:
            result = json.loads(response.read().decode("utf-8"))

        return jsonify({
            "symbol": result["symbol"],
            "price": float(result["price"]),
            "exchange": "BINANCE"
        })

    except Exception as error:
        app.logger.exception("BTC price error")
        return jsonify({"error": str(error)}), 500


# ==============================
# START SERVER
# ==============================

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
