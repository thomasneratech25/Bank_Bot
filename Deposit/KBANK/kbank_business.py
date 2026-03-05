import os
import time
import atexit
import logging
import requests
import traceback
import subprocess
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright, expect

# =========================== Eric WS_Client Settings =================

WS_PROC = None

# =========================== Logging Settings =========================

LOG_DIR = "./logs"
os.makedirs(LOG_DIR, exist_ok=True)

LOG_FILE = os.path.join(LOG_DIR, "KBank_Withdrawal.log")

# Auto-create the logs folder if it doesn't exist
if not os.path.exists(LOG_DIR):
    os.makedirs(LOG_DIR)

logging.basicConfig(
    level=logging.INFO,  # change to logging.INFO if you want less logs
    format="%(asctime)s - %(levelname)s - %(name)s - %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, mode="a", encoding="utf-8"),
        logging.StreamHandler(),  # prints to terminal
    ],
)

logger = logging.getLogger("KBank Web Deposit")

# ================== PLAYWRIGHT SINGLETON ========================

PLAYWRIGHT = None
BROWSER = None
CONTEXT = None
PAGE = None

# ==========================================

# KBank Business (Web)
kbank_web = {
    "chrome_profile": os.getenv("chrome_profile"),
    "chrome_path": os.getenv("chrome_path")
}

# ===========================================

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
        USER_DATA_DIR = rf"{kbank_web['chrome_profile']}"

        cls.chrome_proc = subprocess.Popen([
            rf"{kbank_web['chrome_path']}",
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
                cls.chrome_proc.terminate()
        except Exception:
            pass

    # Wait Chrome CDP Ready
    @staticmethod
    def wait_for_cdp_ready(timeout=10):
        for attempt in range(1, timeout + 1):
            try:
                if requests.get("http://localhost:9222/json").status_code == 200:
                    return
            except Exception:
                pass
            time.sleep(1)
        raise RuntimeError("Chrome CDP not ready")

# ================== KBANK BANK BOT ==================

class BankBot(Automation):


    @classmethod
    def kbank_login(cls):
        
        cls.chrome_cdp()  

        with sync_playwright() as p:
            browser = p.chromium.connect_over_cdp("http://localhost:9222")
            context = browser.contexts[0] if browser.contexts else browser.new_context()
            page = context.new_page()

            # Go to Kbank Website
            page.goto("https://kbiz.kasikornbank.com/authen/login.jsp?lang=en", wait_until="domcontentloaded")
            logger.info("Browsing to Kbank Business Website ...")

            # Fill "User ID"
            page.locator("//input[@id='userName']").fill()
            logger.info("Fill in User ID ...")

            # Fill "Password"
            page.locator("//input[@id='password']").fill()
            logger.info("Fill in User Password ...")

            # Button Click "Log In"
            page.locator("//a[@id='loginBtn']").click()
            logger.info("Button Click Login Account...")

            time.sleep(111111)


BankBot.kbank_login()