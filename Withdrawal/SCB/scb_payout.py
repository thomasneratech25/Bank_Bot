import json
import time
import random
import atexit
import hashlib
import logging
import requests
import queue
import threading
import subprocess
from threading import Lock
from flask import Flask, request, jsonify
from playwright.sync_api import sync_playwright, expect
from airtest.core.api import *
from poco.drivers.android.uiautomation import AndroidUiautomationPoco

# =========================== Flask apps ==============================

app = Flask(__name__)
LOCK = Lock()

# IDLE 
IDLE_SECONDS = 174 # 2.9 minutes
SCB_APP_PACKAGE = "com.scb.corporate"

# ================== LOG File ==================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
logger = logging.getLogger("SCB_Bot_Logger")

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
                done.set()

    @staticmethod
    def _idle_logout():
        global PAGE
        try:
            logger.info("Auto cleanup after %ss idle", IDLE_SECONDS)
            BankBot.scb_kill_apps()
            if PAGE and not PAGE.is_closed():
                BankBot.scb_logout(PAGE)
        except Exception:
            logger.exception("Idle cleanup failed")

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
        
        USER_DATA_DIR = r"C:\Users\Thomas\AppData\Local\Google\Chrome\User Data\Profile99"

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

# ================== SCB BANK BOT ==================

class BankBot(Automation):

    # Simulate Human Click (Faster way)
    @staticmethod
    def human_click(poco, poco_obj):
        # get position of the element
        pos = poco_obj.get_position()

        # convert to screen coords
        w, h = poco.get_screen_size()
        abs_x, abs_y = pos[0] * w, pos[1] * h

        # random offset (human jitter)
        offset_x = random.uniform(-0.01, 0.01) * w
        offset_y = random.uniform(-0.01, 0.01) * h

        # simulate tap
        touch([abs_x + offset_x, abs_y + offset_y])

        # small human delay
        time.sleep(random.uniform(0.15, 0.35))

    # Login
    @classmethod
    def scb_login(cls, data):

        global PLAYWRIGHT, BROWSER, CONTEXT, PAGE

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
            PAGE.bring_to_front()

        page = PAGE

        page.goto("https://www.scbbusinessanywhere.com/", wait_until="networkidle")

        # For your online security, you have been logged out of SCB Business Anywhere (please log in again.)
        try:
            expect(page.get_by_text("For your online security, you have been logged out of SCB Business Anywhere")).to_be_visible(timeout=1000)
            page.locator("//span[normalize-space()='OK']").click(timeout=0) 
        except:
            pass
        
        # if Account already login, can skip
        try: 
            # Fill "Username"
            page.locator("//input[@name='username']").fill(str(data["username"]), timeout=1000)

            # Button Click "Next"
            page.locator("//span[normalize-space()='Next']").click(timeout=0) 

            # Fill "Password"
            page.locator("//input[@name='password']").fill(str(data["password"]), timeout=0)

            # Button Click "Next"
            page.locator("//button[@type='submit']").click(timeout=0) 
        except:
            pass
        
        # only click Transfers if NOT on login page
        if not page.locator("//input[@name='username']").is_visible():
            # Button Click "Transfer"
            page.locator("//p[normalize-space()='Transfers']").click(timeout=0)

        return page

    # Withdrawal
    @classmethod
    def scb_withdrawal(cls, page, data):

        # Button Click "Add New Recipient"
        page.locator("//span[normalize-space()='Add New Recipient']").click(timeout=10000) 
        
        # Fill Bank Name and Click
        page.get_by_label("Bank Name *").fill(str(data["toBankCode"]), timeout=0)
        page.keyboard.press("ArrowDown")
        page.keyboard.press("Enter")

        # Fill Account No.
        page.locator("//input[@id='accountNumber']").fill(str(data["toAccountNum"]), timeout=0)

        # Button Click "Next"
        page.locator("//span[normalize-space()='Next']").click(timeout=0) 

        # Wait for "Recipient Details"
        page.locator("//h4[normalize-space()='Recipient Details']").wait_for(timeout=0) 

        try:
            # Fill Account Name
            page.locator("//input[@name='accountName']").fill(str(data["toAccountName"]), timeout=2000)
        except:
            pass

        # Button Click "Confirm"
        page.locator("//span[normalize-space()='Confirm']").click(timeout=0) 

        # Button Click "Enter"
        page.locator("//span[normalize-space()='Enter']").click(timeout=0) 

        # Fill Amount
        page.locator("//input[@name='amount']").fill(str(data["amount"]), timeout=0)

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
        BankBot.scb_Anywhere_apps(data)

        # Button Click "Done"
        page.locator("//span[normalize-space()='Done']").click(timeout=1000)

        # Delay 0.5 second
        page.wait_for_timeout(500)

        # wait for "Review Information" to be appear
        page.locator("//h2[contains(text(),'You have successfully submitted the transaction re')]").wait_for(timeout=0) 
        
        # Wait for MUI backdrop animation to finish
        page.locator("div.MuiBackdrop-root").wait_for(state="hidden", timeout=5000)

        # Call Eric API
        cls.eric_api(data)

        # Button Click Make New Transfer
        page.locator("//span[normalize-space()='Make New Transfer']").click(timeout=5000)

    # Read Apps OTP Code
    @classmethod
    def scb_Anywhere_apps(cls, data):

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
        start_app(SCB_APP_PACKAGE)

        # Inactive Too Long
        try:
            poco(text="You have been inactive for too long").wait_for_appearance(timeout=1)
            # Click "Continue"
            poco(text="Continue").click()
            poco(text="Continue").click()
        except:
            pass
        
        try:
            # Wait for "Enter PIN" appear
            poco(text="Enter PIN").wait_for_appearance(timeout=3)

            pin = str(data["pin"])
            for digit in pin:
                key = poco(f"Login_{digit}")
                cls.human_click(poco, key)
        except:
            pass
        
        # Wait and Click Notifications
        poco(text="Notifications").wait_for_appearance(timeout=1000)   
        poco("tabNotificationsStack").click()

        # Click "View request"
        poco(text="View request").wait_for_appearance(timeout=1000)
        poco(text="View request").click()

        # Wait and Click "Submit for approval"
        poco("btApprove").click()
        
        # Key SCB Digital Token Pin
        token_pin = str(data["scbDigitalTokenPin"])
        for digit in token_pin:
            key = poco(f"SoftTokenInputPin_{digit}")
            key.wait_for_appearance(timeout=2)
            time.sleep(0.15)               
            cls.human_click(poco, key)
            time.sleep(0.25)                    

        time.sleep(3)
        
        # Click "Go to To-do List"
        poco(text="Approved").wait_for_appearance(timeout=15)
        poco("btTodoList").wait_for_appearance(timeout=10)
        poco("btTodoList").click()

    # Logout
    @classmethod
    def scb_logout(cls, page):

        # Clear all cookies
        page.context.clear_cookies()

        # clear storage
        page.evaluate("""
            () => {
                localStorage.clear();
                sessionStorage.clear();
            }
        """)

        # Reload page if cookies affect session
        page.reload(wait_until="networkidle")

    # Kill SCB app
    @classmethod
    def scb_kill_apps(cls):
        try:
            stop_app(SCB_APP_PACKAGE)
            logger.info("Stopped SCB app: %s", SCB_APP_PACKAGE)
            return
        except Exception:
            logger.exception("stop_app failed for SCB app")

        try:
            device().adb.shell(f"am force-stop {SCB_APP_PACKAGE}")
            logger.info("Force-stopped SCB app via adb: %s", SCB_APP_PACKAGE)
        except Exception:
            logger.exception("ADB force-stop failed for SCB app")

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

def process_withdrawal(data):
    page = BankBot.scb_login(data)
    logger.info(f"Processing {data['transactionId']}")

    BankBot.scb_withdrawal(page, data)

    logger.info(f"Done {data['transactionId']}")
    return data["transactionId"]

@app.route("/scb_company_web/runPython", methods=["POST"])
def runPython():
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"success": False, "message": "Invalid JSON"}), 400

    worker = get_worker()

    with LOCK:
        try:
            transaction_id = worker.submit(process_withdrawal, data)

            return jsonify({
                "success": True,
                "transactionId": transaction_id
            })

        except Exception as e:
            logger.exception("Withdrawal failed")
            return jsonify({"success": False, "message": str(e)}), 500

# ================== MAIN ==============================

if __name__ == "__main__":
    logger.info("🚀 SCB Local API started")
    app.run(host="0.0.0.0", port=5001, debug=False, threaded=False, use_reloader=False)

