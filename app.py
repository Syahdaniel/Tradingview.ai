
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


def run_backtest(candles, fee_percent=0.0004, slippage_percent=0.0002,
                 atr_multiplier=1.5, reward_risk=2.0, max_holding_bars=24):

    trades = []
    equity = 1.0
    peak_equity = 1.0
    max_drawdown = 0.0
    i = 60

    while i < len(candles) - 1:
        history = candles[:i + 1]
        closes = [c["close"] for c in history]

        ema20 = calculate_ema(closes, 20)
        ema50 = calculate_ema(closes, 50)
        rsi = calculate_rsi(closes)
        atr = calculate_atr(history)

        if ema20 is None or ema50 is None or rsi is None or atr is None or atr <= 0:
            i += 1
            continue

        price = closes[-1]
        direction = None

        if price > ema20 and ema20 > ema50 and rsi >= 52:
            direction = "LONG"
        elif price < ema20 and ema20 < ema50 and rsi <= 48:
            direction = "SHORT"

        if direction is None:
            i += 1
            continue

        entry_bar = i + 1
        raw_entry = candles[entry_bar]["open"]

        if direction == "LONG":
            entry = raw_entry * (1 + slippage_percent)
        else:
            entry = raw_entry * (1 - slippage_percent)

        risk = atr * atr_multiplier

        if direction == "LONG":
            stop = entry - risk
            target = entry + risk * reward_risk
        else:
            stop = entry + risk
            target = entry - risk * reward_risk

        last_bar = min(
            entry_bar + max_holding_bars - 1,
            len(candles) - 1
        )

        exit_price = None
        exit_bar = entry_bar
        exit_reason = "TIME_EXIT"

        for j in range(entry_bar, last_bar + 1):
            bar = candles[j]

            if direction == "LONG":
                stop_hit = bar["low"] <= stop
                target_hit = bar["high"] >= target
            else:
                stop_hit = bar["high"] >= stop
                target_hit = bar["low"] <= target

            # Conservative: SL first if both hit
            if stop_hit:
                exit_price = stop
                exit_reason = "STOP_LOSS"
                exit_bar = j
                break

            if target_hit:
                exit_price = target
                exit_reason = "TAKE_PROFIT"
                exit_bar = j
                break

        if exit_price is None:
            exit_bar = last_bar
            exit_price = candles[last_bar]["close"]

        if direction == "LONG":
            executed_exit = exit_price * (1 - slippage_percent)
            gross_return = (executed_exit - entry) / entry
        else:
            executed_exit = exit_price * (1 + slippage_percent)
            gross_return = (entry - executed_exit) / entry

        net_return = gross_return - (fee_percent * 2)

        equity *= max(0, 1 + net_return)
        peak_equity = max(peak_equity, equity)

        drawdown = (peak_equity - equity) / peak_equity * 100
        max_drawdown = max(max_drawdown, drawdown)

        trades.append({
            "direction": direction,
            "entry_time": candles[entry_bar]["time"],
            "exit_time": candles[exit_bar]["time"],
            "entry": round(entry, 2),
            "exit": round(executed_exit, 2),
            "result": "WIN" if net_return > 0 else "LOSS",
            "exit_reason": exit_reason,
            "gross_return_percent": round(gross_return * 100, 4),
            "net_return_percent": round(net_return * 100, 4),
            "equity_percent": round((equity - 1) * 100, 2)
        })

        # No overlapping trades
        i = max(exit_bar, i + 1)

    total = len(trades)
    wins = [t for t in trades if t["net_return_percent"] > 0]
    losses = [t for t in trades if t["net_return_percent"] <= 0]

    gross_profit = sum(t["net_return_percent"] for t in wins)
    gross_loss = abs(sum(t["net_return_percent"] for t in losses))

    def direction_stats(name):
        selected = [t for t in trades if t["direction"] == name]
        won = [t for t in selected if t["net_return_percent"] > 0]
        lost = [t for t in selected if t["net_return_percent"] <= 0]

        gp = sum(t["net_return_percent"] for t in won)
        gl = abs(sum(t["net_return_percent"] for t in lost))

        return {
            "trades": len(selected),
            "wins": len(won),
            "losses": len(lost),
            "win_rate_percent": round(
                len(won) / len(selected) * 100, 2
            ) if selected else 0,
            "net_return_percent": round(
                sum(t["net_return_percent"] for t in selected), 2
            ),
            "profit_factor": round(gp / gl, 3) if gl else None
        }

    return {
        "symbol": "BTCUSDT",
        "timeframe": "15m",
        "strategy": "EMA20/EMA50 + RSI + ATR",
        "total_trades": total,
        "wins": len(wins),
        "losses": len(losses),
        "win_rate_percent": round(
            len(wins) / total * 100, 2
        ) if total else 0,
        "net_return_percent": round((equity - 1) * 100, 2),
        "profit_factor": round(
            gross_profit / gross_loss, 3
        ) if gross_loss else None,
        "expectancy_per_trade_percent": round(
            sum(t["net_return_percent"] for t in trades) / total, 4
        ) if total else 0,
        "max_drawdown_percent": round(max_drawdown, 2),
        "long": direction_stats("LONG"),
        "short": direction_stats("SHORT"),
        "assumptions": {
            "fee_per_side_percent": fee_percent * 100,
            "slippage_per_side_percent": slippage_percent * 100,
            "stop_atr_multiplier": atr_multiplier,
            "reward_risk": reward_risk,
            "max_holding_bars": max_holding_bars,
            "funding_included": False,
            "same_candle_sl_tp": "Stop loss assumed first"
        },
        "trades": trades[-30:],
        "warning": (
            "Historical simulation only. Funding, market impact "
            "and liquidation are not included. Test on unseen "
            "historical data before live trading."
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
