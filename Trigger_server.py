from flask import Flask, request, jsonify
import subprocess
import threading
import sys
import os
from datetime import datetime

# ================== Path setup ==================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Main script path (same directory)
SCRIPT_PATH = os.path.join(BASE_DIR, "bank_bot_withdrawal.py")

# Validate target script exists
if not os.path.exists(SCRIPT_PATH):
    print("Error: main script not found")
    print("Expected path:", SCRIPT_PATH)
    print("Base dir:", BASE_DIR)
    sys.exit(1)

# ================== Logging ==================
LOG_DIR = os.path.join(BASE_DIR, "TriggerLogs")
os.makedirs(LOG_DIR, exist_ok=True)

def log(msg):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_msg = f"[{timestamp}] {msg}"
    print(log_msg)

    log_file = os.path.join(
        LOG_DIR,
        f"{datetime.now().strftime('%Y-%m-%d')}_trigger.log"
    )
    with open(log_file, "a", encoding="utf-8") as f:
        f.write(log_msg + "\n")

# ================== Flask app ==================
app = Flask(__name__)

@app.route('/New_Withdrawal_Requests', methods=['POST'])
def trigger():
    data = request.get_json() or request.form

    # NEW API CONTRACT
    # arg1 = username
    # arg2 = password
    username = data.get('arg1') or request.args.get('arg1')
    password = data.get('arg2') or request.args.get('arg2')

    if not username or not password:
        log("Trigger failed: missing arg1 or arg2")
        return jsonify({
            "success": False,
            "message": "Missing arg1 (username) or arg2 (password)"
        }), 400

    log(f"Trigger received | username={username}")

    def run_task():
        try:
            log(f"Starting task | username={username}")
            log(f"Using script: {SCRIPT_PATH}")

            cmd = [
                sys.executable,
                SCRIPT_PATH,
                "--username", username,
                "--password", password
            ]

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=600,
                cwd=BASE_DIR
            )

            if result.returncode == 0:
                log(f"Task completed | username={username}")
                if result.stdout:
                    log(f"Output: {result.stdout[-500:]}")
            else:
                log(f"Task failed | username={username}")
                if result.stderr:
                    log(f"Error: {result.stderr}")

        except subprocess.TimeoutExpired:
            log(f"Task timeout | username={username}")
        except Exception as e:
            log(f"Task exception: {e}")

    threading.Thread(target=run_task, daemon=True).start()

    return jsonify({
        "success": True,
        "message": "Task started",
        "script": SCRIPT_PATH,
        "timestamp": datetime.now().isoformat()
    })

@app.route('/health', methods=['GET'])
def health():
    return jsonify({
        "status": "ok",
        "service": "Trigger Service",
        "script_path": SCRIPT_PATH
    })

# ================== Start server ==================
if __name__ == '__main__':
    log("Trigger service starting")
    log("Listening on http://0.0.0.0:5000")
    log(f"Main script path: {SCRIPT_PATH}")

    app.run(host='0.0.0.0', port=5000, debug=False)
