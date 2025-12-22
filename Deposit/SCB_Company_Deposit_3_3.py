import os 
import json
import time
import atexit
import hashlib
import logging
import requests
import subprocess
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv
from logging.handlers import RotatingFileHandler
from datetime import datetime, timezone, timedelta
from playwright.sync_api import sync_playwright, expect

# ================= Load .env Credentials =========

env_path = Path(__file__).parent / ".env"
load_dotenv(dotenv_path=env_path, override=True)

# ================= LOGGING SETUP =================

LOG_DIR = Path(__file__).parent / "logs"
LOG_DIR.mkdir(exist_ok=True)

LOG_FILE = LOG_DIR / "eric_api.log"

logger = logging.getLogger("BankBotLogger")
logger.setLevel(logging.DEBUG)

handler = RotatingFileHandler(
    LOG_FILE,
    maxBytes=5 * 1024 * 1024,  # 5MB per file
    backupCount=5,
    encoding="utf-8"
)

formatter = logging.Formatter(
    "%(asctime)s | %(levelname)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)

handler.setFormatter(formatter)
logger.addHandler(handler)

# ==================================================

# SCB Anywhere (Web)
scb_web = {
    "username": os.getenv("USERNAME"),
    "password": os.getenv("PASSWORD"),
    "bank": os.getenv("BANK"),
    "toAccount": os.getenv("toAccount"),
    "amount": os.getenv("AMOUNT"),
    "deviceID": os.getenv("deviceID"),
    "merchant_code": os.getenv("merchant_code"),
    "chrome_profile": os.getenv("chrome_profile"),
    "chrome_path": os.getenv("chrome_path")
}

# Chrome 
class Automation:

    # Chrome CDP 
    chrome_proc = None
    @classmethod
    def chrome_CDP(cls):

        # User Profile
        USER_DATA_DIR = rf"{scb_web['chrome_profile']}"

        # Step 1: Start Chrome normally
        cls.chrome_proc = subprocess.Popen([
            rf"{scb_web['chrome_path']}",
            "--remote-debugging-port=9222",
            "--disable-session-crashed-bubble",
            "--hide-crash-restore-bubble",
            "--no-first-run",
            "--no-default-browser-check",
            f"--user-data-dir={USER_DATA_DIR}",  # User Profile
            # "--headless=new",                    # ------> if want to use headless mode, use --windows-size together, due to headless mode small screen size
            # "--window-size=1920,1080",           # ✅ simulate full HD
            # "--force-device-scale-factor=1",     # ✅ ensure no zoom scalin
        ],
        stdout=subprocess.DEVNULL,  # ✅ hide chrome cdp logs
        stderr=subprocess.DEVNULL   # ✅ hide chrome cdp logs
        )
        print("Chrome launched.....\n\n")
    
        # wait for Chrome CDP launch...
        cls.wait_for_cdp_ready()

        atexit.register(cls.cleanup)

    # Close Chrome CDP
    @classmethod
    def cleanup(cls):
        try:
            print("Gracefully terminating Chrome...")
            cls.chrome_proc.terminate()
        except Exception as e:
            print(f"Error terminating Chrome: {e}")
    
    # Wait for Chrome CDP to be ready
    @staticmethod
    def wait_for_cdp_ready(timeout=10):
        """Wait until Chrome CDP is ready at http://localhost:9222/json"""
        for _ in range(timeout):
            try:
                res = requests.get("http://localhost:9222/json")
                if res.status_code == 200:
                    return True
            except:
                pass
            time.sleep(1)
        raise RuntimeError("Chrome CDP is not ready after waiting.")

# Bank Bot
class Bank_Bot(Automation):

    LAST_SEEN_FILE = Path(__file__).parent / "last_seen.txt"

    # Load Last Seen
    @classmethod
    def load_last_seen_list(cls):   
        """
        Load up to 20 stored transactions from last_seen.txt
        newest → oldest
        """
        file_path = cls.LAST_SEEN_FILE

        if not file_path.exists():
            return []

        with file_path.open("r", encoding="utf-8") as f:
            lines = [x.strip() for x in f.readlines() if x.strip()]

        return lines[:20]

    # Save Last Seen
    @classmethod
    def save_last_seen(cls, new_tx):
        """
        Insert a new transaction at the top and keep newest 20 only.
        """
        max_items = 20
        file_path = cls.LAST_SEEN_FILE

        items = cls.load_last_seen_list()

        if new_tx not in items:
            items.insert(0, new_tx)

        items = items[:max_items]

        with file_path.open("w", encoding="utf-8") as f:
            f.write("\n".join(items))
    
    # ---------- Detection helpers ----------
    @staticmethod
    def detect_first_tx_index(rows, row_count):
        """
        First transaction block can shift (35-56, etc.).
        Pick the first candidate that looks like a date/time pair.
        """
        candidates = list(range(35, 56))  # search a small window for the date/time header
        for offset in candidates:
            if row_count - offset < 12:
                continue
            try:
                date_text = rows.nth(offset).inner_text().strip()
                time_text = rows.nth(offset + 1).inner_text().strip()
                datetime.strptime(date_text, "%d/%m/%Y")
                datetime.strptime(time_text, "%H:%M")
                return offset
            except Exception:
                continue
        print("⚠️ Transaction start index not detected, using fallback 45")
        return 45
    
    # Extract Transactions
    @classmethod
    def extract_page_transactions(cls, page):

        """
        Extracts collapsed transaction data only.
        Each transaction = 12 rows.
        First transaction may start around index 40-45.
        """

        # Extract all the rows (transfer name, account number, amount, date)
        # Count total rows of Transactions
        rows = page.locator("//p[contains(@class,'MuiTypography-body1')]")
        row_count = rows.count()
        
        # Some pages render extra banner rows, so the first tx block can start
        # anywhere in a small window (40-45). Detect the correct offset before slicing.
        start_index = cls.detect_first_tx_index(rows, row_count)

        # Rows before start_index are header / non-transaction
        usable = row_count - start_index
        if usable <= 0:
            return []

        # Limit to 20 because SCB only shows max 20 transactions per page then divide by 12, to know how many new transaction
        tx_count = min(20, usable // 12)
        
        # Use to store transaction
        transactions = []

        # the reason put + 1, let said tx_count = 4, it will only loop 3, thats why have to + 1 to make it loop 4 times
        for n in range(1, tx_count + 1):
            start = start_index + (n - 1) * 12
            end = start + 12
            
            # for loop each element start and end, extract text and store in tx_block
            tx_block = [rows.nth(i).inner_text().strip() for i in range(start, end)]
            # print("TX", n, tx_block)

            date = tx_block[0]       # 09/12/2025
            time = tx_block[1]       # 10:11
            code = tx_block[2]       # FE / X1 / X2 / etc.
            note = tx_block[3]       # รับโอนจาก / Transfer from...
            amount = tx_block[4]     # 100.00 THB    

            # Ignore FE, X2, or any other codes you list
            ignore_codes = ["FE", "X2"]
            if code in ignore_codes:
                # print(f"⚠️ Ignored {code} transaction")
                continue

            signature = f"{date} {time}|{note}|{amount}"
            transactions.append(signature)

        return transactions
    
    # Detect/Record the last seen of Transactions
    @classmethod
    def detect_new_transactions(cls, page):

        tx_list = cls.extract_page_transactions(page)  # newest → oldest
        if not tx_list:
            return []

        # Load history (newest → oldest)
        history = cls.load_last_seen_list()
        new_tx = []

        #============ Not Upload Old Transaction at the first time
        if not history:
            cls.save_last_seen(tx_list[0])
            print(f"Initialized last_seen history with newest: {tx_list[0]}")
            return []

        for tx in tx_list:
            if tx not in history:
                new_tx.append(tx)
            else:
                break

        # #============ Upload Old Transaction at the first time
        # if not history:
        #     # Send ALL transactions (oldest → newest)
        #     all_old_tx = list(reversed(tx_list))

        #     for tx in all_old_tx:
        #         print("🆕 FIRST RUN TX:", tx)

        #     # Save newest only (so next run works normally)
        #     cls.save_last_seen(tx_list[0])
        #     return all_old_tx

        cls.save_last_seen(tx_list[0])
        return list(reversed(new_tx))

    # SCB Company Web
    @classmethod
    def scb_Anywhere_web(cls):
        with sync_playwright() as p: 

            # Wait for Chrome CDP to be ready
            cls.wait_for_cdp_ready()

            # Connect to running Chrome
            browser = p.chromium.connect_over_cdp("http://localhost:9222")
            context = browser.contexts[0]  

            # Open a new browser page
            page = context.new_page() 
            page.goto("https://www.scbbusinessanywhere.com/", wait_until="domcontentloaded")

            # Update your Operating System - skipped as it was commented out in original code
            # try:
            #     expect(page.locator("//span[contains(text(),'Enter Site/เข้าสู่เว็บไซต์')]")).to_be_visible(timeout=3000)
            #     page.locator("//span[contains(text(),'Enter Site/เข้าสู่เว็บไซต์')]").click(timeout=0)
            # except:
            #     pass
            
            # if Account already login, can skip
            # For your online security, you have been logged out of SCB Business Anywhere (please log in again.)
            
            try:
                expect(page.locator("//h2[contains(text(),'For your online security, you have been logged out')]")).to_be_visible(timeout=1500)
                page.locator("//span[normalize-space()='OK']").click(timeout=0) 

                # Update your Operating System
                try:
                    expect(page.locator("//span[contains(text(),'Enter Site/เข้าสู่เว็บไซต์')]")).to_be_visible(timeout=1500)
                    page.locator("//span[contains(text(),'Enter Site/เข้าสู่เว็บไซต์')]").click(timeout=0)
                except:
                    pass
            except:
                pass

            # Fill "Username"
            page.locator("//input[@name='username']").fill(scb_web["username"], timeout=1000)

            # Button Click "Next"
            page.locator("//span[normalize-space()='Next']").click(timeout=0) 

            # Fill "Password"
            page.locator("//input[@name='password']").fill(scb_web["password"], timeout=0)

            # Button Click "submit"
            page.locator("//button[@type='submit']").click(timeout=0) 

            time.sleep(3)
        
            # Browse to Deposit Report
            page.goto("https://www.scbbusinessanywhere.com/account-management", wait_until="domcontentloaded")

            # delay 1 second
            time.sleep(1)

            # Button Click "View Details"
            page.locator("//span[normalize-space()='View Details']").click(timeout=0) 

            # Wait for "Latest Transactions" title appear
            page.locator("//h3[normalize-space()='Latest Transactions']").wait_for(state="visible", timeout=10000)  

            time.sleep(2)   

            counter = 1
            
            while True:
                
                # Detect "Something went wrong" popup
                try:
                    if page.locator("h2.MuiTypography-h6:text('Something went wrong')").is_visible(timeout=1500):
                        page.get_by_text("OK").click()
                        print("Resumed after inactivity.")
                except:
                    pass

                # Detect "You have been inactive" popup
                try:
                    if page.locator("//h2[normalize-space()='You have been inactive for too long']").is_visible(timeout=1500):
                        page.click("//span[normalize-space()='Continue']")
                        print("Resumed after inactivity.")
                except:
                    pass

                # Detect "For your online security" logout popup (MODIFIED BLOCK)
                try:
                    if page.locator("//h2[contains(text(),'For your online security, you have been logged out')]").is_visible(timeout=1500):
                        print("⚠️ Session expired. Attempting relogin...")

                        try:
                            # 1. Click 'OK' on the logout popup
                            page.locator("//span[normalize-space()='OK']").click(timeout=0)
                        except:
                            pass

                        # 2. Re-run the login steps:
                        # Go to the home page (which should be the login page after logout)
                        page.goto("https://www.scbbusinessanywhere.com/", wait_until="domcontentloaded")

                        # Wait for "Username" to appear and fill
                        username_input = page.locator("//input[@name='username']")
                        username_input.wait_for(state="visible", timeout=10000)  
                        username_input.fill(scb_web["username"])

                        # Button Click "Next"
                        page.locator("//span[normalize-space()='Next']").click(timeout=0) 

                        # Fill "Password"
                        page.locator("//input[@name='password']").fill(scb_web["password"], timeout=0)

                        # Button Click "submit"
                        page.locator("//button[@type='submit']").click(timeout=0) 

                        time.sleep(3)
                        
                        # Browse back to Deposit Report
                        page.goto("https://www.scbbusinessanywhere.com/account-management", wait_until="domcontentloaded")

                        # delay 1 second
                        time.sleep(1)

                        # Button Click "View Details"
                        page.locator("//span[normalize-space()='View Details']").click(timeout=0) 

                        # Wait for "Latest Transactions" title appear
                        page.locator("//h3[normalize-space()='Latest Transactions']").wait_for(state="visible", timeout=10000)  

                        time.sleep(2)
                        
                        # Continue the while loop (skip the rest of the current iteration and start fresh)
                        continue 

                except:
                    pass


                # Try only the inner operations, NOT the whole loop
                try:

                    # --- Detect new transactions ---
                    new_items = cls.detect_new_transactions(page)

                    # Process each new transaction (oldest → newest)
                    for tx in new_items:    
                        print("🆕 NEW TX:", tx)

                        parts = tx.split("|")
                        datetime_str = parts[0]     # "dd/MM/yyyy HH:mm"
                        note = parts[1]             
                        amount = parts[2]

                        # Convert datetime string to timestamp ms
                        dt = datetime.strptime(datetime_str, "%d/%m/%Y %H:%M")
                        timestamp_ms = int(dt.timestamp() * 1000)

                        # Raw Data
                        raw_data = f"{note}|{amount}|{scb_web['toAccount']}"

                        # --- send to API ---
                        cls.eric_api(raw_data.strip(), timestamp_ms)

                    # --- Refresh the transaction table ---
                    time.sleep(4)
                    page.locator("//span[normalize-space()='Apply']").click(timeout=2000)
                    time.sleep(3)
                    print(f"\nWait for Incoming Transaction... [#{counter}]\n")
                    counter += 1

                except Exception as e:
                    msg = str(e)
                    if "has been closed" in msg or "Target page" in msg:
                        print("❌ Page or browser is closed. Exiting loop...")
                        raise RuntimeError("SessionExpired")

                    print("⚠️ Minor loop error recovered:", e)
                    time.sleep(1)
                    continue

    # Eric API
    @classmethod
    def eric_api(cls, raw_data, timestamp_ms):
        
        # # Production
        # secret_key = "PRODBankBotIsTheBest"
        # url = "https://bot-integration.cloudbdtech.com/integration-service/transaction/addDepositTransaction"

        # Staging
        secret_key = "DEVBankBotIsTheBest"
        url = "https://stg-bot-integration.cloudbdtech.com/integration-service/transaction/addDepositTransaction"

        # Create payload as a DICTIONARY (not JSON yet)
        payload = {
            "bankCode": "SCB_COMPANY_WEB",
            "deviceId": scb_web["deviceID"],
            "merchantCode": scb_web["merchant_code"],
            "rawMessage": raw_data,
            "transactionTime": timestamp_ms
        }


        # Build the hash string (exact order required)
        string_to_hash = (
            f"bankCode={payload['bankCode']}&"
            f"deviceId={payload['deviceId']}&"
            f"merchantCode={payload['merchantCode']}&"
            f"rawMessage={payload['rawMessage']}&"
            f"transactionTime={payload['transactionTime']}{secret_key}"
        )

        # Convert timestamp ms to "date and time"
        dt_gmt7 = datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone(timedelta(hours=7)))

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

        # Logging
        logger.debug("Transaction Time: %s", dt_gmt7)
        logger.debug("RawData: %s", raw_data)
        logger.debug("Raw string to hash: %s", string_to_hash)
        logger.debug("MD5 Hash: %s", hash_result)
        logger.info("API Response: %s \n", response.text)

        # Debug info
        print("\nRaw string to hash:", string_to_hash)
        print("MD5 Hash:", hash_result)
        print("Response:", response.text)

# =========================== Main Loop ===========================

if __name__ == "__main__":

    Automation.chrome_CDP()

    while True:
        try:
            Bank_Bot.scb_Anywhere_web()
        except RuntimeError as e:
            if "SessionExpired" in str(e):
                print("🔁 Reconnecting after logout...")
                time.sleep(3)
                Automation.chrome_CDP()
                continue
            else:
                print(f"⚠️ Unexpected error: {e}. Restarting in 5s...")
                Automation.cleanup()
                time.sleep(5)
                Automation.chrome_CDP()
                continue
        except Exception as e:
            print(f"⚠️ Fatal error: {e}. Restarting in 10s...")
            Automation.cleanup()
            time.sleep(10)
            Automation.chrome_CDP()
            continue
