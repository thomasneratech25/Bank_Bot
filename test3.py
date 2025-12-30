from airtest.core.api import *
from poco.drivers.android.uiautomation import AndroidUiautomationPoco

auto_setup(__file__)
connect_device("Android:///")

poco = AndroidUiautomationPoco(use_airtest_input=True)

device().shell("cmd statusbar expand-notifications")
sleep(1)

confirm_btn = poco(textMatches=".*Confirm transaction.*Transfer to.*")
confirm_btn.wait_for_appearance(timeout=10)
confirm_btn.click()
confirm_btn.click()
