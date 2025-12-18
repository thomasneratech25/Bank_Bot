import re
import os
import time
import atexit
import logging
import requests
import subprocess
from dotenv import load_dotenv
from datetime import datetime
from playwright.sync_api import sync_playwright
from airtest.core.api import *
from poco.drivers.android.uiautomation import AndroidUiautomationPoco

# ====================================================
# CONFIG
# ====================================================

API_BASE = "https://extended-prolongedly-remona.ngrok-free.dev"   

# ====================================================
# ENV
# ====================================================

env_path = os.path.join(os.path.dirname(__file__), ".env")
load_dotenv(env_path, override=True)

REQUIRED_ENV = [
    "TTB_USERNAME",
    "TTB_PASSWORD",
    "TTB_DEVICE_ID",
    "TTB_MERCHANT_CODE",
]

for key in REQUIRED_ENV:
    if not os.getenv(key):
        raise RuntimeError(f"Missing required env var: {key}")

# ====================================================
# LOGGING
# ====================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
logger = logging.getLogger("TTB_BOT")

# ====================================================
# API HELPERS (JOB QUEUE)
# ====================================================

def fetch_next_job():
    try:
        r = requests.get(f"{API_BASE}/jobs/next", timeout=10)
        r.raise_for_status()
        return r.json().get("job")
    except Exception as e:
        logger.error(f"Fetch job failed: {e}")
        return None


def mark_done(txid):
    try:
        requests.post(f"{API_BASE}/jobs/{txid}/done", timeout=10)
    except Exception as e:
        logger.error(f"Mark done failed: {e}")


def mark_fail(txid, error):
    try:
        requests.post(
            f"{API_BASE}/jobs/{txid}/fail",
            json={"error": str(error)},
            timeout=10,
        )
    except Exception as e:
        logger.error(f"Mark fail failed: {e}")

# ====================================================
# CHROME (CDP)
# ====================================================

class Automation:
    chrome_proc = None

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

    @classmethod
    def cleanup(cls):
        try:
            if cls.chrome_proc and cls.chrome_proc.poll() is None:
                cls.chrome_proc.terminate()
        except:
            pass

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

# ====================================================
# BANK BOT
# ====================================================

class BankBot(Automation):

    _ttb_ref = None

    @classmethod
    def ttb_login(cls, p):
        browser = p.chromium.connect_over_cdp("http://localhost:9222")
        context = browser.contexts[0] if browser.contexts else browser.new_context()
        page = context.pages[0] if context.pages else context.new_page()

        page.goto("https://www.ttbbusinessone.com/auth/login", wait_until="domcontentloaded")
        page.wait_for_timeout(1500)

        try:
            page.locator("//input[@type='text']").fill(os.getenv("TTB_USERNAME"))
            page.locator("//button[normalize-space()='Next']").click()
            page.locator("//input[@type='password']").fill(os.getenv("TTB_PASSWORD"))
            page.locator("//button[normalize-space()='Next']").click()
        except:
            pass

        page.locator("//span[normalize-space()='New payment']").first.click()
        page.locator("//div[@id='PPRT']").click()
        return page

    @classmethod
    def ttb_withdrawal(cls, page, job):
        page.locator("//input[@id='counterparty']").fill(str(job["toAccountName"]))
        page.locator("//ca-combo[@name='counterpartyIdType']//button").click()
        page.locator("//li[normalize-space()='Account no.']").click()

        page.locator("//input[@id='bank']").fill(str(job["toBankCode"]))
        page.wait_for_timeout(500)
        page.locator("//ul//li").click()

        page.locator("//input[@id='counterpartyIdValue']").fill(str(job["toAccountNum"]))
        page.locator("//input[@id='amount']").fill(str(job["amount"]))

        page.locator("//button[normalize-space()='Confirm']").click()
        page.locator("//button[normalize-space()='Approve']").click()

        ref_text = page.locator("label.input-label").inner_text()
        match = re.search(r"ref\s*no\s+([A-Z0-9]+)", ref_text, re.I)
        if match:
            cls._ttb_ref = match.group(1)

        otp = cls.ttb_read_otp()
        page.locator("//input[@type='text']").fill(otp)
        page.locator("//button[@id='orders-summary-sign-and-send-button']").click()

        page.locator("//h1[normalize-space()='Transfer successful']").wait_for(timeout=15000)
        page.locator("//i[@class='icon-payment-result-refresh']").click()

    @classmethod
    def ttb_read_otp(cls):
        poco = AndroidUiautomationPoco(use_airtest_input=True)

        output = device().adb.shell("dumpsys power | grep mWakefulness")
        if "Awake" not in output:
            wake()
            wake()

        start_app("com.google.android.apps.messaging")

        while True:
            nodes = poco("message_list").offspring("message_text")
            for node in reversed(nodes):
                text = node.get_text()
                match = re.search(
                    r"OTP[:\s]*([0-9]{4,8}).*?\(?ref[:\s]*([A-Z0-9]+)\)?",
                    text,
                    re.I,
                )
                if match:
                    otp, ref = match.groups()
                    if ref.upper() == cls._ttb_ref:
                        return otp
            time.sleep(2)

# ====================================================
# MAIN
# ====================================================

if __name__ == "__main__":
    logger.info("🚀 TTB Bot starting")
    Automation.chrome_cdp()

    with sync_playwright() as p:
        page = BankBot.ttb_login(p)
        logger.info("✅ Logged in and ready")

        while True:
            job = fetch_next_job()
            if not job:
                time.sleep(2)
                continue

            try:
                logger.info(f"▶ Processing {job['transactionId']}")
                BankBot.ttb_withdrawal(page, job)
                mark_done(job["transactionId"])
                logger.info(f"✔ Done {job['transactionId']}")
            except Exception as e:
                logger.exception("❌ Withdrawal failed")
                mark_fail(job["transactionId"], e)
