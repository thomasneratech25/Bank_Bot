import os
import io
import sys
import json
import time
import random
import hashlib
import logging
import requests
import traceback
import subprocess
import numpy as np
from dotenv import load_dotenv
from threading import Lock, Thread
from flask import Flask, request, jsonify
from appium import webdriver
from appium.webdriver.common.appiumby import *
from appium.webdriver.common.appiumby import AppiumBy
from appium.options.android import UiAutomator2Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.support import expected_conditions as EC

# ================== Version Change ==========================

# 1.0.2
# - Fix cannot proceed to withdrawal 


# ================== Eric WS_Client Settings =================

WS_PROC = None

# ================== Appium Settings ========================

APPIUM_DRIVER = None
APPIUM_PROC = None
APPIUM_LOCK = Lock()

# =================== Flask apps ============================

app = Flask(__name__)
LOCK = Lock()

# Get Transaction ID
def get_txn_id(data):
    if isinstance(data, dict):
        return str(data.get("transactionId", "unknown"))
    return "unknown"

# ================== Logger Settings =========================

LOG_DIR = "./logs"
os.makedirs(LOG_DIR, exist_ok=True)

LOG_FILE = os.path.join(LOG_DIR, "KBank_Company_Apps_Payout.log")

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

logger = logging.getLogger("KBANK Company Apps")

# ================== Appium Driver ==================

# Android Appium
class Appium_Driver():

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

    # Inactivity Monitor / Timer
    @staticmethod
    def monitor_inactivity():
        while True:
            time.sleep(10)
            # Access via ClassName.VariableName
            with Appium_Driver.time_Lock:
                elapsed = time.time() - Appium_Driver.last_TxN_Time
            
            if elapsed > 174:
                # Access the global APPIUM_DRIVER variable
                global APPIUM_DRIVER
                if APPIUM_DRIVER:
                    try:
                        logger.info("⏳ 2.9 minutes of inactivity. Killing SCB app...")
                        APPIUM_DRIVER.terminate_app("com.kasikornbank.kbiz")
                    except Exception as e:
                        logger.error(f"Failed to kill app: {e}")
                
                with Appium_Driver.time_Lock:
                    Appium_Driver.last_TxN_Time = time.time()

# ================== Eric API ==================

# Eric
class Eric():

    # Eric API
    @classmethod
    def eric_api(cls, data):
        
        try:

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
            response.raise_for_status()

            # Debug info
            print("Raw string to hash:", string_to_hash)
            print("MD5 Hash:", hash_result)
            print("Response:", response.text)
            print("\n\n")

            logger.info("ERIC callback prepared. txn_id=%s bankCode=%s deviceId=%s merchantCode=%s", get_txn_id(data), payload["bankCode"], payload["deviceId"], payload["merchantCode"])
            logger.info("ERIC hash=%s txn_id=%s", hash_result, get_txn_id(data))
            logger.info("ERIC callback response received. txn_id=%s status=%s", get_txn_id(data), response.status_code,)
            logger.info("ERIC callback body. txn_id=%s body=%s", get_txn_id(data), response.text)

        except Exception as e:
            error_trace = traceback.format_exc()
            logging.error(f"ERIC API CALLBACK FAILED for Transaction {get_txn_id(data)}:\n{error_trace}")
            raise Exception(f"API Callback failed: {str(e)}")

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

# ================== Apps Automation  ==================

# Apps Automation
class BankBot(Appium_Driver, Eric):
    
    #  Kbank Company Login
    @classmethod
    def kbank_login(cls, data):

        # The system cannot processs this transaction
        def error_unable_process_this_transaction():
            try:
                # Wait up to 5 seconds for the "Close Application" button to appear.
                # We look directly for the button's accessibility id from your screenshot.
                close_button = WebDriverWait(driver, 0.5).until(
                    EC.element_to_be_clickable((AppiumBy.ACCESSIBILITY_ID, "Close Application"))
                )
                
                # IF it appears, this code will run:
                print("Error popup detected! Clicking 'Close Application'.")
                logger.info("Error popup detected! Clicking 'Close Application'.")
                close_button.click()
                    
            except TimeoutException:
                # IF the button does NOT appear within 5 seconds, it throws a TimeoutException.
                # The 'except' block catches it, meaning the transaction was successful!
                logger.info("No pop up ['error - Sorry Unable to proceed.' ], Proceeding normally...")
                pass

        # Enter Login Pin
        def enter_pin():

            # Wait for "Enter PIN" to appear
            WebDriverWait(driver, 10).until(EC.presence_of_element_located((AppiumBy.XPATH, "//android.view.View[@content-desc='Enter PIN']")))

            # Enter Pin
            pin = str(data["pin"])
            for digit in pin:
                digit_button = WebDriverWait(driver, 10).until(EC.element_to_be_clickable((AppiumBy.ACCESSIBILITY_ID, digit)))
                digit_button.click() 
                # "Sorry, Unable to proceed The system cannot proceed this transaction, please try again later.")
                error_unable_process_this_transaction()
            
            logger.info("Enter KBank Apps Pin... txn_id=%s")
            
        # Use Appium Driver
        driver = cls.use_appium_driver()

        # Forces the terminal to handle those sea creatures correctly
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
        logger.info("="*50)
        logger.info(f"🎰 Starting KBank Company Login Flow ....  {get_txn_id(data)}")
        logger.info("="*50)

        # ADB Shell Never Screen Timeout
        logger.info("ADB Shell Screen never Time Out ...")
        driver.execute_script("mobile: shell", {"command": "settings","args": ["put", "system", "screen_off_timeout", "2147483647"]})

        # Check Apps State
        # 1 = Not Running, 2 = Suspended, 3 = Background, 4 = Foreground
        state = driver.query_app_state("com.kasikornbank.kbiz")
        logger.info(f"Current App state: {state}")

        # Open Apps
        if state == 4:
            logger.info("App already in foreground. Proceeding...")
        else:
            # If state is 1, 2, or 3, we want a CLEAN launch to prevent crashes
            logger.info(f"App state is {state}. Performing a clean restart to prevent auto-crash.")
            
            # Force terminate first to clear any hung background sessions
            driver.terminate_app("com.kasikornbank.kbiz")
            time.sleep(1) 
            
            # Open Apps
            driver.activate_app("com.kasikornbank.kbiz")
            time.sleep(3) 
            
            # Check if Apps is Crash
            if driver.query_app_state("com.kasikornbank.kbiz") != 4:
                logger.error("App failed to reach foreground. Retrying once...")
                driver.activate_app("com.kasikornbank.kbiz")
        
        # If already on Main Page, Skip login
        try:
            WebDriverWait(driver, 3).until(EC.element_to_be_clickable((AppiumBy.ACCESSIBILITY_ID, "Loans")))
            logger.info("Already login, Skipped!")
            return  # Already Login
        except:
            pass
        
        # Wait and Button Click "Login"
        logger.info("Click Login")
        WebDriverWait(driver, 30).until(EC.element_to_be_clickable((AppiumBy.ACCESSIBILITY_ID, "Log in"))).click()

        # Enter PIN
        enter_pin()

    # Kbank Company Withdrawal
    @classmethod
    def kbank_withdrawal(cls, data):

        def human_type(driver, element, text, min_delay=0.2, max_delay=0.25):
            """
            Taps an element to open the Android keyboard, then uses W3C Action Chains 
            to type the given text character by character with random delays.
            """
            # Tap the field to pop up the Android keyboard
            element.click()

            time.sleep(0.5)

            # Queue up the keystrokes and random pauses
            for char in text:
                actions = ActionChains(driver)
                actions.send_keys(char)
                actions.perform()

                time.sleep(random.uniform(min_delay, max_delay))

        # Forces the terminal to handle those sea creatures correctly
        logger.info("="*50)
        logger.info(f"🎰 Starting KBANK Company Withdrawal Flow .... {get_txn_id(data)}")
        logger.info("="*50)

        # Use Appium Driver
        driver = cls.use_appium_driver()

        # Random Click History and Approval
        logger.info("Random Click 'History' or 'Approval' ")
        WebDriverWait(driver, 20).until(EC.element_to_be_clickable((AppiumBy.XPATH, random.choice(['//android.widget.ImageView[contains(@content-desc,"Tab 4 of 5")]', '//android.widget.ImageView[contains(@content-desc,"Tab 2 of 5")]'])))).click()

        time.sleep(2)
        
        # Wait and Button Click "Banking"
        logger.info("Click Banking (QR Code)")
        WebDriverWait(driver, 30).until(EC.element_to_be_clickable((AppiumBy.XPATH, '//android.widget.Button[contains(@content-desc,"Banking")]'))).click()

        # Wait and Button Click "Transfer"
        logger.info("Click Transfer")
        WebDriverWait(driver, 30).until(EC.element_to_be_clickable((AppiumBy.ACCESSIBILITY_ID, "Transfer"))).click()
        
        # Wait "From"
        logger.info("Wait 'From' ...")
        WebDriverWait(driver,20).until(EC.visibility_of_element_located((AppiumBy.ANDROID_UIAUTOMATOR,'new UiSelector().text("From")')))

        time.sleep(1)

        # Select Bank (Drop Down Menu)
        logger.info("Select Bank (Drop Down Menu)")
        WebDriverWait(driver, 30).until(EC.presence_of_element_located((AppiumBy.ANDROID_UIAUTOMATOR, 'new UiSelector().className("android.widget.Spinner").textContains("Kasikornbank")'))).click()

        time.sleep(1)
        
        # Fill Bank Name
        bank_input_element = driver.find_elements(AppiumBy.CLASS_NAME, "android.widget.EditText")[-1]
        # Human Type
        human_type(driver, bank_input_element, data["toBankCode"])

        time.sleep(1)

        # Press Enter
        logger.info("Press Enter ")
        driver.press_keycode(66)

        # Fill Account Number
        logger.info(f"Fill Account Number {str(data['toAccountNum'])} ...")
        account_input = WebDriverWait(driver, 20).until(EC.element_to_be_clickable((AppiumBy.ANDROID_UIAUTOMATOR, 'new UiSelector().className("android.widget.EditText").instance(0)')))
        # Human Type
        human_type(driver, account_input, str(data["toAccountNum"]))

        # Press Enter
        logger.info("Press Enter ")
        driver.press_keycode(66)
        
        # Fill Amount
        logger.info(f"Fill Amount {str(data['amount'])} ...")
        amount_input = WebDriverWait(driver, 20).until(EC.element_to_be_clickable((AppiumBy.ANDROID_UIAUTOMATOR, 'new UiSelector().className("android.widget.EditText").instance(1)')))  
        # Human Type
        human_type(driver, amount_input, str(data["amount"]))

        # Press Enter 
        if driver.is_keyboard_shown():
            driver.hide_keyboard()

        # Scroll Down
        logger.info("Scroll Down ")
        driver.find_element(AppiumBy.ANDROID_UIAUTOMATOR,'new UiScrollable(new UiSelector().scrollable(true)).scrollForward()')
        
        # Click Next
        logger.info("Click Next ")
        WebDriverWait(driver,20).until(EC.element_to_be_clickable((AppiumBy.ACCESSIBILITY_ID,"Next"))).click()

        # Wait for Confirm Transaction Title
        logger.info("Wait for 'Confirm Transaction' ")
        WebDriverWait(driver, 15).until(EC.presence_of_element_located((AppiumBy.XPATH, "//*[contains(@text,'Confirm Transaction')]")))

        # Scroll Down
        logger.info("Scroll Down ")
        driver.find_element(AppiumBy.ANDROID_UIAUTOMATOR,'new UiScrollable(new UiSelector().scrollable(true)).scrollForward()')

        # Wait and Button Click "Confirm"
        logger.info("Click Confirm ")
        driver.find_element(AppiumBy.ANDROID_UIAUTOMATOR, 'new UiSelector().textContains("Confirm")').click()
        driver.find_element(AppiumBy.ANDROID_UIAUTOMATOR, 'new UiSelector().text("Confirm")').click()

        # Wait "Do you confirm to perform this transaction?"
        WebDriverWait(driver, 10).until(EC.presence_of_element_located((AppiumBy.ACCESSIBILITY_ID, "Do you confirm to perform this transaction?")))

        time.sleep(1)

        # Wait and Button Click "Confirm"
        logger.info("Click Confirm again ")
        WebDriverWait(driver,20).until(EC.element_to_be_clickable((AppiumBy.ACCESSIBILITY_ID,"Confirm"))).click()

        # Call Eric API
        cls.eric_api(data)

        # Wait and Button Click "Back to main page"
        logger.info("Click Back to Main Page ")
        WebDriverWait(driver,20).until(EC.element_to_be_clickable((AppiumBy.ACCESSIBILITY_ID,"Back to main page"))).click()

# ================== Code Start Here ==================

# Run API
@app.route("/kbank_company/runPython", methods=["POST"])
def runPython():

    # Count Inactivity Transaction Timer
    with Appium_Driver.time_Lock:
        Appium_Driver.last_TxN_Time = time.time()

    # Flask reads the JSON body sent by the client
    data = request.get_json(silent=True)

    with LOCK:
        try:
            # Perform Login
            BankBot.kbank_login(data)

            # Perform Withdrawal
            BankBot.kbank_withdrawal(data)

            time.sleep(120)

            # Return Successful, if withdrawal Successful
            return jsonify({"success": True,"transactionId": data.get("transactionId")})
        except Exception as e:
            
            # Return Error + Failed, if something went wrong
            full_trace = traceback.format_exc()
            print(f"\n--- CRITICAL TRANSACTION ERROR ---\n{full_trace}")
            logging.error(f"CRITICAL ERROR for Transaction {data.get('transactionId', 'unknown')}:\n"f"{full_trace}\n{'-'*40}")
            return jsonify({"success": False,"message": str(e),"error_type": type(e).__name__}), 500
        
if __name__ == "__main__":

    # Start the inactivity monitor as a daemon thread (so it exits when the main script stops)
    inactivity_thread = Thread(target=Appium_Driver.monitor_inactivity, daemon=True)
    inactivity_thread.start()

    Eric.start_ws_client()
    app.run(host="0.0.0.0", port=5104, debug=False, threaded=False, use_reloader=False)
