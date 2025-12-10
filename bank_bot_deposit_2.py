import os 
import json
import time
import hashlib
import requests
import atexit
import requests
import subprocess
from pathlib import Path
from dotenv import load_dotenv
from datetime import datetime, timedelta
from playwright.sync_api import sync_playwright, expect

# Load .env (Load Credential)
env_path = Path(__file__).parent / ".env"
load_dotenv(dotenv_path=env_path, override=True)

# SCB Anywhere (Web)
scb_web = {
    "username": os.getenv("USERNAME"),
    "password": os.getenv("PASSWORD"),
    "bank": os.getenv("BANK"),
    "toAccount": os.getenv("toAccount"),
    "amount": os.getenv("AMOUNT"),
    "deviceID": os.getenv("deviceID"),
    "merchant_code": os.getenv("merchant_code")
}

# Chrome 
class Automation:

    # Chrome CDP 
    chrome_proc = None
    @classmethod
    def chrome_CDP(cls):

        # User Profile
        USER_DATA_DIR = r"C:\Users\Thomas\AppData\Local\Google\Chrome\User Data\Profile 1"

        # Step 1: Start Chrome normally
        cls.chrome_proc = subprocess.Popen([
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
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

    last_seen = None

    # SCB Anywhere (Web)
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

            # # Update your Operating System
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

                        raw_data = f"{note}|{amount}|{scb_web['toAccount']}"
                        print(raw_data)

                        print(timestamp_ms, raw_data)

                        # --- send to API ---
                        cls.eric_api(raw_data.strip(), timestamp_ms)

                    # --- Refresh the transaction table ---
                    time.sleep(5)
                    page.locator("//span[normalize-space()='Apply']").click(timeout=2000)
                    time.sleep(1)
                    print(f"\nWait for Incoming Transaction... [#{counter}]")
                    counter += 1



                except Exception as e:
                    # Do NOT restart SCB session. Just continue the loop safely.
                    print("⚠️ Minor loop error recovered:", e)
                    time.sleep(1)
                    continue

    # ---------- Detection helpers ----------
    
    # Extract Transactions
    @classmethod
    def extract_page_transactions(cls, page):

        """
        Extracts collapsed transaction data only.
        Each transaction = 12 rows.
        First transaction starts at index 45.
        """

        # Extract all the rows (transfer name, account number, amount, date)
        # Count total rows of Transactions
        rows = page.locator("//p[contains(@class,'MuiTypography-body1')]")
        row_count = rows.count()
        
        # why - 45? to remove the top uneccessary rows, first transactions rows element is start from 46 (in html view)
        # HTML View = 46, code view = 45
        # Rows before 45 are header / non-transaction
        usable = row_count - 45
        if usable <= 0:
            return []

        # Limit to 20 because SCB only shows max 20 transactions per page then divide by 12, to know how many new transaction
        tx_count = min(20, usable // 12)
        
        # Use to store transaction
        transactions = []

        # the reason put + 1, let said tx_count = 4, it will only loop 3, thats why have to + 1 to make it loop 4 times
        for n in range(1, tx_count + 1):
            start = 45 + (n - 1) * 12
            end = start + 12
            
            # for loop each element start and end, extract text and store in tx_block
            tx_block = [rows.nth(i).inner_text().strip() for i in range(start, end)]
            # print("TX", n, tx_block)

            date = tx_block[0]       # 09/12/2025
            time = tx_block[1]       # 10:11
            note = tx_block[3]       # รับโอนจาก / Transfer from...
            amount = tx_block[4]     # 100.00 THB    

            signature = f"{date} {time}|{note}|{amount}"

            transactions.append(signature)

        return transactions
    
    # Detect/Record the last seen of Transactions
    @classmethod
    def detect_new_transactions(cls, page):
        """
        Uses position-based detection:
        - Reads TX list (newest → oldest)
        - Collects all items above last_seen
        - Updates last_seen to newest
        - Handles duplicates safely
        """

        # Use extract page transaction function
        tx_list = cls.extract_page_transactions(page)  # newest → oldest

        # create new index call new_tx
        new_tx = []

        if not tx_list:
            return []

        # First run: initialize last_seen only, do not send anything
        if cls.last_seen is None:
            cls.last_seen = tx_list[0]
            print(f"Initialized last_seen = {cls.last_seen}")
            return []

        # Collect all transactions above last_seen
        found_last = False
        for tx in tx_list:
            if tx == cls.last_seen:
                found_last = True
                break
            new_tx.append(tx)

        # If last_seen was not found (e.g. more than 20 new TX),
        # treat all current page as new but still update last_seen.
        if new_tx:
            cls.last_seen = tx_list[0]
            print(f"🔄 Updated last_seen after new transaction: {cls.last_seen}")
        elif not found_last:
            # didn't find last_seen but no new_tx (weird case) — reset to newest
            cls.last_seen = tx_list[0]
            print(f"⚠️ last_seen missing, reset to: {cls.last_seen}")

        # return in chronological order: oldest → newest
        return list(reversed(new_tx))

    # Eric API
    @classmethod
    def eric_api(cls, raw_data, timestamp_ms):
        
        # # Production
        # url = "https://bot-integration.cloudbdtech.com/integration-service/transaction/addDepositTransaction"
        # Staging
        url = "https://stg-bot-integration.cloudbdtech.com/integration-service/transaction/addDepositTransaction"

        # Create payload as a DICTIONARY (not JSON yet)
        payload = {
            "bankCode": "SCB_COMPANY_WEB",
            "deviceId": scb_web["deviceID"],
            "merchantCode": scb_web["merchant_code"],
            "rawMessage": raw_data,
            "transactionTime": timestamp_ms
        }

        # Your secret key
        # # Production
        # secret_key = "PRODBankBotIsTheBest"
        # Staging
        secret_key = "DEVBankBotIsTheBest"

        # Build the hash string (exact order required)
        string_to_hash = (
            f"bankCode={payload['bankCode']}&"
            f"deviceId={payload['deviceId']}&"
            f"merchantCode={payload['merchantCode']}&"
            f"rawMessage={payload['rawMessage']}&"
            f"transactionTime={payload['transactionTime']}{secret_key}"
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
        print("\nRaw string to hash:", string_to_hash)
        print("MD5 Hash:", hash_result)
        print("Response:", response.text)
        print("\n\n")

# =========================== Main Loop ===========================

if __name__ == "__main__":

    Automation.chrome_CDP()
    Bank_Bot.scb_Anywhere_web()
    # Bank_Bot.eric_api("รับโอนจาก TTB x3850 MR APITOON SEEBOONRO|100.00 THB|8144211935", 1765271880000)
