import os
import random
from airtest.core.api import *
from poco.drivers.android.uiautomation import AndroidUiautomationPoco
from dotenv import load_dotenv

# Timer, Start Time
start_time = time.perf_counter()

# Simulate Human Click (Faster way)
def human_click(poco_obj):
    # get position of the element
    pos = poco_obj.get_position()
    # convert to screen coords
    w, h = poco.get_screen_size()
    abs_x, abs_y = pos[0] * w, pos[1] * h
    
    # random offset within ~10 pixels
    offset_x = random.uniform(-0.01, 0.01) * w
    offset_y = random.uniform(-0.01, 0.01) * h
    
    # simulate tap
    touch([abs_x + offset_x, abs_y + offset_y])
    # small random human delay
    time.sleep(random.uniform(0.15, 0.35))

# Poco Assistant
poco = AndroidUiautomationPoco(use_airtest_input=True, screenshot_each_action=False)
poco("android.widget.FrameLayout")

# Account Credentials
load_dotenv()
login_pass= os.getenv("login_pass")
bank= os.getenv("bank")
acc_no= os.getenv("acc_no")
amount= os.getenv("amount")

# Check screen state (if screenoff then wake up, else skip)
output = device().adb.shell("dumpsys power | grep -E -o 'mWakefulness=(Awake|Asleep|Dozing)'")

if "Awake" in output:
    print("Screen already ON → pass")
else:
    print("Screen is OFF → waking")
    wake()
    wake()

# start app
start_app("com.TMBTOUCH.PRODUCTION")

# Click Transfer
poco("com.TMBTOUCH.PRODUCTION:id/quick_action_button_ic").click()

# Click Passcode number
for digit in login_pass:
    key = poco(f"com.TMBTOUCH.PRODUCTION:id/key_0{digit}")
    human_click(key)

# Wait for "Other" appear
poco("com.TMBTOUCH.PRODUCTION:id/tv_other").wait_for_appearance(timeout=30)

# Click "Other Accounts"
poco("com.TMBTOUCH.PRODUCTION:id/menu_icon")[1].click()

# Click "Select Bank Menu"
poco("com.TMBTOUCH.PRODUCTION:id/to_account_layout").click()

# Bank Select (if Bank name found then click, else scroll down to click)
if poco("com.TMBTOUCH.PRODUCTION:id/txt_bank_name", text=bank).exists():
    poco("com.TMBTOUCH.PRODUCTION:id/txt_bank_name", text=bank).click()
else:
    # Scroll down
    poco.swipe([0.5, 0.8], [0.5, 0.1], duration=0.2)
    sleep(0.3)
    # Bank Select
    poco("com.TMBTOUCH.PRODUCTION:id/txt_bank_name", text=bank).click()

# Enter "Acc No"
poco("com.TMBTOUCH.PRODUCTION:id/edt_account_no").click()
text(acc_no)

# Enter "Amount"
poco("com.TMBTOUCH.PRODUCTION:id/edt_amount").click()
text(amount)

# Scroll Down
swipe((360, 1280), (360, 320), duration=0.2)

# Click "Next" 
poco("com.TMBTOUCH.PRODUCTION:id/btn_next").click()

# Click "Confirm" 
poco("com.TMBTOUCH.PRODUCTION:id/btn_confirm").click()

# Click Passcode number
for digit in login_pass:
    poco(f"com.TMBTOUCH.PRODUCTION:id/pin_key_{digit}").click()

# Timer, End Time
end_time = time.time()
print(f"Elapsed time: {end_time - start_time:.2f} seconds")
