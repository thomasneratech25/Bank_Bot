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
        USER_DATA_DIR = "/Users/nera_thomas/Library/Application Support/Google/Chrome/Profile 1"

        # Step 1: Start Chrome normally
        cls.chrome_proc = subprocess.Popen([
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
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
        print("Chrome launched.....")
    
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

            # toAccount
            toAccount = toAccount

            # Wait for Chrome CDP to be ready
            cls.wait_for_cdp_ready()

            # Connect to running Chrome
            browser = p.chromium.connect_over_cdp("http://localhost:9222")
            context = browser.contexts[0] if browser.contexts else browser.new_context()    

            # Open a new browser page
            page = context.pages[0] if context.pages else context.new_page()
            page.goto("https://www.scbbusinessanywhere.com/", wait_until="domcontentloaded")

            # Update your Operating System
            try:
                expect(page.locator("//span[contains(text(),'Enter Site/เข้าสู่เว็บไซต์')]")).to_be_visible(timeout=3000)
                page.locator("//span[contains(text(),'Enter Site/เข้าสู่เว็บไซต์')]").click(timeout=0)
            except:
                pass
            
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
            
            # Extract all the rows (transfer name, account number, amount, date)
            # Count total rows (use for loops purpose)
            all_rows1 = page.locator("//p[contains(@class, 'MuiTypography-body1')]")
            last_row_count = all_rows1.count()
            
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
                        
                    # Extract all the rows (transfer name, account number, amount, date)
                    all_rows2 = page.locator("//p[contains(@class, 'MuiTypography-body1')]")
                    # Count total rows (use for loops purpose)
                    current_row_count = all_rows2.count()

                    # If no change in row count, skip printing
                    if current_row_count == last_row_count:

                        # Delay 1 second
                        time.sleep(1)
                        # Click Appy (Refresh)
                        page.locator("//span[normalize-space()='Apply']").click(timeout=0) 

                        # Print Incoming Transaction...."
                        print(f"\n\nWait for Incoming Transaction... [#{counter}]")

                        # Delay 5 seconds
                        time.sleep(5)
                        counter+=1
                        continue
                        
                    # If new rows appear (increase in count)
                    if current_row_count > last_row_count:
                        transaction_count = current_row_count - last_row_count
                        transaction_extract = transaction_count // 12
                        print(f"🆕 Detected {transaction_extract} new transactions.")
                        seen_in_loop = set()
                        
                        
                        for i in range(transaction_extract):
                            start_row = 45 + (i * 12)
                            end_row = start_row + 11
                            group = []

                            # print(f"lol{start_row}, {end_row}")
                            # print("\n")
                            # print(current_row_count, last_row_count)

                            if start_row == current_row_count:
                                break

                            for y in range(start_row, end_row):
                                text = all_rows2.nth(y).inner_text().strip()
                                # print(text)
              
                                # if not text, go next loop
                                if not text:
                                    continue 

                                # Add text normally
                                group.append(text)
                                if len(group) == 5:
                                    record = group.copy()

                                    # Remove "X1" if present
                                    record.pop(2)
                                    
                                    # Merge date and time
                                    if len(record) >= 2:
                                        record[0] = f"{record[0]} {record[1]}"
                                        record.pop(1)

                                    # Skip duplicates
                                    record_tuple = tuple(record)  # convert to tuple for set comparison
                                    if record_tuple in seen_in_loop or record_tuple in printed_records:
                                        continue

                                    # Print only once
                                    print(record)

                                    # ✅ Unpack values
                                    if len(record) >= 3:
                                        A = record[0]  # date and time
                                        B = record[1]  # name and bank
                                        C = record[2]  # amount

                                        # ✅ Merge A, B into one raw transaction string
                                        raw_data = f" {B}|{C}|{toAccount}"
                                        print(f"Raw = {raw_data}")

                                    # Convert date and time to Unix Timestamp
                                    # Parse the date string into a datetime object
                                    A = datetime.strptime(A, "%d/%m/%Y %H:%M")

                                    # Unix Timestamp
                                    timestamp_ms = int(A.timestamp() * 1000)
                                    print(f"Unix Timestamp (miliseconds): {timestamp_ms}")
                                    print("-" * 30)

                                    # Call Eric API
                                    cls.eric_api(raw_data.strip(), timestamp_ms)

                                    # ✅ Mark as printed
                                    seen_in_loop.add(record_tuple)
                                    printed_records.add(record_tuple)

                            # Update last_row_count after processing
                            last_row_count = current_row_count
                        
                        counter+=1

                except Exception as e:
                    print(f"Error: {e}")

                # Delay 1 Second
                time.sleep(1)

                # Click Apply (Refresh)
                page.locator("//span[normalize-space()='Apply']").click(timeout=0) 

                # Print Incoming Transaction...."
                print(f"\n\nWait for Incoming Transaction... [#{counter}]")

                # Delay 3 Seconds
                time.sleep(3)
                counter+=1

    @classmethod
    def eric_api(cls, raw_data, timestamp_ms):

        url = "https://bot-integration.cloudbdtech.com/integration-service/transaction/addDepositTransaction"

        # Create payload as a DICTIONARY (not JSON yet)
        payload = {
            "bankCode": "SCB_COMPANY_WEB",
            "deviceId": scb_web["deviceID"],
            "merchantCode": scb_web["merchant_code"],
            "rawMessage": raw_data,
            "transactionTime": timestamp_ms
        }

        # Your secret key
        secret_key = "PRODBankBotIsTheBest"

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
        print(response.json())

        # 7️⃣ Debug info
        print("Raw string to hash:", string_to_hash)
        print("MD5 Hash:", hash_result)
        print("Response:", response.text)
        print("\n\n")


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
