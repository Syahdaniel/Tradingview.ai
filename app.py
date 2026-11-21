import json
import math
import os
import time
import urllib.parse
import urllib.request
import urllib.error
from datetime import datetime, timezone

from flask import Flask, jsonify, render_template

app = Flask(__name__)

BINANCE_SPOT = "https://data-api.binance.vision"
BYBIT_PUBLIC = "https://api.bybit.com"
SYMBOL = "BTCUSDT"
FEE_PER_SIDE_PERCENT = 0.055
SLIPPAGE_PER_SIDE_PERCENT = 0.02


def http_json(url, timeout=15):
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "TradingviewAI/1.0",
            "Accept": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as response:
        raw = response.read().decode("utf-8")
        return json.loads(raw)


def safe_float(value, default=None):
    try:
        number = float(value)
        return number if math.isfinite(number) else default
    except (TypeError, ValueError):
        return default


def get_candles(interval="15m", limit=500):
    """Historical BTCUSDT spot candles. Last forming candle is excluded."""
    query = urllib.parse.urlencode({
        "symbol": SYMBOL,
        "interval": interval,
        "limit": min(max(int(limit), 50), 1000),
    })
    data = http_json(f"{BINANCE_SPOT}/api/v3/klines?{query}")
    candles = []
    for row in data:
        candles.append({
            "time": int(row[0]) // 1000,
            "open": float(row[1]),
            "high": float(row[2]),
            "low": float(row[3]),
            "close": float(row[4]),
            "volume": float(row[5]),
            "close_time": int(row[6]),
        })
    if len(candles) > 1:
        candles = candles[:-1]
    return candles


def ema_series(values, period):
    if not values:
        return []
    alpha = 2.0 / (period + 1.0)
    result = [float(values[0])]
    for value in values[1:]:
        result.append((float(value) * alpha) + (result[-1] * (1.0 - alpha)))
    return result


def rsi_series(values, period=14):
    result = [None] * len(values)
    if len(values) <= period:
        return result
    gains, losses = [], []
    for i in range(1, len(values)):
        change = values[i] - values[i - 1]
        gains.append(max(change, 0.0))
        losses.append(max(-change, 0.0))
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    result[period] = 100.0 if avg_loss == 0 else 100 - (100 / (1 + avg_gain / avg_loss))
    for i in range(period + 1, len(values)):
        avg_gain = ((avg_gain * (period - 1)) + gains[i - 1]) / period
        avg_loss = ((avg_loss * (period - 1)) + losses[i - 1]) / period
        result[i] = 100.0 if avg_loss == 0 else 100 - (100 / (1 + avg_gain / avg_loss))
    return result


def atr_series(candles, period=14):
    trs = []
    for i, candle in enumerate(candles):
        if i == 0:
            tr = candle["high"] - candle["low"]
        else:
            previous_close = candles[i - 1]["close"]
            tr = max(
                candle["high"] - candle["low"],
                abs(candle["high"] - previous_close),
                abs(candle["low"] - previous_close),
            )
        trs.append(tr)
    result = [None] * len(candles)
    if len(trs) < period:
        return result
    current = sum(trs[:period]) / period
    result[period - 1] = current
    for i in range(period, len(trs)):
        current = ((current * (period - 1)) + trs[i]) / period
        result[i] = current
    return result


def timeframe_analysis(interval, label):
    candles = get_candles(interval, 250)
    closes = [c["close"] for c in candles]
    if len(closes) < 60:
        raise RuntimeError(f"Data {label} tidak mencukupi")
    ema20 = ema_series(closes, 20)
    ema50 = ema_series(closes, 50)
    rsi = rsi_series(closes, 14)
    last = len(closes) - 1
    price = closes[last]
    trend = "BULLISH" if ema20[last] > ema50[last] else "BEARISH"
    momentum = "BULLISH" if rsi[last] is not None and rsi[last] >= 55 else (
        "BEARISH" if rsi[last] is not None and rsi[last] <= 45 else "NEUTRAL"
    )
    return {
        "timeframe": label,
        "price": round(price, 2),
        "ema20": round(ema20[last], 2),
        "ema50": round(ema50[last], 2),
        "rsi": round(rsi[last], 2) if rsi[last] is not None else None,
        "trend": trend,
        "momentum": momentum,
        "candle_time": candles[last]["time"],
    }


def build_analysis():
    m15 = timeframe_analysis("15m", "M15")
    h1 = timeframe_analysis("1h", "H1")
    h4 = timeframe_analysis("4h", "H4")
    bullish = sum(x["trend"] == "BULLISH" for x in (m15, h1, h4))
    bearish = sum(x["trend"] == "BEARISH" for x in (m15, h1, h4))
    if bullish >= 2 and m15["momentum"] != "BEARISH":
        decision = "LONG"
    elif bearish >= 2 and m15["momentum"] != "BULLISH":
        decision = "SHORT"
    else:
        decision = "WAIT"
    confidence = round(max(bullish, bearish) / 3 * 100)
    return {
        "symbol": SYMBOL,
        "exchange": "BINANCE SPOT MARKET DATA",
        "decision": decision,
        "confidence_percent": confidence,
        "timeframes": {"M15": m15, "H1": h1, "H4": h4},
        "note": "Analisis indikator sahaja. Data harga daripada Binance Spot; bukan pengesahan order book Futures dan bukan arahan dagangan.",
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }




def get_okx_futures_data():
    result = {
        "status": "UNAVAILABLE",
        "funding_rate_percent": None,
        "mark_price": None,
        "next_funding_time": None,
        "open_interest": None,
        "open_interest_value_usdt": None,
        "error": None,
        "note": "OKX Futures data. Nilai tidak direka atau dianggarkan."
    }

    base_url = "https://www.okx.com"
    inst_id = "BTC-USDT-SWAP"

    endpoints = {
        "funding": f"{base_url}/api/v5/public/funding-rate?instId={inst_id}",
        "mark": f"{base_url}/api/v5/public/mark-price?instType=SWAP&instId={inst_id}",
        "oi": f"{base_url}/api/v5/public/open-interest?instType=SWAP&instId={inst_id}"
    }

    try:
        import json
        import urllib.request

        def fetch(url):
            request = urllib.request.Request(
                url,
                headers={"User-Agent": "Mozilla/5.0"}
            )
            with urllib.request.urlopen(request, timeout=10) as response:
                return json.loads(response.read().decode("utf-8"))

        funding = fetch(endpoints["funding"])
        mark = fetch(endpoints["mark"])
        oi = fetch(endpoints["oi"])

        if funding.get("code") == "0" and funding.get("data"):
            item = funding["data"][0]
            result["funding_rate_percent"] = float(
                item["fundingRate"]
            ) * 100
            result["next_funding_time"] = item.get("nextFundingTime")

        if mark.get("code") == "0" and mark.get("data"):
            result["mark_price"] = float(mark["data"][0]["markPx"])

        if oi.get("code") == "0" and oi.get("data"):
            item = oi["data"][0]
            result["open_interest"] = float(item["oi"])

        available = sum([
            result["funding_rate_percent"] is not None,
            result["mark_price"] is not None,
            result["open_interest"] is not None
        ])

        result["status"] = (
            "LIVE" if available == 3
            else "PARTIAL" if available > 0
            else "UNAVAILABLE"
        )

    except Exception as error:
        result["error"] = str(error)

    return result


def run_backtest():
    candles = get_candles("15m", 1000)
    if len(candles) < 100:
        raise RuntimeError("Candlestick tidak mencukupi untuk backtest")
    closes = [c["close"] for c in candles]
    ema20 = ema_series(closes, 20)
    ema50 = ema_series(closes, 50)
    rsi = rsi_series(closes, 14)
    atr = atr_series(candles, 14)

    balance = 1000.0
    peak = balance
    max_drawdown = 0.0
    trades = []
    position = None
    fee_round_trip = 2 * (FEE_PER_SIDE_PERCENT + SLIPPAGE_PER_SIDE_PERCENT) / 100.0

    for i in range(51, len(candles) - 1):
        if position is not None:
            candle = candles[i]
            exit_price = None
            exit_reason = None
            if position["side"] == "LONG":
                if candle["low"] <= position["sl"]:
                    exit_price, exit_reason = position["sl"], "STOP_LOSS"
                elif candle["high"] >= position["tp"]:
                    exit_price, exit_reason = position["tp"], "TAKE_PROFIT"
            else:
                if candle["high"] >= position["sl"]:
                    exit_price, exit_reason = position["sl"], "STOP_LOSS"
                elif candle["low"] <= position["tp"]:
                    exit_price, exit_reason = position["tp"], "TAKE_PROFIT"

            if exit_price is None and i - position["entry_index"] >= 24:
                exit_price, exit_reason = candle["close"], "TIME_EXIT"

            if exit_price is not None:
                raw_return = (
                    (exit_price - position["entry"]) / position["entry"]
                    if position["side"] == "LONG"
                    else (position["entry"] - exit_price) / position["entry"]
                )
                net_return = raw_return - fee_round_trip
                pnl = balance * net_return
                balance += pnl
                trade = {
                    "side": position["side"],
                    "entry": round(position["entry"], 2),
                    "exit": round(exit_price, 2),
                    "entry_time": position["entry_time"],
                    "exit_time": candle["time"],
                    "return_percent": round(net_return * 100, 3),
                    "pnl_usdt": round(pnl, 2),
                    "result": "WIN" if net_return > 0 else "LOSS",
                    "exit_reason": exit_reason,
                }
                trades.append(trade)
                peak = max(peak, balance)
                if peak > 0:
                    max_drawdown = max(max_drawdown, (peak - balance) / peak * 100)
                position = None

        if position is None and rsi[i] is not None and atr[i] is not None and atr[i] > 0:
            long_signal = ema20[i] > ema50[i] and rsi[i] >= 52
            short_signal = ema20[i] < ema50[i] and rsi[i] <= 48
            entry = candles[i + 1]["open"]
            if long_signal:
                position = {
                    "side": "LONG",
                    "entry": entry,
                    "entry_index": i + 1,
                    "entry_time": candles[i + 1]["time"],
                    "sl": entry - 1.5 * atr[i],
                    "tp": entry + 2.0 * atr[i],
                }
            elif short_signal:
                position = {
                    "side": "SHORT",
                    "entry": entry,
                    "entry_index": i + 1,
                    "entry_time": candles[i + 1]["time"],
                    "sl": entry + 1.5 * atr[i],
                    "tp": entry - 2.0 * atr[i],
                }

    if position is not None:
        last = candles[-1]
        exit_price = last["close"]
        raw_return = (
            (exit_price - position["entry"]) / position["entry"]
            if position["side"] == "LONG"
            else (position["entry"] - exit_price) / position["entry"]
        )
        net_return = raw_return - fee_round_trip
        pnl = balance * net_return
        balance += pnl
        trades.append({
            "side": position["side"],
            "entry": round(position["entry"], 2),
            "exit": round(exit_price, 2),
            "entry_time": position["entry_time"],
            "exit_time": last["time"],
            "return_percent": round(net_return * 100, 3),
            "pnl_usdt": round(pnl, 2),
            "result": "WIN" if net_return > 0 else "LOSS",
            "exit_reason": "END_OF_TEST",
        })

    wins = [t for t in trades if t["result"] == "WIN"]
    losses = [t for t in trades if t["result"] == "LOSS"]
    gross_profit = sum(t["pnl_usdt"] for t in wins)
    gross_loss = abs(sum(t["pnl_usdt"] for t in losses))
    side_stats = {}
    for side in ("LONG", "SHORT"):
        side_trades = [t for t in trades if t["side"] == side]
        side_wins = sum(t["result"] == "WIN" for t in side_trades)
        side_stats[side] = {
            "trades": len(side_trades),
            "wins": side_wins,
            "losses": len(side_trades) - side_wins,
            "win_rate_percent": round(side_wins / len(side_trades) * 100, 2) if side_trades else 0,
        }

    return {
        "symbol": SYMBOL,
        "timeframe": "15m",
        "market_data_source": "BINANCE SPOT",
        "backtest_type": "SPOT_CANDLE_PROXY_FOR_LONG_SHORT",
        "starting_balance_usdt": 1000,
        "ending_balance_usdt": round(balance, 2),
        "net_return_percent": round((balance / 1000 - 1) * 100, 2),
        "total_trades": len(trades),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate_percent": round(len(wins) / len(trades) * 100, 2) if trades else 0,
        "profit_factor": round(gross_profit / gross_loss, 3) if gross_loss else (None if not gross_profit else "infinite"),
        "expectancy_usdt_per_trade": round(sum(t["pnl_usdt"] for t in trades) / len(trades), 3) if trades else 0,
        "max_drawdown_percent": round(max_drawdown, 2),
        "fees_and_slippage": {
            "fee_per_side_percent": FEE_PER_SIDE_PERCENT,
            "slippage_per_side_percent": SLIPPAGE_PER_SIDE_PERCENT,
        },
        "direction_stats": side_stats,
        "trades": trades[-30:],
        "candles_tested": len(candles),
        "warning": [
            "Backtest ini menggunakan candle Binance Spot sebagai proksi arah LONG/SHORT, bukan data kontrak Futures.",
            "Komisen dan slippage ialah andaian tetap; funding, liquidation, leverage dan margin tidak dimodelkan.",
            "Keputusan sejarah bukan jaminan prestasi masa hadapan. Uji out-of-sample sebelum digunakan.",
        ],
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }


@app.route("/")
def home():
    try:
        return render_template("index.html")
    except Exception:
        return jsonify({
            "name": "Tradingview AI BTC Dashboard",
            "status": "RUNNING",
            "endpoints": [
                "/btc-data", "/btc-analysis", "/btc-price",
                "/btc-backtest", "/btc-intelligence"
            ],
        })


@app.route("/health")
def health():
    return jsonify({"status": "ok", "service": "Tradingview AI", "symbol": SYMBOL})


@app.route("/btc-data")
def btc_data():
    try:
        candles = get_candles("15m", 200)
        return jsonify({
            "symbol": SYMBOL,
            "source": "BINANCE SPOT",
            "timeframe": "15m",
            "price": candles[-1]["close"] if candles else None,
            "candles": candles,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        })
    except Exception as exc:
        return jsonify({"error": str(exc), "source": "Binance Spot"}), 502


@app.route("/btc-price")
def btc_price():
    try:
        candles = get_candles("1m", 100)
        last = candles[-1]
        return jsonify({
            "symbol": SYMBOL,
            "price": last["close"],
            "source": "BINANCE SPOT",
            "time": last["time"],
        })
    except Exception as exc:
        return jsonify({"error": str(exc), "source": "Binance Spot"}), 502


@app.route("/btc-analysis")
def btc_analysis():
    try:
        return jsonify(build_analysis())
    except Exception as exc:
        return jsonify({"error": str(exc), "source": "Binance Spot"}), 502


@app.route("/btc-intelligence")
def btc_intelligence():
    futures = get_okx_futures_data()
    try:
        candles = get_candles("15m", 100)
        spot_price = candles[-1]["close"]
    except Exception as exc:
        return jsonify({
            "symbol": SYMBOL,
            "futures": futures,
            "spot": {"status": "UNAVAILABLE", "error": str(exc)},
        }), 200
    return jsonify({
        "symbol": SYMBOL,
        "spot": {
            "status": "LIVE",
            "source": "BINANCE SPOT",
            "price": spot_price,
        },
        "futures": futures,
        "macro": {
            "status": "NOT_CONNECTED",
            "note": "Tiada feed makroekonomi disambungkan dalam versi ini."
        },
        "whale_activity": {
            "status": "NOT_CONNECTED",
            "note": "Tiada feed transaksi whale disambungkan dalam versi ini."
        },
        "liquidations": {
            "status": "NOT_CONNECTED",
            "note": "Tiada feed liquidation disambungkan dalam versi ini."
        },
        "updated_at": datetime.now(timezone.utc).isoformat(),
    })


@app.route("/btc-backtest")
def btc_backtest():
    try:
        return jsonify(run_backtest())
    except Exception as exc:
        return jsonify({"error": str(exc), "source": "Binance Spot backtest"}), 502


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
