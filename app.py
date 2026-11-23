import json
import math
import os
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone

from flask import Flask, jsonify, render_template

app = Flask(__name__)

# BingX Spot public market data. No API key is required for public klines.
BINGX_BASE = "https://open-api.bingx.com"
BINGX_SYMBOL = "BTC-USDT"
SYMBOL = "BTCUSDT"
OKX_BASE = "https://www.okx.com"

FEE_PER_SIDE_PERCENT = 0.055
SLIPPAGE_PER_SIDE_PERCENT = 0.02

CANDLE_CACHE = {}
CANDLE_CACHE_TTL = {"1m": 15, "15m": 45, "1h": 180, "4h": 600}
INTERVAL_MS = {
    "1m": 60_000, "15m": 900_000, "1h": 3_600_000, "4h": 14_400_000
}


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def http_json(url, timeout=12):
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "TradingviewAI/2.0", "Accept": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def safe_float(value, default=None):
    try:
        number = float(value)
        return number if math.isfinite(number) else default
    except (TypeError, ValueError):
        return default


def get_candles(interval="15m", limit=500):
    if interval not in INTERVAL_MS:
        raise ValueError(f"Unsupported interval: {interval}")

    limit = min(max(int(limit), 50), 1440)
    key = (interval, limit)
    now = time.time()
    cached = CANDLE_CACHE.get(key)
    ttl = CANDLE_CACHE_TTL.get(interval, 60)

    if cached and now - cached["cached_at"] < ttl:
        return cached["candles"]

    query = urllib.parse.urlencode({
        "symbol": BINGX_SYMBOL,
        "interval": interval,
        "limit": limit,
    })
    url = f"{BINGX_BASE}/openApi/spot/v2/market/kline?{query}"
    payload = http_json(url)

    if not isinstance(payload, dict) or payload.get("code") != 0:
        raise RuntimeError(
            f"BingX API error: {payload.get('code') if isinstance(payload, dict) else 'invalid response'} "
            f"- {payload.get('msg', '') if isinstance(payload, dict) else ''}"
        )

    rows = payload.get("data")
    if not isinstance(rows, list) or not rows:
        raise RuntimeError("BingX returned no candle data")

    candles = []
    now_ms = int(time.time() * 1000)

    for row in rows:
        if not isinstance(row, (list, tuple)) or len(row) < 6:
            continue
        try:
            open_ms = int(float(row[0]))
            close_ms = int(float(row[6])) if len(row) > 6 else open_ms + INTERVAL_MS[interval] - 1
            # Exclude a candle that has not closed yet.
            if close_ms > now_ms:
                continue
            candle = {
                "time": open_ms // 1000,
                "open": float(row[1]),
                "high": float(row[2]),
                "low": float(row[3]),
                "close": float(row[4]),
                "volume": float(row[5]),
                "close_time": close_ms,
            }
            if all(math.isfinite(candle[k]) for k in ("open", "high", "low", "close", "volume")):
                candles.append(candle)
        except (TypeError, ValueError, IndexError):
            continue

    candles.sort(key=lambda item: item["time"])
    # Remove duplicate open times and retain the newest requested candles.
    unique = {c["time"]: c for c in candles}
    candles = sorted(unique.values(), key=lambda item: item["time"])[-limit:]

    if len(candles) < 60:
        raise RuntimeError(f"BingX returned insufficient closed candles for {interval}: {len(candles)}")

    CANDLE_CACHE[key] = {"cached_at": now, "candles": candles}
    return candles


def ema_series(values, period):
    if not values:
        return []
    alpha = 2.0 / (period + 1.0)
    result = [float(values[0])]
    for value in values[1:]:
        result.append(float(value) * alpha + result[-1] * (1.0 - alpha))
    return result


def rsi_series(values, period=14):
    result = [None] * len(values)
    if len(values) <= period:
        return result
    changes = [values[i] - values[i - 1] for i in range(1, len(values))]
    gains = [max(x, 0.0) for x in changes]
    losses = [max(-x, 0.0) for x in changes]
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    result[period] = 100.0 if avg_loss == 0 else 100 - 100 / (1 + avg_gain / avg_loss)
    for i in range(period + 1, len(values)):
        avg_gain = (avg_gain * (period - 1) + gains[i - 1]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i - 1]) / period
        result[i] = 100.0 if avg_loss == 0 else 100 - 100 / (1 + avg_gain / avg_loss)
    return result


def atr_series(candles, period=14):
    trs = []
    for i, c in enumerate(candles):
        if i == 0:
            tr = c["high"] - c["low"]
        else:
            prev = candles[i - 1]["close"]
            tr = max(c["high"] - c["low"], abs(c["high"] - prev), abs(c["low"] - prev))
        trs.append(tr)
    result = [None] * len(candles)
    if len(trs) < period:
        return result
    current = sum(trs[:period]) / period
    result[period - 1] = current
    for i in range(period, len(trs)):
        current = (current * (period - 1) + trs[i]) / period
        result[i] = current
    return result


def timeframe_analysis(interval, label):
    candles = get_candles(interval, 250)
    closes = [c["close"] for c in candles]
    if len(closes) < 60:
        raise RuntimeError(f"Insufficient candles for {label}")

    e20, e50 = ema_series(closes, 20), ema_series(closes, 50)
    rsi, atr = rsi_series(closes), atr_series(candles)
    last = len(closes) - 1
    price = closes[last]
    trend = "BULLISH" if e20[last] > e50[last] else "BEARISH"
    momentum = (
        "BULLISH" if rsi[last] is not None and rsi[last] >= 55 else
        "BEARISH" if rsi[last] is not None and rsi[last] <= 45 else "NEUTRAL"
    )
    recent = candles[-21:-1]
    swing_high = max(c["high"] for c in recent)
    swing_low = min(c["low"] for c in recent)
    bos = "BULLISH" if price > swing_high else "BEARISH" if price < swing_low else "NONE"

    return {
        "timeframe": label,
        "price": round(price, 2),
        "ema20": round(e20[last], 2),
        "ema50": round(e50[last], 2),
        "rsi": round(rsi[last], 2) if rsi[last] is not None else None,
        "rsi14": round(rsi[last], 2) if rsi[last] is not None else None,
        "atr": round(atr[last], 2) if atr[last] is not None else None,
        "trend": trend,
        "momentum": momentum,
        "candle_time": candles[last]["time"],
        "market_structure": {
            "high_structure": "BREAKOUT" if bos == "BULLISH" else "RANGE",
            "low_structure": "BREAKDOWN" if bos == "BEARISH" else "RANGE",
            "bos": bos,
            "swing_high": round(swing_high, 2),
            "swing_low": round(swing_low, 2),
        },
    }


def build_analysis():
    m15 = timeframe_analysis("15m", "M15")
    h1 = timeframe_analysis("1h", "H1")
    h4 = timeframe_analysis("4h", "H4")

    bullish = sum(x["trend"] == "BULLISH" for x in (m15, h1, h4))
    bearish = sum(x["trend"] == "BEARISH" for x in (m15, h1, h4))

    long_ok = bullish >= 2 and m15["momentum"] == "BULLISH" and h4["trend"] == "BULLISH"
    short_ok = bearish >= 2 and m15["momentum"] == "BEARISH" and h4["trend"] == "BEARISH"

    if long_ok:
        decision, reason = "LONG", "Trend major bullish dan momentum M15 bullish."
    elif short_ok:
        decision, reason = "SHORT", "Trend major bearish dan momentum M15 bearish."
    else:
        decision, reason = "WAIT", "Belum ada pengesahan arah yang mencukupi antara H4, H1 dan M15."

    confidence = round(max(bullish, bearish) / 3 * 100)
    entry = sl = tp1 = tp2 = tp3 = rr = None
    atr = m15["atr"]
    if decision in ("LONG", "SHORT") and atr and atr > 0:
        entry = m15["price"]
        risk = atr * 1.5
        if decision == "LONG":
            sl, tp1, tp2, tp3 = entry - risk, entry + risk, entry + 2 * risk, entry + 3 * risk
        else:
            sl, tp1, tp2, tp3 = entry + risk, entry - risk, entry - 2 * risk, entry - 3 * risk
        entry, sl, tp1, tp2, tp3, rr = round(entry, 2), round(sl, 2), round(tp1, 2), round(tp2, 2), round(tp3, 2), "1:2"

    return {
        "symbol": SYMBOL,
        "exchange": "BINGX SPOT MARKET DATA",
        "data_status": "LIVE",
        "decision": decision,
        "confidence_percent": confidence,
        "entry": entry,
        "stop_loss": sl,
        "take_profit": tp2,
        "take_profits": {"TP1": tp1, "TP2": tp2, "TP3": tp3},
        "risk_reward": rr,
        "signal_reason": reason,
        "timeframes": {"M15": m15, "H1": h1, "H4": h4},
        "note": "Analisis indikator menggunakan candle BingX Spot BTC-USDT. Bukan data kontrak Futures atau arahan dagangan.",
        "updated_at": utc_now(),
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
        "note": "Data OKX Futures berasingan daripada BingX Spot.",
    }
    inst = "BTC-USDT-SWAP"
    urls = {
        "funding": f"{OKX_BASE}/api/v5/public/funding-rate?instId={inst}",
        "mark": f"{OKX_BASE}/api/v5/public/mark-price?instType=SWAP&instId={inst}",
        "oi": f"{OKX_BASE}/api/v5/public/open-interest?instType=SWAP&instId={inst}",
    }
    try:
        funding, mark, oi = (http_json(url) for url in urls.values())
        if funding.get("code") == "0" and funding.get("data"):
            item = funding["data"][0]
            result["funding_rate_percent"] = float(item["fundingRate"]) * 100
            result["next_funding_time"] = item.get("nextFundingTime")
        if mark.get("code") == "0" and mark.get("data"):
            result["mark_price"] = safe_float(mark["data"][0].get("markPx"))
        if oi.get("code") == "0" and oi.get("data"):
            result["open_interest"] = safe_float(oi["data"][0].get("oi"))
        count = sum(result[k] is not None for k in ("funding_rate_percent", "mark_price", "open_interest"))
        result["status"] = "LIVE" if count == 3 else "PARTIAL" if count else "UNAVAILABLE"
    except Exception as exc:
        result["error"] = str(exc)
    return result


def run_backtest():
    candles = get_candles("15m", 1000)
    closes = [c["close"] for c in candles]
    e20, e50 = ema_series(closes, 20), ema_series(closes, 50)
    rsi, atr = rsi_series(closes), atr_series(candles)
    balance, peak, max_dd = 1000.0, 1000.0, 0.0
    position, trades = None, []
    costs = 2 * (FEE_PER_SIDE_PERCENT + SLIPPAGE_PER_SIDE_PERCENT) / 100

    for i in range(51, len(candles) - 1):
        c = candles[i]
        if position:
            exit_price = exit_reason = None
            if position["side"] == "LONG":
                if c["low"] <= position["sl"]:
                    exit_price, exit_reason = position["sl"], "STOP_LOSS"
                elif c["high"] >= position["tp"]:
                    exit_price, exit_reason = position["tp"], "TAKE_PROFIT"
            else:
                if c["high"] >= position["sl"]:
                    exit_price, exit_reason = position["sl"], "STOP_LOSS"
                elif c["low"] <= position["tp"]:
                    exit_price, exit_reason = position["tp"], "TAKE_PROFIT"
            if exit_price is None and i - position["index"] >= 24:
                exit_price, exit_reason = c["close"], "TIME_EXIT"
            if exit_price is not None:
                raw = ((exit_price - position["entry"]) / position["entry"]
                       if position["side"] == "LONG" else
                       (position["entry"] - exit_price) / position["entry"])
                net = raw - costs
                pnl = balance * net
                balance += pnl
                trades.append({"side": position["side"], "entry": round(position["entry"], 2),
                               "exit": round(exit_price, 2), "return_percent": round(net * 100, 3),
                               "pnl_usdt": round(pnl, 2), "result": "WIN" if net > 0 else "LOSS",
                               "exit_reason": exit_reason})
                position = None
                peak = max(peak, balance)
                if peak > 0:
                    max_dd = max(max_dd, (peak - balance) / peak * 100)

        if position is None and rsi[i] is not None and atr[i] and atr[i] > 0:
            side = "LONG" if e20[i] > e50[i] and rsi[i] >= 52 else (
                "SHORT" if e20[i] < e50[i] and rsi[i] <= 48 else None)
            if side:
                entry = candles[i + 1]["open"]
                risk = 1.5 * atr[i]
                position = {"side": side, "entry": entry, "index": i + 1,
                            "sl": entry - risk if side == "LONG" else entry + risk,
                            "tp": entry + 2 * risk if side == "LONG" else entry - 2 * risk}

    if position:
        last_price = candles[-1]["close"]
        raw = ((last_price - position["entry"]) / position["entry"]
               if position["side"] == "LONG" else
               (position["entry"] - last_price) / position["entry"])
        net = raw - costs
        pnl = balance * net
        balance += pnl
        trades.append({"side": position["side"], "entry": round(position["entry"], 2),
                       "exit": round(last_price, 2), "return_percent": round(net * 100, 3),
                       "pnl_usdt": round(pnl, 2), "result": "WIN" if net > 0 else "LOSS",
                       "exit_reason": "END_OF_TEST"})

    wins = [t for t in trades if t["result"] == "WIN"]
    losses = [t for t in trades if t["result"] == "LOSS"]
    gp = sum(t["pnl_usdt"] for t in wins)
    gl = abs(sum(t["pnl_usdt"] for t in losses))
    directions = {}
    for side in ("LONG", "SHORT"):
        selected = [t for t in trades if t["side"] == side]
        w = sum(t["result"] == "WIN" for t in selected)
        directions[side] = {"trades": len(selected), "wins": w, "losses": len(selected) - w,
                            "win_rate_percent": round(w / len(selected) * 100, 2) if selected else 0}
    return {
        "symbol": SYMBOL, "timeframe": "15m", "market_data_source": "BINGX SPOT",
        "backtest_type": "SPOT_CANDLE_PROXY_FOR_LONG_SHORT",
        "starting_balance_usdt": 1000, "ending_balance_usdt": round(balance, 2),
        "net_return_percent": round((balance / 1000 - 1) * 100, 2),
        "total_trades": len(trades), "wins": len(wins), "losses": len(losses),
        "win_rate_percent": round(len(wins) / len(trades) * 100, 2) if trades else 0,
        "profit_factor": round(gp / gl, 3) if gl else (None if not gp else "infinite"),
        "max_drawdown_percent": round(max_dd, 2),
        "fees_and_slippage": {"fee_per_side_percent": FEE_PER_SIDE_PERCENT,
                              "slippage_per_side_percent": SLIPPAGE_PER_SIDE_PERCENT},
        "direction_stats": directions, "trades": trades[-30:], "candles_tested": len(candles),
        "warning": [
            "Backtest menggunakan candle BingX Spot sebagai proksi LONG/SHORT, bukan data Futures.",
            "Funding, leverage, margin dan liquidation tidak dimodelkan.",
            "Komisen dan slippage ialah andaian tetap; keputusan sejarah bukan jaminan masa depan."
        ],
        "updated_at": utc_now(),
    }


@app.route("/")
def home():
    return render_template("index.html")


@app.route("/health")
def health():
    return jsonify({"status": "ok", "service": "Tradingview AI", "symbol": SYMBOL})


@app.route("/btc-data")
def btc_data():
    try:
        candles = get_candles("15m", 200)
        return jsonify({"symbol": SYMBOL, "source": "BINGX SPOT", "timeframe": "15m",
                        "price": candles[-1]["close"], "candles": candles, "updated_at": utc_now()})
    except Exception as exc:
        return jsonify({"error": str(exc), "source": "BingX Spot"}), 502


@app.route("/btc-price")
def btc_price():
    try:
        last = get_candles("1m", 100)[-1]
        return jsonify({"symbol": SYMBOL, "price": last["close"], "source": "BINGX SPOT",
                        "time": last["time"]})
    except Exception as exc:
        return jsonify({"error": str(exc), "source": "BingX Spot"}), 502


@app.route("/btc-analysis")
def btc_analysis():
    try:
        return jsonify(build_analysis())
    except Exception as exc:
        # Explicitly fail closed: never leave a stale LONG/SHORT signal active.
        return jsonify({"symbol": SYMBOL, "exchange": "BINGX SPOT MARKET DATA",
                        "data_status": "ERROR", "decision": "WAIT",
                        "confidence_percent": 0, "entry": None, "stop_loss": None,
                        "take_profit": None, "take_profits": {"TP1": None, "TP2": None, "TP3": None},
                        "risk_reward": None, "signal_reason": "DATA ERROR — tunggu data BingX pulih.",
                        "error": str(exc), "updated_at": utc_now()}), 502


@app.route("/btc-intelligence")
def btc_intelligence():
    futures = get_okx_futures_data()
    try:
        last = get_candles("15m", 100)[-1]
        spot = {"status": "LIVE", "source": "BINGX SPOT", "price": last["close"]}
    except Exception as exc:
        spot = {"status": "UNAVAILABLE", "source": "BINGX SPOT", "error": str(exc)}
    return jsonify({
        "symbol": SYMBOL, "spot": spot, "futures": futures,
        "macro": {"status": "NOT_CONNECTED", "note": "Tiada feed makroekonomi disambungkan."},
        "whale_activity": {"status": "NOT_CONNECTED", "note": "Tiada feed whale disambungkan."},
        "liquidations": {"status": "NOT_CONNECTED", "note": "Tiada feed liquidation disambungkan."},
        "updated_at": utc_now(),
    })


@app.route("/btc-backtest")
def btc_backtest():
    try:
        return jsonify(run_backtest())
    except Exception as exc:
        return jsonify({"error": str(exc), "source": "BingX Spot backtest"}), 502


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
