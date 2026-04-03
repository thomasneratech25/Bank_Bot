import os
import json
import time
import atexit
import threading
import logging
import hashlib
import requests
import traceback
import subprocess
from threading import Lock
from dotenv import load_dotenv
from flask import Flask, request, jsonify
from playwright.sync_api import sync_playwright, expect
from appium import webdriver
from appium.webdriver.common.appiumby import *
from appium.webdriver.common.appiumby import AppiumBy
from appium.webdriver.client_config import AppiumClientConfig
from appium.options.android import UiAutomator2Options
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# =========================== Eric WS_Client Settings =================

WS_PROC = None

# =========================== Logging Settings =========================

LOG_DIR = "./logs"
os.makedirs(LOG_DIR, exist_ok=True)

LOG_FILE = os.path.join(LOG_DIR, "KBank_Samsung_Payout.log")

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

logger = logging.getLogger("KBank_Samsung")
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
        for attempt in range(1, timeout + 1):
            try:
                if requests.get("http://localhost:9222/json").status_code == 200:
                    return
            except Exception:
                pass
            time.sleep(1)
        raise RuntimeError("Chrome CDP not ready")

# ================== KBANK BANK BOT ==================

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

                client_config = AppiumClientConfig(
                    remote_server_addr="http://127.0.0.1:8021",
                    keep_alive=False
                )

                APPIUM_DRIVER = webdriver.Remote(
                    "http://127.0.0.1:8021",
                    options=options,
                    client_config=client_config
                )
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
    def kbank_login(cls, data):
        
        # Get Transaction ID
        txn_id = get_txn_id(data)
        logger.info("Starting KBANK login flow. txn_id=%s", txn_id)
        
        try:
            global PLAYWRIGHT, BROWSER, CONTEXT, PAGE

            # Start Chrome
            cls.chrome_cdp()

            # Start Playwright ONLY ONCE
            if PLAYWRIGHT is None:
                logger.info("Starting Playwright instance. txn_id=%s", txn_id)
                PLAYWRIGHT = sync_playwright().start()
            else:
                logger.info("Reusing Playwright instance. txn_id=%s", txn_id)

            # Connect to running Chrome ONLY ONCE
            if BROWSER is None:
                logger.info("Connecting Playwright to Chrome CDP. txn_id=%s", txn_id)
                BROWSER = PLAYWRIGHT.chromium.connect_over_cdp("http://localhost:9222")
            else:
                logger.info("Reusing existing Chrome CDP browser connection. txn_id=%s", txn_id)

            # Reuse context
            CONTEXT = BROWSER.contexts[0] if BROWSER.contexts else BROWSER.new_context()
            logger.info("Browser context ready. txn_id=%s", txn_id)

            # Reuse page
            if PAGE is None or PAGE.is_closed():
                logger.info("Creating new browser page. txn_id=%s", txn_id)
                PAGE = CONTEXT.new_page()
            else:
                logger.info("Reusing existing browser page. txn_id=%s", txn_id)

            page = PAGE

            # If already on transfer page, skip login
            try:
                page.locator("//h1[normalize-space()='Funds Transfer']").wait_for(timeout=1500)
                logger.info("Already on Transfer page, Skip login...")
                return page # Already Login
            except Exception:
                pass

            # Go to a webpage
            page.goto("https://kbiz.kasikornbank.com/authen/login.jsp?lang=en", wait_until="domcontentloaded")
            logger.info("Navigating to KBANK login page. txn_id=%s", txn_id)

            # If "Sorry" Appear, Button click "Go to login Page"
            try:
                page.wait_for_selector("//span[normalize-space()='Sorry']", timeout=1500)
                
                # Button Click "Go to login Page"
                page.locator("//span[normalize-space()='Go to login page']").click()

                # Log for session expired
                logger.warning("Your session has expired or you are signed in on another device, button click to login Page. txn_id=%s", txn_id)
            except:
                pass

            # if Account already login, can skip
            try: 
                # Fill "User ID"
                page.locator("//input[@id='userName']").fill(str(data["username"]))

                # Fill "Password"
                page.locator("//input[@id='password']").fill(str(data["password"]))

                # Button Click "Log In"
                page.locator("//a[@id='loginBtn']").click()

                logger.info("Login Account...")
            except Exception:
                logger.info("Account Already Login, Skip...")
                pass

            # Button Click "Fund Transfer"
            page.locator("//div[@class='column-menu']//a[@id='BIZ_004']").click(timeout=100000) 
            logger.info("Button click for 'Fund Transfer', txn_id=%s", txn_id)

            # wait for "Fund Transfer" to be appear
            page.locator("//h1[normalize-space()='Funds Transfer']").wait_for() 
            logger.info("Wait for navigate to 'Fund Transfer' Title/Page, txn_id=%s", txn_id)

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
    def kbank_withdrawal(cls, page, data):

        try:
            # Delay 1 second
            time.sleep(1)
            
            # Get Transaction ID
            txn_id = get_txn_id(data)
            # Starting for withdrawal flow...
            logger.info("Starting withdrawal flow. txn_id=%s to_bank=%s to_account=%s amount=%s",txn_id, data.get("toBankCode"), data.get("toAccountNum"), data.get("amount"),)

            # Button Click "Select Bank"
            page.locator("//span[@id='select2-id_select2_example_3-container']//div").click(timeout=10000)
            logger.info(f"Open Bank Menu....., txn_id=%s", txn_id)

            # Locate the input
            page.locator("input.select2-search__field").evaluate("el => el.removeAttribute('readonly')")
            page.locator("input.select2-search__field").fill(str(data["toBankCode"]))
            logger.info("Fill in Bank Name %s, txn_id=%s", data.get("toBankCode"), txn_id)

            # if element == bank code name, then click the third element, else click first element
            if page.locator("//span[@id='select2-id_select2_example_3-container']//span").inner_text().strip() == data["toBankCode"]:
                page.locator(f"//div[span[normalize-space()='{data['toBankCode']}']]").nth(2).click()
            else:
                page.locator(f"//div[span[normalize-space()='{data['toBankCode']}']]").click()
            logger.info("Select the Bank Name/Code %s, txn_id=%s", data.get("toBankCode"), txn_id)

            # Fill Account No.
            page.locator("//input[@placeholder='xxx-x-xxxxx-x']").fill(str(data["toAccountNum"]))
            logger.info("Fill in Account Number %s, txn_id=%s", data.get("toAccountNum"), txn_id)

            # Fill Amount
            page.locator("//input[@placeholder='0.00']").fill(str(data["amount"]))
            logger.info("Fill in Amount %s, txn_id=%s", data.get("amount"), txn_id)

            # Button Click "Next"
            page.locator("//a[@class='btn btn-gradient f-right disabled-button']").click()
            logger.info(f"Click Next, txn_id=%s", txn_id)

            time.sleep(1)

            # If insufficient amount appear, raise and stop code
            if page.locator("//span[normalize-space()='There is insufficient balance in your account.']").is_visible():
                    print(("Stopping code: Insufficient balance detected! (ตรวจพบยอดเงินไม่เพียงพอ! บอทหยุดทำงานแล้ว!)\n") * 10)
                    logger.warning("Stopping code: Insufficient balance detected.")
                    time.sleep(5)
                    raise Exception("Stopping code: Insufficient balance detected.")
            
            logger.info("Sufficient Balance... Continue...")

            # if Notice | You or Company has made this transaction already .... if this appear click confirm else skip
            try: 
                expect(page.locator("//div[@class='mfp-content']//h3[contains(text(),'Notice')]")).to_be_visible(timeout=4000)
                # Button Click "Confirm"
                page.locator("//div[@class='mfp-content']//span[contains(text(),'Confirm')]").click()
                logger.info(f"Notice | You or Company has made this transaction already .... click Confirm, txn_id=%s", txn_id)
            except Exception:
                pass
            
            # Wait for "Confirm Transaction" appear
            try:
                page.get_by_role("heading", name="Confirm Transaction").wait_for(timeout=3000)
            except Exception as e:
                logger.exception("'Confirm Transaction' is not appear after waiting 3 seconds..., txn_id=%s", txn_id)
                
            # Delay 1 second
            time.sleep(1)

            # Kbank Apps Approved   
            logger.info("Moving to mobile approval Confirm transaction. txn_id=%s", txn_id)
            cls.kbank_business_apps(data)
            logger.info("Mobile approval completed. txn_id=%s", txn_id)

            # wait for "Fund Transfer" to be appear
            page.locator("//div[@class='column-menu']//a[@id='BIZ_004']").wait_for(state="visible", timeout=10000)
            logger.info("Wait for Fund Transfer page to appear.")
            
            # Button Click "Fund Transfer"
            page.locator("//div[@class='column-menu']//a[@id='BIZ_004']").click() 
            logger.info("Button click Fund Transfer to wait for the next withdrawal transaction request... ")

            # wait for "Fund Transfer" to be appear
            page.locator("//h1[normalize-space()='Funds Transfer']").wait_for(state="visible", timeout=10000)

        except Exception as e:
            error_trace = traceback.format_exc()
            print(f"\n[!] WITHDRAWAL EXCEPTION:\n{error_trace}")
            logging.error(f"WITHDRAWAL FAILED for Transaction {get_txn_id(data)}:\n{error_trace}")
            raise Exception(f"Withdrawal failed: {str(e)}")
        
    # Apps Approved Transaction
    @classmethod
    def kbank_business_apps(cls, data):

        # Get Transaction ID
        txn_id = get_txn_id(data)
        
        try:
            # ============== Call Appium driver =======================
            
            driver = cls.use_appium_driver()
            logger.info("Start Appium Driver... txn_id=%s", txn_id)

            # ============== Watchdog Timer ============================

            watchdog = {"timer": None, "fired": False}

            # if after 40 seconds exists, it will Trigger restart_and_reopen_confirm function()
            def watchdog_fire():
                logger.info(f"Watchdog timeout triggered -> restarting app now")
                try:
                    restart_and_reopen_confirm()
                except Exception as e:
                    logger.info(f"watchdog restart failed:")

            # Start Watchdog Timer Function
            def start_watchdog():
                # Always cancel existing timer first
                if watchdog["timer"]:
                    try:
                        watchdog["timer"].cancel()
                    except Exception:
                        pass

                watchdog["fired"] = False
                watchdog["timer"] = threading.Timer(120, watchdog_fire)
                watchdog["timer"].daemon = True
                watchdog["timer"].start()
                
                # Start Watchdog Timer
                logger.info("Start Watchdog Timer, txn_id=%s", txn_id)

            # Stop Watchdog Timer Function
            def stop_watchdog():
                if watchdog["timer"]:
                    try:
                        watchdog["timer"].cancel()
                    except Exception:
                        pass
                    watchdog["timer"] = None

                # Stop Watchdog Timer
                logger.info("Stop Watchdog Timer, txn_id=%s", txn_id)
            
            # =============== KBank Apps Part =============================

            # Restart Apps -> Key Pin -> Wait Confirm transaction and click
            def restart_and_reopen_confirm():
                print("40 seconds reached. Force restarting app...")
                logging.info("Force restart after 40 seconds")

                try:
                    # Kill apps
                    print("Kill Kbank App")
                    logging.info("Stopped Kbank App")
                    driver.terminate_app("com.kasikornbank.kbiz")

                    # Open back apps
                    driver.activate_app("com.kasikornbank.kbiz")
                    logging.info("Start Kbank App")

                    # Wait and click "Log In"
                    WebDriverWait(driver, 20).until(EC.element_to_be_clickable((AppiumBy.ACCESSIBILITY_ID, "Log in"))).click()
                    logging.info("Wait for Kbank Log In Page, Click Log in...")

                    # Enter Password
                    enter_pin()
                
                    # Confirm Transaction
                    confirm_transaction()

                    logging.info("Enter PIN and Confirm Transcation...")
                    
                except Exception as e:
                    print("Restart failed:", e)
                    logging.info("Restart Failed")

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
                    logging.info("Error popup detected! Clicking 'Close Application'.")
                    close_button.click()
                      
                except TimeoutException:
                    # IF the button does NOT appear within 5 seconds, it throws a TimeoutException.
                    # The 'except' block catches it, meaning the transaction was successful!
                    print(f'No error - Sorry Unable to proceed. Proceeding normally...')
                    logging.info("No error - Sorry Unable to proceed. Proceeding normally.")
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
                    print(f"Pin: {digit}")
                    # "Sorry, Unable to proceed The system cannot proceed this transaction, please try again later.")
                    error_unable_process_this_transaction()
                
                logger.info("Enter KBank Apps Pin... txn_id=%s", txn_id)

            # Confirm Transaction
            def confirm_transaction(max_retries=3):

                logger.info("Starting Apps confirm transaction sequence. txn_id=%s", txn_id)
            
                # Scroll Down Confirmation Transaction
                def scroll_down(driver, times=2, duration=500):
                    size = driver.get_window_size()
                    x = size["width"] // 2

                    start_y = int(size["height"] * 0.80)
                    end_y = int(size["height"] * 0.25)

                    for _ in range(times):
                        driver.swipe(x, start_y, x, end_y, duration)

                    logger.debug("Scrolled confirmation screen. txn_id=%s swipes=%s", txn_id, times)

                attempt = 0
                while attempt < max_retries:
                    try:
                        print(f"Confirm attempt {attempt + 1}")

                        # Wait for "Confirm Transaction"
                        WebDriverWait(driver, 15).until(EC.presence_of_element_located((AppiumBy.XPATH, "//*[contains(@text,'Confirm Transaction')]")))

                        # Scroll Down
                        scroll_down(driver)

                        # Wait and Button Click "Confirm"
                        WebDriverWait(driver, 20).until(EC.element_to_be_clickable((AppiumBy.XPATH, "//*[@text='Confirm']/.."))).click()

                        # Delay 1 second
                        time.sleep(1)

                        # Wait and Button Click "Confirm"s
                        WebDriverWait(driver, 20).until(EC.element_to_be_clickable((AppiumBy.ACCESSIBILITY_ID, "Confirm"))).click()

                        break
                        
                    except Exception as e:
                        attempt += 1
                        print(f"Confirm failed (attempt {attempt}): {e}")

                        if attempt >= max_retries:
                            print("Max confirm retries reached.")
                            raise Exception("Failed to confirm transaction after 3 attempts")

                        # Restart app before retry
                        try:
                            print("Restarting Kbank App...")
                            
                            # Kill Apps
                            driver.terminate_app("com.kasikornbank.kbiz")

                            # Start Apps
                            driver.activate_app("com.kasikornbank.kbiz")
                            
                            # Click Login
                            WebDriverWait(driver, 20).until(EC.element_to_be_clickable((AppiumBy.ACCESSIBILITY_ID, "Log in"))).click()
                            
                            # Enter Pin
                            enter_pin()

                            # After restart & enter_pin()
                            continue

                        except Exception as restart_error:
                            print("Restart failed:", restart_error)
                            raise restart_error
            
            ### Click K BIZ Confirm transaction ###
            # Expand Notification Bar
            driver.open_notifications()
            logger.info("Open Notification Bar... txn_id=%s", txn_id)

            # Wait for SystemUI notification container
            WebDriverWait(driver, 10).until(EC.presence_of_element_located((AppiumBy.ID, "com.android.systemui:id/notification_stack_scroller")))

            # Click notification that contains "Confirm transaction"
            target_text = "Confirm transaction"
            notif_xpath = f"//*[contains(@text,'{target_text}') or contains(@content-desc,'{target_text}')]"
            WebDriverWait(driver, 10).until(EC.element_to_be_clickable((AppiumBy.XPATH, notif_xpath))).click()
            WebDriverWait(driver, 10).until(EC.element_to_be_clickable((AppiumBy.XPATH, notif_xpath))).click()
            logger.info("Click KBank Confirm Transaction notification... txn_id=%s", txn_id)

            # Delay 1 second
            time.sleep(1)

            # Start Watchdog Timer
            start_watchdog()
            logger.info("Start WatchDog Timer (120s)... txn_id=%s", txn_id)
            logger.info("If Withdrawal cannot complete within 120s, Restart apps and click confirm transaction, txn_id=%s", txn_id)

            while True:
                try:
                    # Session Expired
                    if driver.find_elements(AppiumBy.XPATH, "//*[contains(@content-desc,'session has expired')]"):

                        # Session Expired Log
                        logger.info("Session Expired, KBank Apps Relogin and Perform Confirm Transaction, and stop Watchdog Timer, txn_id=%s", txn_id)
                        
                        # Button Click "Yes"
                        driver.find_element(AppiumBy.XPATH, "//android.widget.Button[@content-desc='Yes']").click()

                        # Enter PIN
                        enter_pin()

                        # Confirm Transaction
                        confirm_transaction()

                        # Stop Watchdog Timer
                        stop_watchdog() 

                        # Break While Loop
                        break

                    # else if Enter Pin Page
                    elif driver.find_elements(AppiumBy.ACCESSIBILITY_ID, "Enter PIN"):

                        try:
                            # Wait for "Session Expired" to appear
                            WebDriverWait(driver, 1).until(EC.presence_of_element_located((AppiumBy.XPATH, "//*[contains(@content-desc,'session has expired')]")))

                            # Session Expired Log
                            logger.info("Session Expired, KBank Apps Relogin and Perform Confirm Transaction, and stop Watchdog Timer, txn_id=%s", txn_id)

                            # Button Click "Yes"
                            driver.find_element(AppiumBy.XPATH, "//android.widget.Button[@content-desc='Yes']").click()

                            # Enter PIN
                            enter_pin()

                            # Confirm Transaction
                            confirm_transaction()

                            # Stop Watchdog Timer
                            stop_watchdog() 

                            # Break While Loop
                            break
                        except Exception:
                            pass

                        # Enter PIN
                        enter_pin()

                        # Confirm Transaction
                        confirm_transaction()

                        # Stop Watchdog Timer
                        stop_watchdog() 

                        # Kbank Apps login and perform confirm transaction
                        logger.info("KBank Apps login and Perform Confirm Transaction, and stop Watchdog Timer, txn_id=%s", txn_id)
       
                        # Break While Loop
                        break
                    
                    # Wait for "Confirm Transaction"
                    elif driver.find_elements(AppiumBy.XPATH, "//*[contains(@text,'Confirm Transaction')]"):
                        try:
                            if driver.find_elements(AppiumBy.XPATH, "//*[contains(@content-desc,'session has expired')]"):

                                # Session Expired Log
                                logger.info("Session Expired, KBank Apps Relogin and Perform Confirm Transaction, and stop Watchdog Timer, txn_id=%s", txn_id)

                                # Button Click "Yes"
                                driver.find_element(AppiumBy.XPATH, "//android.widget.Button[@content-desc='Yes']").click()

                                # Enter PIN
                                enter_pin()

                                # Confirm Transaction
                                confirm_transaction()

                                # Stop Watchdog Timer
                                stop_watchdog() 

                                # Break While Loop
                                break
                        except Exception:
                            pass

                        # Confirm Transaction
                        confirm_transaction()

                        # Stop Watchdog Timer
                        stop_watchdog() 

                        # Confirm Transaction
                        logger.info("Perform Confirm Transaction, and stop Watchdog Timer, txn_id=%s", txn_id)

                        # Break While Loop
                        break

                except TimeoutException:
                    continue
            
            # # Call Back Eric API
            # cls.eric_api(data)
            
            # # Wait and Click "Back to main page"
            # WebDriverWait(driver, 20).until(EC.element_to_be_clickable((AppiumBy.XPATH, "//android.view.View[@content-desc='Back to main page']"))).click()
            # logger.info("Back to main Page...")

        except Exception as e:
            error_trace = traceback.format_exc()
            print(f"\n[!] APPIUM EXCEPTION:\n{error_trace}")
            logging.error(f"MOBILE APP FAILED for Transaction {get_txn_id(data)}:\n{error_trace}")
            raise Exception(f"Mobile app approval failed: {str(e)}")
        
    # Clean all notification 1 round
    @classmethod
    def kbank_business_apps_clean_notif(cls):

        try:

            logger.info("Starting Cleaning Notification Bar...")

            # Call Appium Driver
            driver = cls.use_appium_driver()

            # Screen never sleep
            driver.execute_script("mobile: shell", {"command": "settings", "args": ["put", "system", "screen_off_timeout", "2147483647"], "includeStderr": True, "timeout": 5000})

            # Expand Notification Bar
            driver.open_notifications()

            time.sleep(1)

            try:
                # Use find_elements so "not found" doesn't throw
                clear_buttons = driver.find_elements(AppiumBy.ACCESSIBILITY_ID, "Clear,Button")

                if clear_buttons:
                    clear_buttons[0].click()

            except Exception:
                pass
            finally:
                # Close notification bar
                driver.execute_script("mobile: shell", {"command": "cmd", "args": ["statusbar", "collapse"]})

        except Exception as e:
            # We just log this and pass, because failing to clean notifications shouldn't crash the whole bot
            logging.warning(f"Failed to clean notifications: {str(e)}")

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
            logger.info("Starting For Chrome Browser...")

            # Clean Notification Bar first
            BankBot.kbank_business_apps_clean_notif()
            logger.info("Clean Phone Notification")

            # Login KBANK
            page = BankBot.kbank_login(data)
            logger.info(f"Processing payout started. txn_id={get_txn_id(data)}")

            # Perform Withdrawal and Mobile App Approval
            BankBot.kbank_withdrawal(page, data)
            logger.info(f"Processing payout completed. txn_id={get_txn_id(data)}")

            return jsonify({
                "success": True,
                "transactionId": data.get("transactionId")
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
    app.run(host="0.0.0.0", port=5004, debug=False, threaded=False, use_reloader=False)