import time
from appium import webdriver
from appium.options.common import AppiumOptions

def get_driver():
    options = AppiumOptions()
    options.platformName = "Android"
    options.automationName = "UiAutomator2"
    options.set_capability("noReset", True)
    return webdriver.Remote("http://127.0.0.1:4723", options=options)

driver = get_driver()
driver.activate_app("com.litemed.curapod.app")
time.sleep(5)

print("Getting source...")
source = driver.page_source
with open("relief_debug.xml", "w", encoding="utf-8") as f:
    f.write(source)
print("Dumped to relief_debug.xml")

driver.quit()
