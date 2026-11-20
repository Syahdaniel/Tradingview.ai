
import os
import json
from flask import Flask, request, jsonify
from openai import OpenAI

app = Flask(__name__)

WEBHOOK_SECRET = os.environ.get("TRADINGVIEW_WEBHOOK_SECRET")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")

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

    if not OPENAI_API_KEY:
        return jsonify({"error": "OpenAI API key missing"}), 500

    try:
        client = OpenAI(api_key=OPENAI_API_KEY)

        response = client.responses.create(
            model="gpt-5.5",
            instructions=(
                "You are a cautious financial market analyst. "
                "Analyze only the market data provided. "
                "Do not invent missing data. "
                "Give market bias, reasons, risks, and WAIT/BUY/SELL "
                "as an analysis opinion, not a guaranteed trading signal. "
                "Never execute trades."
            ),
            input=json.dumps(data)
        )

        return jsonify({
            "status": "success",
            "analysis": response.output_text
        }), 200

    except Exception as e:
        return jsonify({
            "error": "AI analysis failed",
            "details": str(e)
        }), 500
