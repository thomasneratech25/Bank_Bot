from flask import Flask, request, jsonify
import json
import logging
from pathlib import Path
from datetime import datetime
import threading

# ====================================================
# APP SETUP
# ====================================================

app = Flask(__name__)

QUEUE_FILE = Path(__file__).parent / "payout_queue.json"
LOCK = threading.Lock()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("payout_api")

# ====================================================
# BANK NORMALIZATION MAP
# ====================================================

BANK_MAP = {
    "SCB": "SCB",
    "SCB COMPANY WEB": "SCB",

    "TTB": "TTB",
    "TTB COMPANY WEB": "TTB",
}

# ====================================================
# QUEUE HELPERS
# ====================================================

def load_queue():
    if not QUEUE_FILE.exists() or QUEUE_FILE.stat().st_size == 0:
        return []
    try:
        with open(QUEUE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, list) else []
    except json.JSONDecodeError:
        logger.warning("Invalid queue file, resetting.")
        return []

def save_queue(queue):
    tmp = QUEUE_FILE.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(queue, f, indent=2)
    tmp.replace(QUEUE_FILE)

# ====================================================
# CREATE PAYOUT (PRODUCER)
# ====================================================

@app.route("/payout", methods=["POST"])
def create_payout():
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"success": False, "message": "Invalid JSON"}), 400

    # ---- Step 2: normalize fromBankCode ----
    raw_bank = data.get("fromBankCode", "")
    normalized_bank = BANK_MAP.get(raw_bank.upper().strip())

    if not normalized_bank:
        return jsonify({
            "success": False,
            "message": f"Unsupported fromBankCode: {raw_bank}"
        }), 400

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
            return jsonify({"success": False, "message": f"Missing field: {field}"}), 400
        if field != "pin" and data[field] in (None, ""):
            return jsonify({"success": False, "message": f"Invalid field: {field}"}), 400

    job = {
        **data,
        "fromBankCode": raw_bank,        # original user value
        "fromBankKey": normalized_bank,  # internal routing key
        "status": "pending",
        "createdAt": datetime.utcnow().isoformat(),
    }

    with LOCK:
        queue = load_queue()
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
        "transactionId": job["transactionId"],
    })

# ====================================================
# BOT: FETCH NEXT JOB (ROUTED)
# ====================================================

@app.route("/jobs/next", methods=["POST"])
def get_next_job():
    data = request.get_json(silent=True) or {}
    worker_bank_key = data.get("fromBankKey")

    if not worker_bank_key:
        return jsonify({
            "success": False,
            "message": "Missing fromBankKey"
        }), 400

    with LOCK:
        queue = load_queue()
        for job in queue:
            if (
                job["status"] == "pending"
                and job.get("fromBankKey") == worker_bank_key
            ):
                job["status"] = "processing"
                job["startedAt"] = datetime.utcnow().isoformat()
                save_queue(queue)
                return jsonify({"success": True, "job": job})

    return jsonify({"success": True, "job": None})

# ====================================================
# BOT: MARK DONE
# ====================================================

@app.route("/jobs/<txid>/done", methods=["POST"])
def mark_done(txid):
    with LOCK:
        queue = load_queue()
        for job in queue:
            if job["transactionId"] == txid:
                job["status"] = "done"
                job["finishedAt"] = datetime.utcnow().isoformat()
                save_queue(queue)
                return jsonify({"success": True})

    return jsonify({"success": False, "message": "Job not found"}), 404

# ====================================================
# BOT: MARK FAIL
# ====================================================

@app.route("/jobs/<txid>/fail", methods=["POST"])

def mark_fail(txid):
    error = request.json.get("error") if request.json else None

    with LOCK:
        queue = load_queue()
        for job in queue:
            if job["transactionId"] == txid:
                job["status"] = "failed"
                job["error"] = error
                job["finishedAt"] = datetime.utcnow().isoformat()
                save_queue(queue)
                return jsonify({"success": True})

    return jsonify({"success": False, "message": "Job not found"}), 404

# ====================================================
# HEALTH
# ====================================================

@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"})

# ====================================================
# RUN
# ====================================================

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
