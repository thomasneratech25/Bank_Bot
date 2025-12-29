import json
import time
import random
import atexit
import hashlib
import logging
import requests
import subprocess
from threading import Lock
from flask import Flask, request, jsonify
from playwright.sync_api import sync_playwright, expect
from airtest.core.api import *
from poco.drivers.android.uiautomation import AndroidUiautomationPoco

# =========================== Flask apps ==============================

app = Flask(__name__)
LOCK = Lock()

# ================== LOG File ==================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
logger = logging.getLogger("SCB_Bot_Logger")

# ================== PLAYWRIGHT SINGLETON ========================

PLAYWRIGHT = None
BROWSER = None
CONTEXT = None
PAGE = None

# ================== Chrome Settings ==================

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

# ================== SCB BANK BOT ==================

class BankBot(Automation):
    
    _scb_ref = None

    # Simulate Human Click (Faster way)
    @staticmethod
    def human_click(poco, poco_obj):
        # get position of the element
        pos = poco_obj.get_position()

        # convert to screen coords
        w, h = poco.get_screen_size()
        abs_x, abs_y = pos[0] * w, pos[1] * h

        # random offset (human jitter)
        offset_x = random.uniform(-0.01, 0.01) * w
        offset_y = random.uniform(-0.01, 0.01) * h

        # simulate tap
        touch([abs_x + offset_x, abs_y + offset_y])

        # small human delay
        time.sleep(random.uniform(0.15, 0.35))

    # Login
    @classmethod
    def scb_login(cls, data):

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
            PAGE.bring_to_front()

        page = PAGE

        page.goto("https://www.scbbusinessanywhere.com/", wait_until="domcontentloaded")

        # For your online security, you have been logged out of SCB Business Anywhere (please log in again.)
        try:
            expect(page.get_by_text("For your online security, you have been logged out of SCB Business Anywhere")).to_be_visible(timeout=1000)
            page.locator("//span[normalize-space()='OK']").click(timeout=0) 
        except:
            pass
        
        # if Account already login, can skip
        try: 
            # Fill "Username"
            page.locator("//input[@name='username']").fill(str(data["username"]), timeout=1000)

            # Button Click "Next"
            page.locator("//span[normalize-space()='Next']").click(timeout=0) 

            # Fill "Password"
            page.locator("//input[@name='password']").fill(str(data["password"]), timeout=0)

            # Button Click "Next"
            page.locator("//button[@type='submit']").click(timeout=0) 
        except:
            pass
        
        # only click Transfers if NOT on login page
        if not page.locator("//input[@name='username']").is_visible():
            # Button Click "Transfer"
            page.locator("//p[normalize-space()='Transfers']").click(timeout=0)

        return page

    # Withdrawal
    @classmethod
    def scb_withdrawal(cls, page, data):

        # Button Click "Add New Recipient"
        page.locator("//span[normalize-space()='Add New Recipient']").click(timeout=0) 
        
        # Fill Bank Name and Click
        page.get_by_label("Bank Name *").fill(str(data["toBankCode"]), timeout=0)
        page.get_by_text(str(data["toBankCode"]), exact=True).click(timeout=0)
        
        # Fill Account No.
        page.locator("//input[@id='accountNumber']").fill(str(data["toAccountNum"]), timeout=0)

        # Button Click "Next"
        page.locator("//span[normalize-space()='Next']").click(timeout=0) 

        # Wait for "Recipient Details"
        page.locator("//h4[normalize-space()='Recipient Details']").wait_for(timeout=0) 

        try:
            # Fill Account Name
            page.locator("//input[@name='accountName']").fill(str(data["toAccountName"]), timeout=2000)
        except:
            pass

        # Button Click "Confirm"
        page.locator("//span[normalize-space()='Confirm']").click(timeout=0) 

        # Button Click "Enter"
        page.locator("//span[normalize-space()='Enter']").click(timeout=0) 

        # Fill Amount
        page.locator("//input[@name='amount']").fill(str(data["amount"]), timeout=0)

        # Press Enter
        page.keyboard.press("Enter")

        # Button Click "Continue to Transfer Services"
        page.locator("//span[normalize-space()='Continue to Transfer Services']").click(timeout=0) 

        # Button Click "Skip to Review Information"
        page.locator("//span[normalize-space()='Skip to Review Information']").click(timeout=0) 

        # wait for "Review Information" to be appear
        page.locator("//h2[normalize-space()='Review Information']").wait_for(timeout=0) 

        # Scroll to very Bottom
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")

        # Button Click "Submit"
        page.locator("//span[normalize-space()='Submit']").click(timeout=0)

        # Button Click "OK"
        page.locator("//span[normalize-space()='OK']").click(timeout=0)

        # Launch Apps to Approve Transfer Request
        BankBot.scb_Anywhere_apps(data)

        # Button Click "Done"
        page.locator("//span[normalize-space()='Done']").click(timeout=1000)

        # Delay 0.5 second
        page.wait_for_timeout(500)

        # wait for "Review Information" to be appear
        page.locator("//h2[contains(text(),'You have successfully submitted the transaction re')]").wait_for(timeout=0) 
        
        # Wait for MUI backdrop animation to finish
        page.locator("div.MuiBackdrop-root").wait_for(state="hidden", timeout=5000)

        # Call Eric API
        cls.eric_api(data)

        # Button Click Make New Transfer
        page.locator("//span[normalize-space()='Make New Transfer']").click(timeout=5000)

    # Read Apps OTP Code
    @classmethod
    def scb_Anywhere_apps(cls, data):

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

        # Start SCB Corporate Apps
        start_app("com.scb.corporate")

        # Inactive Too Long
        try:
            poco(text="You have been inactive for too long").wait_for_appearance(timeout=1)
            # Click "Confirm"
            poco(text="Continue").click()
        except:
            pass
        
        # Session timeout
        try:
            poco(text="Session timeout").wait_for_appearance(timeout=1)
            # Click "Log In"
            poco(text="Log in").click()
        except:
            pass
        
        try:
            # Wait for "Enter PIN" appear
            poco(text="Enter PIN").wait_for_appearance(timeout=2)

            pin = str(data["pin"])
            for digit in pin:
                key = poco(f"Login_{digit}")
                cls.human_click(poco, key)
        except:
            pass
        
        # Wait and Click Notifications
        poco(text="Notifications").wait_for_appearance(timeout=15)   
        poco("tabNotificationsStack").click()

        # Click "View request"
        poco(text="View request").wait_for_appearance(timeout=100)
        poco(text="View request").click()

        # Wait and Click "Submit for approval"
        poco("btApprove").click()
        
        # Key SCB Digital Token Pin
        token_pin = str(data["scbDigitalTokenPin"])
        for digit in token_pin:
            key = poco(f"SoftTokenInputPin_{digit}")
            cls.human_click(poco, key)

        time.sleep(3)
        
        # Click "Go to To-do List"
        poco(text="Approved").wait_for_appearance(timeout=15)
        poco("btTodoList").wait_for_appearance(timeout=10)
        poco("btTodoList").click()

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

# ================== Code Start Here ==================

# Run API
@app.route("/scb_company_web/runPython", methods=["POST"])        
def runPython():
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"success": False, "message": "Invalid JSON"}), 400

    with LOCK:
        try:
            # Run Browser
            Automation.chrome_cdp()
            # Login SCB
            page = BankBot.scb_login(data)
            logger.info(f"▶ Processing {data['transactionId']}")
            BankBot.scb_withdrawal(page, data)
            logger.info(f"✔ Done {data['transactionId']}")
            return jsonify({
                "success": True,
                "transactionId": data["transactionId"]
            })
        except Exception as e:
            logger.exception("❌ Withdrawal failed")
            return jsonify({"success": False, "message": str(e)}), 500

if __name__ == "__main__":
    logger.info("🚀 SCB Local API started")
    app.run(host="0.0.0.0", port=5001, debug=False, threaded=False, use_reloader=False)
