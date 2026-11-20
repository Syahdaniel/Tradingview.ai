
import os
import hmac
from flask import Flask, request, jsonify

app = Flask(__name__)

WEBHOOK_SECRET = os.environ.get("TRADINGVIEW_WEBHOOK_SECRET")

@app.route("/", methods=["GET"])
def home():
    return "BTC AI Server is running!"

@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json(silent=True)

    if not isinstance(data, dict):
        return jsonify({"error": "Invalid JSON"}), 400

    if not WEBHOOK_SECRET:
        return jsonify({"error": "Server not configured"}), 500

    received_secret = str(data.get("secret", ""))

    if not hmac.compare_digest(received_secret, WEBHOOK_SECRET):
        return jsonify({"error": "Unauthorized"}), 401

    data.pop("secret", None)

    print(
        "BTC signal received:",
        data.get("symbol"),
        list(data.get("timeframes", {}).keys())
    )

    return jsonify({
        "status": "received",
        "message": "BTC data received successfully"
    }), 200
