import os
import json
import time
import random
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
from appium.options.android import UiAutomator2Options
from appium.webdriver.common.appiumby import AppiumBy
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.actions.action_builder import ActionBuilder
from selenium.webdriver.common.actions.pointer_input import PointerInput
from selenium.webdriver.common.actions import interaction
from selenium.common.exceptions import TimeoutException


# =========================== Flask apps ==============================

app = Flask(__name__)
LOCK = Lock()

# ================== LOG File ==================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
logger = logging.getLogger("KBANK_Bot_Logger")

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
    
    _kbank_ref = None
    _driver = None

    @classmethod
    def _get_driver(cls):
        if cls._driver is not None:
            try:
                cls._driver.get_window_size()
                return cls._driver
            except Exception:
                try:
                    cls._driver.quit()
                except Exception:
                    pass
                cls._driver = None

        load_dotenv()
        server_url = os.getenv("APPIUM_SERVER_URL", "http://127.0.0.1:4723").rstrip("/")
        options = UiAutomator2Options()
        options.platform_name = "Android"
        options.automation_name = "UiAutomator2"
        options.device_name = os.getenv("APPIUM_DEVICE_NAME", "Android")
        udid = os.getenv("APPIUM_UDID")
        if udid:
            options.udid = udid
        platform_version = os.getenv("APPIUM_PLATFORM_VERSION")
        if platform_version:
            options.platform_version = platform_version
        app_package = os.getenv("APPIUM_APP_PACKAGE")
        app_activity = os.getenv("APPIUM_APP_ACTIVITY")
        if app_package:
            options.app_package = app_package
        if app_activity:
            options.app_activity = app_activity
        options.no_reset = True
        options.new_command_timeout = 300
        options.auto_grant_permissions = True

        cls._driver = webdriver.Remote(server_url, options=options)
        atexit.register(cls._cleanup_driver)
        return cls._driver

    @classmethod
    def _cleanup_driver(cls):
        if cls._driver:
            try:
                cls._driver.quit()
            except Exception:
                logger.exception("Appium cleanup error")
            finally:
                cls._driver = None

    @staticmethod
    def human_click_appium(driver, element):
        rect = element.rect
        cx = rect["x"] + rect["width"] / 2
        cy = rect["y"] + rect["height"] / 2

        offset_x = random.uniform(-0.15, 0.15) * rect["width"]
        offset_y = random.uniform(-0.15, 0.15) * rect["height"]

        x = int(cx + offset_x)
        y = int(cy + offset_y)

        finger = PointerInput(interaction.POINTER_TOUCH, "finger")
        actions = ActionBuilder(driver, mouse=finger)
        actions.pointer_action.move_to_location(x, y)
        actions.pointer_action.pointer_down()
        actions.pointer_action.pause(random.uniform(0.05, 0.15))
        actions.pointer_action.pointer_up()
        actions.perform()

        time.sleep(random.uniform(0.15, 0.35))
    
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
        page.locator("//div[@class='column-menu']//a[@id='BIZ_004']").click() 

        # wait for "Fund Transfer" to be appear
        page.locator("//h1[normalize-space()='Funds Transfer']").wait_for() 

        return page

    # Withdrawal
    @classmethod
    def kbank_withdrawal(cls, page, data):
        
        # Check if logged out
        try:
            page.locator("//span[normalize-space()='Sorry']").wait_for(state="visible",timeout=1000)
            cls.kbank_login(data)
        except:
            pass

        # wait for "Select Bank" to be appear
        page.locator("//span[@id='select2-id_select2_example_3-container']//div").wait_for(state="visible", timeout=10000)

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
        driver = cls._get_driver()
        pin = str(data["pin"])
        
        # Swipe
        def swipe_appium(driver, start, end, duration=0.5):
            finger = PointerInput(interaction.POINTER_TOUCH, "finger")
            actions = ActionBuilder(driver, mouse=finger)

            actions.pointer_action.move_to_location(start[0], start[1])
            actions.pointer_action.pointer_down()
            actions.pointer_action.pause(duration)
            actions.pointer_action.move_to_location(end[0], end[1])
            actions.pointer_action.pointer_up()
            actions.perform()

        # Enter Login Pin
        def enter_pin():

            # Wait for keypad to be fully ready
            WebDriverWait(driver, 10).until(EC.presence_of_element_located((AppiumBy.ACCESSIBILITY_ID, "Enter PIN")))
            WebDriverWait(driver, 10).until(EC.presence_of_element_located((AppiumBy.ACCESSIBILITY_ID, "1")))
            time.sleep(1)

            # key Pin
            for digit in str(pin):
                el = driver.find_element(AppiumBy.ANDROID_UIAUTOMATOR,f'new UiSelector().text("{digit}")')
                cls.human_click_appium(driver, el)
                time.sleep(0.2)

        # Confirm Transaction
        def confirm_transaction():
            
            # Wait for "Confirm Transaction"
            WebDriverWait(driver, 20).until(EC.visibility_of_element_located((AppiumBy.ANDROID_UIAUTOMATOR, 'new UiSelector().textContains("Confirm Transaction")')))

            # Scroll Down (same as your Poco code)
            swipe_appium(driver, (360, 1280), (360, 320), duration=0.5)
            swipe_appium(driver, (360, 1280), (360, 320), duration=0.5)

            # Button Click "Confirm"
            driver.find_element(AppiumBy.ANDROID_UIAUTOMATOR, 'new UiSelector().textContains("Confirm")').click()

            time.sleep(1)

            # Button Click "Confirm"s
            driver.find_element(AppiumBy.ANDROID_UIAUTOMATOR, 'new UiSelector().textContains("Confirm")').click()

        ### Click K BIZ Confirm transaction ###
        # Expand Notification Bar
        driver.execute_script("mobile: shell", {"command": "cmd", "args": ["statusbar", "expand-notifications"], "timeout": 2000})

        # Wait for SystemUI notification container
        WebDriverWait(driver, 10).until(EC.visibility_of_element_located((AppiumBy.ID, "com.android.systemui:id/notification_stack_scroller")))

        # Wait for the notification to appear and then click it
        target_text = "UNICORN NATIONAL"

        try:
            # Wait for notification containing "UNICORN NATIONAL" and click it
            notification = WebDriverWait(driver, 10).until(EC.element_to_be_clickable((AppiumBy.ANDROID_UIAUTOMATOR, f'new UiSelector().textContains("{target_text}")')))
            notification.click()

            # Wait for "Confirm transaction" notification/button
            target_notification = WebDriverWait(driver, 10).until(EC.element_to_be_clickable((AppiumBy.ANDROID_UIAUTOMATOR, 'new UiSelector().textContains("Confirm transaction")')))

            logger.info("✔ Found transaction notification, clicking...")
            target_notification.click()

        except TimeoutException:
            logger.error("❌ Could not find the UNICORN NATIONAL / Confirm transaction notification")

        # Delay 1 second
        time.sleep(1)

        # Check Session Expired or PIN Login or Transfer Page
        while True:

            # Session Expired dialog
            if driver.find_elements(AppiumBy.ANDROID_UIAUTOMATOR, 'new UiSelector().textContains("The session has expired")'):

                # Wait and Click "Yes"
                WebDriverWait(driver, 5).until(EC.element_to_be_clickable((AppiumBy.ANDROID_UIAUTOMATOR, 'new UiSelector().text("Yes")'))).click()

                # Wait for "Enter PIN"
                WebDriverWait(driver, 10).until(EC.presence_of_element_located((AppiumBy.ANDROID_UIAUTOMATOR, 'new UiSelector().textContains("Enter PIN")')))

                # ENTER PIN 
                enter_pin()

                # Confirm Transaction
                confirm_transaction()

                # Expand Notification Bar
                driver.execute_script("mobile: shell", {"command": "cmd", "args": ["statusbar", "expand-notifications"], "timeout": 2000})

                # Clear all notifications 
                clear_all = driver.find_elements(AppiumBy.ID, "com.android.systemui:id/notification_dismiss_view")
                
                # Check if button appears
                if clear_all:
                    # if exists then button click clear all
                    clear_all[0].click()
                    # else collapse notification bar
                else:
                    print("Clear All button NOT found, collapsing notification bar...")

                # Collapse notification bar
                driver.press_keycode(4)
                time.sleep(0.5)

                break

            # else if Enter Pin Page
            elif driver.find_elements(AppiumBy.ANDROID_UIAUTOMATOR, 'new UiSelector().textContains("Enter PIN")'):

                # Wait for "Enter PIN"
                WebDriverWait(driver, 10).until(EC.presence_of_element_located((AppiumBy.ANDROID_UIAUTOMATOR, 'new UiSelector().textContains("Enter PIN")')))

                try:
                    # Session Expired
                    if driver.find_elements(AppiumBy.ANDROID_UIAUTOMATOR, 'new UiSelector().textContains("The session has expired")'):

                        # Wait and Click "Yes"
                        WebDriverWait(driver, 5).until(EC.element_to_be_clickable((AppiumBy.ANDROID_UIAUTOMATOR, 'new UiSelector().text("Yes")'))).click()

                        # Wait for "Enter PIN"
                        WebDriverWait(driver, 10).until(EC.presence_of_element_located((AppiumBy.ANDROID_UIAUTOMATOR, 'new UiSelector().textContains("Enter PIN")')))

                        # ENTER PIN 
                        enter_pin()

                        # Confirm Transaction
                        confirm_transaction()

                        # Expand Notification Bar
                        driver.execute_script("mobile: shell", {"command": "cmd", "args": ["statusbar", "expand-notifications"], "timeout": 2000})

                        # Clear all notifications 
                        clear_all = driver.find_elements(AppiumBy.ID, "com.android.systemui:id/notification_dismiss_view")
                        
                        # Check if button appears
                        if clear_all:
                            # if exists then button click clear all
                            clear_all[0].click()
                            # else collapse notification bar
                        else:
                            print("Clear All button NOT found, collapsing notification bar...")

                        # Collapse notification bar
                        driver.press_keycode(4)
                        time.sleep(0.5)

                        # Exit While Loop
                        break
                except:
                    pass

                # Key PIN
                enter_pin()

                # Confirm Transaction
                confirm_transaction()

                # Expand Notification Bar
                driver.execute_script("mobile: shell", {"command": "cmd", "args": ["statusbar", "expand-notifications"], "timeout": 2000})

                # Define Clear All button
                clear_all = driver.find_elements(AppiumBy.ID, "com.android.systemui:id/notification_dismiss_view")

                # Check if button appears
                if clear_all:
                    # if exists then button click clear all
                    clear_all[0].click()
                    # else collapse notification bar
                else:
                    print("Clear All button NOT found, collapsing notification bar...")

                # Collapse Notification bar
                driver.execute_script("mobile: shell", {"command": "cmd", "args": ["statusbar", "collapse"], "timeout": 2000})

                # Exit While Loop
                break
            
            # Wait for "Confirm Transaction"
            elif bool(driver.find_elements(AppiumBy.ANDROID_UIAUTOMATOR, 'new UiSelector().textContains("Confirm Transaction")')):
                try:
                    # Session Expired
                    if driver.find_elements(AppiumBy.ANDROID_UIAUTOMATOR, 'new UiSelector().textContains("The session has expired")'):

                        # Wait and Click "Yes"
                        WebDriverWait(driver, 5).until(EC.element_to_be_clickable((AppiumBy.ANDROID_UIAUTOMATOR, 'new UiSelector().text("Yes")'))).click()

                        # Wait for "Enter PIN"
                        WebDriverWait(driver, 10).until(EC.presence_of_element_located((AppiumBy.ANDROID_UIAUTOMATOR, 'new UiSelector().textContains("Enter PIN")')))

                        # ENTER PIN 
                        enter_pin()

                        # Confirm Transaction
                        confirm_transaction()

                        # Expand Notification Bar
                        driver.execute_script("mobile: shell", {"command": "cmd", "args": ["statusbar", "expand-notifications"], "timeout": 2000})

                        # Clear all notifications 
                        clear_all = driver.find_elements(AppiumBy.ID, "com.android.systemui:id/notification_dismiss_view")
                        
                        # Check if button appears
                        if clear_all:
                            # if exists then button click clear all
                            clear_all[0].click()
                            # else collapse notification bar
                        else:
                            print("Clear All button NOT found, collapsing notification bar...")

                        # Collapse notification bar
                        driver.press_keycode(4)
                        time.sleep(0.5)

                        # Exit While Loop
                        break
                except:
                    pass

                # Confirm Transaciton
                confirm_transaction()

                # Expand Notification Bar
                driver.execute_script("mobile: shell", {"command": "cmd", "args": ["statusbar", "expand-notifications"], "timeout": 2000})

                # Define Clear All button
                clear_all = driver.find_elements(AppiumBy.ID, "com.android.systemui:id/notification_dismiss_view")

                # Check if button appears
                if clear_all:
                    # if exists then button click clear all
                    clear_all[0].click()
                    # else collapse notification bar
                else:
                    print("Clear All button NOT found, collapsing notification bar...")

                # Collapse Notification bar
                driver.execute_script("mobile: shell", {"command": "cmd", "args": ["statusbar", "collapse"], "timeout": 2000})

                # Exit While Loop
                break
            
            # Delay 0.5 second
            time.sleep(0.5)
        
        # Wait for "Back to main page" and click
        WebDriverWait(driver, 20).until(EC.element_to_be_clickable((AppiumBy.ANDROID_UIAUTOMATOR, 'new UiSelector().text("Back to main page")'))).click()

        
    # Clean all notification 1 round
    @classmethod
    def kbank_business_apps_clean_notif(cls):
        driver = cls._get_driver()

        # Hide Debug Log, if want view, just comment the bottom code
        logging.getLogger("airtest").setLevel(logging.WARNING)
        logging.getLogger("pocoui").setLevel(logging.WARNING) 
        logging.getLogger("airtest.core.helper").setLevel(logging.WARNING)

        # Check screen state (if screenoff then wake up, else skip)
        output = driver.execute_script("mobile: shell", {
            "command": "dumpsys",
            "args": ["power"],
            "includeStderr": True,
            "timeout": 5000
        })["stdout"]

        if "mWakefulness=Awake" in output:
            print("Screen already ON → pass")
        else:
            print("Screen is OFF → waking")
            driver.execute_script("mobile: shell", {"command": "input", "args": ["keyevent", "KEYCODE_WAKEUP"]})
            driver.execute_script("mobile: shell", {"command": "input", "args": ["keyevent", "26"]})  # POWER toggle as fallback

        # Expand Notification Bar
        driver.execute_script("mobile: shell", {"command": "cmd", "args": ["statusbar", "expand-notifications"], "timeout": 2000})

        # Swipe notification away using coordinates
        driver.swipe(58, 719, 702, 721, 10)

        # Clear all notifications 
        clear_all = driver.find_elements(AppiumBy.ID, "com.android.systemui:id/notification_dismiss_view")
        
        # Check if button appears
        if clear_all:
            # if exists then button click clear all
            clear_all[0].click()
            # else collapse notification bar
        else:
            print("Clear All button NOT found, collapsing notification bar...")

        # Collapse notification bar
        driver.press_keycode(4)
        time.sleep(0.5)

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
