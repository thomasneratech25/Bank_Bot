*** Begin Patch
*** Update File: Withdrawal/SCB/scb_payout_appium_1.26.py
@@
         # Check Apps State
         # 1 = Apps Not Running, 2 = App running in background (suspended)
         # 3 = App running in background, 4 = Apps Running in foreground (Apps is running)    
         state = driver.query_app_state(SCB_APP_PACKAGE)
         print("App state:", state)
+
+        def wait_foreground(timeout=6):
+            """Poll until the app is in foreground (state 4)."""
+            end = time.time() + timeout
+            while time.time() < end:
+                if driver.query_app_state(SCB_APP_PACKAGE) == 4:
+                    return True
+                time.sleep(0.5)
+            return False
 
         # If state 1, open apps
         if state == 1:
-            print("App not running → starting activity")
-            driver.execute_script("mobile: startActivity", {
-                "intent": f"{SCB_APP_PACKAGE}/{SCB_APP_ACTIVITY}",
-                "action": "android.intent.action.MAIN",
-                "category": "android.intent.category.LAUNCHER",
-            })
+            print("App not running -> launching")
+
+            launch_errors = []
+
+            # 1) Try the simple activate_app first (works even if not running)
+            try:
+                driver.activate_app(SCB_APP_PACKAGE)
+            except Exception as exc:
+                launch_errors.append(f"activate_app: {exc}")
+
+            # 2) If still not foreground, try Appium's start_activity API
+            if not wait_foreground():
+                try:
+                    driver.start_activity(SCB_APP_PACKAGE, SCB_APP_ACTIVITY)
+                except Exception as exc:
+                    launch_errors.append(f"start_activity: {exc}")
+
+            # 3) Last resort: adb shell am start
+            if not wait_foreground():
+                try:
+                    driver.execute_script(
+                        "mobile: shell",
+                        {"command": "am", "args": ["start", "-n", f"{SCB_APP_PACKAGE}/{SCB_APP_ACTIVITY}"]},
+                    )
+                except Exception as exc:
+                    launch_errors.append(f"adb am start: {exc}")
+
+            if not wait_foreground():
+                raise RuntimeError(f"SCB app failed to launch; attempts: {launch_errors}")
         # else if 2,3, open apps
         elif state in (2, 3):
-            print("App in background → activating")
+            print("App in background -> activating")
             driver.activate_app(SCB_APP_PACKAGE)
+            wait_foreground()
         # else 4, skip
         elif state == 4:
             print("App already in foreground")
*** End Patch
