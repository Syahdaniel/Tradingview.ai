
import os
from flask import Flask, request, jsonify

app = Flask(__name__)

WEBHOOK_SECRET = os.environ.get("TRADINGVIEW_WEBHOOK_SECRET")

@app.route("/", methods=["GET"])
def home():
    return "TradingView AI Server is running!"

@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json(silent=True) or {}

    if not WEBHOOK_SECRET:
        return jsonify({"error": "Server not configured"}), 500

    if data.get("secret") != WEBHOOK_SECRET:
        return jsonify({"error": "Unauthorized"}), 401

    data.pop("secret", None)

    print("TradingView signal received:", data)

    return jsonify({
        "status": "success",
        "message": "Signal received. No trade executed."
    }), 200
