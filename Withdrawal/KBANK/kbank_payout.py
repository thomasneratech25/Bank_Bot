import re
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
logger = logging.getLogger("KBANK_Bot_Logger")

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

# ================== KBANK BANK BOT ==================

class BankBot(Automation):
    
    _kbank_ref = None
    
    # Simulate Human Click (Faster way)
    @staticmethod
    def human_click(poco_obj):
        import random, time
        from airtest.core.api import touch, G

        pos = poco_obj.get_position()

        w = G.DEVICE.display_info["width"]
        h = G.DEVICE.display_info["height"]

        abs_x = pos[0] * w
        abs_y = pos[1] * h

        offset_x = random.uniform(-0.01, 0.01) * w
        offset_y = random.uniform(-0.01, 0.01) * h

        touch([abs_x + offset_x, abs_y + offset_y])
        time.sleep(random.uniform(0.15, 0.35))

    # Login
    @classmethod
    def kbank_login(cls, data):
        
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

        # Go to a webpage
        page.goto("https://kbiz.kasikornbank.com/authen/login.jsp?lang=en", wait_until="networkidle")

        # if Account already login, can skip
        try: 
            # Fill "User ID"
            page.locator("//input[@id='userName']").fill(str(data["username"]))

            # Fill "Password"
            page.locator("//input[@id='password']").fill(str(data["password"]))

            # Button Click "Log In"
            page.locator("//a[@id='loginBtn']").click()
        except:
            pass

        # Button Click "Fund Transfer"
        page.locator("//div[@class='column-menu']//a[@id='BIZ_004']").click() 

        # wait for "Fund Transfer" to be appear
        page.locator("//h1[normalize-space()='Funds Transfer']").wait_for() 

        return page

    # Withdrawal
    @classmethod
    def kbank_withdrawal(cls, page, data):
        
        # Delay 1 seconds
        time.sleep(1)

        # Button Click "Select Bank"
        page.locator("//span[@id='select2-id_select2_example_3-container']//div").click()

        # Locate the input
        page.locator("input.select2-search__field").evaluate("el => el.removeAttribute('readonly')")
        page.locator("input.select2-search__field").fill(str(data["toBankCode"]))
        page.locator(f"//div[span[normalize-space()='{data['toBankCode']}']]").click()

        # Fill Account No.
        page.locator("//input[@placeholder='xxx-x-xxxxx-x']").fill(str(data["toAccountNum"]))

        # Fill Amount
        page.locator("//input[@placeholder='0.00']").fill(str(data["amount"]))

        # Button Click "Next"
        page.locator("//a[@class='btn btn-gradient f-right disabled-button']").click()

        # if Notice | You or Company has made this transaction already .... if this appear click confirm else skip
        try: 
            expect(page.locator("//div[@class='mfp-content']//h3[contains(text(),'Notice')]")).to_be_visible(timeout=4000)
            # Button Click "Confirm"
            page.locator("//div[@class='mfp-content']//span[contains(text(),'Confirm')]").click()
        except:
            pass
        
        # # Kbank Web Ref Code
        # cls._kbank_web_ref_code = page.locator("label.label strong").inner_text()
        # print(f"KBank Web Ref Code: {cls._kbank_web_ref_code}")
        
        # # Run Read OTP Code
        # otp = cls.kbank_read_otp()

        # # Fill OTP Code
        # page.locator("//input[@name='otp']").fill(otp)

        # # Button Click "Confirm"
        # page.locator("//a[@class='btn fixedwidth btn-gradient f-right']").click()

        # Kbank Apps Approved   
        cls.kbank_business_apps()

        # Callback Eric API
        cls.eric_api(data)

        # wait for "Fund Transfer" to be appear
        page.locator("//div[@class='column-menu']//a[@id='BIZ_004']").wait_for(state="visible", timeout=10000)
        
        # Button Click "Fund Transfer"
        page.locator("//div[@class='column-menu']//a[@id='BIZ_004']").click() 

        # wait for "Fund Transfer" to be appear
        page.locator("//h1[normalize-space()='Funds Transfer']").wait_for(state="visible", timeout=10000)

    # # Read Phone Message OTP Code
    # @classmethod
    # def kbank_read_otp(cls):

    #     # Hide Debug Log, if want view, just comment the bottom code
    #     logging.getLogger("airtest").setLevel(logging.WARNING)
    #     logging.getLogger("pocoui").setLevel(logging.WARNING) 
    #     logging.getLogger("airtest.core.helper").setLevel(logging.WARNING)

    #     # Poco Assistant
    #     poco = AndroidUiautomationPoco(use_airtest_input=True, screenshot_each_action=False)

    #     # Check screen state (if screenoff then wake up, else skip)
    #     output = device().adb.shell("dumpsys power | grep -E -o 'mWakefulness=(Awake|Asleep|Dozing)'")

    #     if "Awake" in output:
    #         print("Screen already ON → pass")
    #     else:
    #         print("Screen is OFF → waking")
    #         wake()
    #         wake()

    #     # Start Messages Apps
    #     start_app("com.google.android.apps.messaging")
        
    #     # Click KBank Chat
    #     # If not in inside KBank chat, click it, else passs
    #     if not poco("message_text").exists():
    #         poco(text="KBank").click()
    #     else:
    #         pass
        
    #     # Delay 2 seconds
    #     time.sleep(2)

    #     while True:
    #         # Read All KBank Messages
    #         message_nodes = poco("message_list").offspring("message_text")
    #         for i, node in enumerate(message_nodes):
    #             messages = node.get_text()

    #             # Using Regex to get Messages Ref Code
    #             match = re.search(r"\(Ref:\s*([A-Za-z0-9]+)\)", messages)
                
    #             if match:
    #                 messages_ref_code = match.group(1)

    #             # Compare Kbank Web (Ref Code) and Mobile Message (Ref Code), if is true, extract otp code, else print none
    #             if cls._kbank_web_ref_code == messages_ref_code:
    #                 # Using Regex to get OTP Code
    #                 match = re.search(r'OTP\s*=\s*(\d{6})', messages)
    #                 cls._messages_otp_code = match.group(1) if match else None   
    #                 print(f"Ref Code: {cls._kbank_web_ref_code} = {messages_ref_code} ✅, OTP Code:{cls._messages_otp_code}")
    #                 return cls._messages_otp_code            
    #             else:
    #                 print(f"Ref Code: {cls._kbank_web_ref_code} = {messages_ref_code} ❌")
    #                 continue

    #         # If no match, loop again
    #         print("# OTP not found yet, keep waiting... \n")
    
    # Apps Approved Transaction
    @classmethod
    def kbank_business_apps(cls):

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
        
        # Swipe Down Notification Bar
        swipe((0.5, 0.01), (0.5, 0.7))

        # Wait for notification text name and click
        poco(text="UNICORN NATIONAL").wait_for_appearance(timeout=30)
        poco(text="UNICORN NATIONAL").click()
        poco(text="UNICORN NATIONAL").click()

        # Wait for Tranfers Tab and Click Passcode number, else key Passcode Number
        try:
            if poco("Banking\nTab 3 of 5").wait_for_appearance(timeout=3):
                pass
            else:
                poco("Enter PIN").wait_for_appearance(timeout=30)
                login_pass = "147258"
                for digit in login_pass:
                    key = poco(f"{digit}")
                    cls.human_click(key)
        except:
            pass

        # Wait for "Confirm Transaction"
        poco(text="Confirm Transaction").wait_for_appearance(timeout=20)
        
        # Scroll Down
        swipe((360, 1280), (360, 320), duration=0.5)
        swipe((360, 1280), (360, 320), duration=0.5)

        # Button Click "Confirm"
        poco("Confirm").click()

        time.sleep(1)

        # Button Click "Confirm"s
        poco("Confirm").click()

        # Wait for "Back to main page"
        poco("Back to main page").wait_for_appearance(timeout=20)
        poco("Back to main page").click()
        
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
@app.route("/kbank_company_web/runPython", methods=["POST"])        
def runPython():
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"success": False, "message": "Invalid JSON"}), 400

    with LOCK:
        try:
            # Run Browser
            Automation.chrome_cdp()
            # Login KBANK
            page = BankBot.kbank_login(data)
            logger.info(f"▶ Processing {data['transactionId']}")
            BankBot.kbank_withdrawal(page, data)
            logger.info(f"✔ Done {data['transactionId']}")
            return jsonify({
                "success": True,
                "transactionId": data["transactionId"]
            })
        except Exception as e:
            logger.exception("❌ Withdrawal failed")
            return jsonify({"success": False, "message": str(e)}), 500

if __name__ == "__main__":
    logger.info("🚀 KBANK Local API started")
    app.run(host="0.0.0.0", port=5004, debug=False, threaded=False, use_reloader=False)
