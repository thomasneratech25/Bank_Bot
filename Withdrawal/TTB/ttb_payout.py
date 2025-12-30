import re
import json
import time
import atexit
import hashlib
import logging
import requests
import subprocess
from threading import Lock
from flask import Flask, request, jsonify
from playwright.sync_api import sync_playwright
from airtest.core.api import *
from poco.drivers.android.uiautomation import AndroidUiautomationPoco

# =========================== Flask apps ==============================

app = Flask(__name__)
LOCK = Lock()

# ================== Logging ========================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
logger = logging.getLogger("TTB_Bot_Logger")

# ================== PLAYWRIGHT SINGLETON ========================

PLAYWRIGHT = None
BROWSER = None
CONTEXT = None
PAGE = None

# ============== Chrome Settings ====================

class Automation:
    
    chrome_proc = None

    # Chrome CDP
    @classmethod
    def chrome_cdp(cls):

        # Prevent starting Chrome more than once
        if cls.chrome_proc:
            return
        
        USER_DATA_DIR = r"C:\Users\Thomas\AppData\Local\Google\Chrome\User Data\Profile99"

        cls.chrome_proc = subprocess.Popen([
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            "--remote-debugging-port=9222",
            "--disable-session-crashed-bubble",
            "--hide-crash-restore-bubble",
            "--no-first-run",
            "--no-default-browser-check",
            f"--user-data-dir={USER_DATA_DIR}",
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        cls.wait_for_cdp_ready()
        atexit.register(cls.cleanup)

    # Close Chrome Completely
    @classmethod
    def cleanup(cls):
        try:
            if cls.chrome_proc and cls.chrome_proc.poll() is None:
                logging.getLogger("bank_bot").info("Closing Chrome CDP")
                cls.chrome_proc.terminate()
        except Exception:
            logging.getLogger("bank_bot").exception("Chrome cleanup error")

    # Wait Chrome CDP Ready
    @staticmethod
    def wait_for_cdp_ready(timeout=10):
        for _ in range(timeout):
            try:
                if requests.get("http://localhost:9222/json").status_code == 200:
                    return
            except:
                pass
            time.sleep(1)
        raise RuntimeError("Chrome CDP not ready")

# =============== TTB BANK BOT ======================

class BankBot(Automation):

    _ttb_ref = None

    # TTB Login
    @classmethod
    def ttb_login(cls, data):
        
        global PLAYWRIGHT, BROWSER, CONTEXT, PAGE

        # Start Chrome
        cls.chrome_cdp()

        # Start Playwright ONLY ONCE
        if PLAYWRIGHT is None:
            PLAYWRIGHT = sync_playwright().start()

        # Connect to running Chrome ONLY ONCE
        if BROWSER is None:
            BROWSER = PLAYWRIGHT.chromium.connect_over_cdp("http://localhost:9222")

        # Reuse context
        CONTEXT = BROWSER.contexts[0] if BROWSER.contexts else BROWSER.new_context()

        # Reuse page
        if PAGE is None or PAGE.is_closed():
            PAGE = CONTEXT.new_page()

        page = PAGE

        # If already on transfer page, skip login
        if "PPRT" in page.url or "payment" in page.url:
            return page

        # TTB Login
        page.goto("https://www.ttbbusinessone.com/auth/login", wait_until="domcontentloaded")
        page.wait_for_timeout(1500)

        # if text "Outward Remittance Service....." appear, button click "Accept", else pass
        try:
            if page.locator("//h2[contains(text(),'System will be temporarily unavailable for mainten')]").is_visible():
                # Button Click "Accept"
                page.locator("//button[normalize-space()='ACCEPT']").click(timeout=0) 
            else:
                pass
        except:
            pass

        # if Account already login, can skip
        try: 
            # Fill "Username"
            page.locator("//input[@type='text']").fill(str(data["username"]), timeout=1000)
            # Delay 0.5 seconds
            page.wait_for_timeout(500)
            # Button Click "Next"
            page.locator("//button[normalize-space()='Next']").click(timeout=0) 
            # Fill "Password"
            page.locator("//input[@type='password']").fill(str(data["password"]), timeout=0)
            # Delay 0.5 seconds
            page.wait_for_timeout(500)
            # Button Click "Next"
            page.locator("//button[normalize-space()='Next']").click(timeout=0)
        except:
            pass

        # Button Click "New payment"
        page.locator("//div[@class='shortcuts-container hidden-xs row']//span[@class='shortcut-value'][normalize-space()='New payment']").click(timeout=0) 
        # Button Click "Promptpay Transfer"
        page.locator("//div[@id='PPRT']").click(timeout=0)
        
        return page

    # TTB Withdrawal
    @classmethod
    def ttb_withdrawal(cls, page, data):

        # Check if logged out
        try:
            page.locator("//header[normalize-space()='Your session is about to expire!']").wait_for(state="visible",timeout=2500)
            # Button Click "Keep me Signed in"
            page.locator("//button[normalize-space()='Yes, Keep me signed in']").click(timeout=0) 
        except:
            cls.ttb_login(data)
        finally:
            pass

        # Fill Recipient name
        page.locator("//input[@id='counterparty']").fill(str(data["toAccountName"]), timeout=0)
        # Button Click "Transfer by"
        page.locator("//ca-combo[@name='counterpartyIdType']//button[@type='button']").click(timeout=0)
        # Button Click "Account no"
        page.locator("//li[normalize-space()='Account no.']").click(timeout=0)
        # Select Bank
        page.locator("//input[@id='bank']").fill(str(data["toBankCode"]), timeout=0)
        # Delay 0.5 seconds
        page.wait_for_timeout(500)
        # Button Click Bank
        page.locator("//ul[@class='ng-star-inserted']//li[@class='ng-star-inserted']").click(timeout=0)
        # Fill Account No.
        page.locator("//input[@id='counterpartyIdValue']").fill(str(data["toAccountNum"]), timeout=0)
        # Fill Amount
        page.locator("//input[@id='amount']").fill(str(data["amount"]), timeout=0)
        # Button Click "CONFIRM"
        page.locator("//button[normalize-space()='Confirm']").click(timeout=0)
        # Button Click "Approve"
        page.locator("//button[normalize-space()='Approve']").click(timeout=0)

        # TTB Business One Web Ref Code
        ref_code = page.locator("label.input-label").inner_text()
        match = re.search(r"ref\s*no\s+([A-Z0-9]+)", ref_code, re.IGNORECASE)
        if match:
            cls._ttb_ref = match.group(1)
            print(f"TTB Business One Web Ref Code: {cls._ttb_ref}\n\n")

        # Run Read OTP Code
        otp = cls.ttb_read_otp()
        # Fill OTP Code
        page.locator("//input[@type='text']").fill(otp, timeout=0)
        # Button Click Somewhere, incase cannot click "SIGN AND SEND"
        page.locator("//span[normalize-space()='Sender details']").click(timeout=0)
        # Button Click "SIGN AND SEND"
        page.locator("//button[@id='orders-summary-sign-and-send-button']").click(timeout=0)
        # Wait for Appear "Transfer successful"
        page.locator("//h1[normalize-space()='Transfer successful']").wait_for(timeout=10000)
        # Callback Eric API
        cls.eric_api(data)
        # Delay 1 seconds
        page.wait_for_timeout(1000)
        # Button Click "Transfer again"
        page.locator("//i[@class='icon-payment-result-refresh']").click(timeout=0)

        # WAIT for form reset (IMPORTANT FOR NEXT API CALL)
        page.locator("//input[@id='counterparty']").wait_for(timeout=5000)
    
    # Messages (SMS TTB Business One OTP Code)
    @classmethod
    def ttb_read_otp(cls):

        # Hide Debug Log, if want view, just comment the bottom code
        logging.getLogger("airtest").setLevel(logging.WARNING)
        logging.getLogger("pocoui").setLevel(logging.WARNING) 
        logging.getLogger("airtest.core.helper").setLevel(logging.WARNING)

        # Poco Assistant
        poco = AndroidUiautomationPoco(use_airtest_input=True, screenshot_each_action=False)

        # Check screen state (if screenoff then wake up, else skip)
        output = device().adb.shell("dumpsys power | grep -E -o 'mWakefulness=(Awake|Asleep|Dozing)'")

        if "Awake" in output:
            print("Screen already ON → pass")
        else:
            print("Screen is OFF → waking")
            wake()
            wake()

        # Start Messages Apps
        start_app("com.google.android.apps.messaging")
        
        # Click ttbbank Chat
        # If not in inside ttbank chat, click it, else passs
        try:
            if not poco("message_text").exists():
                poco(text="ttbbank").click()
            else:
                pass
        except:
            pass
        
        while True:
            # Read All TTB Bank Messages
            print("🤖 Reading latest message from TTB bank...")

            # Get all the messages text
            message_nodes = poco("message_list").offspring("message_text")

            # --- Collect OTP + Ref from all new messages ---
            otp_candidates = []
            for i, node in reversed(list(enumerate(message_nodes))):
                messages = node.get_text().strip()
                if not messages:
                    continue

                match = re.search(
                    r"OTP[:\s]*([0-9]{4,8}).*?\(?ref[:\s]*([A-Z0-9]+)\)?",
                    messages,
                    re.IGNORECASE,
                )
                if match:
                    messages_otp_code, messages_ref_code = match.groups()
                    otp_candidates.append((messages_otp_code.strip(), messages_ref_code.strip().upper()))
                    print(f"OTP: {messages_otp_code}, Ref: {messages_ref_code} ❌")

            # --- Match correct Ref Code ---
            for messages_otp_code, messages_ref_code in otp_candidates:
                if cls._ttb_ref == messages_ref_code:
                    print(f"Found matching Ref: {messages_ref_code} | OTP: {messages_otp_code} ✅")
                    return messages_otp_code
                
            # If no match, loop again
            print("# OTP not found yet, keep waiting... \n")

    # Callback ERIC API
    @classmethod
    def eric_api(cls, data):

        url = "https://stg-bot-integration.cloudbdtech.com/integration-service/transaction/payoutScriptCallback"

        # Create payload as a DICTIONARY (not JSON yet)
        payload = {
            "transactionId": str(data["transactionId"]),
            "bankCode": str(data["fromBankCode"]),
            "deviceId": str(data["deviceId"]),
            "merchantCode": str(data["merchantCode"]),
        }

        # Your secret key
        secret_key = "DEVBankBotIsTheBest"

        # Build the hash string (exact order required)
        string_to_hash = (
            f"transactionId={payload['transactionId']}&"
            f"bankCode={payload['bankCode']}&"
            f"deviceId={payload['deviceId']}&"
            f"merchantCode={payload['merchantCode']}{secret_key}"
        )

        # Generate MD5 hash
        hash_result = hashlib.md5(string_to_hash.encode("utf-8")).hexdigest()

        # Convert payload to JSON string AFTER hash
        payload_json = json.dumps(payload)

        # Send request
        headers = {
            'accept': '*/*',
            'hash': hash_result,
            'Content-Type': 'application/json'
        }

        response = requests.post(url, headers=headers, data=payload_json)

        # 7️⃣ Debug info
        print("Raw string to hash:", string_to_hash)
        print("MD5 Hash:", hash_result)
        print("Response:", response.text)
        print("\n\n")

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
            page = BankBot.ttb_login(data)
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

