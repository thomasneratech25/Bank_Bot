import re
import time
from threading import Lock
from flask import Flask, request, jsonify

app = Flask(__name__)

# Store latest OTP messages in memory
OTP_STORE = []
OTP_LOCK = Lock()

# Krungsri regex function to get Ref and OTP Code
def krungsri_ref_otp(message_text: str):
    ref_match = re.search(r"Ref[:\s]*(\d+)", message_text)
    otp_match = re.search(r"OTP[:\s]*(\d{4,8})", message_text)

    ref_number = ref_match.group(1) if ref_match else None
    otp_code   = otp_match.group(1) if otp_match else None
    return ref_number, otp_code

# KBank regex function to get Ref and OTP Code
def kbank_ref_otp(message_text: str):
    ref_match = re.search(r"Ref[:\s]*(\d+)", message_text)
    otp_match = re.search(r"OTP[:\s]*(\d{4,8})", message_text)

    ref_number = ref_match.group(1) if ref_match else None
    otp_code   = otp_match.group(1) if otp_match else None
    return ref_number, otp_code

# Map sender -> handler + label + color
BANK_HANDLERS = {
    "Krungsri": (krungsri_ref_otp, "Krungsri Bank OTP", "\033[93m"),  # yellow
    "KBank":    (kbank_ref_otp,    "KBank OTP",         "\033[92m"),  # green
}

# Rest API Post Method
@app.route("/sms", methods=["POST"])
def sms():
    
    # Json format
    data = request.get_json(silent=True)

    # Fallback to form-data
    if not data:
        form = request.form.to_dict()
        if form:
            data = {"form": form}

    # Validate payload
    if not data or "form" not in data or "content" not in data["form"]:
        return jsonify({
            "success": False,
            "error": "Invalid payload: missing form/content"
        }), 400

    form = data["form"]
    sender = (form.get("from") or "").strip()
    content = form.get("content") or ""
    
    # Store data in content variable
    # ✅ Filter: accept only Krungsri/KBank
    if sender not in BANK_HANDLERS:
        print("⚠️ Ignored SMS from:", sender)
        return jsonify({"success": False, "ignored": True}), 200

    # Run Correct regex handler
    handler, title, color = BANK_HANDLERS[sender]
    ref, otp = handler(content)

    # ✅ Save OTP into memory (for Playwright to read later)
    with OTP_LOCK:
        OTP_STORE.append({
            "bank": sender,
            "ref": ref,
            "otp": otp,
            "ts": time.time()
        })

        # ✅ Keep only last 50 OTP records (memory limit)
        OTP_STORE[:] = OTP_STORE[-50:]

    # Print result
    print("\n====================")
    print(f"{color}【 {title} 】\033[0m")
    print(f"🔖 Ref : {ref}")
    print(f"🔐 OTP : {otp}")
    print("====================\n")

    return jsonify({"success": True, "bank": sender, "ref": ref, "otp": otp}), 200

# ============================================
# ✅ OTP Fetch API (Playwright GET)
# ============================================

@app.route("/otp/latest", methods=["GET"])
def get_latest_otp():

    bank = request.args.get("bank", "").strip()

    with OTP_LOCK:
        # Search newest OTP first
        for item in reversed(OTP_STORE):
            if item["bank"] == bank:
                return jsonify({"success": True, **item})

    return jsonify({"success": False, "error": "OTP not found"}), 404

# ============================================
# ✅ Ref Fetch API (Playwright GET)
# ============================================

@app.route("/otp/by_ref", methods=["GET"])
def get_otp_by_ref():
    bank = (request.args.get("bank") or "").strip()
    ref = (request.args.get("ref") or "").strip()

    if not bank or not ref:
        return jsonify({"success": False, "error": "bank and ref are required"}), 400

    with OTP_LOCK:
        for item in reversed(OTP_STORE):
            if item.get("bank") == bank and str(item.get("ref")) == ref:
                return jsonify({"success": True, **item})

    return jsonify({"success": False, "error": "OTP not found"}), 404

# ============================================
# ✅ Run Flask Server
# ============================================

if __name__ == "__main__":
    # print("✅ SMS Webhook Running at: http://0.0.0.0:3000")
    # print("✅ OTP Fetch Endpoint:    /otp/latest?bank=Krungsri")
    app.run(host="0.0.0.0", port=3000)