import os
import re
import json
import time
import atexit
import hashlib
import requests
import subprocess
from threading import Lock
from dotenv import load_dotenv
from flask import Flask, request, jsonify
from playwright.sync_api import sync_playwright
from appium import webdriver
from appium.webdriver.common.appiumby import *
from appium.webdriver.common.appiumby import AppiumBy
from appium.options.android import UiAutomator2Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC


# =========================== Eric WS_Client Settings =================

WS_PROC = None

# =========================== Appium Settings =========================

APPIUM_DRIVER = None
APPIUM_PROC = None
APPIUM_LOCK = Lock()

# =========================== Flask apps ==============================

app = Flask(__name__)
LOCK = Lock()



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
        
        # Load .env file
        load_dotenv()
        USER_DATA_DIR = os.getenv("CHROME_PATH")

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
                cls.chrome_proc.terminate()
        except Exception:
            pass

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

# ================== KMA BANK BOT ==================

class BankBot(Automation):
    
    _kma_ref = None

    # Use Appium Driver
    @classmethod
    def use_appium_driver(cls):
        global APPIUM_DRIVER

        cls.start_appium_server()

        with APPIUM_LOCK:
            if APPIUM_DRIVER is None:
                options = UiAutomator2Options()
                options.platform_name = "Android"
                options.device_name = "androidtesting"
                options.automation_name = "UiAutomator2"
                options.new_command_timeout = 86400

                APPIUM_DRIVER = webdriver.Remote(
                    "http://127.0.0.1:8021",
                    options=options
                )

        return APPIUM_DRIVER
    
    # Start Appium Server
    @classmethod
    def start_appium_server(cls):
        
        global APPIUM_PROC
        
        # if appium server start already, then skip
        # Prevent starting multiple appium server
        if APPIUM_PROC: 
            return

        # Start Appium Server Command
        load_dotenv()
        APPIUM_CMD = os.getenv("APPIUM_CMD")
        APPIUM_PROC = subprocess.Popen([
            APPIUM_CMD,
            "--port", "8021",
            "--allow-insecure", "uiautomator2:adb_shell",
            "--allow-cors"
        ])
                
        # Wait until Appium server is ready, retry 10 times
        for attempt in range(1, 11):
            try:
                if requests.get("http://127.0.0.1:8021/status").ok:
                    return
            except Exception:
                time.sleep(1)

        # if after 10 times retry, appium still not ready, then raise the error to stop the program
        raise RuntimeError("Appium not started")
    
    # Start Eric Server (ws_client)
    @classmethod
    def start_ws_client(cls):
        global WS_PROC

        if WS_PROC and WS_PROC.poll() is None:
            return

        load_dotenv()
        ws_client = os.getenv("WS_CLIENT")
        workdir = os.path.dirname(ws_client)

        WS_PROC = subprocess.Popen(
            ws_client,
            shell=True,
            cwd=workdir
        )


    # Login
    @classmethod
    def kma_login(cls, data):
        
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
        try:
            page.locator("//div[@class='page_header']").wait_for(timeout=1500)
            return page # Already Login
        except:
            pass

        # Go to a webpage
        page.goto("https://www.krungsribizonline.com/BAY.KOL.Corp.WebSite/Common/Login.aspx?language=en", wait_until="domcontentloaded")

        # Fill in Username
        page.fill("#ctl00_cphLoginBox_txtUsernameSME", str(data["username"]))

        # Fill in Password
        page.fill("#ctl00_cphLoginBox_txtPasswordSME", str(data["password"]))

        # Button Click Login
        page.click("#ctl00_cphLoginBox_imgLogin")

        # Click "Other Account"
        page.locator("//div[normalize-space()='Other Account']").wait_for(timeout=15000)
        page.locator("//div[normalize-space()='Other Account']").click()
        return page

    # Withdrawal
    @classmethod
    def kma_withdrawal(cls, page, data):
        
        # Select Bank Code
        page.locator("#ddlBanking").wait_for(timeout=10000)
        page.select_option("#ddlBanking", str(data["toBankCode"]))

        try:
            # Wait only 5 seconds for the message
            page.wait_for_selector("//div[@class='header_error']", timeout=5000)
            
            # Print Detect Invalid Session
            print("Detected logout message. Redirecting to login.")

            # Button Click Sign in
            page.click("//input[@id='ctl00_cphSectionButton_btnLogin']")

            time.sleep(1)

            BankBot.kma_login(data)    

            # Select Bank Code
            page.locator("#ddlBanking").wait_for(timeout=10000)
            page.select_option("#ddlBanking", str(data["toBankCode"]))
  
        except:
            pass


        # Fill in Account Number
        page.fill("#ctl00_cphSectionData_txtAccTo", str(data["toAccountNum"]))

        # Fill in Amount
        page.fill("#ctl00_cphSectionData_txtAmountTransfer", str(data["amount"]))

        # Click Submit
        page.click("#ctl00_cphSectionData_btnSubmit")

        # Wait for OTP Box Appear
        page.locator(".otpbox_header").wait_for(timeout=10000)

        # Capture OTP Reference Number
        cls._kma_ref = page.locator("//div[@class='inputbox_half_center']//div[@class='input_input_half']").first.inner_text().strip()

        # Run Read OTP Code
        otp = cls.kma_read_otp()

        # Fill OTP Code
        page.fill("#ctl00_cphSectionData_OTPBox1_txtOTPPassword", otp)
        
        # Delay 0.5 second
        page.wait_for_timeout(500)

        time.sleep(1111111)

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
    def kma_read_otp(cls):
        
        driver = cls.use_appium_driver()

        try:
            # Start Messages Apps
            driver.activate_app("com.google.android.apps.messaging")
            
            while True:
                try:

                    # Read All KMA Bank Messages
                    print("ðŸ¤– Reading latest message from KMA bank...")

                    # Wait for the 'message_list' container to be visible
                    # We use the specific XPath from your screenshot to avoid ID errors
                    WebDriverWait(driver, 15).until(EC.visibility_of_element_located((AppiumBy.XPATH, '//android.view.View[@resource-id="message_list"]')))

                    # Find all 'message_text' elements that are descendants (offspring) of 'message_list'
                    # The "//" in the middle acts as the .offspring() command
                    message_nodes = driver.find_elements(AppiumBy.XPATH, '//android.view.View[@resource-id="message_list"]//android.widget.TextView[@resource-id="message_text"]')
                    
                    # Store Messages OTP
                    otp_candidates = []

                    # Process the messages (Newest first)
                    for node in reversed(message_nodes):
                        try:
                            # Get the text content
                            messages = node.text
                            
                            if not messages:
                                continue
                                
                            # Regex to find Ref and OTP
                            match = re.search(r"\bRef\s*[:\-]?\s*(\d+)\b.*?\bOTP\s*[:\-]?\s*(\d+)\b", messages, re.IGNORECASE)

                            if match:
                                _messages_ref_code, messages_otp_code = match.groups()
                                otp_candidates.append((_messages_ref_code.strip(), messages_otp_code.strip()))
                                print(f"# Ref: {_messages_ref_code}, OTP: {messages_otp_code} âŒ")

                        except Exception:
                            # Ignore errors for single stale elements
                            continue

                    # Match correct Ref Code 
                    for _messages_ref_code, messages_otp_code in otp_candidates:
                        if cls._kma_ref == _messages_ref_code:
                            print(f"Found matching Ref: {_messages_ref_code} | OTP: {messages_otp_code} âœ…")
                            return messages_otp_code
                        
                    # If no match, loop again
                    print("# OTP not found yet, retrying... \n")
                    time.sleep(1)

                except Exception as e:
                    print(f"âš ï¸ Error reading messages: {e}")
                    time.sleep(1)

        finally:
            driver.quit() 
    
    # Callback ERIC API
    @classmethod
    def eric_api(cls, data):

        url = "https://bot-integration.cloudbdtech.com/integration-service/transaction/payoutScriptCallback"

        # Create payload as a DICTIONARY (not JSON yet)
        payload = {
            "bankCode": str(data["fromBankCode"]),
            "deviceId": str(data["deviceId"]),
            "merchantCode": str(data["merchantCode"]),
            "transactionId": str(data["transactionId"]),
        }

        # Your secret key
        secret_key = "PRODBankBotIsTheBest"

        # Build the hash string (exact order required)
        string_to_hash = (
            f"bankCode={payload['bankCode']}&"
            f"deviceId={payload['deviceId']}&"
            f"merchantCode={payload['merchantCode']}&"
            f"transactionId={payload['transactionId']}{secret_key}"
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

        # 7ï¸âƒ£ Debug info
        print("Raw string to hash:", string_to_hash)
        print("MD5 Hash:", hash_result)
        print("Response:", response.text)
        print("\n\n")

# ================== Code Start Here ==================

# Run API
@app.route("/kma_company_web/runPython", methods=["POST"])        
def runPython():
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"success": False, "message": "Invalid JSON"}), 400

    with LOCK:
        try:
            # Run Browser
            Automation.chrome_cdp()
            # Login KMA
            page = BankBot.kma_login(data)
            BankBot.kma_withdrawal(page, data)
            return jsonify({
                "success": True,
                "transactionId": data["transactionId"]
            })
        except Exception as e:
            return jsonify({"success": False, "message": str(e)}), 500

if __name__ == "__main__":
    BankBot.start_ws_client()

    app.run(host="0.0.0.0", port=5002, debug=False, threaded=False, use_reloader=False)

# BankBot.use_appium_driver()
