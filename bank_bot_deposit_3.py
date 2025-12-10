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

    # SCB Anywhere (Web)
    @classmethod
    def scb_Anywhere_web(cls):
        with sync_playwright() as p: 

            # Counter
            counter = 1

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
            try: 
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

                # Button Click "Next"
                page.locator("//button[@type='submit']").click(timeout=0) 

                time.sleep(3)
            except:
                pass
            
            # Browse to Deposit Report
            page.goto("https://www.scbbusinessanywhere.com/account-management", wait_until="domcontentloaded")

            # delay 1 second
            time.sleep(1)

            # Button Click "View Details"
            page.locator("//span[normalize-space()='View Details']").click(timeout=0) 

            # Wait for "Latest Transactions" title appear
            page.locator("//h3[normalize-space()='Latest Transactions']").wait_for(state="visible", timeout=10000)  

            time.sleep(2)   

            # --- Outer persistent memory (keeps data across while loops) ---
            printed_records = set()  

            while True:
                try:

                    # Detect "Something went wrong" popup
                    try:
                        if page.locator("h2.MuiTypography-h6:text('Something went wrong')").is_visible(timeout=2000):
                            page.get_by_text("OK").click()
                            print("Resumed after inactivity.")
                    except:
                        pass

                    # Detect "You have been inactive" popup
                    try:
                        if page.locator("//h2[normalize-space()='You have been inactive for too long']").is_visible(timeout=2000):
                            page.click("//span[normalize-space()='Continue']")
                            print("Resumed after inactivity.")
                    except:
                        pass

                    # Detect "For your online security" logout popup
                    try:
                        if page.locator("//h2[contains(text(),'For your online security, you have been logged out')]").is_visible(timeout=3000):
                            print("⚠️ Session expired. Restarting browser...")
                            page.locator("//span[normalize-space()='OK']").click(timeout=0)
                            browser.close()
                            context.close()
                            Automation.cleanup()
                            time.sleep(3)
                            Automation.chrome_CDP()
                            return Bank_Bot.scb_Anywhere_web()  # Relaunch recursively
                    except:
                        pass
                        
                    # ALWAYS re-extract all rows (SCB only shows latest 20)
                    all_rows = page.locator("//p[contains(@class, 'MuiTypography-body1')]")
                    total_rows = all_rows.count()

                    tx_index = 0

                    # ---- Extract transactions by content, not row count ----
                    while True:
                        start_row = 45 + tx_index * 12
                        end_row = start_row + 12

                        if end_row > total_rows:
                            break

                        # Collect the 12-row block for this transaction
                        block = []
                        for i in range(start_row, end_row):
                            text = all_rows.nth(i).inner_text().strip()
                            if text:
                                block.append(text)

                        # Not enough data → skip
                        if len(block) < 5:
                            tx_index += 1
                            continue

                        # ------- Same cleaning logic as your original code -------
                        record = block.copy()

                        # remove "X1"
                        record.pop(2)

                        # merge date + time
                        record[0] = f"{record[0]} {record[1]}"
                        record.pop(1)

                        # Convert to tuple for duplicate detection
                        record_tuple = tuple(record)
                        # ----------------------------------------------------------


                        # 🔥 NEW DETECTION LOGIC:
                        # A transaction is NEW if not in printed_records
                        if record_tuple not in printed_records:
                            print("-" * 40)
                            print("🆕 NEW TRANSACTION:", record)

                            printed_records.add(record_tuple)

                            # Prepare API values
                            A = record[0]  # date time
                            B = record[1]  # name/bank
                            C = record[2]  # amount

                            raw_data = f"{B}|{C}|{scb_web['toAccount']}"

                            # convert to timestamp
                            dt = datetime.strptime(A, "%d/%m/%Y %H:%M")
                            timestamp_ms = int(dt.timestamp() * 1000)

                            # send to Eric API
                            cls.eric_api(raw_data.strip(), timestamp_ms)
                            print("-" * 40)

                        tx_index += 1
 
                    # Refresh UI and wait
                    time.sleep(5)
                    page.locator("//span[normalize-space()='Apply']").click(timeout=0)
                    print(f"\n\nWait for Incoming Transaction... [#{counter}]")
                    time.sleep(1)
                    counter += 1

                except Exception as e:
                    print(f"Error: {e}")

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
        print("\n")
        
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
