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
logger = logging.getLogger("KTB_Bot_Logger")

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

# ================== KTB BANK BOT ==================

class BankBot(Automation):
    
    _ktb_ref = None

    # Login
    @classmethod
    def ktb_login(cls, data):
        
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

        page.goto("https://business.krungthai.com/#/", wait_until="domcontentloaded")

        # Change Language (English)
        page.locator("//p[@class='language-english']").click(timeout=0) 

        # Click Login
        page.locator("//span[@class='login']").click(timeout=0) 

        # Delay 0.5 seconds
        page.wait_for_timeout(500)

        # if Account already login, can skip
        try: 
            # Fill "Company ID"
            page.locator("//input[@placeholder='Enter company ID']").fill(str(data["companyId"]), timeout=1000)
            # Fill "User ID"
            page.locator("//input[@placeholder='Enter user ID']").fill(str(data["username"]), timeout=1000)
            # Fill "Password"
            page.locator("//input[@placeholder='Enter password']").fill(str(data["password"]), timeout=1000)
            # Delay 0.5 seconds
            page.wait_for_timeout(500)
            # Button Click "Login"
            page.locator("//span[@class='ktb-button-label']").click(timeout=0)
        except:
            pass
        
        # Wait for "OTP Verification" Appear
        page.locator("//h4[normalize-space()='OTP Verification']").wait_for(state="visible", timeout=30000)
        # Delay 1 second
        page.wait_for_timeout(1000)  

        # Get KTB Ref Code
        cls._ktb_web_ref_code = page.locator("//p[@class='ref ref-number-size mb-16px']").inner_text().strip()
        match = re.search(r"Ref\.?\s*([A-Za-z0-9]+)", cls._ktb_web_ref_code, re.IGNORECASE)
        if match:
            cls._ktb_web_ref_code = match.group(1).upper().strip()
            print(f"KTB Web Ref Code: {cls._ktb_web_ref_code}")

        # Call messages_OTP_4() function and Get OTP Code
        _messages_otp_code = cls.messages_OTP_4()

        # Fill OTP Code
        page.locator("//input[@id='otp-input-0']").fill(_messages_otp_code)

        # Button Click "Verify"
        page.locator("//span[@class='ktb-button-label']").click()

        # If "Announcement" Appear, click "OK", else pass
        try:
            expect(page.locator("//h2[normalize-space()='Announcement']")).to_be_visible(timeout=50000)
            # Button Click "OK"
            page.locator("//span[normalize-space()='OK']").click()
        except:
            pass

        # Wait for "Account Overview" Appear
        page.locator("//h4[normalize-space()='Account Overview']").wait_for(state="visible", timeout=30000)

        # Hover to Left Menu
        page.locator("//a[@class='link active']").hover()

        # Click Transfer & Pay
        page.locator("//span[normalize-space()='Transfer & Pay']").click()
        
        # Wait for "Transfer & Bill Payment" Appear
        page.locator("//a[normalize-space()='Transfer & Bill Payment']").wait_for(state="visible", timeout=0)

        # Button Click "New Transfer"
        page.locator("//body/ktb-root/ui-layout[@class='ng-star-inserted']/div[@class='main-container']/ui-side-panel/ng-sidebar-container[@backdropclass='custom-backdrop']/div[@class='ng-sidebar__content ng-sidebar__content--animate']/main/div[@class='main-inner']/ktb-module-transfer-pay[@class='ng-star-inserted']/ktb-module-transfer-pay-index-page[@class='ng-star-inserted']/ui-section[@class='transfer-landing-header section-wrapper ng-star-inserted']/section[@class='is-dark']/div[@class='section-content']/ui-container/div[@class='container']/div[@class='inner']/div[@class='sub-menu-container ng-star-inserted']/ui-card-sub-menu[1]/div[1]").click(timeout=0)

        # Wait for "Transfer Details" Appear
        page.locator("//h4[normalize-space()='Transfer Details']").wait_for(state="visible", timeout=30000)

        # Click "Select Payee"
        page.locator("//div[@class='add-payee-button']").click()

        # Wait for "New Account" Appear
        page.locator("//h6[normalize-space()='New Account']").wait_for(state="visible", timeout=30000)

        # Click "New Account"  
        page.locator("//h6[normalize-space()='New Account']").click()
        # Delay 1 second
        page.wait_for_timeout(1000)

        return page

    # Withdrawal
    @classmethod
    def ktb_withdrawal(cls, page, data):

        # Select Bank Code
        page.locator("#ddlBanking").wait_for(timeout=10000)
        page.select_option("#ddlBanking", str(data["toBankCode"]))

        # Fill in Account Number
        page.fill("#ctl00_cphSectionData_txtAccTo", str(data["toAccountName"]))

        # Fill in Amount
        page.fill("#ctl00_cphSectionData_txtAmountTransfer", str(data["amount"]))

        # Click Submit
        page.click("#ctl00_cphSectionData_btnSubmit")

        # Wait for OTP Box Appear
        page.locator(".otpbox_header").wait_for(timeout=10000)

        # Capture OTP Reference Number
        cls._ktb_ref = page.locator("//div[@class='inputbox_half_center']//div[@class='input_input_half']").first.inner_text().strip()
        
        # Run Read OTP Code
        otp = cls.ktb_read_otp()
        
        # Fill OTP Code
        page.fill("#ctl00_cphSectionData_OTPBox1_txtOTPPassword", otp)
        
        # Delay 0.5 second
        page.wait_for_timeout(500)
       
        # Button Click "Confirm"
        page.locator("//input[@id='ctl00_cphSectionData_OTPBox1_btnConfirm']").click(timeout=0)
        page.locator("//input[@id='ctl00_cphSectionData_OTPBox1_btnConfirm']").click(timeout=0)
       
        # Wait for Appear withdrawal Successful
        page.locator("#ctl00_cphSectionData_pnlSuccessMsg").wait_for(timeout=10000)
       
        # Delay 1 second
        page.wait_for_timeout(1000)
        
        # Call Eric API
        cls.eric_api(data)
       
       # Button click "Transfer other transaction"
        page.click("#ctl00_cphSectionData_btnOtherTxn")

    # Read Phone Message OTP Code
    @classmethod
    def ktb_read_otp(cls):

        # Hide Debug Log, if want view, just comment the bottom code
        logging.getLogger("airtest").setLevel(logging.WARNING)
        logging.getLogger("pocoui").setLevel(logging.WARNING) 
        logging.getLogger("airtest.core.helper").setLevel(logging.WARNING)

        # Poco Assistant
        poco = AndroidUiautomationPoco(use_airtest_input=True, screenshot_each_action=False)

        # Check screen state (if screenoff then wake up, else skip)
        output = device().adb.shell("dumpsys power | grep -E -o 'mWakefulness=(Awake|Asleep|Dozing)'")

        if "Awake" in output:
            print("Screen already ON  pass")
        else:
            print("Screen is OFF waking")
            wake()
            wake()

        time.sleep(1) 

        # Start Messages Apps
        start_app("com.google.android.apps.messaging")
        
        # Click KTB Chat
        # If not in inside KTB chat, click it, else passs
        if not poco("message_text").exists():
            poco(text="Krungsri").click()
        else:
            pass
        
        while True:

            # Read All KTB Bank Messages
            print("🤖 Reading latest message from KTB bank...")

            # Read All KTB Messages
            message_nodes = poco("message_list").offspring("message_text")

            # --- Collect OTP + Ref from all new messages ---
            otp_candidates = []
            for i, node in reversed(list(enumerate(message_nodes))):
                messages = node.get_text().strip()
                if not messages:
                    continue
                
                # using regex to get Message OTP Code and Ref Code
                match = re.search(r"\bRef\s*[:\-]?\s*(\d+)\b.*?\bOTP\s*[:\-]?\s*(\d+)\b", messages, re.IGNORECASE,)

                if match:
                    _messages_ref_code, messages_otp_code = match.groups()
                    otp_candidates.append((_messages_ref_code.strip(), messages_otp_code.strip()))
                    print(f"# Ref: {_messages_ref_code}, OTP: {messages_otp_code} ❌")

            # --- Match correct Ref Code ---
            for _messages_ref_code, messages_otp_code in otp_candidates:
                if cls._ktb_ref == _messages_ref_code:
                    print(f"Found matching Ref: {_messages_ref_code} | OTP: {messages_otp_code} ✅")
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

# ================== Code Start Here ==================

# Run API
@app.route("/ktb_company_web/runPython", methods=["POST"])        
def runPython():
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"success": False, "message": "Invalid JSON"}), 400

    with LOCK:
        try:
            # Run Browser
            Automation.chrome_cdp()
            # Login KTB
            page = BankBot.ktb_login(data)
            logger.info(f"▶ Processing {data['transactionId']}")
            BankBot.ktb_withdrawal(page, data)
            logger.info(f"✔ Done {data['transactionId']}")
            return jsonify({
                "success": True,
                "transactionId": data["transactionId"]
            })
        except Exception as e:
            logger.exception("❌ Withdrawal failed")
            return jsonify({"success": False, "message": str(e)}), 500

if __name__ == "__main__":
    logger.info("🚀 KTB Local API started")
    app.run(host="0.0.0.0", port=5003, debug=False, threaded=False, use_reloader=False)
