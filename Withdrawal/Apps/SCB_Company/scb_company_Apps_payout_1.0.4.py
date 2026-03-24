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
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# ================== Version Change =========================

# - 1.0.4
# Fix cannot click services

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

LOG_FILE = os.path.join(LOG_DIR, "SCBAnywhere_Apps_Payout.log")

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

logger = logging.getLogger("SCB Company Apps")

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
                        APPIUM_DRIVER.terminate_app("com.scb.corporate")
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
    
    # SCB Anywhere Login
    @classmethod
    def scbAnywhere_login(cls, data):

        # Use Appium Driver
        driver = cls.use_appium_driver()

        # Forces the terminal to handle those sea creatures correctly
        # sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
        logger.info("="*50)
        logger.info(f"🎰 Starting SCB Company Login Flow .... {get_txn_id(data)}")
        logger.info("="*50)
        
        # If already on Quick Transfer, skip login
        try:
            WebDriverWait(driver, 1).until(EC.presence_of_element_located((AppiumBy.ACCESSIBILITY_ID, "PromptPay")))
            logger.info("Already on Transfer page, Skip login...")

            # Withdrawal Process
            cls.scbAnywhere_withdrawal(data)
            return

        except Exception:
            logger.info("Not in Quick Transfer page, Continue ...")
            pass

        # ADB Shell Never Screen Timeout
        logger.info("ADB Shell Screen never Time Out ...")
        driver.execute_script("mobile: shell", {"command": "settings","args": ["put", "system", "screen_off_timeout", "2147483647"]})
 
        # bypass scbanyware detect using usb debugging
        driver.execute_script('mobile: shell', {'command': 'settings', 'args': ['put', 'global', 'adb_enabled', '12']})
        logger.info("Bypass USB Debugging...")

        # Check Apps State
        # 1 = Not Running, 2 = Suspended, 3 = Background, 4 = Foreground
        state = driver.query_app_state("com.scb.corporate")
        logger.info(f"Current App state: {state}")

        # Open Apps
        if state == 4:
            logger.info("App already in foreground. Proceeding...")
        else:
            # If state is 1, 2, or 3, we want a CLEAN launch to prevent crashes
            logger.info(f"App state is {state}. Performing a clean restart to prevent auto-crash.")
            
            # Force terminate first to clear any hung background sessions
            driver.terminate_app("com.scb.corporate")
            time.sleep(1) 
            
            # Open Apps
            driver.activate_app("com.scb.corporate")
            time.sleep(3) 
            
            # Check if Apps is Crash
            if driver.query_app_state("com.scb.corporate") != 4:
                logger.error("App failed to reach foreground. Retrying once...")
                driver.activate_app("com.scb.corporate")

        # Inactive Too Long
        try:
            # wait for text "You have been inactive too long"
            WebDriverWait(driver, 1).until(EC.presence_of_element_located((AppiumBy.XPATH, "//*[contains(@text, 'You have been inactive for too long')]")))
            
            # Find "Continue" button and click continue
            driver.find_element(AppiumBy.XPATH, "//*[contains(@text, 'Continue')]").click()
            logger.info("You have been inactive too long, Click Continue...")
        except:
            pass

        # Session Timeout
        try:
            # wait for text "Session Timeout"
            WebDriverWait(driver, 1).until(EC.presence_of_element_located((AppiumBy.XPATH, "//*[contains(@text, 'Session timeout')]")))
            logger.info("Session Timeout, Click Continue / Log in...")

            # Find "Continue" / "Log in" button and click continue
            try:
                driver.find_element(AppiumBy.XPATH, "//*[contains(@text, 'Continue')]").click()
                logger.info("Click Continue ....")
            except:
                driver.find_element(AppiumBy.XPATH, "//*[contains(@text, 'Log in')]").click()
                logger.info("Click Log in ....")
        except:
            logger.info("No Session Timeout, Skip ...")
            pass

        # Enter Pin / Pending edit (0)
        while True:
            try: 
                # Wait for "Enter PIN" to appear
                WebDriverWait(driver, 1).until(EC.visibility_of_element_located((AppiumBy.XPATH, "//*[@text='Enter PIN']")))
                logger.info("Enter PIN Appear...")
                logger.info("Start Enter PIN...")
            
                # Enter Pin
                pin = str(data["pin"])
                print(pin)
                for digit in pin:
                    digit_button = WebDriverWait(driver, 10).until(EC.element_to_be_clickable((AppiumBy.XPATH, f"//android.widget.TextView[@text='{digit}']")))
                    digit_button.click()
                break
            except:
                try:
                    # Wait for "Pending edit (0)" to appear
                    WebDriverWait(driver, 1).until(EC.visibility_of_element_located((AppiumBy.XPATH, "//*[@text='Pending edit (0)']")))
                    logger.info("Wait for Pending edit (0) appear ...")
                    break
                except:
                    pass

        time.sleep(4)
        
        # Wait for Pending Edit (0) 
        logger.info("Wait for Pending Edit (0) ...")
        WebDriverWait(driver, 20).until(EC.presence_of_element_located((AppiumBy.ANDROID_UIAUTOMATOR, 'new UiSelector().textContains("Pending edit")')))

        # Wait and Button click "Services"
        logger.info("Click 'Services' ...")
        WebDriverWait(driver, 30).until(EC.element_to_be_clickable((AppiumBy.ACCESSIBILITY_ID, "Services"))).click()

        # Wait for "Manage your transactions"
        logger.info("Wait for 'Manage your transaction appear' ...")
        WebDriverWait(driver, 20).until(EC.visibility_of_element_located((AppiumBy.XPATH, '//android.widget.TextView[@text="Manage your transactions"]')))
        time.sleep(1)

        # Wait and Button click "Quick Transfer"
        logger.info("Button click 'Quick Transfer' ...")
        WebDriverWait(driver, 20).until(EC.element_to_be_clickable((AppiumBy.ACCESSIBILITY_ID, "Quick Transfer"))).click()

        # Proceed to withdrawal
        cls.scbAnywhere_withdrawal(data)

    # SCB Anywhere Withdrawal
    @classmethod
    def scbAnywhere_withdrawal(cls, data):

        # Forces the terminal to handle those sea creatures correctly
        logger.info("="*50)
        logger.info(f"🎰 Starting SCB Company Withdrawal Flow .... {get_txn_id(data)}")
        logger.info("="*50)

        # Use Appium Driver
        driver = cls.use_appium_driver()

        # Wait for "Account No."
        logger.info("Wait for 'PromptPay' ...")
        WebDriverWait(driver, 20).until(EC.presence_of_element_located((AppiumBy.ACCESSIBILITY_ID, "PromptPay")))
        time.sleep(1)

        # Select Bank (If not found, scroll down until it found)
        logger.info(f"Select Bank ... {data.get('toBankCode')}")
        driver.find_element(AppiumBy.ANDROID_UIAUTOMATOR,f'new UiScrollable(new UiSelector().scrollable(true)).scrollIntoView(new UiSelector().text("{data.get("toBankCode")}"))')
        WebDriverWait(driver, 10).until(EC.element_to_be_clickable((AppiumBy.XPATH, f'//android.widget.TextView[@text="{data.get("toBankCode")}"]/..'))).click()
        
        # Wait for Recipient Details
        WebDriverWait(driver, 20).until(EC.presence_of_element_located((AppiumBy.XPATH, '//android.widget.TextView[@text="Recipient details"]')))
        logger.info("Wait for 'Recipient Details' appear ...")
        time.sleep(1)

        # Fill Account No
        logger.info('Fill Account No ...')
        WebDriverWait(driver, 20).until(EC.element_to_be_clickable((AppiumBy.XPATH, '//android.widget.EditText[@resource-id="tfAccountNo"]'))).send_keys(str(data["toAccountNum"]))

        # Fill Amount
        logger.info('Fill Amount ...')
        WebDriverWait(driver, 20).until(EC.element_to_be_clickable((AppiumBy.XPATH, '//android.widget.EditText[@resource-id="transactionAmount"]'))).send_keys(str(data["amount"]))

        # Wait and Button Click "Next"
        logger.info('Click Next ...')
        WebDriverWait(driver, 20).until(EC.element_to_be_clickable((AppiumBy.ACCESSIBILITY_ID, "Next"))).click()

        # Wait for Review Information 
        logger.info('Wait for Review Information ...')
        WebDriverWait(driver, 20).until(EC.presence_of_element_located((AppiumBy.XPATH, '//android.widget.TextView[@text="Review information"]')))
        time.sleep(1)

        # Wait and Button Click "Submit"
        logger.info('Click Submit ...')
        WebDriverWait(driver, 20).until(EC.element_to_be_clickable((AppiumBy.ACCESSIBILITY_ID, "Submit"))).click()

        # Wait for SCB Digital Token Pin
        logger.info("Wait For 'SCB Digital Token Pin' appear ...")
        WebDriverWait(driver, 300).until(EC.visibility_of_element_located((AppiumBy.XPATH, "//*[@text='Enter the 8-digit\nSCB Digital Token PIN']")))
        logger.info("Key in SCB Digital Token PIN...")
        time.sleep(1)

        token_pin = str(data["scbDigitalTokenPin"])
        for digit in token_pin:
            digit_button = WebDriverWait(driver, 10).until(EC.element_to_be_clickable((AppiumBy.XPATH, f"//android.widget.TextView[@text='{digit}']")))
            digit_button.click()

        # Call Back Eric API
        cls.eric_api(data)

        # Click "Share payment slip"
        logger.info("Wait for 'Share payment slip' ...")
        WebDriverWait(driver, 30).until(EC.presence_of_element_located((AppiumBy.ACCESSIBILITY_ID, "Share payment slip")))
        
        time.sleep(1)

        # Click Back
        while True:
            try:
                logger.info("Click Back ...")
                WebDriverWait(driver,2).until(EC.element_to_be_clickable((AppiumBy.ACCESSIBILITY_ID,"Back"))).click()
                break
            except:
                pass

        time.sleep(1)

        # Wait for Success
        logger.info("Wait for Success ...")
        WebDriverWait(driver, 30).until(EC.presence_of_element_located((AppiumBy.XPATH, '//android.widget.TextView[@text="Success"]')))

        time.sleep(1)

        # Button Click "Make another transfer"
        logger.info("Withdrawal Completed Make Another Transfer ...")
        WebDriverWait(driver, 30).until(EC.element_to_be_clickable((AppiumBy.ACCESSIBILITY_ID, "Make another transfer"))).click()

# ================== Code Start Here ==================

# Run API
@app.route("/scb_company/runPython", methods=["POST"])
def runPython():

    # Count Inactivity Transaction Timer
    with Appium_Driver.time_Lock:
        Appium_Driver.last_TxN_Time = time.time()

    # Flask reads the JSON body sent by the client
    data = request.get_json(silent=True)

    with LOCK:
        try:
            # Perform Withdrawal
            BankBot.scbAnywhere_login(data)

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
    app.run(host="0.0.0.0", port=5101, debug=False, threaded=False, use_reloader=False)

