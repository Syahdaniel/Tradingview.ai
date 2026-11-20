
import json
import urllib.request
from flask import Flask, jsonify

app = Flask(__name__)

@app.route("/", methods=["GET"])
def home():
    return "BTC AI Server is running!"

def get_candles(interval):
    url = (
        "https://data-api.binance.vision/api/v3/klines"
        f"?symbol=BTCUSDT&interval={interval}&limit=51"
    )

    req = urllib.request.Request(
        url,
        headers={"User-Agent": "BTC-AI-Server"}
    )

    with urllib.request.urlopen(req, timeout=10) as response:
        candles = json.loads(response.read().decode())

    # Abaikan candle terakhir yang masih berjalan
    return [
        {
            "time": candle[0],
            "open": float(candle[1]),
            "high": float(candle[2]),
            "low": float(candle[3]),
            "close": float(candle[4]),
            "volume": float(candle[5])
        }
        for candle in candles[:-1]
    ]

@app.route("/btc-data", methods=["GET"])
def btc_data():
    try:
        data = {
            "symbol": "BTCUSDT",
            "exchange": "BINANCE",
            "timeframes": {
                "M15": get_candles("15m"),
                "H1": get_candles("1h"),
                "H4": get_candles("4h")
            }
        }

        return jsonify(data), 200

    except Exception as error:
        return jsonify({
            "status": "error",
            "message": str(error)
        }), 502
