# flash_api.py

from flask import Flask, request, jsonify
from threading import Lock
import logging

from Withdrawal.old_file.ttb_payout_2 import Automation, BankBot

# =========================== Flask apps ==============================

app = Flask(__name__)
LOCK = Lock()

# ================== Logging ========================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
logger = logging.getLogger("TTB_API")

# ================== Code Start Here ================

# Run API
@app.route("/ttb_company_web/runPython", methods=["POST"])        
def runPython():
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"success": False, "message": "Invalid JSON"}), 400

    with LOCK:
        try:
            # Run Browser
            Automation.chrome_cdp()
            # Login TTB
            page = BankBot.ttb_login()
            logger.info(f"▶ Processing {data['transactionId']}")
            BankBot.ttb_withdrawal(page, data)
            logger.info(f"✔ Done {data['transactionId']}")
            return jsonify({
                "success": True,
                "transactionId": data["transactionId"]
            })
        except Exception as e:
            logger.exception("❌ Withdrawal failed")
            return jsonify({"success": False, "message": str(e)}), 500

if __name__ == "__main__":
    logger.info("🚀 TTB Local API started")
    app.run(host="0.0.0.0", port=5000, debug=False, threaded=False, use_reloader=False)
