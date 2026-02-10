from airtest.core.api import *
from poco.drivers.android.uiautomation import AndroidUiautomationPoco

poco = AndroidUiautomationPoco()


# Expand Notification Bar
device().shell("cmd statusbar expand-notifications")  

# Swipe notification away using coordinates
swipe((58, 719), (702, 721), duration=0.01)

# Define Clear All button
clear_all = poco("com.android.systemui:id/notification_dismiss_view")

# Check if button appears
if clear_all.exists():
    # if exists then button click clear all
    clear_all.click()
    # else collapse notification bar
else:
    print("Clear All button NOT found, collapsing notification bar...")

# Collapse Notification bar
device().shell("cmd statusbar collapse")

sleep(1)


