from flask import Flask, request, jsonify
import json
import logging
from pathlib import Path
from datetime import datetime
import threading

app = Flask(__name__)

QUEUE_FILE = Path(__file__).parent / "payout_queue.json"
LOCK = threading.Lock()
logger = logging.getLogger(__name__)


def load_queue():
    if not QUEUE_FILE.exists() or QUEUE_FILE.stat().st_size == 0:
        return []
    with open(QUEUE_FILE, "r", encoding="utf-8") as f:
        try:
            data = json.load(f)
        except json.JSONDecodeError:
            logger.warning("Queue file empty or invalid JSON. Resetting to empty list.")
            return []

    if isinstance(data, list):
        return data

    logger.warning("Queue file content not a list. Resetting to empty list.")
    return []


def save_queue(queue):
    tmp = QUEUE_FILE.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(queue, f, indent=2)
    tmp.replace(QUEUE_FILE)


@app.route("/payout", methods=["POST"])
def kma_withdraw():
    
    data = request.get_json()
    if not data:
        return jsonify({
            "success": False,
            "message": "Invalid or missing JSON body"
        }), 400


    # ---- Validate input ----
    required_fields = [
        "deviceId",
        "merchantCode",
        "fromBankCode",
        "fromAccountNum",
        "toBankCode",
        "toAccountNum",
        "toAccountName",
        "amount",
        "username",
        "password",
        "pin",
        "transactionId",
    ]

    for field in required_fields:
        if field not in data:
            return jsonify({
                "success": False,
                "message": f"Missing field: {field}"
            }), 400

        if field != "pin" and data[field] in (None, ""):
            return jsonify({
                "success": False,
                "message": f"Invalid field: {field}"
            }), 400

    job = {
    "deviceId": data["deviceId"],
    "merchantCode": data["merchantCode"],
    "fromBankCode": data["fromBankCode"],
    "fromAccountName": data["fromAccountNum"],
    "toBankCode": data["toBankCode"],
    "toAccountNum": data["toAccountNum"],
    "toAccountName": data["toAccountName"],
    "amount": data["amount"],
    "username": data["username"],
    "password": data["password"],
    "pin": data["pin"],
    "transactionId": data["transactionId"],
    "status": "pending",
    "createdAt": datetime.utcnow().isoformat()
    }

    with LOCK:
        queue = load_queue()

        # Prevent duplicate transactionId
        for existing in queue:
            if existing["transactionId"] == job["transactionId"]:
                return jsonify({
                    "success": False,
                    "message": "transactionId already exists"
                }), 409

        queue.append(job)
        save_queue(queue)

    return jsonify({
        "success": True,
        "message": "Withdrawal Request Received",
        "transactionId": job["transactionId"]
    }), 200


@app.route("/health", methods=["GET"])
def health():
    return jsonify({
        "status": "ok",
        "service": "Payout API Server"
    })


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=80, debug=False)

