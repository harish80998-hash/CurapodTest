import base64
import io
import json
import math
import os
import time
import xml.etree.ElementTree as ET
from datetime import datetime

from appium import webdriver
from appium.options.android import UiAutomator2Options
from appium.webdriver.common.appiumby import AppiumBy
from selenium.common.exceptions import NoSuchElementException, StaleElementReferenceException, TimeoutException
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

try:
    from PIL import Image
    PIL_OK = True
except ImportError:
    PIL_OK = False


# =================================================================
# CONFIG
# =================================================================
APPIUM_HOST = "http://127.0.0.1:4723"
APP_PACKAGE = "com.litemed.curapod.app"
APP_ACTIVITY = "com.litemed.curapod.app.MainActivity"
ELEMENT_WAIT = 20
DEVICE_ID = None

RUN_ID = datetime.now().strftime("%Y%m%d_%H%M%S")
RUN_DIR = os.path.join("relief_matrix_runs", RUN_ID)
SCREENSHOT_DIR = os.path.join(RUN_DIR, "screenshots")
RECORDING_DIR = os.path.join(RUN_DIR, "recordings")
REPORT_DIR = RUN_DIR

for _d in (RUN_DIR, SCREENSHOT_DIR, RECORDING_DIR):
    os.makedirs(_d, exist_ok=True)

RECORDING_ENABLED = True
RUN_RECOVERY = False

CENTRAL_SITES = ["Neck", "Upper Back", "Middle Back", "Lower Back"]
LATERAL_SITES = ["Shoulder", "Biceps", "Triceps", "Elbow", "Forearm", "Wrist", "Hip", "Thigh", "Knee", "Lower Leg", "Ankle & Foot"]
ALL_SITES = CENTRAL_SITES + LATERAL_SITES
# To prevent the app from skipping the wizard due to active plans,
# we only test one duration per run. Change this to test the other duration.
DURATIONS = ["Less than 3 months", "More than 3 months"]
SIDES = ["Left", "Right"]

TEST_PAIN_SCORE = 8
POST_PAIN_SCORE = 6


def tprint(msg: str):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)

def safe_name(*parts) -> str:
    joined = "_".join(p for p in parts if p)
    return "".join(c if c.isalnum() or c in "_-" else "" for c in joined.replace(" ", ""))

def start_recording(driver):
    if not RECORDING_ENABLED: return
    try:
        driver.start_recording_screen(
            videoType="h264", videoSize="480x854", bitRate=500000, timeLimit=180,
        )
    except Exception as e:
        tprint(f"   WARN Recording start failed: {str(e)[:100]}")

def stop_recording_and_save(driver, filename: str) -> str:
    if not RECORDING_ENABLED: return ""
    try:
        video_b64 = driver.stop_recording_screen()
        path = os.path.join(RECORDING_DIR, filename)
        with open(path, "wb") as f:
            f.write(base64.b64decode(video_b64))
        return path
    except Exception as e:
        tprint(f"   WARN Recording save failed: {str(e)[:100]}")
        return ""

def stop_recording_and_discard(driver):
    if not RECORDING_ENABLED: return
    try:
        driver.stop_recording_screen()
    except Exception:
        pass

def save_screenshot_file(driver, filename: str) -> str:
    try:
        path = os.path.join(SCREENSHOT_DIR, filename)
        driver.get_screenshot_as_file(path)
        return path
    except Exception as e:
        tprint(f"   WARN Screenshot save failed: {str(e)[:100]}")
        return ""



def _coord_tap_fallback(driver, xpath, blanket_tap=False) -> bool:
    try:
        els = driver.find_elements(AppiumBy.XPATH, xpath)
    except Exception:
        return False
    for el in els:
        try:
            bounds = el.get_attribute("bounds")
            center = None
            if bounds:
                nums = bounds.replace("[", " ").replace("]", " ").replace(",", " ").split()
                if len(nums) == 4:
                    x1, y1, x2, y2 = (int(n) for n in nums)
                    center = ((x1 + x2) // 2, (y1 + y2) // 2)
            if not center:
                loc, size = el.location, el.size
                center = (loc['x'] + size['width'] // 2, loc['y'] + size['height'] // 2)
            try:
                # Normal center tap
                driver.tap([center], 100)
                if blanket_tap:
                    # 5-point sweeping tap. We use driver.tap separately for each point 
                    # so the OS doesn't interpret it as a single fast multi-touch swipe.
                    screen_w = driver.get_window_size()['width']
                    for pct in [0.1, 0.3, 0.7, 0.9]:
                        driver.tap([(int(screen_w * pct), center[1])], 100)
                        time.sleep(0.1)
            except Exception:
                pass
            return True
        except Exception:
            continue
    return False


def try_tap(driver, *xpaths, timeout=5, blanket_tap=False) -> bool:
    end_time = time.time() + timeout
    while time.time() < end_time:
        for xp in xpaths:
            if _coord_tap_fallback(driver, xp, blanket_tap=blanket_tap):
                return True
            try:
                els = driver.find_elements(AppiumBy.XPATH, xp)
                if els:
                    els[0].click()
                    return True
            except Exception:
                pass
        time.sleep(0.3)
    return False

def tap_relative(driver, x_pct: float, y_pct: float) -> bool:
    try:
        size = driver.get_window_size()
        x = int(size["width"] * x_pct)
        y = int(size["height"] * y_pct)
        try:
            from selenium.webdriver.common.action_chains import ActionChains
            from selenium.webdriver.common.actions.action_builder import ActionBuilder
            from selenium.webdriver.common.actions.pointer_input import PointerInput
            from selenium.webdriver.common.actions import interaction

            pointer = PointerInput(interaction.POINTER_TOUCH, "touch")
            actions = ActionChains(driver)
            actions.w3c_actions = ActionBuilder(driver, mouse=pointer)
            actions.w3c_actions.pointer_action.move_to_location(x, y)
            actions.w3c_actions.pointer_action.pointer_down()
            actions.w3c_actions.pointer_action.pause(0.1)
            actions.w3c_actions.pointer_action.pointer_up()
            actions.perform()
        except Exception:
            driver.tap([(x, y)], 100)
        return True
    except Exception:
        return False

def screen_has(driver, xpath, timeout=8) -> bool:
    end_time = time.time() + timeout
    while time.time() < end_time:
        try:
            if driver.find_elements(AppiumBy.XPATH, xpath):
                return True
        except Exception:
            pass
        time.sleep(0.3)
    return False

def screenshot_b64(driver) -> str:
    try:
        png = driver.get_screenshot_as_png()
        if PIL_OK:
            img = Image.open(io.BytesIO(png))
            img.thumbnail((480, 960))
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            return base64.b64encode(buf.getvalue()).decode()
        return base64.b64encode(png).decode()
    except Exception:
        return ""

def proceed_to_next(driver, screen_title_xpath=None) -> bool:
    """
    Tries to proceed to the next screen. Handles cases where a 'Continue'
    button on an image must be tapped to enable the 'Next' button.
    """
    tapped_continue = False
    if screen_has(driver, "//*[@text='Continue']", timeout=2):
        tapped_continue = try_tap(driver, "//*[@text='Continue']", timeout=2)
        time.sleep(0.6)
    
    if screen_title_xpath and screen_has(driver, screen_title_xpath, timeout=1):
        # We are still on the same screen, so 'Continue' just dismissed an overlay.
        # Now we must tap 'Next'.
        return try_tap(driver, "//*[@text='Next']", timeout=3)
    elif not tapped_continue:
        # No continue button was found, just tap Next
        return try_tap(driver, "//*[@text='Next']", timeout=3)
    
    return True
def site_xpath(site: str) -> str:
    site_lower = site.lower()
    if "&" in site:
        return f"//*[contains(translate(@text, 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), '{site_lower}')]"
    return f"//*[contains(translate(@text, 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), '{site_lower}')]"


def go_to_relief_mode_tab(driver) -> bool:
    return try_tap(driver, "//*[@text='Relief Mode']", "//*[contains(@text,'Relief') and not(contains(@text,'Recovery'))]", timeout=10)

def go_to_recovery_mode_tab(driver) -> bool:
    return try_tap(driver, "//*[@text='Recovery Mode']", timeout=10)

def start_new_relief_session(driver) -> bool:
    return try_tap(driver, "//*[@text='Start New Relief Session']", "//*[contains(@text,'Start New Relief Session')]", timeout=10)

def select_site(driver, site: str) -> bool:
    if not screen_has(driver, "//*[contains(@text,'Where are you')]", timeout=8):
        return False

    def w3c_swipe(direction="down"):
        try:
            from selenium.webdriver.common.action_chains import ActionChains
            from selenium.webdriver.common.actions.action_builder import ActionBuilder
            from selenium.webdriver.common.actions.pointer_input import PointerInput
            from selenium.webdriver.common.actions import interaction

            size = driver.get_window_size()
            start_x = size['width'] // 2
            start_x = size['width'] // 2
            if direction == "down":
                start_y = int(size['height'] * 0.70)
                end_y = int(size['height'] * 0.35)
            else:
                start_y = int(size['height'] * 0.35)
                end_y = int(size['height'] * 0.70)
                end_y = int(size['height'] * 0.75)

            pointer = PointerInput(interaction.POINTER_TOUCH, "touch")
            actions = ActionChains(driver)
            actions.w3c_actions = ActionBuilder(driver, mouse=pointer)
            actions.w3c_actions.pointer_action.move_to_location(start_x, start_y)
            actions.w3c_actions.pointer_action.pointer_down()
            actions.w3c_actions.pointer_action.pause(0.2)
            actions.w3c_actions.pointer_action.move_to_location(start_x, end_y)
            actions.w3c_actions.pointer_action.pause(0.2)
            actions.w3c_actions.pointer_action.pointer_up()
            actions.perform()
            time.sleep(1)
        except Exception:
            pass

    found = False
    for _ in range(4):
        if screen_has(driver, site_xpath(site), timeout=1):
            found = True
            break
        w3c_swipe("down")

    if not found:
        for _ in range(6):
            if screen_has(driver, site_xpath(site), timeout=1):
                found = True
                break
            w3c_swipe("up")

    if not try_tap(driver, site_xpath(site), timeout=5, blanket_tap=False):
        return False
    return try_tap(driver, "//*[@text='Continue']", "//*[@text='Next']", timeout=5)

def maybe_select_side(driver, site: str, side: str) -> bool:
    if not screen_has(driver, "//*[contains(@text,'Which side')]", timeout=6):
        return False
    side_lower = side.lower()
    xpath = (
        f"//*["
        f"translate(normalize-space(@text), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz') = '{side_lower}' "
        f"or translate(normalize-space(@content-desc), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz') = '{side_lower}'"
        f"]"
    )
    if not try_tap(driver, xpath, timeout=5):
        return False
    return try_tap(driver, "//*[@text='Next']", "//*[@text='Continue']", timeout=5)

def select_duration(driver, duration: str) -> bool:
    if not screen_has(driver, "//*[contains(@text,'How long') or contains(@text,'long have')]", timeout=8):
        return False

    less_or_more = "Less" if "Less" in duration else "More"
    option_xpaths = [
        f"//*[@text='{duration}']",
        f"//*[contains(translate(@text, 'MORELESS', 'moreless'), '{less_or_more.lower()}') and contains(translate(@text, 'MONTHS', 'months'), 'month')]",
        f"//*[contains(translate(@text, 'MORELESS', 'moreless'), '{less_or_more.lower()}')]",
    ]

    tapped = False
    for xp in option_xpaths:
        if _coord_tap_fallback(driver, xp, blanket_tap=True):
            tapped = True
            break
    if not tapped:
        tapped = try_tap(driver, *option_xpaths, timeout=4, blanket_tap=True)
        
    time.sleep(0.6)
    return try_tap(driver, "//*[@text='Next']", "//*[@text='Continue']", timeout=5)

def select_dont_know_condition(driver) -> bool:
    if not screen_has(driver, "//*[contains(@text,'pain condition') or contains(@text,'condition')]", timeout=8):
        return False

    try:
        from selenium.webdriver.common.action_chains import ActionChains
        from selenium.webdriver.common.actions.action_builder import ActionBuilder
        from selenium.webdriver.common.actions.pointer_input import PointerInput
        from selenium.webdriver.common.actions import interaction

        size = driver.get_window_size()
        start_x = size['width'] // 2
        start_y = int(size['height'] * 0.75)
        end_y = int(size['height'] * 0.25)

        pointer = PointerInput(interaction.POINTER_TOUCH, "touch")
        actions = ActionChains(driver)
        actions.w3c_actions = ActionBuilder(driver, mouse=pointer)
        actions.w3c_actions.pointer_action.move_to_location(start_x, start_y)
        actions.w3c_actions.pointer_action.pointer_down()
        actions.w3c_actions.pointer_action.pause(0.2)
        actions.w3c_actions.pointer_action.move_to_location(start_x, end_y)
        actions.w3c_actions.pointer_action.pause(0.2)
        actions.w3c_actions.pointer_action.pointer_up()
        actions.perform()
        time.sleep(1)
    except Exception:
        pass

    option_xpaths = [
        "//*[@text=\"I don't know my condition\"]",
        "//*[contains(@text,\"don't know my condition\")]",
        "//*[contains(@text,\"don't know\")]",
        "//*[contains(@text,'know my condition')]",
    ]

    tapped = False
    for xp in option_xpaths:
        if _coord_tap_fallback(driver, xp, blanket_tap=True):
            tapped = True
            break
    if not tapped:
        tapped = try_tap(driver, *option_xpaths, timeout=4, blanket_tap=True)
    if not tapped:
        return False
        
    time.sleep(0.8)

    selected = screen_has(driver, "//*[contains(@text,\"don't know\")][@selected='true'] | "
                                  "//*[contains(@text,\"don't know\")]/parent::*[@selected='true']", timeout=2)
    if not selected:
        for xp in option_xpaths:
            if _coord_tap_fallback(driver, xp, blanket_tap=True):
                break
        time.sleep(0.6)

    return try_tap(driver, "//*[@text='Next']", "//*[@text='Continue']", timeout=5)

def confirm_relief_plan_ready(driver, site: str, timeout=15) -> bool:
    if not screen_has(driver, "//*[contains(@text,'relief plan is ready')]", timeout=timeout):
        return False
    short = site.split(" ")[0]
    return screen_has(driver, f"//*[contains(@text,'{short}')]", timeout=5)

def _vas_target_point(cx: float, cy: float, r: float, value: float):
    clock_deg = (225 + (value / 10.0) * 270) % 360
    rad = math.radians(clock_deg)
    x = cx + r * math.sin(rad)
    y = cy - r * math.cos(rad)
    return (int(x), int(y))

def _find_vas_slider_bounds(driver):
    candidates = []
    try:
        root = ET.fromstring(driver.page_source)
        for node in root.iter():
            b = node.attrib.get("bounds", "")
            if not b:
                continue
            try:
                nums = b.replace("[", " ").replace("]", " ").replace(",", " ").split()
                x1, y1, x2, y2 = (int(n) for n in nums)
            except Exception:
                continue
            w, h = x2 - x1, y2 - y1
            if w < 150 or h < 150:
                continue
            ratio = w / h if h else 0
            if 0.75 <= ratio <= 1.35:
                candidates.append((w * h, x1, y1, x2, y2))
    except Exception:
        pass

    if not candidates:
        tprint("   INFO  XML bounds failed, falling back to relative screen dimensions for VAS slider")
        try:
            size = driver.get_window_size()
            w, h = size['width'], size['height']
            cx = w / 2
            cy = h * 0.48
            radius = w * 0.34
            return (cx, cy, radius)
        except Exception:
            return None

    candidates.sort(reverse=True)
    _, x1, y1, x2, y2 = candidates[0]
    cx = (x1 + x2) / 2
    cy = (y1 + y2) / 2
    radius = min(x2 - x1, y2 - y1) / 2 * 0.82
    return (cx, cy, radius)

def _read_chip_text(driver, label_substring: str, expected_title: str = "") -> str:
    try:
        root = ET.fromstring(driver.page_source)
    except Exception:
        return "(xml parse failed)"
    
    parent_map = {child: parent for parent in root.iter() for child in parent}
    for node in root.iter():
        node_text = node.attrib.get("text", "")
        if label_substring not in node_text:
            continue
            
        container = parent_map.get(node, node)
        texts = [n.attrib.get("text", "") for n in container.iter() if n.attrib.get("text")]
        combined = " ".join(t for t in texts if t).strip()
        
        if combined and not any(c.isdigit() for c in combined):
            grandparent = parent_map.get(container, container)
            texts2 = [n.attrib.get("text", "") for n in grandparent.iter() if n.attrib.get("text")]
            combined2 = " ".join(t for t in texts2 if t).strip()
            if any(c.isdigit() for c in combined2):
                combined = combined2
                
        if expected_title and expected_title.lower() not in combined.lower():
            continue
            
        if combined:
            return combined
            
    return "(not found)"

def _read_vas_displayed_value(driver) -> str:
    return "?"

def set_vas_pain_score(driver, value: int) -> dict:
    info = {"submitted": False, "initial_score": "?", "landed_score": "?"}

    if not screen_has(driver,
        "//*[contains(@text,'How do you feel') or contains(@text,'session begins') or contains(@text,'How are you feeling now') or contains(@text,'How is your pain now')]",
        timeout=10):
        return info

    # Give the slider time to render so XML coordinates might catch it
    time.sleep(2)

    info["initial_score"] = _read_vas_displayed_value(driver)
    tprint(f"   VAS  Initial score on screen: {info['initial_score']}")

    bounds = _find_vas_slider_bounds(driver)
    if not bounds:
        tprint("   WARN VAS slider region not found  skipping score, tapping Submit as-is")
        info["submitted"] = try_tap(driver, "//*[@text='Submit']", timeout=6)
        return info

    cx, cy, r = bounds
    target = _vas_target_point(cx, cy, r, value)
    tprint(f"   VAS  slider bounds cx={cx:.0f} cy={cy:.0f} r={r:.0f} -> "
           f"target {target} for value={value}")

    try:
        from selenium.webdriver.common.action_chains import ActionChains
        from selenium.webdriver.common.actions.action_builder import ActionBuilder
        from selenium.webdriver.common.actions.pointer_input import PointerInput
        from selenium.webdriver.common.actions import interaction

        # Calculate start point (value=0) to drag from
        start_pt = _vas_target_point(cx, cy, r, 0)

        pointer = PointerInput(interaction.POINTER_TOUCH, "touch")
        actions = ActionChains(driver)
        actions.w3c_actions = ActionBuilder(driver, mouse=pointer)

        actions.w3c_actions.pointer_action.move_to_location(start_pt[0], start_pt[1])
        actions.w3c_actions.pointer_action.pointer_down()
        actions.w3c_actions.pointer_action.pause(0.2)
        # Drag to the target value
        actions.w3c_actions.pointer_action.move_to_location(target[0], target[1])
        actions.w3c_actions.pointer_action.pause(0.2)
        actions.w3c_actions.pointer_action.pointer_up()
        actions.perform()
    except Exception as e:
        tprint(f"   WARN VAS drag gesture failed: {str(e)[:120]}")

    info["submitted"] = try_tap(driver, "//*[@text='Submit']", "//*[@text='Next']", "//*[@text='Continue']", timeout=6)
    return info

def _soft_reset_to_home(driver, max_rounds=6) -> bool:
    for _ in range(max_rounds):
        if try_tap(driver, "//*[@text='Home']", "//*[@content-desc='Home']", timeout=2):
            time.sleep(1.5)
            if screen_has(driver, "//*[@text='Home']", timeout=2):
                return True
        try_tap(driver, "//android.widget.ImageView[@content-desc='Close']", "//*[@content-desc='Close']", "//*[@text='Close']", "//*[@text='Cancel']", timeout=2)
        time.sleep(0.5)
    return False

def _hard_reset_to_home(driver):
    try:
        driver.terminate_app(APP_PACKAGE)
    except Exception:
        pass
    time.sleep(1)
    try:
        driver.activate_app(APP_PACKAGE)
    except Exception:
        pass
    time.sleep(2.5)

    try_tap(driver, "//*[@content-desc='Close']", "//*[@text='Close']", "//*[@text='Cancel']", timeout=2)
    time.sleep(0.3)
    try_tap(driver, "//*[@text='Home']", "//*[@content-desc='Home']", timeout=8)
    time.sleep(1.5)

def reset_to_home(driver):
    if _soft_reset_to_home(driver):
        return
    tprint("   INFO Soft reset couldn't reach Home ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã‚Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â falling back to app terminate/relaunch")
    _hard_reset_to_home(driver)

def module_w3c_swipe(driver, direction="down", y_percent=0.50):
    try:
        from selenium.webdriver.common.action_chains import ActionChains
        from selenium.webdriver.common.actions.action_builder import ActionBuilder
        from selenium.webdriver.common.actions.pointer_input import PointerInput
        from selenium.webdriver.common.actions import interaction

        size = driver.get_window_size()
        start_x = size['width'] // 2
        if direction == "down":
            start_y = int(size['height'] * 0.70)
            end_y = int(size['height'] * 0.35)
            end_x = start_x
        elif direction == "up":
            start_y = int(size['height'] * 0.35)
            end_y = int(size['height'] * 0.70)
            end_x = start_x
        elif direction == "left":
            start_y = int(size['height'] * y_percent)
            end_y = start_y
            start_x = int(size['width'] * 0.80)
            end_x = int(size['width'] * 0.20)
        elif direction == "right":
            start_y = int(size['height'] * y_percent)
            end_y = start_y
            start_x = int(size['width'] * 0.20)
            end_x = int(size['width'] * 0.80)
        else:
            start_y = int(size['height'] * 0.35)
            end_y = int(size['height'] * 0.70)
            end_x = start_x

        pointer = PointerInput(interaction.POINTER_TOUCH, "touch")
        actions = ActionChains(driver)
        actions.w3c_actions = ActionBuilder(driver, mouse=pointer)
        actions.w3c_actions.pointer_action.move_to_location(start_x, start_y)
        actions.w3c_actions.pointer_action.pointer_down()
        actions.w3c_actions.pointer_action.pause(0.1)
        
        # Simulate a gradual drag so React Native's gesture responder registers the velocity
        steps = 10
        for i in range(1, steps + 1):
            mid_x = int(start_x + (end_x - start_x) * (i / steps))
            mid_y = int(start_y + (end_y - start_y) * (i / steps))
            actions.w3c_actions.pointer_action.move_to_location(mid_x, mid_y)
            actions.w3c_actions.pointer_action.pause(0.02)
            
        actions.w3c_actions.pointer_action.pointer_up()
        actions.perform()
    except:
        pass

def delete_active_plan(driver) -> bool:
    tprint("   INFO  Deleting the active plan to clear state for the next test...")
    # Make sure we are on the Relief Mode tab! (exit_wizard drops us on Home)
    if not go_to_relief_mode_tab(driver):
        tprint("   WARN  Could not switch to Relief Mode tab to delete plan.")
        return False
        
    # Tap Settings tab under the plan card
    settings_found = False
    for swipe_attempt in range(3):
        if try_tap(driver, "//*[@text='Settings']", timeout=2):
            settings_found = True
            break
            
        if swipe_attempt == 0:
            tprint("   INFO  Settings tab not found. Swiping left on carousel...")
            module_w3c_swipe(driver, direction="left", y_percent=0.62)
            time.sleep(1)
        elif swipe_attempt == 1:
            tprint("   INFO  Still not found. Scrolling down to reveal bottom of screen...")
            module_w3c_swipe(driver, direction="down")
            time.sleep(1)

    if not settings_found:
        tprint("   WARN  Could not find Settings tab to delete plan across any slides.")
        return False
    
    time.sleep(1)
    # Scroll down because End Relief Plan is likely off-screen and unmounted by React Native
    module_w3c_swipe(driver, direction="down")
    time.sleep(1)
    # Tap End Relief Plan
    if try_tap(driver, "//*[@text='End Relief Plan']", "//*[@text='END RELIEF PLAN']", "//*[contains(translate(@text, 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'end relief')]", timeout=5):
        time.sleep(1)
        # Tap confirmation (Yes, End, or Confirm)
        if try_tap(driver, "//*[@text='Yes']", "//*[@text='YES']", "//*[@text='End']", "//*[@text='Confirm']", "//*[contains(@text, 'Yes')]", timeout=5):
            time.sleep(3)
            # Verify it actually deleted! If Settings is still there, it didn't delete!
            if not screen_has(driver, "//*[@text='Settings']", timeout=2):
                tprint("   INFO  Plan deleted successfully.")
                return True
            else:
                tprint("   WARN  Clicked Yes, but Settings is still visible! Retrying deletion...")
                return delete_active_plan(driver)
        else:
            tprint("   WARN  Clicked End Relief Plan, but confirmation Yes button didn't appear! Retrying...")
            return delete_active_plan(driver)
    
    tprint("   WARN  Could not find End Relief Plan button. Dumping UI...")
    try:
        with open("failed_delete_plan_ui.xml", "w", encoding="utf-8") as f: f.write(driver.page_source)
    except: pass
    return False

def exit_wizard_to_relief_tab(driver):
    try_tap(driver, "//android.widget.ImageView[@content-desc='Close']", "//*[@content-desc='Close']", timeout=3)
    time.sleep(0.5)
    reset_to_home(driver)
    time.sleep(0.5)

def select_recovery_site(driver, site: str) -> bool:
    if not screen_has(driver, "//*[contains(@text,'Where are you')]", timeout=10):
        return False
    if not try_tap(driver, site_xpath(site), timeout=8, blanket_tap=False):
        return False
    return True

def start_recovery_session(driver) -> bool:
    return try_tap(driver, "//*[@text='Start Recovery Session']", "//*[contains(@text,'Start Recovery Session')]", timeout=10)

def confirm_recovery_started(driver, timeout=15) -> bool:
    return screen_has(driver, "//*[contains(@text,'Recovery') and (contains(@text,'Session') or contains(@text,'started'))]", timeout=timeout)

def run_relief_combo(driver, site: str, side: str, duration: str) -> dict:
    label = f"{site}" + (f" [{side}]" if side else "") + f" / {duration}"
    tprint(f"RELIEF  {label} ...")
    
    result = {
        "mode": "relief", "site": site, "side": side, "duration": duration,
        "status": "FAIL", "error": "", "screenshot": "", "screenshot_file": "", "recording": "",
        "pre_score_submitted": False, "initial_score": "?", "landed_score": "?",
        "post_score_submitted": False, "post_initial_score": "?", "post_landed_score": "?",
        "home_initial_chip": "", "home_current_chip": "", "note": ""
    }
    fname_base = safe_name("relief", site, side, duration)
    start_recording(driver)

    def _finish(status: str):
        result["status"] = status
        result["screenshot"] = screenshot_b64(driver)
        result["screenshot_file"] = save_screenshot_file(driver, f"{fname_base}.png")
        result["recording"] = stop_recording_and_save(driver, f"{fname_base}.mp4")
        try:
            exit_wizard_to_relief_tab(driver)
            delete_active_plan(driver)
        except:
            pass
        return result
    # dummy to replace old lines
    # dummy to replace old lines
    # dummy to replace old lines
    # dummy to replace old lines
    # dummy to replace old lines
    # dummy to replace old lines
    # dummy to replace old lines
        try:
            exit_wizard_to_relief_tab(driver)
            delete_active_plan(driver)
        except:
            pass
        result["status"] = status
        result["screenshot"] = screenshot_b64(driver)
        result["screenshot_file"] = save_screenshot_file(driver, f"{fname_base}.png")
        result["recording"] = stop_recording_and_save(driver, f"{fname_base}.mp4")
        return result

    reset_to_home(driver)

    if not go_to_relief_mode_tab(driver):
        result["error"] = "Could not reach Relief Mode tab"
        return _finish("FAIL")
    if not start_new_relief_session(driver):
        result["error"] = "Could not tap 'Start New Relief Session'"
        tprint("   FAIL  " + result["error"])
        return _finish("FAIL")
    if not select_site(driver, site):
        result["error"] = "Could not select site '" + site + "'"
        tprint("   FAIL  " + result["error"])
        return _finish("FAIL")
    if side:
        if not maybe_select_side(driver, site, side):
            result["error"] = f"Side screen/selection failed for '{side}'"
            return _finish("FAIL")
    if not select_duration(driver, duration):
        result["error"] = f"Duration screen/selection failed for '{duration}'"
        return _finish("FAIL")
    if not select_dont_know_condition(driver):
        result["error"] = "Pain condition screen/selection failed"
        return _finish("FAIL")
    if not confirm_relief_plan_ready(driver, site):
        result["error"] = "'Your relief plan is ready' screen did not appear/match site"
        return _finish("FAIL")

    if try_tap(driver, "//*[@text='Start Session']", "//*[contains(@text,'Start Session')]", timeout=8):
        time.sleep(1.5)

        if screen_has(driver, "//*[contains(@text,'How to start your Cura-Session') or contains(@text,'Power on both your pods')]", timeout=1):
            tprint("   INFO  Pod pairing instructions screen detected - tapping through...")
            if not try_tap(driver, "//*[@text='Start Session']", "//*[contains(@text,'Start Session')]", timeout=2):
                tprint("   INFO  Element-based tap didn't land - using coordinate tap instead...")
                tap_relative(driver, 0.5, 0.92)
            time.sleep(0.5)

            if screen_has(driver, "//*[contains(@text,'How to start your Cura-Session') or contains(@text,'Power on both your pods')]", timeout=3):
                tap_relative(driver, 0.5, 0.92)
                time.sleep(0.5)
            if screen_has(driver, "//*[contains(@text,'How to start your Cura-Session') or contains(@text,'Power on both your pods')]", timeout=3):
                result["note"] = "Blocked on pod-pairing instructions screen ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã‚Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â likely no pod connected"
                return _finish("FAIL")

        if screen_has(driver, "//*[contains(@text,'session begins')]", timeout=6):
            vas = set_vas_pain_score(driver, TEST_PAIN_SCORE)
            result["initial_score"] = vas["initial_score"]
            result["landed_score"] = vas["landed_score"]
            if not vas["submitted"]:
                result["error"] = "Pre-session pain score screen did not submit"
                return _finish("FAIL")
            time.sleep(0.5)
            result["pre_score_submitted"] = True

            if screen_has(driver, "//*[contains(@text,'Remaining Time') or contains(@text,'End Session')]", timeout=15):
                tprint("   INFO  Session started. Waiting 20 seconds for better output...")
                time.sleep(20)
                tprint("   INFO  Ending session early...")
                if try_tap(driver, "//*[@text='End Session']", "//*[contains(@text,'End Session')]", timeout=5):
                    if try_tap(driver, "//*[@text='YES']", "//*[@text='Yes']", timeout=5):
                        time.sleep(0.5)
                        tprint("   INFO  Setting post-session pain score...")
                        post_vas = set_vas_pain_score(driver, POST_PAIN_SCORE)
                        result["post_initial_score"] = post_vas["initial_score"]
                        result["post_landed_score"] = post_vas["landed_score"]
                        if post_vas["submitted"]:
                            result["post_score_submitted"] = True

                        tprint("   INFO  Navigating Home to verify card...")
                        _hard_reset_to_home(driver)
                        tprint("   INFO  Waiting 10 seconds for Home card data to sync...")
                        time.sleep(10)
                        tprint("   INFO  Verifying Home screen card...")
                        
                        expected_text = f"{side} {site}" if side else site
                        initial_chip = "(not found)"
                        current_chip = "(not found)"
                        
                        for swipe_attempt in range(2):
                            initial_chip = _read_chip_text(driver, "Initial Pain", expected_title=expected_text)
                            current_chip = _read_chip_text(driver, "Current Pain", expected_title=expected_text)
                            if initial_chip != "(not found)" and current_chip != "(not found)":
                                break
                            tprint("   INFO  Target card not found on this slide. Swiping left on Home carousel...")
                            module_w3c_swipe(driver, direction="left", y_percent=0.75)
                            time.sleep(1.5)
                            
                        result["home_initial_chip"] = initial_chip
                        result["home_current_chip"] = current_chip
                        tprint(f"   INFO  Home card - Initial Pain chip: '{initial_chip}' | Current Pain chip: '{current_chip}'")
                        
                        has_initial = f"Initial Pain {TEST_PAIN_SCORE}" in initial_chip
                        has_current = f"Current Pain {POST_PAIN_SCORE}" in current_chip
                        if has_initial and has_current:
                            result["note"] = f"Success! Home card shows Initial Pain {TEST_PAIN_SCORE} and Current Pain {POST_PAIN_SCORE}"
                        else:
                            result["error"] = f"Pain scores not stored correctly on Home card. Found: Initial chip='{initial_chip}', Current chip='{current_chip}'"
                            return _finish("FAIL")
                    else:
                        result["error"] = "YES button not found on End Session popup"
                        return _finish("FAIL")
                else:
                    result["error"] = "End Session button not found"
                    return _finish("FAIL")
            else:
                result["error"] = "Session screen not reached after pre-session pain score"
                return _finish("FAIL")
        else:
            result["error"] = "Pre-session score screen not found"
            return _finish("FAIL")
    else:
        result["error"] = "'Start Session' button not found on plan-ready screen"
        return _finish("FAIL")

    tprint(f"OK      {label}")
    _finish("PASS")


    return result

def run_recovery_combo(driver, site: str) -> dict:
    tprint(f"RECOV   {site} ...")
    result = {
        "mode": "recovery", "site": site, "side": "", "duration": "",
        "status": "FAIL", "error": "", "screenshot": "", "screenshot_file": "", "recording": "", "note": ""
    }
    fname_base = safe_name("recovery", site)
    start_recording(driver)

    def _finish(status: str):
        result["status"] = status
        result["screenshot"] = screenshot_b64(driver)
        result["screenshot_file"] = save_screenshot_file(driver, f"{fname_base}.png")
        result["recording"] = stop_recording_and_save(driver, f"{fname_base}.mp4")
        try:
            exit_wizard_to_relief_tab(driver)
            delete_active_plan(driver)
        except:
            pass
        return result
    # dummy to replace old lines
    # dummy to replace old lines

    if not go_to_recovery_mode_tab(driver):
        result["error"] = "Could not reach Recovery Mode tab"
        return _finish("FAIL")
    if not select_recovery_site(driver, site):
        result["error"] = f"Could not select site '{site}'"
        return _finish("FAIL")
    if not start_recovery_session(driver):
        result["error"] = "Could not tap 'Start Recovery Session'"
        return _finish("FAIL")
    if not confirm_recovery_started(driver):
        result["error"] = "Recovery session did not appear to start"
        return _finish("FAIL")

    tprint(f"OK      {site}")
    _finish("PASS")
    go_to_recovery_mode_tab(driver)
    time.sleep(1)
    return result

def generate_report(results: list, device_name: str = "Unknown Device"):
    total = len(results)
    passed = sum(1 for r in results if r["status"] == "PASS")
    failed = total - passed

    rows = ""
    for r in results:
        color = "#3fb950" if r["status"] == "PASS" else "#f85149"
        combo = f"{r['site']}" + (f" [{r['side']}]" if r["side"] else "") + \
                (f" / {r['duration']}" if r["duration"] else "")
        score_note = ""
        if r.get("pre_score_submitted"):
            score_note = f'<div style="color:#3fb950;font-size:11px">Pre-session score submitted (target={TEST_PAIN_SCORE})</div>'
        
        note_html = (f'<div style="color:#8b949e;font-size:11px">{r["note"]}</div>' if r.get("note") else "")
        chip_html = ""
        if r.get("home_initial_chip") or r.get("home_current_chip"):
            chip_html = (
                f'<div style="color:#8b949e;font-size:11px">'
                f'Home card - Initial: "{r.get("home_initial_chip","")}" | '
                f'Current: "{r.get("home_current_chip","")}"</div>'
            )
        
        links_html = ""
        if r.get("screenshot_file"):
            rel = os.path.relpath(r["screenshot_file"], REPORT_DIR)
            links_html += f'<a href="{rel}" style="color:#58a6ff;font-size:11px;margin-right:10px">screenshot.png</a>'
        if r.get("recording"):
            rel = os.path.relpath(r["recording"], REPORT_DIR)
            links_html += f'<a href="{rel}" style="color:#58a6ff;font-size:11px">recording.mp4</a>'
            
        img_html = (f'<img src="data:image/png;base64,{r["screenshot"]}" '
                    f'style="height:140px;border-radius:6px;border:1px solid #30363d">' if r["screenshot"] else "")
        
        rows += (
            f'<div style="background:#161b22;border:1px solid #30363d;border-radius:8px;'
            f'padding:12px;margin-bottom:10px;display:flex;gap:14px;align-items:center">'
            f'<div style="width:90px;color:{color};font-weight:700">{r["status"]}</div>'
            f'<div style="flex:1">'
            f'<div style="color:#e6edf3;font-weight:600">[{r["mode"].upper()}] {combo}</div>'
            f'<div style="color:#8b949e;font-size:12px">{r["error"]}</div>'
            f'{score_note}{note_html}{chip_html}{links_html}'
            f'</div>{img_html}</div>'
        )
        
    html = f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<title>Relief/Recovery Mode Matrix Report</title>
<style>body{{background:#0d1117;color:#e6edf3;font-family:Segoe UI,Arial,sans-serif;padding:24px}}</style>
</head><body>
<h1>Relief Mode / Recovery Mode Combination Matrix</h1>
<p style="color:#8b949e; margin-bottom:4px;">{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} - Tested on: <strong style="color:#e6edf3">{device_name}</strong></p>
<p style="margin-top:0px;">{total} combinations tested - <span style="color:#3fb950">{passed} passed</span> / <span style="color:#f85149">{failed} failed</span></p>
{rows}
</body></html>"""
    
    html_path = os.path.join(REPORT_DIR, "report.html")
    json_path = os.path.join(REPORT_DIR, "report.json")
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html)
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)
    tprint(f"REPORT  {html_path}")
    tprint(f"REPORT  {json_path}")

def build_combinations():
    combos = []
    for site in CENTRAL_SITES:
        for dur in DURATIONS:
            combos.append((site, None, dur))
    for site in LATERAL_SITES:
        for side in SIDES:
            for dur in DURATIONS:
                combos.append((site, side, dur))
    return combos

def clean_slate(driver):
    tprint("[START] Aggressively scanning ALL tabs for leftover active plans...")
    
    deleted = 0
    # Loop over all sites to aggressively clean up
    for site in ALL_SITES:
        # Try to select the site by tapping its tab
        if not try_tap(driver, f"//*[@text='{site}']", timeout=2, blanket_tap=False):
            # If the tab isn't visible, swipe the top slider left (moves tabs right)
            found = False
            for _ in range(3):
                module_w3c_swipe(driver, direction="left", y_percent=0.35)
                time.sleep(0.5)
                if try_tap(driver, f"//*[@text='{site}']", timeout=1, blanket_tap=False):
                    found = True
                    break
            # If still not found, swipe right (moves tabs left)
            if not found:
                for _ in range(4):
                    module_w3c_swipe(driver, direction="right", y_percent=0.35)
                    time.sleep(0.5)
                    if try_tap(driver, f"//*[@text='{site}']", timeout=1, blanket_tap=False):
                        found = True
                        break
                        
            if not found:
                tprint(f"   INFO  Tab for '{site}' not found on slider. Aborting cleanup sweep and starting tests!")
                break
        
        # Now that we selected the tab, try to delete any plans on it
        while delete_active_plan(driver):
            deleted += 1
            time.sleep(1)
            
    tprint(f"[START] Cleaned up {deleted} leftover plan(s). Slate is completely clean!")

def main():
    options = UiAutomator2Options()
    options.platform_name = "Android"
    options.automation_name = "UiAutomator2"
    if DEVICE_ID: options.device_name = DEVICE_ID
    options.app_package = APP_PACKAGE
    options.app_activity = APP_ACTIVITY
    options.no_reset = True
    options.auto_grant_permissions = True
    
    options.set_capability("waitForIdleTimeout", 0)

    tprint(f"RUN     Output folder: {os.path.abspath(RUN_DIR)}")
    tprint("START   Connecting to Appium & launching app...")
    driver = webdriver.Remote(APPIUM_HOST, options=options)
    time.sleep(5)  # Wait for app to fully load

    time.sleep(3)
    clean_slate(driver)

    results = []
    try:
        relief_combos = build_combinations()
        tprint(f"Running {len(relief_combos)} Relief Mode combinations...")
        for site, side, dur in relief_combos:
            results.append(run_relief_combo(driver, site, side, dur))

        if RUN_RECOVERY:
            tprint(f"Running {len(ALL_SITES)} Recovery Mode combinations...")
            for site in ALL_SITES:
                results.append(run_recovery_combo(driver, site))
        else:
            tprint("Recovery Mode SKIPPED (RUN_RECOVERY=False)")
            
    finally:
        device_name = "Unknown Device"
        try:
            device_name = driver.capabilities.get("deviceModel", driver.capabilities.get("deviceName", "Unknown Device"))
        except:
            pass
            
        generate_report(results, device_name)
        driver.quit()
        passed = sum(1 for r in results if r["status"] == "PASS")
        tprint(f"DONE    {passed}/{len(results)} combinations passed")

if __name__ == "__main__":
    main()
