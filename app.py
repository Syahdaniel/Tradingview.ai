
import json
import urllib.request
import urllib.error
from datetime import datetime, timezone
from flask import Flask, jsonify, render_template

app = Flask(__name__)

BINANCE_URL = "https://data-api.binance.vision/api/v3"
FUTURES_URL = "https://fapi.binance.com/fapi/v1"


# =====================================
# BINANCE DATA
# =====================================

def fetch_json(url, timeout=15):
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "TradingviewAI/2.0"}
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def get_candles(interval, limit=200):
    url = (
        f"{BINANCE_URL}/klines"
        f"?symbol=BTCUSDT&interval={interval}&limit={limit}"
    )
    raw = fetch_json(url)

    # Ignore the currently forming candle
    raw = raw[:-1]

    candles = []
    for item in raw:
        candles.append({
            "time": int(item[0]),
            "open": float(item[1]),
            "high": float(item[2]),
            "low": float(item[3]),
            "close": float(item[4]),
            "volume": float(item[5])
        })

    if len(candles) < 60:
        raise ValueError("Insufficient candle data")

    return candles


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


# =====================================
# INDICATORS
# =====================================

def calculate_ema(values, period):
    if len(values) < period:
        return None

    multiplier = 2 / (period + 1)
    ema = sum(values[:period]) / period

    for value in values[period:]:
        ema = value * multiplier + ema * (1 - multiplier)

    return round(ema, 2)


def calculate_rsi(values, period=14):
    if len(values) <= period:
        return None

    gains = []
    losses = []

    for i in range(1, len(values)):
        change = values[i] - values[i - 1]
        gains.append(max(change, 0))
        losses.append(max(-change, 0))

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    for i in range(period, len(gains)):
        avg_gain = ((avg_gain * (period - 1)) + gains[i]) / period
        avg_loss = ((avg_loss * (period - 1)) + losses[i]) / period

    if avg_loss == 0:
        return 100.0

    rs = avg_gain / avg_loss
    return round(100 - (100 / (1 + rs)), 2)


def calculate_atr(candles, period=14):
    if len(candles) <= period:
        return None

    ranges = []

    for i in range(1, len(candles)):
        current = candles[i]
        previous_close = candles[i - 1]["close"]

        ranges.append(max(
            current["high"] - current["low"],
            abs(current["high"] - previous_close),
            abs(current["low"] - previous_close)
        ))

    return sum(ranges[-period:]) / period


# =====================================
# MARKET STRUCTURE
# =====================================

def analyze_structure(candles):
    highs = []
    lows = []

    for i in range(2, len(candles) - 2):
        candle = candles[i]

        if (
            candle["high"] > candles[i - 1]["high"]
            and candle["high"] > candles[i - 2]["high"]
            and candle["high"] > candles[i + 1]["high"]
            and candle["high"] > candles[i + 2]["high"]
        ):
            highs.append(candle["high"])

        if (
            candle["low"] < candles[i - 1]["low"]
            and candle["low"] < candles[i - 2]["low"]
            and candle["low"] < candles[i + 1]["low"]
            and candle["low"] < candles[i + 2]["low"]
        ):
            lows.append(candle["low"])

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

    previous_high, latest_high = highs[-2], highs[-1]
    previous_low, latest_low = lows[-2], lows[-1]
    close = candles[-1]["close"]

    if close > latest_high:
        bos = "BULLISH_BOS"
    elif close < latest_low:
        bos = "BEARISH_BOS"
    else:
        bos = "NO_CONFIRMED_BOS"

    return {
        "high_structure": "HH" if latest_high > previous_high else "LH",
        "low_structure": "HL" if latest_low > previous_low else "LL",
        "swing_high": latest_high,
        "swing_low": latest_low,
        "previous_swing_high": previous_high,
        "previous_swing_low": previous_low,
        "bos": bos
    }


# =====================================
# TIMEFRAME ANALYSIS
# =====================================

def analyze_timeframe(candles):
    closes = [c["close"] for c in candles]

    price = closes[-1]
    ema20 = calculate_ema(closes, 20)
    ema50 = calculate_ema(closes, 50)
    rsi = calculate_rsi(closes)

    if price > ema20 and ema20 > ema50:
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


# =====================================
# SIGNAL ENGINE
# =====================================

def analyze_market(data):
    tf = data["timeframes"]

    h4 = tf["H4"]
    h1 = tf["H1"]
    m15 = tf["M15"]

    entry = m15["price"]
    structure = m15["market_structure"]

    decision = "WAIT"
    stop_loss = None
    take_profit = None
    reason = "Belum ada confirmation lengkap."

    if (
        h4["trend"] == "BULLISH"
        and h1["trend"] == "BULLISH"
        and m15["trend"] == "BULLISH"
        and structure["bos"] == "BULLISH_BOS"
    ):
        swing_low = structure["swing_low"]

        if swing_low and swing_low < entry:
            decision = "LONG"
            stop_loss = round(swing_low, 2)
            take_profit = round(entry + 2 * (entry - stop_loss), 2)
            reason = "H4, H1 dan M15 bullish dengan bullish BOS."

    elif (
        h4["trend"] == "BEARISH"
        and h1["trend"] == "BEARISH"
        and m15["trend"] == "BEARISH"
        and structure["bos"] == "BEARISH_BOS"
    ):
        swing_high = structure["swing_high"]

        if swing_high and swing_high > entry:
            decision = "SHORT"
            stop_loss = round(swing_high, 2)
            take_profit = round(entry - 2 * (stop_loss - entry), 2)
            reason = "H4, H1 dan M15 bearish dengan bearish BOS."

    return {
        "decision": decision,
        "exchange": data["exchange"],
        "symbol": data["symbol"],
        "entry": entry if decision != "WAIT" else None,
        "stop_loss": stop_loss,
        "take_profit": take_profit,
        "risk_reward": "1:2" if decision != "WAIT" else None,
        "signal_reason": reason,
        "timeframes": tf,
        "note": "Analisis sahaja. Tiada order sebenar dihantar."
    }


# =====================================
# HISTORICAL BACKTEST
# =====================================

def run_backtest(candles, fee_percent=0.0004):
    """
    EMA20/EMA50 trend strategy.
    Entry at next candle open.
    Stop = 1.5 ATR; target = 2R.
    If stop and target hit in the same candle, stop is assumed first.
    """

    trades = []
    closes = [c["close"] for c in candles]

    for i in range(60, len(candles) - 1):
        history = candles[:i]
        price = closes[i - 1]

        ema20 = calculate_ema(closes[:i], 20)
        ema50 = calculate_ema(closes[:i], 50)
        rsi = calculate_rsi(closes[:i])
        atr = calculate_atr(history)

        if not ema20 or not ema50 or not atr or not rsi:
            continue

        direction = None

        if price > ema20 and ema20 > ema50 and rsi > 50:
            direction = "LONG"
        elif price < ema20 and ema20 < ema50 and rsi < 50:
            direction = "SHORT"

        if direction is None:
            continue

        entry = candles[i]["open"]
        risk = atr * 1.5

        if direction == "LONG":
            stop = entry - risk
            target = entry + (risk * 2)
        else:
            stop = entry + risk
            target = entry - (risk * 2)

        outcome = "OPEN"
        exit_price = candles[i]["close"]

        # Maximum holding period: 24 candles
        for future in candles[i:min(i + 25, len(candles))]:
            if direction == "LONG":
                stop_hit = future["low"] <= stop
                target_hit = future["high"] >= target
            else:
                stop_hit = future["high"] >= stop
                target_hit = future["low"] <= target

            if stop_hit:
                outcome = "LOSS"
                exit_price = stop
                break

            if target_hit:
                outcome = "WIN"
                exit_price = target
                break

        if outcome == "OPEN":
            continue

        if direction == "LONG":
            gross_return = (exit_price - entry) / entry
        else:
            gross_return = (entry - exit_price) / entry

        net_return = gross_return - (fee_percent * 2)

        trades.append({
            "direction": direction,
            "entry": round(entry, 2),
            "exit": round(exit_price, 2),
            "result": outcome,
            "return_percent": round(net_return * 100, 4)
        })

    total = len(trades)
    wins = sum(1 for t in trades if t["return_percent"] > 0)
    losses = total - wins

    win_rate = (wins / total * 100) if total else 0
    total_return = sum(t["return_percent"] for t in trades)

    return {
        "symbol": "BTCUSDT",
        "timeframe": "15m",
        "total_trades": total,
        "wins": wins,
        "losses": losses,
        "win_rate_percent": round(win_rate, 2),
        "net_return_percent": round(total_return, 2),
        "fee_per_side_percent": fee_percent * 100,
        "trades": trades[-30:],
        "warning": (
            "Historical simulation only. Results do not predict "
            "future performance. Slippage and funding are not included."
        )
    }


# =====================================
# BINANCE FUTURES INTELLIGENCE
# =====================================

def get_futures_data():
    funding = fetch_json(
        f"{FUTURES_URL}/premiumIndex?symbol=BTCUSDT"
    )

    open_interest = fetch_json(
        f"{FUTURES_URL}/openInterest?symbol=BTCUSDT"
    )

    return {
        "symbol": "BTCUSDT",
        "funding_rate": float(funding["lastFundingRate"]),
        "next_funding_time": int(funding["nextFundingTime"]),
        "mark_price": float(funding["markPrice"]),
        "open_interest": float(open_interest["openInterest"]),
        "source": "Binance USD-M Futures",
        "note": (
            "Open interest is a market-wide contract measure, "
            "not proof of whale buying or selling."
        )
    }


# =====================================
# DASHBOARD ROUTES
# =====================================

@app.route("/")
def home():
    return render_template("index.html")


@app.route("/btc-data")
def btc_data():
    try:
        data = get_market_data()

        return jsonify({
            "symbol": data["symbol"],
            "exchange": data["exchange"],
            "timeframes": {
                name: analyze_timeframe(candles)
                for name, candles in data["timeframes"].items()
            }
        })

    except Exception as error:
        app.logger.exception("BTC data error")
        return jsonify({"error": str(error)}), 500


@app.route("/btc-analysis")
def btc_analysis():
    try:
        data = get_market_data()

        analyzed = {
            "symbol": data["symbol"],
            "exchange": data["exchange"],
            "timeframes": {
                name: analyze_timeframe(candles)
                for name, candles in data["timeframes"].items()
            }
        }

        return jsonify(analyze_market(analyzed))

    except Exception as error:
        app.logger.exception("BTC analysis error")
        return jsonify({"error": str(error)}), 500


@app.route("/btc-price")
def btc_price():
    try:
        result = fetch_json(
            f"{BINANCE_URL}/ticker/price?symbol=BTCUSDT"
        )

        return jsonify({
            "symbol": result["symbol"],
            "price": float(result["price"]),
            "exchange": "BINANCE"
        })

    except Exception as error:
        app.logger.exception("BTC price error")
        return jsonify({"error": str(error)}), 500


@app.route("/btc-backtest")
def btc_backtest():
    try:
        candles = get_candles("15m", limit=1000)
        return jsonify(run_backtest(candles))

    except Exception as error:
        app.logger.exception("Backtest error")
        return jsonify({"error": str(error)}), 500


@app.route("/btc-intelligence")
def btc_intelligence():
    try:
        return jsonify(get_futures_data())

    except Exception as error:
        app.logger.exception("Futures data error")
        return jsonify({
            "error": str(error),
            "source": "Binance USD-M Futures"
        }), 500


# =====================================
# START SERVER
# =====================================

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
