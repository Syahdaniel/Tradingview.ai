import json
import math
import urllib.request
from flask import Flask, jsonify, render_template

app = Flask(__name__)

SPOT_URL = "https://data-api.binance.vision/api/v3"
FUTURES_URL = "https://fapi.binance.com/fapi/v1"


def fetch_json(url, timeout=15):
    request = urllib.request.Request(url, headers={"User-Agent": "TradingviewAI/3.0"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def get_candles(interval="15m", limit=200, futures=False):
    base = FUTURES_URL if futures else SPOT_URL
    url = f"{base}/klines?symbol=BTCUSDT&interval={interval}&limit={limit}"
    raw = fetch_json(url)[:-1]  # Exclude the still-forming candle
    candles = [{
        "time": int(x[0]), "open": float(x[1]), "high": float(x[2]),
        "low": float(x[3]), "close": float(x[4]), "volume": float(x[5])
    } for x in raw]
    if len(candles) < 60:
        raise ValueError("Insufficient candle data from Binance")
    return candles


def ema_series(values, period):
    out = [None] * len(values)
    if len(values) < period:
        return out
    alpha = 2 / (period + 1)
    current = sum(values[:period]) / period
    out[period - 1] = current
    for i in range(period, len(values)):
        current = values[i] * alpha + current * (1 - alpha)
        out[i] = current
    return out


def rsi_series(values, period=14):
    out = [None] * len(values)
    if len(values) <= period:
        return out
    changes = [values[i] - values[i - 1] for i in range(1, len(values))]
    gains = [max(x, 0.0) for x in changes]
    losses = [max(-x, 0.0) for x in changes]
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    out[period] = 100.0 if avg_loss == 0 else 100 - 100 / (1 + avg_gain / avg_loss)
    for i in range(period + 1, len(values)):
        avg_gain = (avg_gain * (period - 1) + gains[i - 1]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i - 1]) / period
        out[i] = 100.0 if avg_loss == 0 else 100 - 100 / (1 + avg_gain / avg_loss)
    return out


def atr_series(candles, period=14):
    out = [None] * len(candles)
    true_ranges = []
    for i, c in enumerate(candles):
        previous_close = candles[i - 1]["close"] if i else c["close"]
        true_ranges.append(max(
            c["high"] - c["low"],
            abs(c["high"] - previous_close),
            abs(c["low"] - previous_close)
        ))
    if len(true_ranges) < period:
        return out
    current = sum(true_ranges[:period]) / period
    out[period - 1] = current
    for i in range(period, len(true_ranges)):
        current = (current * (period - 1) + true_ranges[i]) / period
        out[i] = current
    return out


def analyze_structure(candles):
    swing_highs, swing_lows = [], []
    for i in range(2, len(candles) - 2):
        if all(candles[i]["high"] > candles[j]["high"] for j in (i-2, i-1, i+1, i+2)):
            swing_highs.append(candles[i]["high"])
        if all(candles[i]["low"] < candles[j]["low"] for j in (i-2, i-1, i+1, i+2)):
            swing_lows.append(candles[i]["low"])
    if len(swing_highs) < 2 or len(swing_lows) < 2:
        return {"high_structure": "UNKNOWN", "low_structure": "UNKNOWN",
                "swing_high": None, "swing_low": None, "bos": "NO_CONFIRMED_BOS"}
    ph, lh = swing_highs[-2:]
    pl, ll = swing_lows[-2:]
    close = candles[-1]["close"]
    bos = "BULLISH_BOS" if close > lh else "BEARISH_BOS" if close < ll else "NO_CONFIRMED_BOS"
    return {
        "high_structure": "HH" if lh > ph else "LH",
        "low_structure": "HL" if ll > pl else "LL",
        "swing_high": lh, "swing_low": ll, "bos": bos
    }


def analyze_timeframe(candles):
    closes = [c["close"] for c in candles]
    e20, e50 = ema_series(closes, 20)[-1], ema_series(closes, 50)[-1]
    rsi = rsi_series(closes)[-1]
    price = closes[-1]
    trend = "BULLISH" if price > e20 > e50 else "BEARISH" if price < e20 < e50 else "SIDEWAYS"
    return {
        "price": round(price, 2), "ema20": round(e20, 2),
        "ema50": round(e50, 2), "rsi14": round(rsi, 2),
        "trend": trend, "market_structure": analyze_structure(candles)
    }


def get_market_data():
    return {
        "symbol": "BTCUSDT", "exchange": "BINANCE",
        "timeframes": {
            "M15": get_candles("15m"),
            "H1": get_candles("1h"),
            "H4": get_candles("4h")
        }
    }


def analyze_market(data):
    tf = data["timeframes"]
    h4, h1, m15 = tf["H4"], tf["H1"], tf["M15"]
    entry = m15["price"]
    structure = m15["market_structure"]
    decision, stop, target = "WAIT", None, None
    reason = "Belum ada confirmation lengkap."
    if all(tf[x]["trend"] == "BULLISH" for x in ("H4", "H1", "M15")) and structure["bos"] == "BULLISH_BOS":
        stop = structure["swing_low"]
        if stop and stop < entry:
            decision, target = "LONG", entry + 2 * (entry - stop)
            reason = "H4, H1 dan M15 bullish dengan bullish BOS."
    elif all(tf[x]["trend"] == "BEARISH" for x in ("H4", "H1", "M15")) and structure["bos"] == "BEARISH_BOS":
        stop = structure["swing_high"]
        if stop and stop > entry:
            decision, target = "SHORT", entry - 2 * (stop - entry)
            reason = "H4, H1 dan M15 bearish dengan bearish BOS."
    return {
        "decision": decision, "exchange": data["exchange"], "symbol": data["symbol"],
        "entry": round(entry, 2) if decision != "WAIT" else None,
        "stop_loss": round(stop, 2) if stop is not None else None,
        "take_profit": round(target, 2) if target is not None else None,
        "risk_reward": "1:2" if decision != "WAIT" else None,
        "signal_reason": reason, "timeframes": tf,
        "note": "Analisis sahaja. Tiada order sebenar dihantar."
    }


def run_backtest(candles, fee_percent=0.0004, slippage_percent=0.0002,
                 atr_multiplier=1.5, reward_risk=2.0, max_holding_bars=24):
    """Backtest on Binance USD-M Futures candles; one position at a time."""
    if len(candles) < 100:
        return {"error": "Not enough candle data"}

    closes = [c["close"] for c in candles]
    ema20, ema50 = ema_series(closes, 20), ema_series(closes, 50)
    rsi14, atr14 = rsi_series(closes), atr_series(candles)
    trades, equity, peak, max_dd = [], 1.0, 1.0, 0.0
    i = 60

    while i < len(candles) - 1:
        if any(x is None for x in (ema20[i], ema50[i], rsi14[i], atr14[i])) or atr14[i] <= 0:
            i += 1
            continue
        side = None
        if closes[i] > ema20[i] > ema50[i] and rsi14[i] >= 52:
            side = "LONG"
        elif closes[i] < ema20[i] < ema50[i] and rsi14[i] <= 48:
            side = "SHORT"
        if side is None:
            i += 1
            continue

        entry_bar = i + 1
        raw_entry = candles[entry_bar]["open"]
        entry = raw_entry * (1 + slippage_percent if side == "LONG" else 1 - slippage_percent)
        risk = atr14[i] * atr_multiplier
        stop = entry - risk if side == "LONG" else entry + risk
        target = entry + risk * reward_risk if side == "LONG" else entry - risk * reward_risk
        last_bar = min(entry_bar + max_holding_bars - 1, len(candles) - 1)
        exit_price, exit_bar, reason = None, last_bar, "TIME_EXIT"

        for j in range(entry_bar, last_bar + 1):
            bar = candles[j]
            o, h, l = bar["open"], bar["high"], bar["low"]
            if side == "LONG":
                if l <= stop:
                    exit_price, exit_bar, reason = min(o, stop), j, "STOP_LOSS"
                    break
                if h >= target:
                    exit_price, exit_bar, reason = max(o, target) if o >= target else target, j, "TAKE_PROFIT"
                    break
            else:
                if h >= stop:
                    exit_price, exit_bar, reason = max(o, stop), j, "STOP_LOSS"
                    break
                if l <= target:
                    exit_price, exit_bar, reason = min(o, target) if o <= target else target, j, "TAKE_PROFIT"
                    break
        if exit_price is None:
            exit_price = candles[last_bar]["close"]

        executed_exit = exit_price * (1 - slippage_percent if side == "LONG" else 1 + slippage_percent)
        gross = (executed_exit - entry) / entry if side == "LONG" else (entry - executed_exit) / entry
        net = gross - 2 * fee_percent
        equity *= max(0.0, 1 + net)
        peak = max(peak, equity)
        max_dd = max(max_dd, (peak - equity) / peak)
        trades.append({
            "direction": side, "entry_time": candles[entry_bar]["time"],
            "exit_time": candles[exit_bar]["time"], "entry": round(entry, 2),
            "exit": round(executed_exit, 2), "exit_reason": reason,
            "gross_return_percent": round(gross * 100, 4),
            "net_return_percent": round(net * 100, 4),
            "equity_percent": round((equity - 1) * 100, 2),
            "result": "WIN" if net > 0 else "LOSS"
        })
        i = exit_bar

    def stats(side):
        selected = [t for t in trades if t["direction"] == side]
        wins = [t for t in selected if t["net_return_percent"] > 0]
        losses = [t for t in selected if t["net_return_percent"] <= 0]
        gp = sum(t["net_return_percent"] for t in wins)
        gl = abs(sum(t["net_return_percent"] for t in losses))
        compounded = math.prod(1 + t["net_return_percent"] / 100 for t in selected)
        return {
            "trades": len(selected), "wins": len(wins), "losses": len(losses),
            "win_rate_percent": round(100 * len(wins) / len(selected), 2) if selected else 0,
            "net_return_percent": round((compounded - 1) * 100, 2),
            "profit_factor": round(gp / gl, 3) if gl else None,
            "expectancy_per_trade_percent": round(sum(t["net_return_percent"] for t in selected) / len(selected), 4) if selected else 0
        }

    return {
        "symbol": "BTCUSDT", "market": "BINANCE_USD_M_FUTURES", "timeframe": "15m",
        "strategy": "EMA20/EMA50 + RSI14 + ATR14", "total_trades": len(trades),
        "net_return_percent": round((equity - 1) * 100, 2),
        "max_drawdown_percent": round(max_dd * 100, 2),
        "long": stats("LONG"), "short": stats("SHORT"),
        "assumptions": {
            "fee_per_side_percent": fee_percent * 100,
            "slippage_per_side_percent": slippage_percent * 100,
            "stop_atr_multiplier": atr_multiplier, "reward_risk": reward_risk,
            "max_holding_bars": max_holding_bars, "funding_included": False,
            "same_candle_stop_and_target": "Stop loss assumed first",
            "entry": "Next candle open", "position_overlap": False
        },
        "trades": trades[-30:],
        "warning": "Simulation only. Funding, liquidation fees, market impact and out-of-sample validation are not included."
    }


def get_futures_data():
    funding = fetch_json(f"{FUTURES_URL}/premiumIndex?symbol=BTCUSDT")
    oi = fetch_json(f"{FUTURES_URL}/openInterest?symbol=BTCUSDT")
    return {
        "symbol": "BTCUSDT", "funding_rate": float(funding["lastFundingRate"]),
        "next_funding_time": int(funding["nextFundingTime"]),
        "mark_price": float(funding["markPrice"]),
        "open_interest": float(oi["openInterest"]),
        "source": "Binance USD-M Futures",
        "note": "Open interest is market-wide contract data, not proof of whale activity."
    }


@app.route("/")
def home():
    return render_template("index.html")


@app.route("/btc-data")
def btc_data():
    try:
        data = get_market_data()
        return jsonify({
            "symbol": data["symbol"], "exchange": data["exchange"],
            "timeframes": {k: analyze_timeframe(v) for k, v in data["timeframes"].items()}
        })
    except Exception as error:
        app.logger.exception("BTC data error")
        return jsonify({"error": str(error)}), 500


@app.route("/btc-analysis")
def btc_analysis():
    try:
        data = get_market_data()
        analyzed = {
            "symbol": data["symbol"], "exchange": data["exchange"],
            "timeframes": {k: analyze_timeframe(v) for k, v in data["timeframes"].items()}
        }
        return jsonify(analyze_market(analyzed))
    except Exception as error:
        app.logger.exception("BTC analysis error")
        return jsonify({"error": str(error)}), 500


@app.route("/btc-price")
def btc_price():
    try:
        result = fetch_json(f"{SPOT_URL}/ticker/price?symbol=BTCUSDT")
        return jsonify({"symbol": result["symbol"], "price": float(result["price"]), "exchange": "BINANCE"})
    except Exception as error:
        app.logger.exception("BTC price error")
        return jsonify({"error": str(error)}), 500


@app.route("/btc-backtest")
def btc_backtest():
    try:
        candles = get_candles("15m", limit=1000, futures=True)
        return jsonify(run_backtest(candles))
    except Exception as error:
        app.logger.exception("Backtest error")
        return jsonify({"error": str(error)}), 500


@app.route("/btc-intelligence")
def btc_intelligence():
    try:
        return jsonify(get_futures_data())
    except Exception as error:
        app.logger.exception("Futures intelligence error")
        return jsonify({"error": str(error), "source": "Binance USD-M Futures"}), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
