import os
import io
import re
import sys
import json
import time
import queue
import atexit
import hashlib
import logging
import requests
import traceback
import threading
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

# ================== Version Change ==========================

# - 1.0.1
# Remove sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8') causing error 


# ================== Eric WS_Client Settings =================

WS_PROC = None

# ================== Appium Settings ========================

APPIUM_DRIVER = None
APPIUM_PROC = None
APPIUM_LOCK = Lock()

# =========================== Flask apps ==============================

app = Flask(__name__)
LOCK = Lock()

# IDLE
IDLE_SECONDS = 300 # 5 minutes

# ================== PLAYWRIGHT SINGLETON ========================

PLAYWRIGHT = None
BROWSER = None
CONTEXT = None
PAGE = None

# ================== Logger Settings =========================

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_DIR = os.path.join(BASE_DIR, "logs")
os.makedirs(LOG_DIR, exist_ok=True)

LOG_FILE = os.path.join(LOG_DIR, "KTB_Company_Web_Payout.log")

# Auto-create the logs folder if it doesn't exist
if not os.path.exists(LOG_DIR):
    os.makedirs(LOG_DIR)

logging.basicConfig(
    level=logging.INFO,  # change to logging.INFO if you want less logs
    format="%(asctime)s - %(levelname)s - %(name)s - %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, mode="a", encoding="utf-8"),
        logging.StreamHandler(),  # prints to terminal
    ],
)

logger = logging.getLogger("KTB COMPANY WEB")

# ================== Appium Driver ==================

# Android Appium
class Appium_Driver:

    # Inactivity Timeout Timer
    last_TxN_Time = time.time()
    time_Lock = Lock()

    # Use Appium Driver
    @classmethod
    def use_appium_driver(cls):
        global APPIUM_DRIVER
        logger.info("Preparing Appium driver")

        cls.start_appium_server()

        with APPIUM_LOCK:
            if APPIUM_DRIVER is None:
                options = UiAutomator2Options()
                options.platform_name = "Android"
                options.device_name = "androidtesting"
                options.automation_name = "UiAutomator2"
                options.new_command_timeout = 86400

                APPIUM_DRIVER = webdriver.Remote("http://127.0.0.1:8021", options=options)
                APPIUM_DRIVER.update_settings({"waitForIdleTimeout": 0})   ### This setting SUPER IMPORTANT Settings, This can make Appium 2–3× faster because it stops waiting for Android UI idle.
            else:
                logger.info("Reusing existing Appium driver session")

        return APPIUM_DRIVER
    
    # Start Appium Server
    @classmethod
    def start_appium_server(cls):
        
        global APPIUM_PROC
        logger.info("Reusing existing Appium driver session")
        
        # if appium server start already, then skip
        # Prevent starting multiple appium server
        if APPIUM_PROC: 
            logger.info("Appium process already exists, skipping new start")
            return

        # Start Appium Server Command
        load_dotenv()
        APPIUM_CMD = os.getenv("APPIUM_CMD")
        APPIUM_PROC = subprocess.Popen([
            APPIUM_CMD,
            "--port", "8021",
            "--allow-insecure", "uiautomator2:adb_shell",
            "--allow-cors"
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
        )

        logger.info("Appium process started with PID %s", APPIUM_PROC.pid)
                
        # Wait until Appium server is ready, retry 10 times
        for attempt in range(1, 11):
            try:
                if requests.get("http://127.0.0.1:8021/status").ok:
                    logger.info("Appium server is ready (attempt %s/10)", attempt)
                    return
            except Exception:
                logger.debug("Appium status check failed (attempt %s/10)", attempt)
                time.sleep(1)

        # if after 10 times retry, appium still not ready, then raise the error to stop the program
        logger.error("Appium server did not become ready after 10 attempts")
        raise RuntimeError("Appium not started")

# ================== Eric Settings ==================

class Eric:

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

        # 7️⃣ Debug info
        print("Raw string to hash:", string_to_hash)
        print("MD5 Hash:", hash_result)
        print("Response:", response.text)
        print("\n\n")

    # Start Eric Server (ws_client)
    @classmethod
    def start_ws_client(cls):
        global WS_PROC

        logger.info("Starting for Eric WS_Client ...")
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

class BankBot(Automation, Appium_Driver, Eric):
    
    _ktb_web_ref_code = None

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

        # Forces the terminal to handle those sea creatures correctly
        logger.info("="*50)
        logger.info("🎰 Starting KTB Company Web Login Flow ....")
        logger.info("="*50)

        # If already on transfer page, skip login
        try:
            page.locator("//h4[normalize-space()='Transfer Details']").wait_for(timeout=1500)
            return page # Already Login
        except:
            pass
        
        # Browse to Krungthai Website 
        logger.info("Browse to Krungthai Website ...")
        page.goto("https://business.krungthai.com/#/login", wait_until="domcontentloaded")

        # Change Language (English)
        logger.info("Force change to English Language ...")
        page.locator("//p[@class='language-english']").click(timeout=0) 

        # Delay 0.5 seconds
        page.wait_for_timeout(500)

        # if Account already login, can skip
        logger.info("Perform Login ...")
        try: 
            # Fill "Company ID"
            logger.info("Fill in Company ID ...")
            page.locator("//input[@placeholder='Enter company ID']").fill(str(data["companyId"]), timeout=1000)

            # Fill "User ID"
            logger.info("Fill in User ID ...")
            page.locator("//input[@placeholder='Enter user ID']").fill(str(data["username"]), timeout=1000)

            # Fill "Password"
            logger.info('Fill in Password ...')
            page.locator("//input[@placeholder='Enter password']").fill(str(data["password"]), timeout=1000)

            # Delay 0.5 seconds
            page.wait_for_timeout(500)

            # Button Click "Login"
            logger.info("Click Login ...")
            page.locator("//span[@class='ktb-button-label']").click(timeout=0)

        except:
            logger.info("Already Login, Skip ...")
            pass
        
        # Wait for "OTP Verification" Appear
        logger.info("Wait for OTP Verification ...")
        page.locator("//h4[normalize-space()='OTP Verification']").wait_for(state="visible", timeout=30000)
        
        # Delay 1 second
        page.wait_for_timeout(1000)  

        # Get KTB Ref Code
        logger.info("Read KTB Ref Code ...")
        cls._ktb_web_ref_code = page.locator("//p[@class='ref ref-number-size mb-16px']").inner_text().strip()
        match = re.search(r"Ref\.?\s*([A-Za-z0-9]+)", cls._ktb_web_ref_code, re.IGNORECASE)
        if match:
            cls._ktb_web_ref_code = match.group(1).upper().strip()
            logger.info(f"KTB Web Ref Code: {cls._ktb_web_ref_code}")

        # Run Read OTP Code
        otp = cls.ktb_read_otp()
        logger.info("Get OTP-Code Successful ....")

        # Fill OTP Code
        logger.info("Fill in OTP-Code ...")
        page.locator("//input[@id='otp-input-0']").fill(otp)

        # Button Click "Verify"
        logger.info("Button click 'Verify' ...")
        page.locator("//span[@class='ktb-button-label']").click()

        # Wait for "Account Overview" Appear
        logger.info("Wait for 'Account Overview' Appear ... " )
        page.locator("//h4[normalize-space()='Account Overview']").wait_for(state="visible", timeout=300000)

        return page

    # Withdrawal
    @classmethod
    def ktb_withdrawal(cls, page, data):
        
        # Withdrawal Processs
        logger.info("="*50)
        logger.info("🎰 Starting KTB Company Web Withdrawal Flow ....")
        logger.info("="*50)

        # Hover to Left Menu
        page.locator("//a[@class='link active']").hover()
        logger.info("Hover to left Menu ...")

        # Delay 1 second
        page.wait_for_timeout(1000)

        # Click Transfer & Pay
        logger.info("Click 'Transfer & Pay' ... ")
        page.locator("//span[normalize-space()='Transfer & Pay']").click()
        
        # Wait for "Transfer & Bill Payment" Appear
        logger.info("Wait for 'Transfer & Bill Payment' ... ")
        page.locator("//a[normalize-space()='Transfer & Bill Payment']").wait_for(state="visible", timeout=0)

        # Delay 1 second
        page.wait_for_timeout(1000)

        # Button Click "New Transfer"
        logger.info("Click 'New Transfer' ... ")
        page.locator("//body/ktb-root/ui-layout/div[@class='main-container']/ui-side-panel/ng-sidebar-container[@backdropclass='custom-backdrop']/div[@class='ng-sidebar__content ng-sidebar__content--animate']/main/div[@class='main-inner']/ktb-module-transfer-pay[@class='ng-star-inserted']/ktb-module-transfer-pay-index-page[@class='ng-star-inserted']/ui-section[@class='transfer-landing-header section-wrapper ng-star-inserted']/section[@class='is-dark']/div[@class='section-content']/ui-container/div[@class='container']/div[@class='inner']/div[@class='sub-menu-container ng-star-inserted']/ui-card-sub-menu[1]/div[1]").click(timeout=0)

        # Wait for "Transfer Details" Appear
        logger.info("Wait for 'Transfer Details' ...")
        page.locator("//h4[normalize-space()='Transfer Details']").wait_for(state="visible", timeout=30000)

        # Click "Select Payee"
        logger.info("Select Payee ...")
        page.locator("//div[@class='add-payee-button']").click()

        # Wait for "New Account" Appear
        logger.info("Wait for 'New Account' Appear ...")
        page.locator("//h6[normalize-space()='New Account']").wait_for(state="visible", timeout=30000)

        # Click "New Account"  
        logger.info("Click 'New Account' ...")
        page.locator("//h6[normalize-space()='New Account']").click()

        # Delay 1 second
        page.wait_for_timeout(1000)

        # Open dropdown (# Select Bank Code)
        logger.info("Open 'Select Bank' Drop Down Menu ...")
        bank_input = page.locator("input[formcontrolname='searchControl']")
        bank_input.click()
        bank_input.fill(str(data["toBankCode"]))

        # Delay 1 second
        page.wait_for_timeout(1000)

        # Select bank
        logger.info("Select Bank ...")
        page.get_by_text(str(data["toBankCode"]), exact=True).wait_for(state="visible", timeout=5000)
        page.get_by_text(str(data["toBankCode"]), exact=True).click()

        # Delay 1 second
        page.wait_for_timeout(1000)

        # Fill AccouNT Number 
        logger.info("Fill Account Number ...")
        page.get_by_placeholder("Enter account no.").click()
        page.get_by_placeholder("Enter account no.").fill(str(data["toAccountNum"])) 
        page.keyboard.press("Tab")

        # Delay 1 second
        page.wait_for_timeout(1000)

        # Fill Beneficiary Name
        try:
            logger.info("Fill Beneficiary Name ...")
            page.locator("//input[@placeholder='Enter name / company name (in full)']").click()
            page.locator("//input[@placeholder='Enter name / company name (in full)']").fill(str(data["toAccountName"]), timeout=1000)
        except:
            pass

        # Delay 1 second
        page.wait_for_timeout(1000)

        # Click "Add Details"  
        logger.info("Click 'Add Details' ....")
        page.locator("//span[normalize-space()='Add Details']").click()

        # Delay 1 second
        page.wait_for_timeout(1000)

        # Wait for "value date" appear
        logger.info("Wait for 'Value Date' ...")
        page.locator("//label[normalize-space()='Value Date']").wait_for(state="visible", timeout=30000)

        # Delay 1 second
        page.wait_for_timeout(1000)
        
        # Fill AccouNT Number 
        logger.info("Fill Account Number ...")
        page.locator("//input[@formcontrolname='amount']").click()
        page.locator("//input[@formcontrolname='amount']").fill(str(data["amount"]))

        # Delay 2.5 second
        page.wait_for_timeout(2500)

        # Click "SAVE"
        logger.info("Click Save ...")
        page.locator("//span[normalize-space()='SAVE']").click()

        # Delay 1 second
        page.wait_for_timeout(1000)

        # Click "NEXT"
        logger.info("Click Next ...")
        page.locator("//span[normalize-space()='NEXT']").click()

        # Delay 1 second
        page.wait_for_timeout(1000)

        # Click "CONFIRM"
        logger.info("Click Confirm ...")
        page.locator("//span[normalize-space()='CONFIRM']").click()

        # Delay 1 second
        page.wait_for_timeout(1000)

        # Wait for "OTP Verification"
        logger.info("Wait for OTP Verification Code Title Appear ...")
        page.locator("//h4[normalize-space()='OTP Verification']").wait_for(state="visible", timeout=30000)

        # Delay 1 second
        page.wait_for_timeout(1000)

        # Wait until the Ref element is visible
        logger.info("Wait for Ref ID Element Appear ...")
        page.locator("//p[@class='ref ref-number-size mb-16px']").wait_for(state="visible", timeout=10000)

        # Delay 1 second
        page.wait_for_timeout(1000)

        # Get KTB Ref Code (Comfirm Transfer there)
        logger.info("Get KTB Ref Code ....")
        cls._ktb_web_ref_code = page.locator("//p[@class='ref ref-number-size mb-16px']").inner_text().strip()
        match = re.search(r"Ref\.?\s*([A-Za-z0-9]+)", cls._ktb_web_ref_code, re.IGNORECASE)
        if match:
            cls._ktb_web_ref_code = match.group(1)
            logger.info(f"KTB Web Ref Code: {cls._ktb_web_ref_code}")
        
        # Run Read OTP Code
        otp = cls.ktb_read_otp()
        logger.info("Successful Get OTP-CODE ...")

        # Fill OTP Code
        logger.info("Fill OTP Code ...")
        page.locator("//input[@id='otp-input-0']").fill(otp)

        # Delay 1 second
        page.wait_for_timeout(1000)

        # Button Click "Verify"
        logger.info("Click Verify button ...")
        page.locator("//span[normalize-space()='VERIFY']").click()

        # Delay 1 second
        page.wait_for_timeout(1000)

        # Call Eric API
        cls.eric_api(data)

        # Print Withdrawal SuccessFul!!
        logger.info(f"Withdrawal SuccessFul!!!")

    # Logout
    @classmethod
    def ktb_logout(cls, page):

        # Clear all cookies
        page.context.clear_cookies()

        # clear storage
        page.evaluate("""
            () => {
                localStorage.clear();
                sessionStorage.clear();
            }
        """)

        # Reload page if cookies affect session
        page.reload(wait_until="networkidle")

    # Read Phone Message OTP Code
    @classmethod
    def ktb_read_otp(cls):

        # Forces the terminal to handle those sea creatures correctly
        logger.info("="*50)
        logger.info("🎰 Starting Read Phone SMS OTP-Code Flow ....")
        logger.info("="*50)
        
        # Use Appium Driver
        driver = cls.use_appium_driver()

        # ADB Shell Never Screen Timeout
        logger.info("ADB Shell Screen never Time Out ...")
        driver.execute_script("mobile: shell", {"command": "settings","args": ["put", "system", "screen_off_timeout", "2147483647"]})
 
        # Start Messages Apps
        driver.activate_app("com.google.android.apps.messaging")
        
        while True:

            # Read All KTB Bank Messages
            print("🤖 Reading latest message from KTB bank...")

            # Wait for the 'message_list' container to be visible
            # We use the specific XPath from your screenshot to avoid ID errors
            WebDriverWait(driver, 15).until(EC.visibility_of_element_located((AppiumBy.XPATH, '//android.view.View[@resource-id="message_list"]')))

            # Find all 'message_text' elements that are descendants (offspring) of 'message_list'
            # The "//" in the middle acts as the .offspring() command
            message_nodes = driver.find_elements(AppiumBy.XPATH, '//android.view.View[@resource-id="message_list"]//android.widget.TextView[@resource-id="message_text"]')
            
            # --- Collect OTP + Ref from all new messages ---
            otp_candidates = []
            
            # Process the messages (Newest first)
            for node in reversed(message_nodes):

                try:

                    # Get the text content
                    messages = node.text
                    
                    if not messages:
                        continue
                
                    # using regex to get Message OTP Code and Ref Code
                    match = re.search(r"\bOTP\s*(?:is|:)?\s*(\d{4,8})\b.*?\bRef\s*(?:No\.?|:)?\s*([A-Z0-9]+)\b", messages, re.IGNORECASE,)

                    if match:
                        messages_otp_code, _messages_ref_code = match.groups()
                        otp_candidates.append((_messages_ref_code.strip(), messages_otp_code.strip()))
                        print(f"# Ref: {_messages_ref_code}, OTP: {messages_otp_code} ❌")
                
                except Exception:
                    # Ignore errors for single stale elements
                    continue

            # --- Match correct Ref Code ---
            for _messages_ref_code, messages_otp_code in otp_candidates:
                if cls._ktb_web_ref_code == _messages_ref_code:
                    print(f"Found matching Ref: {_messages_ref_code} | OTP: {messages_otp_code} ✅")
                    return messages_otp_code
                
            # If no match, loop again
            print("# OTP not found yet, keep waiting... \n")
    
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

            # Login KMA
            page = BankBot.ktb_login(data)

            # Withdrawal KMA
            BankBot.ktb_withdrawal(page, data)

            # Return Success
            return jsonify({
                "success": True,
                "transactionId": data["transactionId"]
            })
        
        except Exception as e:
            full_trace = traceback.format_exc()
            
            # Prints to console
            print(f"\n--- CRITICAL TRANSACTION ERROR ---\n{full_trace}")
            
            # WRITES TO LOG FILE
            logging.error(f"CRITICAL ERROR for Transaction {data.get('transactionId', 'unknown')}:\n{full_trace}\n{'-'*40}")
            
            # Kill Browser
            try:
                Automation.cleanup()
            except:
                pass

            # FORCE EXIT: This stops the entire Python script and Flask server
            # Use os._exit(1) to exit immediately from the thread
            os._exit(1)
            
            return jsonify({
                "success": False,
                "message": str(e),
                "error_type": type(e).__name__
            }), 500
        
if __name__ == "__main__":
    BankBot.start_ws_client()
    app.run(host="0.0.0.0", port=5003, debug=False, threaded=False, use_reloader=False)
