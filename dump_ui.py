from appium import webdriver
from appium.options.android import UiAutomator2Options

options = UiAutomator2Options()
options.platform_name = "Android"
options.automation_name = "UiAutomator2"
options.no_reset = True
# Don't set app_package/activity so it doesn't try to relaunch the app
driver = webdriver.Remote("http://127.0.0.1:4723", options=options)
with open("ui_dump_live.xml", "w", encoding="utf-8") as f:
    f.write(driver.page_source)
driver.quit()
print("Dumped live UI to ui_dump_live.xml")
