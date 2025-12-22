import re
import os
import json
import time
import random
import atexit
import hashlib
import logging
import requests
import subprocess
from pathlib import Path
from datetime import datetime
from airtest.core.api import *
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright, expect
from poco.drivers.android.uiautomation import AndroidUiautomationPoco

# ================== Global Variable ==================

BASE_DIR = Path(__file__).resolve().parents[1]  # → Withdrawal/
QUEUE_FILE = BASE_DIR / "payout_queue.json"

# ================== Read .env file ==================

env_path = Path(__file__).parent / ".env"
load_dotenv(dotenv_path=env_path, override=True)

REQUIRED_ENV = [
    "SCB_USERNAME",
    "SCB_PASSWORD",
    "SCB_DEVICE_ID",
    "SCB_MERCHANT_CODE",
    "SCB_MERCHANT_CODE",
    "SCB_login_pass",
    "SCB_digital_token",
]

for key in REQUIRED_ENV:
    if not os.getenv(key):
        raise RuntimeError(f"Missing required env var: {key}")

# ================== LOG File ==================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
logger = logging.getLogger("Bot_Logger")

# ================== Job Queue ==================

class JobQueue:
    
    def __init__(self, path: Path):
        self.path = path

    def load(self):
        # File missing or empty → safe empty queue
        if not self.path.exists() or self.path.stat().st_size == 0:
            return []

        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            logger.warning("Queue file invalid or being written. Returning empty queue.")
            return []
    
    def save(self, queue):
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(queue, indent=2), encoding="utf-8")
        tmp.replace(self.path)

    def get_next_job(self):
        queue = self.load()
        for job in queue:
            if job.get("status") == "pending":
                job["status"] = "processing"
                job["startedAt"] = datetime.utcnow().isoformat()
                self.save(queue)
                return job
        return None

    def mark_done(self, txid, success=True, error=None):
        queue = self.load()
        for job in queue:
            if job["transactionId"] == txid:
                job["status"] = "done" if success else "failed"
                job["finishedAt"] = datetime.utcnow().isoformat()
                if error:
                    job["error"] = str(error)
                break
        self.save(queue)

# ================== Chrome Settings ==================

class Automation:
    chrome_proc = None

    # Chrome CDP
    @classmethod
    def chrome_cdp(cls):
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

# ================== BANK BOT ==================

class BankBot(Automation):
    
    _scb_ref = None
    
    # ==============================
    # -=-=-=-=-= SCB =-=-=-=-=-=-=-=
    # ==============================

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
    def scb_login(cls, p):
        
        # Connect to running Chrome
        browser = p.chromium.connect_over_cdp("http://localhost:9222")
        context = browser.contexts[0] if browser.contexts else browser.new_context()    

        # Open a new browser page
        page = context.pages[0] if context.pages else context.new_page()
        page.goto("https://www.scbbusinessanywhere.com/", wait_until="domcontentloaded")

        # For your online security, you have been logged out of SCB Business Anywhere (please log in again.)
        try:
            expect(page.get_by_text("For your online security, you have been logged out of SCB Business Anywhere")).to_be_visible(timeout=1000)
            page.locator("//span[normalize-space()='OK']").click(timeout=0) 
        except:
            pass
        
        # if Account already login, can skip
        try: 
            # Fill "Username"
            page.locator("//input[@name='username']").fill(os.getenv("SCB_USERNAME"), timeout=1000)

            # Button Click "Next"
            page.locator("//span[normalize-space()='Next']").click(timeout=0) 

            # Fill "Password"
            page.locator("//input[@name='password']").fill(os.getenv("SCB_PASSWORD"), timeout=0)

            # Button Click "Next"
            page.locator("//button[@type='submit']").click(timeout=0) 
        except:
            pass
        
        # Button Click "Transfer"
        page.locator("//p[normalize-space()='Transfers']").click(timeout=0) 

        return page

    # Withdrawal
    @classmethod
    def scb_withdrawal(cls, page, job):

        # Button Click "Add New Recipient"
        page.locator("//span[normalize-space()='Add New Recipient']").click(timeout=0) 
        
        # Fill Bank Name and Click
        page.get_by_label("Bank Name *").fill(str(job["toBankCode"]), timeout=0)
        page.get_by_text(str(job["toBankCode"]), exact=True).click(timeout=0)
        
        # Fill Account No.
        page.locator("//input[@id='accountNumber']").fill(str(job["toAccountNum"]), timeout=0)

        # Button Click "Next"
        page.locator("//span[normalize-space()='Next']").click(timeout=0) 

        # Wait for "Recipient Details"
        page.locator("//h4[normalize-space()='Recipient Details']").wait_for(timeout=0) 

        try:
            # Fill Account Name
            page.locator("//input[@name='accountName']").fill(str(job["toAccountName"]), timeout=2000)
        except:
            pass

        # Button Click "Confirm"
        page.locator("//span[normalize-space()='Confirm']").click(timeout=0) 

        # Button Click "Enter"
        page.locator("//span[normalize-space()='Enter']").click(timeout=0) 

        # Fill Amount
        page.locator("//input[@name='amount']").fill(str(job["amount"]), timeout=0)

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
        BankBot.scb_Anywhere_apps()

        # Button Click "Done"
        page.locator("//span[normalize-space()='Done']").click(timeout=1000)

        # Delay 0.5 second
        page.wait_for_timeout(500)

        # wait for "Review Information" to be appear
        page.locator("//h2[contains(text(),'You have successfully submitted the transaction re')]").wait_for(timeout=0) 
        
        # Wait for MUI backdrop animation to finish
        page.locator("div.MuiBackdrop-root").wait_for(state="hidden", timeout=5000)

        # Button Click Make New Transfer
        page.locator("//span[normalize-space()='Make New Transfer']").click(timeout=5000)

    # Read Apps OTP Code
    @classmethod
    def scb_Anywhere_apps(cls):

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
        start_app("com.scb.corporate")

        # Inactive Too Long
        try:
            poco(text="You have been inactive for too long").wait_for_appearance(timeout=1)
            # Click "Confirm"
            poco(text="Continue").click()
        except:
            pass
        
        # Session timeout
        try:
            poco(text="Session timeout").wait_for_appearance(timeout=1)
            # Click "Log In"
            poco(text="Log in").click()
        except:
            pass
        
        try:
            # Wait for "Enter PIN" appear
            poco(text="Enter PIN").wait_for_appearance(timeout=2)

            pin = os.getenv("SCB_login_pass")
            for digit in pin:
                key = poco(f"Login_{digit}")
                cls.human_click(poco, key)
        except:
            pass
        
        # Wait and Click Notifications
        poco(text="Notifications").wait_for_appearance(timeout=15)   
        poco("tabNotificationsStack").click()

        # Click "View request"
        poco(text="View request").wait_for_appearance(timeout=100)
        poco(text="View request").click()

        # Wait and Click "Submit for approval"
        poco("btApprove").click()
        
        # Key SCB Digital Token Pin
        token_pin = os.getenv("SCB_digital_token")
        for digit in token_pin:
            key = poco(f"SoftTokenInputPin_{digit}")
            cls.human_click(poco, key)

        time.sleep(3)
        
        # Click "Go to To-do List"
        poco(text="Approved").wait_for_appearance(timeout=15)
        poco("btTodoList").wait_for_appearance(timeout=10)
        poco("btTodoList").click()

    # Call back to ERIC API
    @classmethod
    def callback(cls, job):

        url = "https://stg-bot-integration.cloudbdtech.com/integration-service/transaction/payoutScriptCallback"

        payload = {
            "transactionId": job["transactionId"],
            "bankCode": job["toBankCode"],
            "deviceId": os.getenv("SCB_DEVICE_ID"),
            "merchantCode": os.getenv("SCB_MERCHANT_CODE"),
        }

        secret = "DEVBankBotIsTheBest"
        base = "&".join(f"{k}={v}" for k, v in payload.items()) + secret
        hash_val = hashlib.md5(base.encode()).hexdigest()

        requests.post(
            url,
            headers={"hash": hash_val, "Content-Type": "application/json"},
            data=json.dumps(payload)
        )

# ================== Code Start Here ==================

if __name__ == "__main__":
    queue = JobQueue(QUEUE_FILE)

    logger.info("🚀 SCB bot starting (env-based)")
    Automation.chrome_cdp()

    with sync_playwright() as p:
        page = BankBot.scb_login(p)
        logger.info("✅ Logged in once — waiting at transfer page")

        while True:
            job = queue.get_next_job()
            if not job:
                time.sleep(2)
                continue
            try:
                logger.info(f"▶ Processing {job['transactionId']}")
                BankBot.scb_withdrawal(page, job)
                queue.mark_done(job["transactionId"], True)
                logger.info(f"✔ Done {job['transactionId']}")
            except Exception as e:
                logger.exception("❌ Withdrawal failed")
                queue.mark_done(job["transactionId"], False, e)

