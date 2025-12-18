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
    "TTB_USERNAME",
    "TTB_PASSWORD",
    "TTB_DEVICE_ID",
    "TTB_MERCHANT_CODE",
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
    
    def __init__(self, api_base):
        self.api_base = api_base.rstrip("/")

    def fetch_next_job(self):
        try:
            r = requests.post(f"{self.api_base}/jobs/next", timeout=10)
            r.raise_for_status()
            return r.json().get("job")
        except Exception as e:
            logger.error(f"Fetch job failed: {e}")
            return None

    def mark_done(self, txid):
        requests.post(f"{self.api_base}/jobs/{txid}/done", timeout=10)

    def mark_fail(self, txid, error):
        requests.post(
            f"{self.api_base}/jobs/{txid}/fail",
            json={"error": str(error)},
            timeout=10,
        )

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
    
    _ttb_ref = None

    # ==============================
    # -=-=-=-=-= TTB =-=-=-=-=-=-=-=
    # ==============================

    # TTB Business One (Web)
    @classmethod
    def ttb_login(cls, p):

        # Connect to running Chrome
        browser = p.chromium.connect_over_cdp("http://localhost:9222")
        context = browser.contexts[0] if browser.contexts else browser.new_context()    

        # Open a new browser page
        page = context.pages[0] if context.pages else context.new_page()
        page.goto("https://www.ttbbusinessone.com/auth/login", wait_until="domcontentloaded")
        
        # Delay 1.5 seconds
        page.wait_for_timeout(1500)

        # if text "Outward Remittance Service....." appear, button click "Accept", else pass
        try:
            if page.locator("//h2[contains(text(),'System will be temporarily unavailable for mainten')]").is_visible():
                # Button Click "Accept"
                page.locator("//button[normalize-space()='ACCEPT']").click(timeout=0) 
            else:
                pass
        except:
            pass

        # if Account already login, can skip
        try: 
            # Fill "Username"
            page.locator("//input[@type='text']").fill(os.getenv("TTB_USERNAME"), timeout=1000)
            # Delay 0.5 seconds
            page.wait_for_timeout(500)
            # Button Click "Next"
            page.locator("//button[normalize-space()='Next']").click(timeout=0) 
            # Fill "Password"
            page.locator("//input[@type='password']").fill(os.getenv("TTB_PASSWORD"), timeout=0)
            # Delay 0.5 seconds
            page.wait_for_timeout(500)
            # Button Click "Next"
            page.locator("//button[normalize-space()='Next']").click(timeout=0)
        except:
            pass

        # Button Click "New payment"
        page.locator("//div[@class='shortcuts-container hidden-xs row']//span[@class='shortcut-value'][normalize-space()='New payment']").click(timeout=0) 
        # Button Click "Promptpay Transfer"
        page.locator("//div[@id='PPRT']").click(timeout=0)
        
        return page

    # Withdrawal
    @classmethod
    def ttb_withdrawal(cls, page, job):

        # Fill Recipient name
        page.locator("//input[@id='counterparty']").fill(str(job["toAccountName"]), timeout=0)
        # Button Click "Transfer by"
        page.locator("//ca-combo[@name='counterpartyIdType']//button[@type='button']").click(timeout=0)
        # Button Click "Account no"
        page.locator("//li[normalize-space()='Account no.']").click(timeout=0)
        # Select Bank
        page.locator("//input[@id='bank']").fill(str(job["toBankCode"]), timeout=0)
        # Delay 0.5 seconds
        page.wait_for_timeout(500)
        # Button Click Bank
        page.locator("//ul[@class='ng-star-inserted']//li[@class='ng-star-inserted']").click(timeout=0)
        # Fill Account No.
        page.locator("//input[@id='counterpartyIdValue']").fill(str(job["toAccountNum"]), timeout=0)
        # Fill Amount
        page.locator("//input[@id='amount']").fill(str(job["amount"]), timeout=0)
        # Button Click "CONFIRM"
        page.locator("//button[normalize-space()='Confirm']").click(timeout=0)
        # Button Click "Approve"
        page.locator("//button[normalize-space()='Approve']").click(timeout=0)

        # TTB Business One Web Ref Code
        ref_code = page.locator("label.input-label").inner_text()
        match = re.search(r"ref\s*no\s+([A-Z0-9]+)", ref_code, re.IGNORECASE)
        if match:
            cls._ttb_ref = match.group(1)
            print(f"TTB Business One Web Ref Code: {cls._ttb_ref}\n\n")

        # Run Read OTP Code
        otp = cls.ttb_read_otp()
        # Fill OTP Code
        page.locator("//input[@type='text']").fill(otp, timeout=0)
        # Button Click Somewhere, incase cannot click "SIGN AND SEND"
        page.locator("//span[normalize-space()='Sender details']").click(timeout=0)
        # Button Click "SIGN AND SEND"
        page.locator("//button[@id='orders-summary-sign-and-send-button']").click(timeout=0)
        # Wait for Appear "Transfer successful"
        page.locator("//h1[normalize-space()='Transfer successful']").wait_for(timeout=10000)
        # Delay 1 seconds
        page.wait_for_timeout(1000)
        # Button Click "Transfer again"
        page.locator("//i[@class='icon-payment-result-refresh']").click(timeout=0)
    
    # Messages (SMS TTB Business One OTP Code)
    @classmethod
    def ttb_read_otp(cls):

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

        # Start Messages Apps
        start_app("com.google.android.apps.messaging")
        
        # Click ttbbank Chat
        # If not in inside ttbank chat, click it, else passs
        if not poco("message_text").exists():
            poco(text="ttbbank").click()
        else:
            pass
        
        while True:
            # Read All TTB Bank Messages
            print("🤖 Reading latest message from TTB bank...")

            # Get all the messages text
            message_nodes = poco("message_list").offspring("message_text")

            # --- Collect OTP + Ref from all new messages ---
            otp_candidates = []
            for i, node in reversed(list(enumerate(message_nodes))):
                messages = node.get_text().strip()
                if not messages:
                    continue

                match = re.search(
                    r"OTP[:\s]*([0-9]{4,8}).*?\(?ref[:\s]*([A-Z0-9]+)\)?",
                    messages,
                    re.IGNORECASE,
                )
                if match:
                    messages_otp_code, messages_ref_code = match.groups()
                    otp_candidates.append((messages_otp_code.strip(), messages_ref_code.strip().upper()))
                    print(f"OTP: {messages_otp_code}, Ref: {messages_ref_code} ❌")

            # --- Match correct Ref Code ---
            for messages_otp_code, messages_ref_code in otp_candidates:
                if cls._ttb_ref == messages_ref_code:
                    print(f"Found matching Ref: {messages_ref_code} | OTP: {messages_otp_code} ✅")
                    return messages_otp_code
                
            # If no match, loop again
            print("# OTP not found yet, keep waiting... \n")

# ================== Code Start Here ==================

if __name__ == "__main__":
    queue = JobQueue(API_BASE)
    Automation.start_chrome()

    with sync_playwright() as p:
        logger.info("Bot started")

        while True:
            job = queue.fetch_next_job()
            if not job:
                time.sleep(2)
                continue

            txid = job["transactionId"]
            try:
                logger.info(f"Processing {txid}")

                # 🔴 YOUR ORIGINAL TTB LOGIN + WITHDRAW LOGIC GOES HERE
                # BankBot.ttb_withdrawal(page, job)

                queue.mark_done(txid)
                logger.info(f"Done {txid}")

            except Exception as e:
                logger.exception("Withdrawal failed")
                queue.mark_fail(txid, e)
