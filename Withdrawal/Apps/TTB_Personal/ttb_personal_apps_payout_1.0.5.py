import os
import io
import sys
import json
import time
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
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# =================== Version Change =========================

# - 1.0.3
# - Fix Doesnt go back to transfer page
# - Added skip login, if already in transfer page

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

LOG_FILE = os.path.join(LOG_DIR, "TTBTouch_Apps_Payout.log")

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

logger = logging.getLogger("TTB Touch Apps")

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
            
            if elapsed > 180:
                # Access the global APPIUM_DRIVER variable
                global APPIUM_DRIVER
                if APPIUM_DRIVER:
                    try:
                        logger.info("⏳ 3 minutes of inactivity. Killing TTB app...")
                        APPIUM_DRIVER.terminate_app("com.TMBTOUCH.PRODUCTION")
                    except Exception as e:
                        logger.error(f"Failed to kill app: {e}")
                
                with Appium_Driver.time_Lock:
                    Appium_Driver.last_TxN_Time = time.time()

# ================== Eric Settings ==================

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

            response = requests.post(url, headers=headers, data=payload_json, timeout=300)
            response.raise_for_status()

            # Debug info
            logger.info(
                "ERIC callback success. txn_id=%s bankCode=%s deviceId=%s merchantCode=%s status=%s",
                get_txn_id(data),
                payload["bankCode"],
                payload["deviceId"],
                payload["merchantCode"],
                response.status_code,
            )
            logger.info("ERIC callback body. txn_id=%s body=%s", get_txn_id(data), response.text)

        except Exception as e:
            error_trace = traceback.format_exc()
            logger.error("ERIC API CALLBACK FAILED for Transaction %s:\n%s", get_txn_id(data), error_trace)
            raise RuntimeError(f"API Callback failed: {e}") from e

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
    
    # TTB Touch Login
    @classmethod
    def ttbTouch_login(cls, data):

        # Use Appium Driver
        driver = cls.use_appium_driver()

        # Forces the terminal to handle those sea creatures correctly
        logger.info("="*50)
        logger.info("🎰 Starting TTB Touch Login Flow ....")
        logger.info("="*50)

        # ADB Shell Never Screen Timeout
        logger.info("ADB Shell Screen never Time Out ...")
        driver.execute_script("mobile: shell", {"command": "settings","args": ["put", "system", "screen_off_timeout", "2147483647"]})

        # If already on Transfer, skip login
        try:
            WebDriverWait(driver, 3).until(EC.presence_of_element_located((AppiumBy.ID, "com.TMBTOUCH.PRODUCTION:id/centerTitle")))
            logger.info("Already on Transfer page, Skip login...")

            # Withdrawal Process
            cls.ttbTouch_withdrawal(data)
            return

        except Exception:
            logger.info("Not in Transfer page, Continue ...")
            pass

        # Launch TTB Touch Apps
        logger.info("Launch TTB Touch Apps ...")
        driver.activate_app("com.TMBTOUCH.PRODUCTION")     

        # Click Transfer
        logger.info('Click Transfer ...')   
        WebDriverWait(driver, 20).until(EC.element_to_be_clickable((By.XPATH, "//android.widget.TextView[@text='Transfer']"))).click()

        # Wait for Enter Pin
        logger.info("Waiting for Enter Pin ...")
        WebDriverWait(driver, 20).until(EC.presence_of_element_located((By.ID, "com.TMBTOUCH.PRODUCTION:id/title_pin")))
        
        # Click Passcode Number
        logger.info('Key Login Passcode ...')
        pin = str(data["pin"])
        for digit in pin:
            driver.find_element(By.ID, f"com.TMBTOUCH.PRODUCTION:id/key_0{digit}").click()
        logger.info("Successfully Login ...")

        # TTBTouch Withdrawal
        cls.ttbTouch_withdrawal(data)
        
    # TTB Touch Withdrawal
    @classmethod
    def ttbTouch_withdrawal(cls, data):

        # Forces the terminal to handle those sea creatures correctly
        logger.info("="*50)
        logger.info("🎰 Starting TTB Touch Withdrawal Flow ....")
        logger.info("="*50)

        # Use Appium Driver
        driver = cls.use_appium_driver()
        
        # Wait and Button Click "Other Accounts"
        logger.info("Click 'Other Accounts' ...")
        WebDriverWait(driver, 20).until(EC.element_to_be_clickable((By.XPATH, '//*[@resource-id="com.TMBTOUCH.PRODUCTION:id/menu_name" and @text="Other Accounts"]'))).click()

        # Select Bank Name (Drop Down Menu)
        logger.info("Click Select Bank ... (Drop Down Menu)")
        WebDriverWait(driver, 20).until(EC.element_to_be_clickable((By.ID, "com.TMBTOUCH.PRODUCTION:id/to_account_layout"))).click()

        # Wait for Select Bank MENU
        logger.info("Wait for Select Bank Menu ...")
        WebDriverWait(driver, 20).until(EC.presence_of_element_located((By.ID, "com.TMBTOUCH.PRODUCTION:id/title_text")))

        # Select Bank
        logger.info("Select Bank ....")
        driver.find_element(AppiumBy.ANDROID_UIAUTOMATOR, f'new UiScrollable(new UiSelector().scrollable(true)).scrollIntoView(new UiSelector().text("{str(data["toBankCode"])}"))').click()

        # Wait and Fill Account Number
        logger.info("Fill Account No ...")
        WebDriverWait(driver, 20).until(EC.presence_of_element_located((By.ID, "com.TMBTOUCH.PRODUCTION:id/edt_account_no"))).send_keys(str(data["toAccountNum"]))
        
        # Wait and Fill Amount
        logger.info("Fill Amount ...")
        WebDriverWait(driver, 20).until(EC.element_to_be_clickable((AppiumBy.ID, "com.TMBTOUCH.PRODUCTION:id/edt_amount"))).click()
        WebDriverWait(driver, 20).until(EC.element_to_be_clickable((By.ID, "com.TMBTOUCH.PRODUCTION:id/edt_amount"))).send_keys(str(data["amount"]))
        driver.hide_keyboard()
        
        # Scroll Down 
        logger.info("Scroll Down ...")
        driver.find_element(AppiumBy.ANDROID_UIAUTOMATOR,'new UiScrollable(new UiSelector().scrollable(true)).scrollForward()')

        # Button Click Next
        logger.info("Click Next ...")
        WebDriverWait(driver, 20).until(EC.element_to_be_clickable((By.ID, "com.TMBTOUCH.PRODUCTION:id/btn_next"))).click()
        
        # Button Click Confirm
        logger.info("Click Confirm Transaction ...")
        WebDriverWait(driver, 20).until(EC.element_to_be_clickable((By.ID, "com.TMBTOUCH.PRODUCTION:id/btn_confirm"))).click()

        # Wait for Enter Pin
        logger.info("Waiting for Enter Pin ...")
        WebDriverWait(driver, 20).until(EC.presence_of_element_located((By.ID, "com.TMBTOUCH.PRODUCTION:id/title_pin")))
        
        # Click Passcode Number
        logger.info('Key Login Passcode ...')
        pin = str(data["pin"])
        for digit in pin:
            driver.find_element(By.ID, f"com.TMBTOUCH.PRODUCTION:id/pin_key_{digit}").click()

        time.sleep(2)

        # Call Back Eric API
        cls.eric_api(data)

        # Scroll to bottom
        logger.info("Scroll to bottom")
        driver.find_element(AppiumBy.ANDROID_UIAUTOMATOR, 'new UiScrollable(new UiSelector().scrollable(true)).scrollToEnd(10)')

        # Click Transfer More
        logger.info("Click 'Transfer More'")
        WebDriverWait(driver, 20).until(EC.element_to_be_clickable((AppiumBy.ID, "com.TMBTOUCH.PRODUCTION:id/buttonTransferMore"))).click()

        logger.info("Withdrawal Completed ")
        
# ================== Code Start Here ==================

# Run API
@app.route("/ttb_personal/runPython", methods=["POST"])
def runPython():

    # Count Inactivity Transaction Timer
    with Appium_Driver.time_Lock:
        Appium_Driver.last_TxN_Time = time.time()

    # Flask reads the JSON body sent by the client
    data = request.get_json(silent=True)

    with LOCK:
        try:
            # Perform Withdrawal
            BankBot.ttbTouch_login(data)

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
    app.run(host="0.0.0.0", port=5100, debug=False, threaded=False, use_reloader=False)
