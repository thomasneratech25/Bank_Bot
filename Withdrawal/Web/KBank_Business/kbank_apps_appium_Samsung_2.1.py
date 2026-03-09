import os
import json
import time
import atexit
import hashlib
import logging
import requests
import subprocess
from threading import Lock
from dotenv import load_dotenv
from flask import Flask, request, jsonify
from playwright.sync_api import sync_playwright, expect
from appium import webdriver
from appium.webdriver.common.appiumby import *
from appium.webdriver.common.appiumby import AppiumBy
from appium.options.android import UiAutomator2Options
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC


# =========================== Appium Settings =========================

APPIUM_DRIVER = None
APPIUM_PROC = None
APPIUM_LOCK = Lock()

# =========================== Flask apps ==============================

app = Flask(__name__)
LOCK = Lock()

# ================== LOG File ==================

LOG_DIR = "logs"
os.makedirs(LOG_DIR, exist_ok=True)

LOG_FILE = os.path.join(LOG_DIR, "kbank_payout_samsung.log")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("KBANK_BOT__Samsung_Logger")
logger.info("Logging started: %s", LOG_FILE)

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
        logger.info("Initializing Chrome CDP process")

        # Prevent starting Chrome more than once
        if cls.chrome_proc:
            logger.info("Chrome CDP process already exists, reusing current process")
            return
        
        # Load .env file
        load_dotenv()
        USER_DATA_DIR = os.getenv("CHROME_PATH")
        if USER_DATA_DIR:
            logger.info("Using Chrome user data dir from CHROME_PATH")
        else:
            logger.warning("CHROME_PATH is not set; Chrome may use an unexpected profile")

        cls.chrome_proc = subprocess.Popen([
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            "--remote-debugging-port=9222",
            "--disable-session-crashed-bubble",
            "--hide-crash-restore-bubble",
            "--no-first-run",
            "--no-default-browser-check",
            f"--user-data-dir={USER_DATA_DIR}",
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        logger.info("Chrome started with PID %s", cls.chrome_proc.pid)

        cls.wait_for_cdp_ready()
        atexit.register(cls.cleanup)
        logger.info("Chrome CDP is ready")

    # Close Chrome Completely
    @classmethod
    def cleanup(cls):
        try:
            if cls.chrome_proc and cls.chrome_proc.poll() is None:
                logger.info("Closing Chrome CDP process")
                cls.chrome_proc.terminate()
            else:
                logger.info("Chrome CDP cleanup skipped; no running process found")
        except Exception:
            logger.exception("Chrome cleanup failed")

    # Wait Chrome CDP Ready
    @staticmethod
    def wait_for_cdp_ready(timeout=10):
        logger.info("Waiting for Chrome CDP readiness, timeout=%ss", timeout)
        for attempt in range(1, timeout + 1):
            try:
                if requests.get("http://localhost:9222/json").status_code == 200:
                    logger.info("Chrome CDP endpoint is available (attempt %s/%s)", attempt, timeout)
                    return
            except Exception:
                logger.debug("Chrome CDP endpoint not ready yet (attempt %s/%s)", attempt, timeout)
            time.sleep(1)
        logger.error("Chrome CDP not ready after %s seconds", timeout)
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
                logger.info("Creating new Appium driver session")
                options = UiAutomator2Options()
                options.platform_name = "Android"
                options.device_name = "androidtesting"
                options.automation_name = "UiAutomator2"
                options.new_command_timeout = 2000

                APPIUM_DRIVER = webdriver.Remote(
                    "http://127.0.0.1:8021",
                    options=options
                )
            else:
                logger.info("Reusing existing Appium driver session")

        return APPIUM_DRIVER
    
    # Start Appium Server
    @classmethod
    def start_appium_server(cls):
        
        global APPIUM_PROC
        logger.info("Ensuring Appium server is running")
        
        # if appium server start already, then skip
        # Prevent starting multiple appium server
        if APPIUM_PROC: 
            logger.info("Appium process already exists, skipping new start")
            return

        # Start Appium Server Command
        APPIUM_CMD = os.getenv("APPIUM_CMD")
        APPIUM_PROC = subprocess.Popen([
            APPIUM_CMD,
            "--port", "8021",
            "--allow-insecure", "uiautomator2:adb_shell",
            "--allow-cors"
        ])
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
    
    # Login
    @classmethod
    def kbank_login(cls, data):
        
        global PLAYWRIGHT, BROWSER, CONTEXT, PAGE
        txn_id = get_txn_id(data)
        logger.info("Starting KBANK login flow. txn_id=%s", txn_id)

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
            logger.info("Already logged in at Funds Transfer page. txn_id=%s", txn_id)
            return page # Already Login
        except Exception:
            logger.info("Session not at Funds Transfer page, proceeding with login. txn_id=%s", txn_id)
            pass

        # Go to a webpage
        logger.info("Navigating to KBANK login page. txn_id=%s", txn_id)
        page.goto("https://kbiz.kasikornbank.com/authen/login.jsp?lang=en", wait_until="domcontentloaded")

        # if Account already login, can skip
        try: 
            # Fill "User ID"
            page.locator("//input[@id='userName']").fill(str(data["username"]))

            # Fill "Password"
            page.locator("//input[@id='password']").fill(str(data["password"]))

            # Button Click "Log In"
            page.locator("//a[@id='loginBtn']").click()
            logger.info("Login form submitted. txn_id=%s", txn_id)
        except Exception:
            logger.info("Login form step skipped (session may already be authenticated). txn_id=%s", txn_id)

        # Button Click "Fund Transfer"
        logger.info("Opening Funds Transfer menu. txn_id=%s", txn_id)
        page.locator("//div[@class='column-menu']//a[@id='BIZ_004']").click(timeout=100000) 

        # wait for "Fund Transfer" to be appear
        page.locator("//h1[normalize-space()='Funds Transfer']").wait_for() 
        logger.info("Funds Transfer page is ready. txn_id=%s", txn_id)

        return page

    # Withdrawal
    @classmethod
    def kbank_withdrawal(cls, page, data):
        txn_id = get_txn_id(data)
        logger.info(
            "Starting withdrawal flow. txn_id=%s to_bank=%s to_account=%s amount=%s",
            txn_id,
            data.get("toBankCode"),
            data.get("toAccountNum"),
            data.get("amount"),
        )

        # wait for "Select Bank" to be appear
        page.locator("//span[@id='select2-id_select2_example_3-container']//div").wait_for(state="visible", timeout=100000)
        logger.info("Withdrawal form is ready. txn_id=%s", txn_id)

        # Delay 1 second
        time.sleep(1)
        
        # Button Click "Select Bank"
        logger.info("Selecting destination bank. txn_id=%s", txn_id)
        page.locator("//span[@id='select2-id_select2_example_3-container']//div").click()

        # Locate the input
        page.locator("input.select2-search__field").evaluate("el => el.removeAttribute('readonly')")
        page.locator("input.select2-search__field").fill(str(data["toBankCode"]))

        # if element == bank code name, then click the third element, else click first element
        if page.locator("//span[@id='select2-id_select2_example_3-container']//span").inner_text().strip() == data["toBankCode"]:
            page.locator(f"//div[span[normalize-space()='{data['toBankCode']}']]").nth(2).click()
        else:
            page.locator(f"//div[span[normalize-space()='{data['toBankCode']}']]").click()
        logger.info("Destination bank selected. txn_id=%s", txn_id)

        # Fill Account No.
        page.locator("//input[@placeholder='xxx-x-xxxxx-x']").fill(str(data["toAccountNum"]))

        # Fill Amount
        page.locator("//input[@placeholder='0.00']").fill(str(data["amount"]))
        logger.info("Destination account and amount entered. txn_id=%s", txn_id)

        # Button Click "Next"
        page.locator("//a[@class='btn btn-gradient f-right disabled-button']").click()
        logger.info("Submitted transfer details, waiting for confirmations. txn_id=%s", txn_id)

        # if Notice | You or Company has made this transaction already .... if this appear click confirm else skip
        try: 
            expect(page.locator("//div[@class='mfp-content']//h3[contains(text(),'Notice')]")).to_be_visible(timeout=4000)
            # Button Click "Confirm"
            page.locator("//div[@class='mfp-content']//span[contains(text(),'Confirm')]").click()
            logger.info("Notice modal appeared and was confirmed. txn_id=%s", txn_id)
        except Exception:
            logger.info("No Notice modal detected. txn_id=%s", txn_id)
        # Wait for "Confirm Transaction" appear
        page.locator("//app-notification-modal-header//h3[1]").wait_for(state="visible", timeout=100000)

        # Delay 1 second
        time.sleep(1)

        # Kbank Apps Approved   
        logger.info("Web confirm dialog ready; moving to mobile approval. txn_id=%s", txn_id)
        cls.kbank_business_apps(data)
        logger.info("Mobile approval completed. txn_id=%s", txn_id)

        # Callback Eric API
        cls.eric_api(data)
        logger.info("ERIC callback completed. txn_id=%s", txn_id)

        # wait for "Fund Transfer" to be appear
        page.locator("//div[@class='column-menu']//a[@id='BIZ_004']").wait_for(state="visible", timeout=10000)
        
        # Button Click "Fund Transfer"
        page.locator("//div[@class='column-menu']//a[@id='BIZ_004']").click() 

        # wait for "Fund Transfer" to be appear
        page.locator("//h1[normalize-space()='Funds Transfer']").wait_for(state="visible", timeout=10000)
        logger.info("Withdrawal flow completed and returned to Funds Transfer page. txn_id=%s", txn_id)

    # Apps Approved Transaction
    @classmethod
    def kbank_business_apps(cls, data):
        txn_id = get_txn_id(data)
        logger.info("Starting KBANK mobile approval flow. txn_id=%s", txn_id)
        
        # Call Appium driver
        driver = cls.use_appium_driver()

        # Enter Login Pin
        def enter_pin():
            logger.info("Waiting for Enter PIN screen. txn_id=%s", txn_id)

            # Wait for "Enter PIN" to appear
            WebDriverWait(driver, 30).until(EC.presence_of_element_located((AppiumBy.XPATH, "//android.view.View[@content-desc='Enter PIN']")))

            # Enter Pin
            logger.info("Entering mobile PIN. txn_id=%s", txn_id)
            pin = str(data["pin"])
            for digit in pin:
                digit_button = WebDriverWait(driver, 10).until(EC.element_to_be_clickable((AppiumBy.ACCESSIBILITY_ID, digit)))
                digit_button.click()
            logger.info("Mobile PIN entry complete. txn_id=%s", txn_id)

        # Confirm Transaction
        def confirm_transaction():
            logger.info("Starting mobile confirm transaction sequence. txn_id=%s", txn_id)

            # Scroll Down Confirmation Transaction
            def scroll_down(driver, times=2, duration=500):
                size = driver.get_window_size()
                x = size["width"] // 2

                start_y = int(size["height"] * 0.80)
                end_y = int(size["height"] * 0.25)

                for _ in range(times):
                    driver.swipe(x, start_y, x, end_y, duration)
                logger.debug("Scrolled confirmation screen. txn_id=%s swipes=%s", txn_id, times)

            # Wait for "Confirm Transaction"
            WebDriverWait(driver, 30).until(EC.presence_of_element_located((AppiumBy.XPATH, "//*[contains(@text,'Confirm Transaction')]")))

            # Scroll Down
            scroll_down(driver)

            # Wait and Button Click "Confirm"
            WebDriverWait(driver, 20).until(EC.element_to_be_clickable((AppiumBy.XPATH, "//*[@text='Confirm']/.."))).click()

            # Delay 1 second
            time.sleep(1)

            # Wait and Button Click "Confirm"s
            WebDriverWait(driver, 20).until(EC.element_to_be_clickable((AppiumBy.ACCESSIBILITY_ID, "Confirm"))).click()
            logger.info("Mobile confirm buttons clicked. txn_id=%s", txn_id)

        ### Click K BIZ Confirm transaction ###
        # Expand Notification Bar
        driver.open_notifications()
        logger.info("Opened Android notification shade. txn_id=%s", txn_id)

        # Wait for SystemUI notification container
        WebDriverWait(driver, 10).until(EC.presence_of_element_located((AppiumBy.ID, "com.android.systemui:id/notification_stack_scroller")))
        logger.info("Notification container is visible. txn_id=%s", txn_id)

        # Click notification that contains "PRIME MOTO PARTS"
        target_text = "PRIME MOTO PARTS"
        notif_xpath = f"//*[contains(@text,'{target_text}') or contains(@content-desc,'{target_text}')]"
        WebDriverWait(driver, 10).until(EC.element_to_be_clickable((AppiumBy.XPATH, notif_xpath))).click()
        logger.info("Opened PRIME MOTO PARTS notification. txn_id=%s", txn_id)

        # Delay 1 second
        time.sleep(1)
        
        loop_count = 0
        logger.info("Waiting for mobile approval screens. txn_id=%s", txn_id)
        while True:
            loop_count += 1
            try:
                # Session Expired
                if driver.find_elements(AppiumBy.XPATH, "//*[contains(@content-desc,'session has expired')]"):
                    logger.warning("Session expired detected on mobile app. txn_id=%s", txn_id)

                    # Button Click "Yes"
                    driver.find_element(AppiumBy.XPATH, "//android.widget.Button[@content-desc='Yes']").click()

                    # Enter PIN
                    enter_pin()

                    # Confirm Transaction
                    confirm_transaction()

                    # Break While Loop
                    break
                
                # else if Enter Pin Page
                elif driver.find_elements(AppiumBy.ACCESSIBILITY_ID, "Enter PIN"):
                    logger.info("Enter PIN screen detected. txn_id=%s", txn_id)
                    
                    try:
                        # Wait for "Session Expired" to appear
                        WebDriverWait(driver, 1).until(EC.presence_of_element_located((AppiumBy.XPATH, "//*[contains(@content-desc,'session has expired')]")))

                        # Button Click "Yes"
                        driver.find_element(AppiumBy.XPATH, "//android.widget.Button[@content-desc='Yes']").click()

                        # Enter PIN
                        enter_pin()

                        # Confirm Transaction
                        confirm_transaction()

                        # Break While Loop
                        break
                    except Exception:
                        logger.debug("No session-expired dialog after PIN screen. txn_id=%s", txn_id)

                    # Enter PIN
                    enter_pin()

                    # Confirm Transaction
                    confirm_transaction()
                    
                    # Break While Loop
                    break
                
                # Wait for "Confirm Transaction"
                elif driver.find_elements(AppiumBy.XPATH, "//*[contains(@text,'Confirm Transaction')]"):
                    logger.info("Confirm Transaction screen detected. txn_id=%s", txn_id)
                    try:
                        if driver.find_elements(AppiumBy.XPATH, "//*[contains(@content-desc,'session has expired')]"):
                            logger.warning("Session expired detected on Confirm screen. txn_id=%s", txn_id)

                            # Button Click "Yes"
                            driver.find_element(AppiumBy.XPATH, "//android.widget.Button[@content-desc='Yes']").click()

                            # Enter PIN
                            enter_pin()

                            # Confirm Transaction
                            confirm_transaction()

                            # Break While Loop
                            break
                    except Exception:
                        logger.debug("Session-expired check failed on Confirm screen. txn_id=%s", txn_id)

                    # Confirm Transaction
                    confirm_transaction()

                    # Break While Loop
                    break

            except TimeoutException:
                logger.warning("Timeout while checking mobile state, retrying. txn_id=%s", txn_id)
                continue

            if loop_count % 10 == 0:
                logger.info("Still waiting for mobile state. attempts=%s txn_id=%s", loop_count, txn_id)

        # Wait and Click "Back to main page"
        WebDriverWait(driver, 20).until(EC.element_to_be_clickable((AppiumBy.XPATH, "//android.view.View[@content-desc='Back to main page']"))).click()
        logger.info("Returned to mobile app main page. txn_id=%s", txn_id)
           
    # Clean all notification 1 round
    @classmethod
    def kbank_business_apps_clean_notif(cls):
        logger.info("Starting notification cleanup flow")

        # Call Appium Driver
        driver = cls.use_appium_driver()

        # Screen never sleep
        driver.execute_script("mobile: shell", {"command": "settings", "args": ["put", "system", "screen_off_timeout", "2147483647"], "includeStderr": True, "timeout": 5000})

        # Expand Notification Bar
        driver.open_notifications()
        logger.info("Notification shade expanded")

        time.sleep(1)

        try:
            # Use find_elements so "not found" doesn't throw
            clear_buttons = driver.find_elements(AppiumBy.ACCESSIBILITY_ID, "Clear,Button")

            if clear_buttons:
                clear_buttons[0].click()
                logger.info("Tapped 'Clear all' notification button")
            else:
                logger.info("No 'Clear all' button found")

        except Exception:
            logger.exception("Error while trying to clear notifications")
        finally:
            # Always close shade
            driver.back()
                
    # Callback ERIC API
    @classmethod
    def eric_api(cls, data):
        txn_id = get_txn_id(data)
        logger.info("Calling ERIC callback API. txn_id=%s", txn_id)

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

        try:
            response = requests.post(url, headers=headers, data=payload_json)
            logger.info(
                "ERIC callback response received. txn_id=%s status=%s",
                txn_id,
                response.status_code,
            )
            logger.info("ERIC callback body. txn_id=%s body=%s", txn_id, response.text)
        except Exception:
            logger.exception("ERIC callback request failed. txn_id=%s", txn_id)
            raise

# ================== Code Start Here ==================

# Run API
@app.route("/kbank_company_web/runPython", methods=["POST"])        
def runPython():
    logger.info("Received /kbank_company_web/runPython request")
    data = request.get_json(silent=True)
    if not data:
        logger.warning("Rejected request due to invalid JSON body")
        return jsonify({"success": False, "message": "Invalid JSON"}), 400
    
    txn_id = get_txn_id(data)
    logger.info("Incoming payout request parsed. txn_id=%s", txn_id)

    with LOCK:
        logger.info("LOCK acquired for payout processing. txn_id=%s", txn_id)
        try:
            # Run Browser
            Automation.chrome_cdp()
            # Clean Notification Bar first
            BankBot.kbank_business_apps_clean_notif()
            # Login KBANK
            page = BankBot.kbank_login(data)
            logger.info("Processing payout started. txn_id=%s", txn_id)
            BankBot.kbank_withdrawal(page, data)
            logger.info("Processing payout completed. txn_id=%s", txn_id)
            return jsonify({
                "success": True,
                "transactionId": data["transactionId"]
            })
        except Exception as e:
            logger.exception("Withdrawal failed. txn_id=%s", txn_id)
            return jsonify({"success": False, "message": str(e)}), 500

if __name__ == "__main__":
    logger.info("KBANK Local API started on host=0.0.0.0 port=5004")
    app.run(host="0.0.0.0", port=5004, debug=False, threaded=False, use_reloader=False)
