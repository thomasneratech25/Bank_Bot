import json
import os
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
from appium.options.android import UiAutomator2Options
from appium.webdriver.common.appiumby import AppiumBy
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

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
    _appium_driver = None

    @classmethod
    def _get_driver(cls):
        if cls._appium_driver is not None:
            try:
                cls._appium_driver.get_window_size()
                return cls._appium_driver
            except Exception:
                try:
                    cls._appium_driver.quit()
                except Exception:
                    pass
                cls._appium_driver = None

        load_dotenv()
        server_url = os.getenv("APPIUM_SERVER_URL", "http://127.0.0.1:4723")

        options = UiAutomator2Options()
        options.set_capability("platformName", "Android")
        options.set_capability("automationName", "UiAutomator2")
        options.set_capability("deviceName", os.getenv("ANDROID_DEVICE_NAME", "Android"))
        options.set_capability("noReset", True)

        app_package = os.getenv("APPIUM_APP_PACKAGE")
        app_activity = os.getenv("APPIUM_APP_ACTIVITY")
        if app_package:
            options.set_capability("appPackage", app_package)
        if app_activity:
            options.set_capability("appActivity", app_activity)

        extra_caps = os.getenv("APPIUM_CAPS_JSON")
        if extra_caps:
            try:
                for key, value in json.loads(extra_caps).items():
                    options.set_capability(key, value)
            except json.JSONDecodeError:
                logger.warning("Invalid APPIUM_CAPS_JSON; ignoring.")

        cls._appium_driver = webdriver.Remote(server_url, options=options)
        return cls._appium_driver

    @staticmethod
    def _wake_device(driver):
        try:
            result = driver.execute_script(
                "mobile: shell",
                {"command": "dumpsys", "args": ["power"]},
            )
            output = (result or {}).get("stdout", "")
        except Exception:
            return

        if "mWakefulness=Awake" in output:
            return

        if "mWakefulness=Asleep" in output or "mWakefulness=Dozing" in output:
            driver.press_keycode(26)
            time.sleep(0.5)

    @staticmethod
    def _clear_notifications(driver):
        try:
            driver.open_notifications()
            WebDriverWait(driver, 5).until(
                EC.presence_of_element_located(
                    (AppiumBy.ID, "com.android.systemui:id/notification_stack_scroller")
                )
            )
        except Exception:
            return

        size = driver.get_window_size()
        y = int(size["height"] * 0.45)
        driver.swipe(
            int(size["width"] * 0.1),
            y,
            int(size["width"] * 0.9),
            y,
            200,
        )

        clear_all = driver.find_elements(
            AppiumBy.ID, "com.android.systemui:id/notification_dismiss_view"
        )
        if clear_all:
            clear_all[0].click()
            time.sleep(0.5)

        try:
            driver.back()
        except Exception:
            pass
    
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
        cls._wake_device(driver)

        def ui(text=None, contains=None, matches=None):
            if text is not None:
                return (AppiumBy.ANDROID_UIAUTOMATOR, f'new UiSelector().text("{text}")')
            if contains is not None:
                return (
                    AppiumBy.ANDROID_UIAUTOMATOR,
                    f'new UiSelector().textContains("{contains}")',
                )
            if matches is not None:
                return (
                    AppiumBy.ANDROID_UIAUTOMATOR,
                    f'new UiSelector().textMatches("{matches}")',
                )
            raise ValueError('ui() requires text, contains, or matches')

        def wait_visible(locator, timeout=30):
            return WebDriverWait(driver, timeout).until(
                EC.visibility_of_element_located(locator)
            )

        # Open notification shade and click the transaction notification
        driver.open_notifications()
        wait_visible(
            (AppiumBy.ID, 'com.android.systemui:id/notification_stack_scroller'),
            10,
        )

        target_text = 'UNICORN NATIONAL'
        notif = driver.find_elements(*ui(contains=target_text))
        if notif:
            notif[0].click()
        else:
            logger.error("Could not find notification containing '%s'", target_text)

        confirm_locator = ui(matches='(?i).*confirm transaction.*')
        confirm_notif = driver.find_elements(*confirm_locator)
        if confirm_notif:
            confirm_notif[0].click()
        else:
            logger.error('Could not find the confirm transaction notification')

        time.sleep(1)

        session_expired = ui(contains='session has expired')
        enter_pin = ui(contains='Enter PIN')
        confirm_screen = ui(matches='(?i).*confirm transaction.*')
        confirm_button = ui(text='Confirm')
        yes_button = ui(text='Yes')

        pin_entered = False

        def find_digit_button(digit):
            locators = [
                ui(text=digit),
                (AppiumBy.ANDROID_UIAUTOMATOR, f'new UiSelector().description("{digit}")'),
                (AppiumBy.ACCESSIBILITY_ID, digit),
            ]
            for locator in locators:
                try:
                    elems = driver.find_elements(*locator)
                    if elems:
                        return elems[0]
                except Exception:
                    continue
            return None

        while True:
            if driver.find_elements(*session_expired):
                try:
                    wait_visible(yes_button, 5).click()
                    pin_entered = False
                except Exception:
                    pass

            if not pin_entered and driver.find_elements(*enter_pin):
                wait_visible(enter_pin, 30)
                for digit in str(data['pin']):
                    if not str(digit).isdigit():
                        raise RuntimeError(f"PIN must be numeric, got '{digit}'")
                    button = find_digit_button(digit)
                    if button:
                        button.click()
                    else:
                        try:
                            driver.press_keycode(7 + int(digit))
                        except Exception as e:
                            raise RuntimeError(f"PIN digit not found: {digit}") from e
                    time.sleep(0.2)
                pin_entered = True

            if driver.find_elements(*confirm_screen):
                wait_visible(confirm_screen, 20)

                size = driver.get_window_size()
                start_x = size['width'] // 2
                start_y = int(size['height'] * 0.8)
                end_y = int(size['height'] * 0.2)
                driver.swipe(start_x, start_y, start_x, end_y, 600)
                driver.swipe(start_x, start_y, start_x, end_y, 600)

                wait_visible(confirm_button, 10).click()
                time.sleep(1)
                wait_visible(confirm_button, 10).click()

                cls._clear_notifications(driver)
                break

            time.sleep(0.5)

        wait_visible(ui(text='Back to main page'), 20).click()

    # Clean all notification 1 round
    @classmethod
    def kbank_business_apps_clean_notif(cls):
        driver = cls._get_driver()
        cls._wake_device(driver)
        cls._clear_notifications(driver)

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

        # Debug info
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
            logger.info(f"Processing {data['transactionId']}")
            BankBot.kbank_withdrawal(page, data)
            logger.info(f"Done {data['transactionId']}")
            return jsonify({
                "success": True,
                "transactionId": data["transactionId"]
            })
        except Exception as e:
            logger.exception("Withdrawal failed")
            return jsonify({"success": False, "message": str(e)}), 500

if __name__ == "__main__":
    logger.info("KBANK Local API started")
    app.run(host="0.0.0.0", port=5004, debug=False, threaded=False, use_reloader=False)
