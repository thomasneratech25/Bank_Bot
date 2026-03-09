import os
import sys
import json
import time
import queue
import atexit
import random
import hashlib
import logging
import requests
import traceback
import threading
import subprocess
from threading import Lock
from dotenv import load_dotenv
from flask import Flask, request, jsonify
from playwright.sync_api import sync_playwright, expect
from appium import webdriver
from appium.webdriver.common.appiumby import *
from appium.webdriver.common.appiumby import AppiumBy
from appium.options.android import UiAutomator2Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# =========================== Eric WS_Client Settings =================

WS_PROC = None

# =========================== Logging Settings =========================

LOG_DIR = "./logs"
os.makedirs(LOG_DIR, exist_ok=True)

LOG_FILE = os.path.join(LOG_DIR, "SCB_Payout.log")

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

logger = logging.getLogger("SCB_WEB")
logger.info("Logging started: %s", LOG_FILE)

def get_txn_id(data):
    if isinstance(data, dict):
        return str(data.get("transactionId", "unknown"))
    return "unknown"


# =========================== Appium Settings =========================

APPIUM_DRIVER = None
APPIUM_PROC = None
APPIUM_LOCK = Lock()

# =========================== Flask apps ==============================

app = Flask(__name__)
LOCK = Lock()

def get_txn_id(data):
    if isinstance(data, dict):
        return str(data.get("transactionId", "unknown"))
    return "unknown"

# IDLE 
IDLE_SECONDS = 174 # 2.9 minutes
SCB_APP_PACKAGE = "com.scb.corporate"

# ================== PLAYWRIGHT WORKER ===========================

WORKER = None
WORKER_LOCK = Lock()

class PlaywrightWorker:

    def __init__(self, idle_seconds):
        self.idle_seconds = idle_seconds
        self.queue = queue.Queue()
        self.thread = threading.Thread(
            target=self._run,
            name="playwright-worker",
            daemon=True,
        )
        self.last_activity = None
        self.idle_logged_out = False

    def start(self):
        self.thread.start()

    def submit(self, func, *args, **kwargs):
        done = threading.Event()
        result = {"value": None, "error": None}
        self.queue.put((func, args, kwargs, done, result))
        done.wait()
        if result["error"] is not None:
            raise result["error"]
        return result["value"]

    def _run(self):
        while True:
            if self.idle_logged_out:
                timeout = None
            elif self.last_activity is None:
                timeout = None
            else:
                elapsed = time.time() - self.last_activity
                remaining = self.idle_seconds - elapsed
                if remaining <= 0:
                    self._idle_logout()
                    self.last_activity = None
                    self.idle_logged_out = True
                    continue
                timeout = remaining

            try:
                item = self.queue.get(timeout=timeout)
            except queue.Empty:
                self._idle_logout()
                self.last_activity = time.time()
                continue

            if item is None:
                break

            func, args, kwargs, done, result = item
            try:
                result["value"] = func(*args, **kwargs)
            except Exception as exc:
                result["error"] = exc
            finally:
                self.last_activity = time.time()
                self.idle_logged_out = False

                logging.info("Transaction finished. Idle timer started (%ss)", self.idle_seconds)

                done.set()

    @staticmethod
    def _idle_logout():
        global PAGE, APPIUM_DRIVER
        try:

            # NO LOCK HERE
            BankBot.scb_kill_apps(APPIUM_DRIVER)

            if PAGE and not PAGE.is_closed():
                BankBot.scb_logout(PAGE)
        except Exception as e:
            error_trace = traceback.format_exc()
            logging.error(f"Idle cleanup failed:\n{error_trace}")
    
    def get_worker():
        global WORKER
        if WORKER is None:
            with WORKER_LOCK:
                if WORKER is None:
                    WORKER = PlaywrightWorker(IDLE_SECONDS)
                    WORKER.start()
        return WORKER

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
                logging.info("Closing Chrome CDP")
                cls.chrome_proc.terminate()
        except Exception as e:
            error_trace = traceback.format_exc()
            logging.error(f"Chrome cleanup error:\n{error_trace}")

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

        logger.info(f"WS client started with PID {WS_PROC.pid}")

    # Login
    @classmethod
    def scb_login(cls, data):

        # Get Transaction ID
        txn_id = get_txn_id(data)
        logger.info("Starting SCB login flow. txn_id=%s", txn_id)

        try:

            global PLAYWRIGHT, BROWSER, CONTEXT, PAGE

            # Start Chrome
            cls.chrome_cdp()

            # Start Playwright ONLY ONCE
            if PLAYWRIGHT is None:
                logger.info("Starting Playwright instance. ")
                PLAYWRIGHT = sync_playwright().start()
            else:
                logger.info("Reusing Playwright instance. txn_id=%s", txn_id)

            # Connect to running Chrome ONLY ONCE
            if BROWSER is None:
                BROWSER = PLAYWRIGHT.chromium.connect_over_cdp("http://localhost:9222")

            # Reuse context
            CONTEXT = BROWSER.contexts[0] if BROWSER.contexts else BROWSER.new_context()
            logger.info("Browser context ready. ")

            # Reuse page
            if PAGE is None or PAGE.is_closed():
                PAGE = CONTEXT.new_page()
                PAGE.bring_to_front()
            else:
                logger.info("Reusing existing browser page. ")

            page = PAGE

            # If already on transfer page, skip login
            try:
                page.locator("//span[normalize-space()='Add New Recipient']").wait_for(timeout=1000)
                logger.info("Already on Transfer page, Skip login...")
                return page # Already Login
            except Exception:
                pass

            # Go to SCB Business Website to login
            page.goto("https://www.scbbusinessanywhere.com/", wait_until="networkidle")
            logger.info("Navigating to SCB_Businesss login page. ")

            # Wait for Username appear
            expect(page.locator("//input[@name='username']")).to_be_visible(timeout=0)
            logger.info("Wait for Username appear. ")

            # For your online security, you have been logged out of SCB Business Anywhere (please log in again.)
            try:
                expect(page.get_by_text("For your online security, you have been logged out of SCB Business Anywhere")).to_be_visible(timeout=1500)
                page.locator("//span[normalize-space()='OK']").click(timeout=1000) 
                logger.info("For your online security, you have been logged out of SCB Business Anywhere, Button Click OK! ")
            except:
                pass

            # Update your Operating System 
            try:
                expect(page.locator("//span[contains(text(),'Enter Site/เข้าสู่เว็บไซต์')]")).to_be_visible(timeout=1500)
                page.locator("//span[contains(text(),'Enter Site/เข้าสู่เว็บไซต์')]").click(timeout=1500)
                logger.info("Update SCB Apps Notes, Click Enter Site to continue... ")
            except:
                pass
            
            # if Account already login, can skip
            try: 
                # Fill "Username"
                page.locator("//input[@name='username']").fill(str(data["username"]), timeout=1000)
                logger.info("Fill Account Username.. ")

                # Button Click "Next"
                try:
                    # English
                    page.locator("//span[normalize-space()='Next']").click(timeout=1000) 
                except:
                    # Thai
                    page.locator("//span[contains(text(),'ถัดไป')]").click(timeout=1000)
                logger.info("Click Next...")

                # Fill "Password"
                page.locator("//input[@name='password']").fill(str(data["password"]), timeout=0)
                logger.info("Fill Account Password...")

                # Button Click "Next"
                try:
                    # English
                    page.locator("//button[@type='submit']").click(timeout=1000) 
                except:
                    # Thai
                    page.locator("//span[contains(text(),'ถัดไป')]").click(timeout=1000)
                logger.info("Click Next...")
            except:
                pass
            
            # only click Transfers if NOT on login page
            if not page.locator("//input[@name='username']").is_visible():
                # Button Click "Transfer"
                page.locator("//p[normalize-space()='Transfers']").click(timeout=0)
                logger.info("Click to Transfer Page...")

            return page
        
        except Exception as e:

            error_trace = traceback.format_exc()
            
            # This prints to the terminal
            print(f"\n[!] LOGIN EXCEPTION:\n{error_trace}")
            
            # THIS WRITES TO THE LOG FILE
            logging.error(f"LOGIN FAILED for Transaction {data.get('transactionId', 'unknown')}:\n{error_trace}")
            
            raise Exception(f"Login failed at step: {str(e)}")

    # Withdrawal
    @classmethod
    def scb_withdrawal(cls, page, data):

        # Get Transaction ID
        txn_id = get_txn_id(data)
        logger.info("Starting SCB Withdrawal flow.")

        try:

            # Button Click "Add New Recipient"
            page.locator("//span[normalize-space()='Add New Recipient']").click(timeout=10000) 
            logger.info("Click Add New Recipient...")
            
            # Fill Bank Name and Click
            page.get_by_label("Bank Name *").fill(str(data["toBankCode"]), timeout=0)
            page.keyboard.press("ArrowDown")
            page.keyboard.press("Enter")
            logger.info("Fill and Select Bank Name/Code %s", data.get("toBankCode"))

            # Fill Account No.
            page.locator("//input[@id='accountNumber']").fill(str(data["toAccountNum"]), timeout=0)
            logger.info("Fill in Account Number %s", data.get("toAccountNum"))

            # Button Click "Next"
            page.locator("//span[normalize-space()='Next']").click(timeout=0) 
            logger.info("Button Click Next ...")

            # Wait for "Recipient Details"
            page.locator("//h4[normalize-space()='Recipient Details']").wait_for(timeout=0) 
            logger.info("Waiting for Recipient Details Appear ...")
            
            # Fill Account Name
            try:
                page.locator("//input[@name='accountName']").fill(str(data["toAccountName"]), timeout=2000)
                logger.info("Fill in Account Name %s", data.get("toAccountName"))
            except:
                pass

            # Button Click "Confirm"
            page.locator("//span[normalize-space()='Confirm']").click(timeout=0) 
            logger.info("Click Confirm ...")

            # Button Click "Enter"
            page.locator("//span[normalize-space()='Enter']").click(timeout=0) 
            logger.info("Click Next ...")

            # Fill Amount
            page.locator("//input[@name='amount']").fill(str(data["amount"]), timeout=0)
            logger.info("Fill in Amount ...")

            # Press Enter
            page.keyboard.press("Enter")
            logger.info("Press Enter ... ")

            # Button Click "Continue to Transfer Services"
            page.locator("//span[normalize-space()='Continue to Transfer Services']").click(timeout=0) 
            logger.info("Continue to Transfer ...")

            # if insufficient pop up appear, break
            try:
                page.wait_for_selector("//h2[normalize-space()='Insufficient funds in the selected account.']", timeout=1500)
                
                # Print to console for immediate visibility
                print(("Stopping code: Insufficient balance detected! (ตรวจพบยอดเงินไม่เพียงพอ! บอทหยุดทำงานแล้ว!)\n") * 10)
                logger.warning("Stopping code: Insufficient balance detected.")
                time.sleep(5)
                # Raise an exception instead of sys.exit() to trigger your robust error handling
                raise Exception("Bot stopped: Insufficient funds detected!")
            except Exception as e:
                # If the exception is exactly our custom insufficient funds error, re-raise it
                if str(e) == "Bot stopped: Insufficient funds detected!":
                    raise e
                # Otherwise, the pop-up didn't appear, so we just pass and continue the transfer
                logger.info("Sufficient Balance... Continue...")
                pass

            # Button Click "Skip to Review Information"
            page.locator("//span[normalize-space()='Skip to Review Information']").click(timeout=0) 
            logger.info("Click Skip to Review Information ...")

            # wait for "Review Information" to be appear
            page.locator("//h2[normalize-space()='Review Information']").wait_for(timeout=0) 
            logger.info("Wating for Review Information appear ...")

            # Scroll to very Bottom
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            logger.info("Scroll down to the Bottom ...")

            # Button Click "Submit"
            page.locator("//span[normalize-space()='Submit']").click(timeout=0)
            logger.info("Click Submit Button ...")

            # Button Click "OK"
            page.locator("//span[normalize-space()='OK']").click(timeout=0)
            logger.info("Button Click OK ...")

            # Wait for "Please authorize transaction(s) within 5 minutes.
            page.locator("//p[normalize-space()='Please authorize transaction(s) within 5 minutes.']").wait_for(timeout=0) 
            logger.info("Wait for 'Please authorize transaction(s) within 5 minutes'")

            # Launch Apps to Approve Transfer Request
            BankBot.scb_Anywhere_apps(data)
            logger.info("Successful to Approve Transfer Request!!!")

            # Button Click "Done"
            page.locator("//span[normalize-space()='Done']").click(timeout=1000)
            logger.info("Click Done...")

            # Delay 0.5 second
            page.wait_for_timeout(500)

            # wait for "Review Information" to be appear
            page.locator("//h2[contains(text(),'You have successfully submitted the transaction re')]").wait_for(timeout=0) 
            logger.info("Waiting for You have successfully submitted the transaction re...")
            
            # Wait for MUI backdrop animation to finish
            page.locator("div.MuiBackdrop-root").wait_for(state="hidden", timeout=5000)

            # Call Eric API
            cls.eric_api(data)

            # Button Click Make New Transfer
            page.locator("//span[normalize-space()='Make New Transfer']").click(timeout=5000)
            logger.info("Click Make New Transfer...")
            logger.info("Wait for next Withdrawal Transaction Request...")

        except Exception as e:
            error_trace = traceback.format_exc()
            print(f"\n[!] WITHDRAWAL EXCEPTION:\n{error_trace}")
            logging.error(f"WITHDRAWAL FAILED for Transaction {get_txn_id(data)}:\n{error_trace}")
            raise Exception(f"Withdrawal failed: {str(e)}")
        
    # Read Apps OTP Code
    @classmethod
    def scb_Anywhere_apps(cls, data):

        # Get Transaction ID
        txn_id = get_txn_id(data)
        logger.info("Starting SCB View Request Confirm Transaction flow.")

        try:

            # ============== Call Appium driver =======================
            
            driver = cls.use_appium_driver()
            logger.info("Start Appium Driver...")

            # bypass scbanyware detect using usb debugging
            driver.execute_script('mobile: shell', {'command': 'settings', 'args': ['put', 'global', 'adb_enabled', '12']})
            logger.info("Bypass USB Debugging...")

            # Check Apps State
            # 1 = Apps Not Running, 2 = App running in background (suspended)
            # 3 = App running in background, 4 = Apps Running in foreground (Apps is running)    
            state = driver.query_app_state(SCB_APP_PACKAGE)
            print("App state:", state)
            
            # If state 1, open apps
            if state == 1:
                print("App not running → starting activity")
                logger.info("App not running → starting activity.")
                driver.activate_app(SCB_APP_PACKAGE)
            # else if 2,3, open apps
            elif state in (2, 3):
                print("App in background → activating")
                logger.info("App in background → activating. ")
                driver.activate_app(SCB_APP_PACKAGE)
            # else 4, skip
            elif state == 4:
                print("App already in foreground")
                logger.info("App already in foreground.")

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
                
                # Find "Continue" / "Log in" button and click continue
                try:
                    driver.find_element(AppiumBy.XPATH, "//*[contains(@text, 'Continue')]").click()
                except:
                    driver.find_element(AppiumBy.XPATH, "//*[contains(@text, 'Log in')]").click()
                
                logger.info("Session Timeout, Click Continue / Log in...")
            except:
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
            
            # Click Notification / You have been inactive too long
            while True:
                try:
                    # Wait and Click Notifications
                    notif = WebDriverWait(driver, 300).until(EC.element_to_be_clickable((AppiumBy.ANDROID_UIAUTOMATOR, 'new UiSelector().text("Notifications")')))
                    notif.click()
                    logger.info("Wait and Click Notifications ...")
                    break
                except:
                    try:
                        # wait for text "You have been inactive too long"
                        WebDriverWait(driver, 1).until(EC.presence_of_element_located((AppiumBy.XPATH, "//*[contains(@text, 'You have been inactive for too long')]")))

                        # Find "Continue" button and click continue
                        driver.find_element(AppiumBy.XPATH, "//*[contains(@text, 'Continue')]").click()

                        logger.info("You have been inactive too long, click Continue...")

                        break
                    except:
                        pass

            # Click "View request"
            btn_view_request = WebDriverWait(driver, 300).until(EC.element_to_be_clickable((AppiumBy.ANDROID_UIAUTOMATOR,'new UiSelector().text("View request")')))
            time.sleep(0.3)
            driver.execute_script("mobile: clickGesture", {"elementId": btn_view_request.id})
            logger.info("Button click View Request...")

            # Wait and Click "Submit for approval"
            label = WebDriverWait(driver, 300).until(EC.presence_of_element_located((AppiumBy.ANDROID_UIAUTOMATOR,'new UiSelector().text("Submit for approval")')))
            time.sleep(0.3)
            driver.execute_script("mobile: clickGesture", {"elementId": label.id})
            logger.info("Wait and Click Submit for Approval...")

            # Wait for SCB Digital Token Pin
            WebDriverWait(driver, 300).until(EC.visibility_of_element_located((AppiumBy.XPATH, "//*[@text='Enter the 8-digit\nSCB Digital Token PIN']")))
            logger.info("Key in SCB Digital Token PIN...")

            time.sleep(1)
            token_pin = str(data["scbDigitalTokenPin"])
            for digit in token_pin:
                digit_button = WebDriverWait(driver, 10).until(EC.element_to_be_clickable((AppiumBy.XPATH, f"//android.widget.TextView[@text='{digit}']")))
                digit_button.click()
                time.sleep(0.5)

            # Click "Go to To-do List"
            gtdList = WebDriverWait(driver, 20).until(EC.presence_of_element_located((AppiumBy.ANDROID_UIAUTOMATOR, 'new UiSelector().text("Go to To-do List")')))
            time.sleep(2)
            gtdList.click()

            logger.info("Click Go to To-do List... txn_id=%s", txn_id)
            

        except Exception as e:
            error_trace = traceback.format_exc()
            print(f"\n[!] APPIUM EXCEPTION:\n{error_trace}")
            logging.error(f"MOBILE APP FAILED for Transaction {get_txn_id(data)}:\n{error_trace}")
            raise Exception(f"Mobile app approval failed: {str(e)}")

    # Logout
    @classmethod
    def scb_logout(cls, page):

        try:
            # Clear all cookies
            page.context.clear_cookies()

            # clear storage
            page.evaluate("""
                () => {
                    localStorage.clear();
                    sessionStorage.clear();
                }
            """)
            # Successful logout
            logger.warning(f"Successful to logout")
    
        except Exception as e:
            # Failed logour
            logger.warning(f"Failed to logout: {str(e)}")


        # Reload page if cookies affect session
        page.reload(wait_until="networkidle")

    # Kill SCB app
    @classmethod
    def scb_kill_apps(cls, driver):

        logger.info("Timeout Trigger, Processing to Kill Apps... ")

        # Call Appium driver
        driver = cls.use_appium_driver()

        # If you keep locking here, DO NOT lock before calling this function.
        with APPIUM_LOCK:
            if driver is None:
                driver = APPIUM_DRIVER  # optional: use global if caller passed None

            if driver is None:
                logging.error("No APPIUM_DRIVER yet; skipping terminate_app")
                return

            try:
                driver.terminate_app(SCB_APP_PACKAGE)
                logging.info("Stopped SCB app: %s", SCB_APP_PACKAGE)
                return
            except Exception as e:
                error_trace = traceback.format_exc()
                logging.error(f"terminate_app failed for SCB app:\n{error_trace}")

            try:
                driver.execute_script("mobile: shell",{"command": "am", "args": ["force-stop", SCB_APP_PACKAGE]})
                logging.info("Force-stopped SCB app via adb: %s", SCB_APP_PACKAGE)
            except Exception as e:
                error_trace = traceback.format_exc()
                logging.error(f"adb force-stop failed for SCB app:\n{error_trace}")

                try:
                    driver.quit()
                except Exception as e:
                    quit_trace = traceback.format_exc()
                    logging.error(f"driver.quit() failed during app kill:\n{quit_trace}")

                APPIUM_DRIVER = None

    # Callback ERIC API
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
            print("\n\n")
            print("Raw string to hash:", string_to_hash)
            print("MD5 Hash:", hash_result)
            print("Response:", response.text)
            print("\n\n")

            logging.info("Raw string to hash: %s", string_to_hash)
            logging.info("MD5 Hash: %s", hash_result)
            logging.info("Response: %s", response.text)

        except Exception as e:
            error_trace = traceback.format_exc()
            logging.error(f"ERIC API CALLBACK FAILED for Transaction {get_txn_id(data)}:\n{error_trace}")
            raise Exception(f"API Callback failed: {str(e)}")

# ================== Code Start Here ==================

def process_withdrawal(data):
    page = BankBot.scb_login(data)
    logging.info(f"Processing {data['transactionId']}")

    BankBot.scb_withdrawal(page, data)
    logging.info(f"Withdrawal Completed !!! {data['transactionId']}")

    return data["transactionId"]

@app.route("/scb_company_web/runPython", methods=["POST"])
def runPython():
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"success": False, "message": "Invalid JSON"}), 400

    worker = PlaywrightWorker.get_worker()

    with LOCK:
        try:
            transaction_id = worker.submit(process_withdrawal, data)

            return jsonify({
                "success": True,
                "transactionId": transaction_id
            })

        except Exception as e:
            full_trace = traceback.format_exc()
            
            # Prints to console
            print(f"\n--- CRITICAL TRANSACTION ERROR ---\n{full_trace}")
            
            # WRITES TO LOG FILE
            logging.error(f"CRITICAL ERROR for Transaction {data.get('transactionId', 'unknown')}:\n{full_trace}\n{'-'*40}")
            
            return jsonify({
                "success": False,
                "message": str(e),
                "error_type": type(e).__name__
            }), 500
        
# ================== MAIN ==============================

if __name__ == "__main__":
    logging.info("🚀 SCB Local API started")
    BankBot.start_ws_client()
    app.run(host="0.0.0.0", port=5001, debug=False, threaded=False, use_reloader=False)

