import re
import sys
import os 
import json
import time
import atexit
import hashlib
import logging
import requests
import traceback
import subprocess
from pathlib import Path
from dotenv import load_dotenv
from datetime import datetime, timedelta
from bson.objectid import ObjectId  
from playwright.sync_api import sync_playwright, expect
from airtest.core.api import *
from poco.drivers.android.uiautomation import AndroidUiautomationPoco

# Load .env (Load Credential)
env_path = Path(__file__).parent / ".env"
load_dotenv(dotenv_path=env_path, override=True)

# Logging
LOG_DIR = Path(__file__).parent / "logs"
LOG_FILE = LOG_DIR / "error.log"

# Log File
def setup_logging():
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger("bank_bot")
    logger.setLevel(logging.INFO)
    logger.propagate = False

    # Reset handlers to avoid duplicate logs on re-runs
    if logger.handlers:
        logger.handlers.clear()

    log_format = logging.Formatter("%(asctime)s | %(levelname)s | %(name)s | %(message)s")

    file_handler = logging.FileHandler(LOG_FILE, encoding="utf-8")
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(log_format)

    stream_handler = logging.StreamHandler()
    stream_handler.setLevel(logging.INFO)
    stream_handler.setFormatter(log_format)

    logger.addHandler(file_handler)
    logger.addHandler(stream_handler)
    return logger

logger = setup_logging()

def log_uncaught_exception(exc_type, exc_value, exc_traceback):
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, exc_traceback)
        return
    logger.critical("Unhandled exception", exc_info=(exc_type, exc_value, exc_traceback))

sys.excepthook = log_uncaught_exception

# All Account
account={}

# SCB Anywhere (Web)
scb_web = {
    "username": os.getenv("USERNAME"),
    "password": os.getenv("PASSWORD"),
    "bank": os.getenv("BANK"),
    "acc_no": os.getenv("ACC_NO"),
    "amount": os.getenv("AMOUNT")
}

# SCB Anywhere (App)
scb_app = {
    "pin": os.getenv("login_pass"),
    "digital_token": os.getenv("scb_digital_token")
}

# Kbank Business(Web)
kbank_web = {
    "username": os.getenv("USERNAME_2"),
    "password": os.getenv("PASSWORD_2"),
    "bank": os.getenv("BANK_2"),
    "acc_no": os.getenv("ACC_NO_2"),
    "amount": os.getenv("AMOUNT_2")
}

# TTB BusinessOne (Web)
ttb_web = {
    "username": os.getenv("USERNAME_3"),
    "password": os.getenv("PASSWORD_3"),
    "rcpt_name": os.getenv("Recipient_Name_3"),
    "bank": os.getenv("BANK_3"),
    "acc_no": os.getenv("ACC_NO_3"),
    "amount": os.getenv("AMOUNT_3")
}

# KMA Business (Web)
kma_web = {
    "deviceID": sys.argv[1],
    "merchantCode": sys.argv[2],
    "fromBankCode": sys.argv[3],
    "fromAccNo": sys.argv[4],
    "toBankCode": sys.argv[5],
    "toAccNo": sys.argv[6],
    "toAccName": sys.argv[7],
    "amount": sys.argv[8],
    "username": sys.argv[9],
    "password": sys.argv[10],
}

# KTB Business (Web)
ktb_web = {
    "company_id":os.getenv("COMPANY_ID_5"),
    "username": os.getenv("USERNAME_5"),
    "password": os.getenv("PASSWORD_5"),
    "rcpt_name": os.getenv("Recipient_Name_5"),
    "bank": os.getenv("BANK_5"),
    "acc_no": os.getenv("ACC_NO_5"),
    "amount": os.getenv("AMOUNT_5"),
}

# Chrome 
class Automation:

    # Chrome CDP 
    chrome_proc = None
    @classmethod
    def chrome_CDP(cls):

        # User Profile
        USER_DATA_DIR = fr"C:\Users\Thomas\AppData\Local\Google\Chrome\User Data\Profile99"

        # Step 1: Start Chrome normally
        cls.chrome_proc = subprocess.Popen([
            fr"C:\Program Files\Google\Chrome\Application\chrome.exe",
            "--remote-debugging-port=9222",
            "--disable-session-crashed-bubble",
            "--hide-crash-restore-bubble",
            "--no-first-run",
            "--no-default-browser-check",
            f"--user-data-dir={USER_DATA_DIR}",  # User Profile
        ],
        stdout=subprocess.DEVNULL,  # ✅ hide chrome cdp logs
        stderr=subprocess.DEVNULL   # ✅ hide chrome cdp logs
        )
        print("Chrome launched.....")
    
        # wait for Chrome CDP launch...
        cls.wait_for_cdp_ready()

        atexit.register(cls.cleanup)

    # Close Chrome CDP
    @classmethod
    def cleanup(cls):
        try:
            logger.info("Gracefully terminating Chrome...")
            cls.chrome_proc.terminate()
        except Exception as e:
            logger.exception("Error terminating Chrome")
    
    # Wait for Chrome CDP to be ready
    @staticmethod
    def wait_for_cdp_ready(timeout=10):
        """Wait until Chrome CDP is ready at http://localhost:9222/json"""
        for _ in range(timeout):
            try:
                res = requests.get("http://localhost:9222/json")
                if res.status_code == 200:
                    return True
            except:
                pass
            time.sleep(1)
        raise RuntimeError("Chrome CDP is not ready after waiting.")

# Bank Bot
class Bank_Bot(Automation):

    # Kbank Ref Code and Messsage OTP Code
    _kbank_web_ref_code = None
    _messages_otp_code = None

    # TTB Business One Ref Code
    _ttb_web_ref_code = None
    
    # KMA Business Ref Code
    _kma_web_ref_code = None

    # KTB Business Ref Code 
    _ktb_web_ref_code = None
    _ktb_web_ref_code_2 = None

    @classmethod
    def eric_api(cls, transactionID):

        url = "https://stg-bot-integration.cloudbdtech.com/integration-service/transaction/payoutScriptCallback"

        # Create payload as a DICTIONARY (not JSON yet)
        payload = {
            "transactionID": transactionID,
            "bankCode": sys.argv[3],
            "deviceId": sys.argv[1],
            "merchantCode": sys.argv[2],
        }

        # Your secret key
        secret_key = "DEVBankBotIsTheBest"

        # Build the hash string (exact order required)
        string_to_hash = (
            f"transactionID={payload['transactionID']}&"
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

    # SCB Anywhere (Web)
    @classmethod
    def scb_Anywhere_web(cls):
        with sync_playwright() as p:  

            # Wait for Chrome CDP to be ready
            cls.wait_for_cdp_ready()

            # Connect to running Chrome
            browser = p.chromium.connect_over_cdp("http://localhost:9222")
            context = browser.contexts[0] if browser.contexts else browser.new_context()    

            # Open a new browser page
            page = context.pages[0] if context.pages else context.new_page()
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
                page.locator("//input[@name='username']").fill(scb_web["username"], timeout=1000)

                # Button Click "Next"
                page.locator("//span[normalize-space()='Next']").click(timeout=0) 

                # Fill "Password"
                page.locator("//input[@name='password']").fill(scb_web["password"], timeout=0)

                # Button Click "Next"
                page.locator("//button[@type='submit']").click(timeout=0) 
            except:
                pass
            
            # Button Click "Transfer"
            page.locator("//p[normalize-space()='Transfers']").click(timeout=0) 

            # Button Click "Add New Recipient"
            page.locator("//span[normalize-space()='Add New Recipient']").click(timeout=0) 
            
            # Fill Bank Name and Click
            page.get_by_label("Bank Name *").fill(scb_web["bank"], timeout=0)
            page.get_by_text(scb_web["bank"], exact=True).click(timeout=0)
            
            # Fill Account No.
            page.locator("//input[@id='accountNumber']").fill(scb_web["acc_no"], timeout=0)

            # Button Click "Next"
            page.locator("//span[normalize-space()='Next']").click(timeout=0) 

            # Button Click "Confirm"
            page.locator("//span[normalize-space()='Confirm']").click(timeout=0) 

            # Button Click "Enter"
            page.locator("//span[normalize-space()='Enter']").click(timeout=0) 

            # Fill Amount
            page.locator("//input[@name='amount']").fill(scb_web["amount"], timeout=0)

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
            Bank_Bot.scb_Anywhere_apps()

            # Button Click "Done"
            page.locator("//span[normalize-space()='Done']").click(timeout=1000)

            time.sleep(5)

    # SCB Anywhere (Apps)
    def scb_Anywhere_apps():

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

        # Wait for "Enter PIN" appear
        try:
            poco(text="Enter PIN").wait_for_appearance(timeout=15)
        except:
            pass

        # Key Pin
        for digit in scb_app["pin"]:
            poco(f"Login_{digit}").click()

        # Wait and Click Notifications
        poco(text="Notifications").wait_for_appearance(timeout=15)   
        poco("tabNotificationsStack").click()

        # Click "View request"
        poco(text="View request").click()

        # Wait and Click "Submit for approval"
        poco("btApprove").click()
        
        # Key SCB Digital Token Pin
        for digit in scb_app["digital_token"]:
            poco(f"SoftTokenInputPin_{digit}").click()
        
        # Click "Go to To-do List"
        poco("btTodoList").click()

    # KBank Corporate (Web)
    @classmethod
    def kbank_web(cls):
        with sync_playwright() as p:  

            # Wait for Chrome CDP to be ready
            cls.wait_for_cdp_ready()

            # Connect to running Chrome
            browser = p.chromium.connect_over_cdp("http://localhost:9222")
            context = browser.contexts[0] if browser.contexts else browser.new_context()

            # Open an existing page if available, otherwise create one
            page = context.pages[0] if context.pages else context.new_page()
            page.set_default_timeout(15000)
            page.bring_to_front()
            print("Navigating to KBank...")
            try:
                page.goto("https://kbiz.kasikornbank.com", wait_until="networkidle")
                print("Navigation finished.")
            except Exception as nav_err:
                print(f"Navigation error: {nav_err}")
                raise

            # if Account already login, can skip
            try: 
                # Fill "User ID"
                page.locator("//input[@id='userName']").fill(kbank_web["username"])

                # Fill "Password"
                page.locator("//input[@id='password']").fill(kbank_web["password"])

                # Button Click "Log In"
                page.locator("//a[@id='loginBtn']").click()
            except:
                pass

            # Button Click "Fund Transfer"
            page.locator("//div[@class='column-menu']//a[@id='BIZ_004']").click() 

            # wait for "Fund Transfer" to be appear
            page.locator("//h1[normalize-space()='Funds Transfer']").wait_for() 

            # Delay 1 second
            page.wait_for_timeout(1000) 

            # Button Click "Select Bank"
            page.locator("//span[@id='select2-id_select2_example_3-container']//div").click()

            # Locate the input
            page.locator("input.select2-search__field").evaluate("el => el.removeAttribute('readonly')")
            page.locator("input.select2-search__field").fill(kbank_web["bank"])
            page.locator(f"//div[span[normalize-space()='{kbank_web['bank']}']]").click()

            # Fill Account No.
            page.locator("//input[@placeholder='xxx-x-xxxxx-x']").fill(kbank_web["acc_no"])

            # Fill Amount
            page.locator("//input[@placeholder='0.00']").fill(kbank_web["amount"])

            # Button Click "Next"
            page.locator("//a[@class='btn btn-gradient f-right disabled-button']").click()

            # if Notice | You or Company has made this transaction already .... if this appear click confirm else skip
            try: 
                expect(page.locator("//div[@class='mfp-content']//h3[contains(text(),'Notice')]")).to_be_visible(timeout=4000)
                # Button Click "Confirm"
                page.locator("//div[@class='mfp-content']//span[contains(text(),'Confirm')]").click()
            except:
                pass
            
            # Kbank Web Ref Code
            cls._kbank_web_ref_code = page.locator("label.label strong").inner_text()
            print(f"KBank Web Ref Code: {cls._kbank_web_ref_code}")
            
            # Call messages_OTP() function and Get OTP Code
            _messages_otp_code = cls.messages_OTP()

            # Fill OTP Code
            if _messages_otp_code:
                page.locator("//input[@name='otp']").fill(_messages_otp_code)
            else:
                print("Error: No OTP code found, cannot fill OTP input")

            # Button Click "Confirm"
            page.locator("//a[@class='btn fixedwidth btn-gradient f-right']").click()

            # Wait 3 seconds then close
            time.sleep(3)

    # Messages (SMS Kbank OTP Code)
    @classmethod
    def messages_OTP(cls):

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
        
        # Click KBank Chat
        # If not in inside KBank chat, click it, else passs
        if not poco("message_text").exists():
            poco(text="KBank").click()
        else:
            pass
        
        # Delay 2 seconds
        time.sleep(2)

        # Read All KBank Messages
        message_nodes = poco("message_list").offspring("message_text")
        for i, node in enumerate(message_nodes):
            messages = node.get_text()

            # Using Regex to get Messages Ref Code
            match = re.search(r"\(Ref:\s*([A-Za-z0-9]+)\)", messages)
            if match:
                messages_ref_code = match.group(1)

            # Compare Kbank Web (Ref Code) and Mobile Message (Ref Code), if is true, extract otp code, else print none
            if cls._kbank_web_ref_code == messages_ref_code:
                # Using Regex to get OTP Code
                match = re.search(r'OTP\s*=\s*(\d{6})', messages)
                cls._messages_otp_code = match.group(1) if match else None   
                print(f"Ref Code: {cls._kbank_web_ref_code} = {messages_ref_code} ✅, OTP Code:{cls._messages_otp_code}")
                return cls._messages_otp_code            
            else:
                print(f"Ref Code: {cls._kbank_web_ref_code} = {messages_ref_code} ❌")
                continue

    # TTB Business One (Web)
    @classmethod
    def ttb_businessOne_web(cls):
        with sync_playwright() as p:  

            # Wait for Chrome CDP to be ready
            cls.wait_for_cdp_ready()

            # Connect to running Chrome
            browser = p.chromium.connect_over_cdp("http://localhost:9222")
            context = browser.contexts[0] if browser.contexts else browser.new_context()    

            # Open a new browser page
            page = context.pages[0] if context.pages else context.new_page()
            page.goto("https://www.ttbbusinessone.com/auth/login", wait_until="domcontentloaded")
            
            # Delay 1.5 seconds
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
                page.locator("//input[@type='text']").fill(ttb_web["username"], timeout=1000)
                # Delay 0.5 seconds
                page.wait_for_timeout(500)
                # Button Click "Next"
                page.locator("//button[normalize-space()='Next']").click(timeout=0) 
                # Fill "Password"
                page.locator("//input[@type='password']").fill(ttb_web["password"], timeout=0)
                # Delay 0.5 seconds
                page.wait_for_timeout(500)
                # Button Click "Next"
                page.locator("//button[normalize-space()='Next']").click(timeout=0)
            except:
                pass
            
            try:
                # Button Click "New payment"
                page.locator("//div[@class='shortcuts-container hidden-xs row']//span[@class='shortcut-value'][normalize-space()='New payment']").click(timeout=0) 
                # Button Click "Promptpay Transfer"
                page.locator("//div[@id='PPRT']").click(timeout=0)
                # Fill Recipient name
                page.locator("//input[@id='counterparty']").fill(ttb_web["rcpt_name"], timeout=0)
                # Button Click "Transfer by"
                page.locator("//ca-combo[@name='counterpartyIdType']//button[@type='button']").click(timeout=0)
                # Button Click "Account no"
                page.locator("//li[normalize-space()='Account no.']").click(timeout=0)
                # Select Bank
                page.locator("//input[@id='bank']").fill(ttb_web["bank"], timeout=0)
                # Delay 0.5 seconds
                page.wait_for_timeout(500)
                # Button Click Bank
                page.locator("//ul[@class='ng-star-inserted']//li[@class='ng-star-inserted']").click(timeout=0)
                # Fill Account No.
                page.locator("//input[@id='counterpartyIdValue']").fill(ttb_web["acc_no"], timeout=0)
                # Fill Amount
                page.locator("//input[@id='amount']").fill(ttb_web["amount"], timeout=0)
                # Button Click "CONFIRM"
                page.locator("//button[normalize-space()='Confirm']").click(timeout=0)
                # Button Click "Approve"
                page.locator("//button[normalize-space()='Approve']").click(timeout=0)

                # TTB Business One Web Ref Code
                ref_code = page.locator("label.input-label").inner_text()
                match = re.search(r"ref\s*no\s+([A-Z0-9]+)", ref_code, re.IGNORECASE)
                if match:
                    cls._ttb_web_ref_code = match.group(1)
                    print(f"TTB Business One Web Ref Code: {cls._ttb_web_ref_code}\n\n")

                # Call messages_OTP() function and Get OTP Code
                _messages_otp_code = cls.messages_OTP_2()

                # Fill OTP Code
                if _messages_otp_code:
                    page.locator("//input[@type='text']").fill(_messages_otp_code, timeout=0)

                # Button Click "Approve"
                page.locator("//button[normalize-space()='Approve']").click(timeout=0)

                # Delay 5 seconds
                page.wait_for_timeout(5000)

            except Exception as error:
                print(f"An error occurred: {error}")
                pass

    # Messages (SMS TTB Business One OTP Code)
    @classmethod
    def messages_OTP_2(cls):

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
        if not poco("message_text").exists():
            poco(text="ttbbank").click()
        else:
            pass

        # Delay 2 seconds
        time.sleep(2)

        # Timer Setting
        start_time = time.time()
        timeout = 60  # seconds

        # Get all the messages text
        message_nodes = poco("message_list").offspring("message_text")
        # Calculate the current total messages
        initial_count = len(message_nodes)
        # The Last Message
        last_text = message_nodes[-1].get_text().strip() if message_nodes else ""
        print("Waiting for new message from ttbbank...")

        # Timer, timeout 60 seconds, wait for new OTP Message come in...
        while time.time() - start_time < timeout:
            message_nodes = poco("message_list").offspring("message_text")
            current_count = len(message_nodes)

            # Get Last Message
            current_last_text = message_nodes[-1].get_text().strip()

            # Detect new messages (if current count > inital count or current text != last test, that means got new message come in )
            if current_count > initial_count or current_last_text != last_text:
                print("✅ New message(s) detected!")

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
                        _messages_otp_code, messages_ref_code = match.groups()
                        otp_candidates.append((_messages_otp_code.strip(), messages_ref_code.strip().upper()))
                        print(f"OTP: {_messages_otp_code}, Ref: {messages_ref_code} ❌")

                # --- Match correct Ref Code ---
                for _messages_otp_code, messages_ref_code in otp_candidates:
                    if cls._ttb_web_ref_code.upper() == messages_ref_code:
                        print(f"Found matching Ref: {messages_ref_code} | OTP: {_messages_otp_code} ✅")
                        return _messages_otp_code
                    
                # Saves the latest message count and text.
                # ✅ Prevents detecting the same OTP again on the next loop cycle.
                initial_count = current_count
                last_text = current_last_text

            time.sleep(2)

        print(f"⏰ Timeout - No OTP found for ref: {cls._ttb_web_ref_code}")
        return None

    # KMA Business (Web)
    @classmethod
    def kma_business_web(cls):
        with sync_playwright() as p:  

            try:
                # Wait for Chrome CDP to be ready
                cls.wait_for_cdp_ready()

                # Connect to running Chrome
                browser = p.chromium.connect_over_cdp("http://localhost:9222")
                context = browser.contexts[0] if browser.contexts else browser.new_context()    

                # Open a new browser page
                page = context.pages[0] if context.pages else context.new_page()
                page.goto("https://www.krungsribizonline.com/BAY.KOL.Corp.WebSite/Common/Login.aspx?language=en", wait_until="domcontentloaded")

                
                try:
                    # Fill "Username"
                    page.locator("//input[@id='ctl00_cphLoginBox_txtUsernameSME']").fill(sys.argv[9], timeout=1000)
                    # Fill "Password"
                    page.locator("//input[@id='ctl00_cphLoginBox_txtPasswordSME']").fill(sys.argv[10], timeout=1000)
                    # Button Click "Login"
                    page.locator("//input[@id='ctl00_cphLoginBox_imgLogin']").click(timeout=0)
                except:
                    pass
                
                # Button Click "Other Account"
                page.locator("//div[normalize-space()='Other Account']").click(timeout=0)
                time.sleep(2)

                # Button Click Bank Dropdown Menu
                page.locator("#ddlBanking").select_option(sys.argv[5])

                # Fill Account No
                page.locator("//input[@id='ctl00_cphSectionData_txtAccTo']").fill(sys.argv[6], timeout=0)

                # Fill Amount 
                page.locator("//input[@id='ctl00_cphSectionData_txtAmountTransfer']").fill(sys.argv[8], timeout=0)

                # Button Click "Submit"
                page.locator("//input[@id='ctl00_cphSectionData_btnSubmit']").click(timeout=0)

                # Wait for "Please enter OTP to confirm transaction"
                page.locator("//div[@class='otpbox_header']").wait_for(state="visible", timeout=10000)

                # KMA Business Web Ref Code
                cls._kma_web_ref_code = page.locator("//div[@class='inputbox_half_center']//div[@class='input_input_half']").nth(0).inner_text()
                print(cls._kma_web_ref_code)

                # Call kma_messages_OTP() function and Get OTP Code
                _messages_otp_code = cls.kma_messages_OTP()
                print(_messages_otp_code)

                # Fill OTP Code
                page.locator("//input[@id='ctl00_cphSectionData_OTPBox1_txtOTPPassword']").fill(_messages_otp_code, timeout=0)

                # Delay 0.5 second
                page.wait_for_timeout(500)

                # Button Click "Confirm"
                page.locator("//input[@id='ctl00_cphSectionData_OTPBox1_btnConfirm']").click(timeout=0)
                page.locator("//input[@id='ctl00_cphSectionData_OTPBox1_btnConfirm']").click(timeout=0)
                
                # Transaction ID
                transactionID = page.locator(".transaction_detail_row_value").nth(5).text_content().strip()
                print(transactionID)

                print("-" * 30)

                # Call Eric API
                cls.eric_api(transactionID)

                time.sleep(10)

            except Exception as error:
                print(f"An error occurred: {error}")
                time.sleep(111111)     
                
    # Messages (SMS KMA OTP Code)
    @classmethod
    def kma_messages_OTP(cls):

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

        # Start Messages Apps
        start_app("com.google.android.apps.messaging")
        
        # Click KMA Chat
        # If not in inside KMA chat, click it, else passs
        if not poco("message_text").exists():
            poco(text="Krungsri").click()
        else:
            pass

        # Timer Setting
        start_time = time.time()
        timeout = 60  # seconds

        # Get all the messages text
        message_nodes = poco("message_list").offspring("message_text")
        # Calculate the current total messages
        initial_count = len(message_nodes)
        # The Last Message
        last_text = message_nodes[-1].get_text().strip() if message_nodes else ""
        print("Waiting for new message from KMA bank...")

        # Timer, timeout 60 seconds, wait for new OTP Message come in...
        while time.time() - start_time < timeout:
            message_nodes = poco("message_list").offspring("message_text")
            current_count = len(message_nodes)

            # Get Last Message
            current_last_text = message_nodes[-1].get_text().strip()

            # Detect new messages (if current count > inital count or current text != last test, that means got new message come in )
            if current_count > initial_count or current_last_text != last_text:
                print("✅ New message(s) detected!")

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
                        print(f"# Ref: {_messages_ref_code}, OTP: {messages_otp_code}")

                # --- Match correct Ref Code ---
                for _messages_ref_code, messages_otp_code in otp_candidates:
                    if cls._kma_web_ref_code == _messages_ref_code:
                        print(f"Found matching Ref: {_messages_ref_code} | OTP: {messages_otp_code} #")
                        return messages_otp_code
                    
                # Saves the latest message count and text.
                # ✅ Prevents detecting the same OTP again on the next loop cycle.
                initial_count = current_count
                last_text = current_last_text

    # KTB Business (Web)
    @classmethod
    def ktb_business_web(cls):
        with sync_playwright() as p:  
            
            try:
                # Wait for Chrome CDP to be ready
                cls.wait_for_cdp_ready()

                # Connect to running Chrome
                browser = p.chromium.connect_over_cdp("http://localhost:9222")
                context = browser.contexts[0] if browser.contexts else browser.new_context()    

                # Open a new browser page
                page = context.pages[0] if context.pages else context.new_page()
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
                    page.locator("//input[@placeholder='Enter company ID']").fill(ktb_web["company_id"], timeout=1000)
                    # Fill "User ID"
                    page.locator("//input[@placeholder='Enter user ID']").fill(ktb_web["username"], timeout=1000)
                    # Fill "Password"
                    page.locator("//input[@placeholder='Enter password']").fill(ktb_web["password"], timeout=1000)
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
                
                # Fill Bank Name (Select Bank)
                page.get_by_placeholder("Bank").click()
                page.get_by_placeholder("Bank").fill(ktb_web["bank"])
                page.get_by_text(ktb_web["bank"], exact=True).wait_for(state="visible", timeout=5000)
                page.get_by_text(ktb_web["bank"], exact=True).click()

                # Fill AccouNT Number 
                page.get_by_placeholder("Enter account no.").click()
                page.get_by_placeholder("Enter account no.").fill(ktb_web["acc_no"])
                page.keyboard.press("Tab")

                # Delay 1.5 second
                page.wait_for_timeout(1500)

                # Fill Beneficiary Name
                page.locator("//input[@placeholder='Enter name / company name (in full)']").fill(ktb_web["rcpt_name"])

                # Delay 0.5 second
                page.wait_for_timeout(500)

                # Click "Add Details"  
                page.locator("//span[normalize-space()='Add Details']").click()

                # Wait for "value date" appear
                page.locator("//label[normalize-space()='Value Date']").wait_for(state="visible", timeout=30000)

                # Delay 0.5 second
                page.wait_for_timeout(500)
                
                # Fill AccouNT Number 
                page.locator("//input[@formcontrolname='amount']").click()
                page.locator("//input[@formcontrolname='amount']").fill(ktb_web["amount"])

                # Delay 2.5 second
                page.wait_for_timeout(2500)

                # Click "SAVE"
                page.locator("//span[normalize-space()='SAVE']").click()

                # Delay 1 second
                page.wait_for_timeout(1000)

                # Click "NEXT"
                page.locator("//span[normalize-space()='NEXT']").click()

                # Delay 1 second
                page.wait_for_timeout(1000)

                # Click "CONFIRM"
                page.locator("//span[normalize-space()='CONFIRM']").click()

                # Wait for "OTP Verification"
                page.locator("//h4[normalize-space()='OTP Verification']").wait_for(state="visible", timeout=30000)

                # Wait until the Ref element is visible
                page.locator("//p[@class='ref ref-number-size mb-16px']").wait_for(state="visible", timeout=10000)

                # Get KTB Ref Code (Comfirm Transfer there)
                cls._ktb_web_ref_code = page.locator("//p[@class='ref ref-number-size mb-16px']").inner_text().strip()

                match = re.search(r"Ref\.?\s*([A-Za-z0-9]+)", cls._ktb_web_ref_code, re.IGNORECASE)
                if match:
                    cls._ktb_web_ref_code = match.group(1)
                    print(f"KTB Web Ref Code: {cls._ktb_web_ref_code}")

                # Call messages_OTP_4() function and Get OTP Code
                _messages_otp_code = cls.messages_OTP_4()
                
                # Fill OTP Code
                page.locator("//input[@id='otp-input-0']").fill(_messages_otp_code)

                # Delay 1 second
                page.wait_for_timeout(1000)

                # Button Click "Verify"
                page.locator("//span[normalize-space()='VERIFY']").click()

                # Print Withdrawal SuccessFul!!
                print(f"Withdrawal SuccessFul!!!")

                # Delay 10 second
                page.wait_for_timeout(10000)
            
            except Exception as error:
                print(f"An error occurred: {error}")
                time.sleep(111111)     

            time.sleep(111111)

    # Messages (SMS KTB Business OTP Code) 
    @classmethod
    def messages_OTP_4(cls):

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
        
        # Click ktb Chat
        # If not in inside ktb bank chat, click it, else passs
        if not poco("message_text").exists():
            poco(text="Krungthai").click()
        else:
            pass

        # Timer Setting
        start_time = time.time()
        timeout = 60  # seconds

        # Get all the messages text
        message_nodes = poco("message_list").offspring("message_text")
        # Calculate the current total messages
        initial_count = len(message_nodes)
        # The Last Message
        last_text = message_nodes[-1].get_text().strip() if message_nodes else ""
        print("Waiting for new message from ktb bank...")

        # Timer, timeout 60 seconds, wait for new OTP Message come in...
        while time.time() - start_time < timeout:
            message_nodes = poco("message_list").offspring("message_text")
            current_count = len(message_nodes)

            # Get Last Message
            current_last_text = message_nodes[-1].get_text().strip()

            # Detect new messages (if current count > inital count or current text != last test, that means got new message come in )
            if current_count > initial_count or current_last_text != last_text:
                print("✅ New message(s) detected!")

                # --- Collect OTP + Ref from all new messages ---
                otp_candidates = []
                for i, node in reversed(list(enumerate(message_nodes))):
                    messages = node.get_text().strip()
                    if not messages:
                        continue

                    match = re.search(
                        r"Your\s+OTP\s+is\s+(\d+).*?\(Ref\s+No\.?\s*([A-Za-z0-9]+)\)",
                        messages,
                        re.IGNORECASE,
                    )

                    if match:
                        _messages_otp_code, messages_ref_code = match.groups()
                        otp_candidates.append((_messages_otp_code.strip(), messages_ref_code.strip().upper()))
                        print(f"✅ OTP: {_messages_otp_code}, Ref: {messages_ref_code}")

                # --- Match correct Ref Code ---
                for _messages_otp_code, messages_ref_code in otp_candidates:
                    if cls._ktb_web_ref_code == messages_ref_code:
                        print(f"Found matching Ref: {messages_ref_code} | OTP: {_messages_otp_code} ✅")
                        return _messages_otp_code
                    
                # Saves the latest message count and text.
                # ✅ Prevents detecting the same OTP again on the next loop cycle.
                initial_count = current_count
                last_text = current_last_text

            time.sleep(2)

        print(f"⏰ Timeout - No OTP found for ref: {cls._ktb_web_ref_code}")
        return None


# Launch Chrome CDP
Automation.chrome_CDP()

# ----- Run Bank_Bot ------
# Bank_Bot.scb_Anywhere_web()
# Bank_Bot.kbank_web()
# Bank_Bot.ttb_businessOne_web()
Bank_Bot.kma_business_web()
# Bank_Bot.ktb_business_web() 
