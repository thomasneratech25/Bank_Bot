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

BASE_DIR = Path(__file__).resolve().parents[1]  # → Withdrawal/
QUEUE_FILE = BASE_DIR / "payout_queue.json"

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
    
    _kma_ref = None

    # ==============================
    # -=-=-=-=-= KMA =-=-=-=-=-=-=-=
    # ==============================

    # Login
    @classmethod
    def kma_login(cls, p):
        
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
        page.locator("//div[normalize-space()='Other Account']").wait_for(timeout=15000)
        page.locator("//div[normalize-space()='Other Account']").click()
        return page

    # Withdrawal
    @classmethod
    def kma_withdrawal(cls, page, job):

        # Select Bank Code
        page.locator("#ddlBanking").wait_for(timeout=10000)
        page.select_option("#ddlBanking", str(job["toBankCode"]))

        # Fill in Account Number
        page.fill("#ctl00_cphSectionData_txtAccTo", str(job["toAccountNum"]))

        # Fill in Amount
        page.fill("#ctl00_cphSectionData_txtAmountTransfer", str(job["amount"]))

        # Click Submit
        page.click("#ctl00_cphSectionData_btnSubmit")

        # Wait for OTP Box Appear
        page.locator(".otpbox_header").wait_for(timeout=10000)

        # Capture OTP Reference Number
        cls._kma_ref = page.locator("//div[@class='inputbox_half_center']//div[@class='input_input_half']").first.inner_text().strip()

        # Run Read OTP Code
        otp = cls.kma_read_otp()

        # Fill OTP Code
        page.fill("#ctl00_cphSectionData_OTPBox1_txtOTPPassword", otp)

        # Delay 0.5 second
        page.wait_for_timeout(500)

        # Button Click "Confirm"
        page.locator("//input[@id='ctl00_cphSectionData_OTPBox1_btnConfirm']").click(timeout=0)
        page.locator("//input[@id='ctl00_cphSectionData_OTPBox1_btnConfirm']").click(timeout=0)

        # Wait for Appear withdrawal Successful
        page.locator("#ctl00_cphSectionData_pnlSuccessMsg").wait_for(timeout=10000)

        # Delay 1 second
        page.wait_for_timeout(1000)

        # Call Eric API
        cls.callback(job)

        # Button click "Transfer other transaction"
        page.click("#ctl00_cphSectionData_btnOtherTxn")

    # Read Phone Message OTP Code
    @classmethod
    def kma_read_otp(cls):

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

        time.sleep(1) 

        # Start Messages Apps
        start_app("com.google.android.apps.messaging")
        
        # Click KMA Chat
        # If not in inside KMA chat, click it, else passs
        if not poco("message_text").exists():
            poco(text="Krungsri").click()
        else:
            pass
        
        while True:

            # Read All KMA Bank Messages
            print("🤖 Reading latest message from KMA bank...")

            # Read All KMA Messages
            message_nodes = poco("message_list").offspring("message_text")

            # --- Collect OTP + Ref from all new messages ---
            otp_candidates = []
            for i, node in reversed(list(enumerate(message_nodes))):
                messages = node.get_text().strip()
                if not messages:
                    continue
                
                # using regex to get Message OTP Code and Ref Code
                match = re.search(r"\bRef\s*[:\-]?\s*(\d+)\b.*?\bOTP\s*[:\-]?\s*(\d+)\b", messages, re.IGNORECASE,)

                if match:
                    _messages_ref_code, messages_otp_code = match.groups()
                    otp_candidates.append((_messages_ref_code.strip(), messages_otp_code.strip()))
                    print(f"# Ref: {_messages_ref_code}, OTP: {messages_otp_code} ❌")

            # --- Match correct Ref Code ---
            for _messages_ref_code, messages_otp_code in otp_candidates:
                if cls._kma_ref == _messages_ref_code:
                    print(f"Found matching Ref: {_messages_ref_code} | OTP: {messages_otp_code} ✅")
                    return messages_otp_code
                
            # If no match, loop again
            print("# OTP not found yet, keep waiting... \n")
    
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
        page = BankBot.kma_login(p)
        logger.info("✅ Logged in once — waiting at transfer page")

        while True:
            job = queue.get_next_job()
            if not job:
                time.sleep(2)
                continue
            try:
                logger.info(f"▶ Processing {job['transactionId']}")
                BankBot.kma_withdrawal(page, job)
                queue.mark_done(job["transactionId"], True)
                logger.info(f"✔ Done {job['transactionId']}")
            except Exception as e:
                logger.exception("❌ Withdrawal failed")
                queue.mark_done(job["transactionId"], False, e)
