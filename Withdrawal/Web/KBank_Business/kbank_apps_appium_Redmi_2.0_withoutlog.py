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

# =========================== LOG File ================================

LOG_DIR = "logs"
os.makedirs(LOG_DIR, exist_ok=True)

LOG_FILE = os.path.join(LOG_DIR, "kbank_payout_redmi.log")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger("KBANK_BOT__Redmi_Logger")
logger.info(f"✅ Logging started: {LOG_FILE}")

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

# ================== KBANK BANK BOT ==================

class BankBot(Automation):
    
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
                options.new_command_timeout = 2000

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
        APPIUM_PROC = subprocess.Popen([
            "appium", "--port", "8021",
            "--allow-insecure", "uiautomator2:adb_shell",
            "--allow-cors"
        ])
                
        # Wait until Appium server is ready, retry 10 times
        for _ in range(10):
            try:
                if requests.get("http://127.0.0.1:8021/status").ok:
                    return
            except:
                time.sleep(1)

        # if after 10 times retry, appium still not ready, then raise the error to stop the program
        raise RuntimeError("Appium not started")
    
    # Login
    @classmethod
    def kbank_login(cls, data):
        
        global PLAYWRIGHT, BROWSER, CONTEXT, PAGE

        # Clean Notification Bar first
        BankBot.kbank_business_apps_clean_notif()

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

        # Check if logged out
        try:
            page.locator("//span[normalize-space()='Sorry']").wait_for(state="visible",timeout=1500)
            cls.kbank_login(data)
        except:
            pass

        # If already on transfer page, skip login
        try:
            page.locator("//h1[normalize-space()='Funds Transfer']").wait_for(timeout=1500)
            return page # Already Login
        except:
            pass

        # Go to a webpage
        page.goto("https://kbiz.kasikornbank.com/authen/login.jsp?lang=en", wait_until="domcontentloaded")

        # if Account already login, can skip
        try: 
            # Fill "User ID"
            page.locator("//input[@id='userName']").fill(str(data["username"]))

            # Fill "Password"
            page.locator("//input[@id='password']").fill(str(data["password"]))

            # Button Click "Log In"
            page.locator("//a[@id='loginBtn']").click()
        except:
            pass

        # Button Click "Fund Transfer"
        page.locator("//div[@class='column-menu']//a[@id='BIZ_004']").click(timeout=100000) 

        # wait for "Fund Transfer" to be appear
        page.locator("//h1[normalize-space()='Funds Transfer']").wait_for() 

        return page

    # Withdrawal
    @classmethod
    def kbank_withdrawal(cls, page, data):
        
        # wait for "Select Bank" to be appear
        page.locator("//span[@id='select2-id_select2_example_3-container']//div").wait_for(state="visible", timeout=100000)

        # Delay 1 second
        time.sleep(1)
        
        # Button Click "Select Bank"
        page.locator("//span[@id='select2-id_select2_example_3-container']//div").click()

        # Locate the input
        page.locator("input.select2-search__field").evaluate("el => el.removeAttribute('readonly')")
        page.locator("input.select2-search__field").fill(str(data["toBankCode"]))

        # if element == bank code name, then click the third element, else click first element
        if page.locator("//span[@id='select2-id_select2_example_3-container']//span").inner_text().strip() == data["toBankCode"]:
            page.locator(f"//div[span[normalize-space()='{data['toBankCode']}']]").nth(2).click()
        else:
            page.locator(f"//div[span[normalize-space()='{data['toBankCode']}']]").click()

        # Fill Account No.
        page.locator("//input[@placeholder='xxx-x-xxxxx-x']").fill(str(data["toAccountNum"]))

        # Fill Amount
        page.locator("//input[@placeholder='0.00']").fill(str(data["amount"]))

        # Button Click "Next"
        page.locator("//a[@class='btn btn-gradient f-right disabled-button']").click()

        # if Notice | You or Company has made this transaction already .... if this appear click confirm else skip
        try: 
            expect(page.locator("//div[@class='mfp-content']//h3[contains(text(),'Notice')]")).to_be_visible(timeout=4000)
            # Button Click "Confirm"
            page.locator("//div[@class='mfp-content']//span[contains(text(),'Confirm')]").click()
        except:
            pass

        # Wait for "Confirm Transaction" appear
        page.locator("//app-notification-modal-header//h3[1]").wait_for(state="visible", timeout=100000)

        # Kbank Apps Approved   
        cls.kbank_business_apps(data)

        # Callback Eric API
        cls.eric_api(data)

        # wait for "Fund Transfer" to be appear
        page.locator("//div[@class='column-menu']//a[@id='BIZ_004']").wait_for(state="visible", timeout=10000)
        
        # Button Click "Fund Transfer"
        page.locator("//div[@class='column-menu']//a[@id='BIZ_004']").click() 

        # wait for "Fund Transfer" to be appear
        page.locator("//h1[normalize-space()='Funds Transfer']").wait_for(state="visible", timeout=10000)

    # Apps Approved Transaction
    @classmethod
    def kbank_business_apps(cls, data):
        
        # Call Appium driver
        driver = cls.use_appium_driver()

        # Enter Login Pin
        def enter_pin():

            # Wait for "Enter PIN" to appear
            WebDriverWait(driver, 30).until(EC.presence_of_element_located((AppiumBy.XPATH, "//android.view.View[@content-desc='Enter PIN']")))

            # Enter Pin
            pin = str(data["pin"])
            for digit in pin:
                digit_button = WebDriverWait(driver, 10).until(EC.element_to_be_clickable((AppiumBy.ACCESSIBILITY_ID, digit)))
                digit_button.click()

        # Confirm Transaction
        def confirm_transaction():

            # Scroll Down Confirmation Transaction
            def scroll_down(driver, times=2, duration=500):
                size = driver.get_window_size()
                x = size["width"] // 2

                start_y = int(size["height"] * 0.80)
                end_y = int(size["height"] * 0.25)

                for _ in range(times):
                    driver.swipe(x, start_y, x, end_y, duration)

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

        ### Click K BIZ Confirm transaction ###
        # Expand Notification Bar
        driver.open_notifications()

        # Wait for SystemUI notification container
        WebDriverWait(driver, 10).until(EC.presence_of_element_located((AppiumBy.ID, "com.android.systemui:id/notification_stack_scroller")))

        # Click notification that contains "UNICORN NATIONAL"
        target_text = "UNICORN NATIONAL"
        notif_xpath = f"//*[contains(@text,'{target_text}') or contains(@content-desc,'{target_text}')]"
        WebDriverWait(driver, 10).until(EC.element_to_be_clickable((AppiumBy.XPATH, notif_xpath))).click()

        # Find + click "Confirm transaction" (if exists)
        confirm_text = "Confirm transaction"
        confirm_xpath = f"//*[contains(@text,'{confirm_text}') or contains(@content-desc,'{confirm_text}')]"

        if driver.find_elements(AppiumBy.XPATH, confirm_xpath):
            logger.info("✔ Found transaction notification, clicking...")
            WebDriverWait(driver, 10).until(EC.element_to_be_clickable((AppiumBy.XPATH, confirm_xpath))).click()
        else:
            logger.error("❌ Could not find the UNICORN NATIONAL notification")
        
        # Delay 1 second
        time.sleep(1)
        
        while True:
            try:
                # Session Expired
                if driver.find_elements(AppiumBy.XPATH, "//*[contains(@content-desc,'session has expired')]"):

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
                    except:
                        pass

                    # Enter PIN
                    enter_pin()

                    # Confirm Transaction
                    confirm_transaction()
          
                    # Break While Loop
                    break
                
                # Wait for "Confirm Transaction"
                elif driver.find_elements(AppiumBy.XPATH, "//*[contains(@text,'Confirm Transaction')]"):
                    try:
                        if driver.find_elements(AppiumBy.XPATH, "//*[contains(@content-desc,'session has expired')]"):

                            # Button Click "Yes"
                            driver.find_element(AppiumBy.XPATH, "//android.widget.Button[@content-desc='Yes']").click()

                            # Enter PIN
                            enter_pin()

                            # Confirm Transaction
                            confirm_transaction()

                            # Break While Loop
                            break
                    except:
                        pass

                    # Confirm Transaction
                    confirm_transaction()
                    
                    # Break While Loop
                    break

            except TimeoutException:
                continue

        # Wait and Click "Back to main page"
        WebDriverWait(driver, 20).until(EC.element_to_be_clickable((AppiumBy.XPATH, "//android.view.View[@content-desc='Back to main page']"))).click()
           
    # Clean all notification 1 round
    @classmethod
    def kbank_business_apps_clean_notif(cls):

        # Swipe all notification
        def swipe_all_notifications(driver, max_swipes=1):
            
            # Open Notification Bar
            driver.open_notifications()

            # swipe left clear one notification
            for _ in range(max_swipes):
                notifs = driver.find_elements(
                    AppiumBy.ANDROID_UIAUTOMATOR,
                    'new UiSelector().resourceIdMatches(".*(notification|row).*")'
                )
                if not notifs:
                    break

                # Swipe the first one left
                n = notifs[0]
                r = n.rect
                y = r["y"] + r["height"] // 2
                start_x = r["x"] + int(r["width"] * 0.85)
                end_x   = r["x"] + int(r["width"] * 0.15)

                driver.swipe(start_x, y, end_x, y, 100)

        # Call Appium Driver
        driver = cls.use_appium_driver()

        # Expand Notification Bar
        driver.open_notifications()

        # Swipe notification away using coordinates
        swipe_all_notifications(driver)

        time.sleep(1)

        # Define Clear All button
        clear_all = driver.find_elements(AppiumBy.ID, "com.android.systemui:id/notification_dismiss_view")

        # Check if button appears, if True then click X clear All button, else Close Notification Bar
        if clear_all:
            clear_all[0].click()
        else:
            # Close Notification Bar
            driver.back()
                
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
            # Login KBANK
            page = BankBot.kbank_login(data)
            logger.info(f"▶ Processing {data['transactionId']}")
            BankBot.kbank_withdrawal(page, data)
            logger.info(f"✔ Done {data['transactionId']}")
            return jsonify({
                "success": True,
                "transactionId": data["transactionId"]
            })
        except Exception as e:
            logger.exception("❌ Withdrawal failed")
            return jsonify({"success": False, "message": str(e)}), 500

if __name__ == "__main__":
    logger.info("🚀 KBANK Local API started")
    app.run(host="0.0.0.0", port=5004, debug=False, threaded=False, use_reloader=False)
 