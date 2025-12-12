import re
import os
import json
import time
import atexit
import hashlib
import logging
import requests
import subprocess
from pathlib import Path
from dotenv import load_dotenv
from datetime import datetime
from playwright.sync_api import sync_playwright
from airtest.core.api import *
from poco.drivers.android.uiautomation import AndroidUiautomationPoco

# ================== Global Variable ==================

QUEUE_FILE = Path(__file__).parent / "kma_queue.json"

# ================== Read .env file ==================

env_path = Path(__file__).parent / ".env"
load_dotenv(dotenv_path=env_path, override=True)

REQUIRED_ENV = [
    "KMA_USERNAME",
    "KMA_PASSWORD",
    "KMA_DEVICE_ID",
    "KMA_MERCHANT_CODE",
]

for key in REQUIRED_ENV:
    if not os.getenv(key):
        raise RuntimeError(f"Missing required env var: {key}")

# ================== LOG File ==================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
logger = logging.getLogger("KMA-BOT")

# ================== Job Queue ==================

class JobQueue:
    
    def __init__(self, path: Path):
        self.path = path

    def load(self):
        if not self.path.exists():
            return []
        return json.loads(self.path.read_text(encoding="utf-8"))

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
    _kma_ref = None

    # Login
    @classmethod
    def login(cls, p):
        
        # Connect to running Chrome
        browser = p.chromium.connect_over_cdp("http://localhost:9222")
        context = browser.contexts[0] if browser.contexts else browser.new_context()

        # Open a new browser
        page = context.pages[0] if context.pages else context.new_page()

        # Go to a webpage
        page.goto("https://www.krungsribizonline.com/BAY.KOL.Corp.WebSite/Common/Login.aspx?language=en", wait_until="domcontentloaded")

        # Fill in Username
        page.fill("#ctl00_cphLoginBox_txtUsernameSME", os.getenv("KMA_USERNAME"))

        # Fill in Password
        page.fill("#ctl00_cphLoginBox_txtPasswordSME", os.getenv("KMA_PASSWORD"))

        # Button Click Login
        page.click("#ctl00_cphLoginBox_imgLogin")

        # Click "Other Account"
        page.locator("//div[normalize-space()='Other Account']").click()
        page.wait_for_timeout(2000)
        return page

    # Withdrawal
    @classmethod
    def withdraw(cls, page, job):

        # Select Bank Code
        page.select_option("#ddlBanking", job["toBankCode"])

        # Fill in Account Number
        page.fill("#ctl00_cphSectionData_txtAccTo", job["toAccountNum"])

        # Fill in Amount
        page.fill("#ctl00_cphSectionData_txtAmountTransfer", job["amount"])

        # Click Submit
        page.click("#ctl00_cphSectionData_btnSubmit")

        # Wait for OTP Box Appear
        page.locator(".otpbox_header").wait_for(timeout=10000)

        # Capture OTP Reference Number
        cls._kma_ref = page.locator("//div[@class='inputbox_half_center']//div[@class='input_input_half']").first.inner_text()

        # Run Read OTP Code
        otp = cls.read_otp()

        # Fill OTP Code
        page.fill("#ctl00_cphSectionData_OTPBox1_txtOTPPassword", otp)

        # Click Button Confirm
        page.click("#ctl00_cphSectionData_OTPBox1_btnConfirm")

        # Wait for Appear withdrawal Successful
        page.locator("#ctl00_cphSectionData_pnlSuccessMsg").wait_for(timeout=10000)

        # Call Eric API
        cls.callback(job)

        # Button click "Transfer other transaction"
        page.click("#ctl00_cphSectionData_btnOtherTxn")

    # Read Phone Message OTP Code
    @classmethod
    def read_otp(cls):

        # Hide Debug Log, if want view, just comment the bottom code
        logging.getLogger("airtest").setLevel(logging.WARNING)
        logging.getLogger("pocoui").setLevel(logging.WARNING) 
        logging.getLogger("airtest.core.helper").setLevel(logging.WARNING)

        # Poco Assistant
        poco = AndroidUiautomationPoco(use_airtest_input=True, screenshot_each_action=False)

        # Check screen state (if screenoff then wake up, else skip)
        output = device().adb.shell("dumpsys power | grep -E -o 'mWakefulness=(Awake|Asleep|Dozing)'")

        if "Awake" in output:
            print("Screen already ON  pass")
        else:
            print("Screen is OFF waking")
            wake()
            wake()

        # Start Apps and Click Apps
        start_app("com.google.android.apps.messaging")
        poco(text="Krungsri").click()

        # While loop until the ref code match the sms ref code, then get the OTP Code
        while True:
            time.sleep(3)
            messages = poco("message_list").offspring("message_text")

            for node in reversed(messages):
                text = node.get_text()
                match = re.search(r"Ref\s*(\d+).*OTP\s*(\d+)", text)
                if match and match.group(1) == cls._kma_ref:
                    return match.group(2)
    
    # Call back to ERIC API
    @classmethod
    def callback(cls, job):

        url = "https://stg-bot-integration.cloudbdtech.com/integration-service/transaction/payoutScriptCallback"

        payload = {
            "transactionId": job["transactionId"],
            "bankCode": job["toBankCode"],
            "deviceId": os.getenv("KMA_DEVICE_ID"),
            "merchantCode": os.getenv("KMA_MERCHANT_CODE"),
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

    logger.info("🚀 KMA bot starting (env-based)")
    Automation.chrome_cdp()

    with sync_playwright() as p:
        page = BankBot.login(p)
        logger.info("✅ Logged in once — waiting at transfer page")

        while True:
            job = queue.get_next_job()
            if not job:
                time.sleep(2)
                continue

            try:
                logger.info(f"▶ Processing {job['transactionId']}")
                BankBot.withdraw(page, job)
                queue.mark_done(job["transactionId"], True)
                logger.info(f"✔ Done {job['transactionId']}")
            except Exception as e:
                logger.exception("❌ Withdrawal failed")
                queue.mark_done(job["transactionId"], False, e)
