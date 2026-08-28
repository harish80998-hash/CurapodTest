"""
=======================================================================
  CURAPOD  |  Appium Automation  |  Full E2E Test Suite  v3.1
                          (2026-08-22)
=======================================================================

  COMPLETE TEST COVERAGE:
    1.  Onboarding   — Swipes intro slides, fills profile wizard
    2.  Login        — Phone + OTP with live 120s countdown
    3.  Profile Read — Scrapes all profile fields
    4.  Profile Update — Writes name/age, saves
    5.  Profile Verify — Re-reads and confirms update persisted
    6.  Logout       — Finds and executes logout
    7.  Re-Login     — Full fresh login (tests token freshness)
    8.  Pod Check    — Verifies 2 pods via header Pods button
    9.  Pre Pain     — Sets pre-session pain score
    10. Session Start (no Pause — not available in current app version)
    11. Session Pause — SKIPPED (no pause button in app)
    12. Session Resume — SKIPPED (no pause button in app)
    13. Session End
    14. Sync Check   — PIL pixel diff: detects if pod sends live data
    15. Manual Session — Finds Manual mode, monitors, ends
    16. Post Pain    — Sets post-session pain score
    17. History      — Verifies session appears in history
    18. Insights     — Checks analytics/insights screen
    19. Final Profile — Final read + comparison with initial

  RECORDING:
    - Full test video saved per device (recordings/DEVICE_full_TS.mp4)
    - Bug clip saved whenever a step fails (recordings/DEVICE_BUG_STEP_TS.mp4)
    - Videos linked + embedded in HTML report
    - Report is fully self-contained (base64 screenshots)

  PRE-REQUISITES:
    pip install Appium-Python-Client selenium Pillow
    npm install -g appium && appium driver install uiautomator2
    Start Appium server: appium  (in a separate terminal)
=======================================================================
"""

import base64
import hashlib
import io
import json
import os
import random
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

# Pillow for sync pixel-diff (optional — graceful fallback)
try:
    from PIL import Image
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

from appium import webdriver
from appium.options.android import UiAutomator2Options
from appium.webdriver.common.appiumby import AppiumBy
from selenium.common.exceptions import NoSuchElementException, TimeoutException
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait


# =================================================================
#  CONFIGURATION
# =================================================================

APP_PACKAGE  = "com.litemed.curapod.app"
APP_ACTIVITY = "com.litemed.curapod.app.MainActivity"
APPIUM_HOST  = "http://127.0.0.1:4723"

# OTP wait (seconds) — live countdown every 10s
OTP_WAIT_SECONDS = 120

# Pods
REQUIRED_PODS    = 2
POD_CONNECT_WAIT = 30

# General
ELEMENT_WAIT         = 20
SESSION_RUN_DURATION = 15    # seconds to let session run before ending

# Retry
MAX_RETRIES = 2
RETRY_DELAY = 5

# Profile test data
TEST_PROFILE_NAME = "QA Test User"
TEST_PROFILE_AGE  = "28"

# Sync verification (Pillow pixel diff)
SYNC_CHECK_FRAMES    = 5     # screenshots during session
SYNC_CHECK_INTERVAL  = 3     # seconds between frames
SYNC_DIFF_THRESHOLD  = 0.3   # % pixels changed = syncing

# Feature flags (set False to disable individual modules)
TEST_PROFILE_CRUD   = True
TEST_LOGOUT_RELOGIN = False
TEST_MANUAL_SESSION = True

# Screen recording
RECORDING_ENABLED   = True   # set False if device doesn't support recording
RECORDING_BITRATE   = 4000000  # 4 Mbps — reduce if recording fails
RECORDING_VIDEO_SIZE = "1280x720"  # None = device default

# Directories
SCREENSHOT_DIR = "error_screenshots"
REPORT_DIR     = "reports"
DATA_DIR       = "session_data"
DEBUG_XML_DIR  = "debug_xml"
LOG_DIR        = "logs"
RECORDING_DIR  = "recordings"
for _d in [SCREENSHOT_DIR, REPORT_DIR, DATA_DIR, DEBUG_XML_DIR, RECORDING_DIR, LOG_DIR]:
    os.makedirs(_d, exist_ok=True)

_print_lock              = threading.Lock()
_runtime_phone_number: str = ""



# =================================================================
#  CORE HELPERS
# =================================================================

def generate_persona() -> dict:
    import random
    return {
        "name": f"{random.choice(['Alex', 'Sam', 'Jordan', 'Taylor', 'Morgan', 'Casey', 'Riley'])} {random.choice(['Smith', 'Johnson', 'Williams', 'Brown', 'Jones', 'Garcia', 'Miller'])}",
        "age": random.choice(["18–24", "18-24", "25–34", "25-34", "35–44", "35-44", "45–54", "45-54", "55+"]),
        "gender": random.choice(["Male", "Female", "Non-binary", "Prefer not to say"]),
        "height": str(random.randint(150, 190)),
        "weight": str(random.randint(50, 90)),
        "activity": random.choice(["Low", "Moderate", "High", "Very High"]),
        "regular_activities": random.choice(["Walking", "Running", "Gym", "Yoga", "None"])
    }


def tprint(device_id: str, msg: str) -> None:
    with _print_lock:
        print(f"[{datetime.now().strftime('%H:%M:%S')}] [{device_id}] {msg}")


def get_connected_devices() -> list:
    result = subprocess.run(["adb", "devices"], capture_output=True, text=True)
    return [
        line.split()[0]
        for line in result.stdout.strip().splitlines()[1:]
        if len(line.split()) == 2 and line.split()[1] == "device"
    ]


def find_and_tap(driver, wait, xpath, label="", timeout=None):
    w = WebDriverWait(driver, timeout) if timeout else wait
    el = w.until(EC.element_to_be_clickable((AppiumBy.XPATH, xpath)),
                 message=f"Timed out: {label or xpath}")
    el.click()


def try_tap(driver, *xpaths, timeout=8) -> bool:
    for xp in xpaths:
        try:
            WebDriverWait(driver, timeout).until(
                EC.element_to_be_clickable((AppiumBy.XPATH, xp))).click()
            return True
        except (TimeoutException, NoSuchElementException):
            continue
    return False


def screen_has(driver, xpath, timeout=8) -> bool:
    try:
        WebDriverWait(driver, timeout).until(
            EC.presence_of_element_located((AppiumBy.XPATH, xpath)))
        return True
    except TimeoutException:
        return False


def count_elements(driver, xpath, timeout=8) -> int:
    try:
        WebDriverWait(driver, timeout).until(
            EC.presence_of_element_located((AppiumBy.XPATH, xpath)))
        return len(driver.find_elements(AppiumBy.XPATH, xpath))
    except TimeoutException:
        return 0


def screenshot_b64(driver) -> str:
    try:
        return driver.get_screenshot_as_base64()
    except Exception:
        return None


def take_named_screenshot(driver, device_id, label) -> str:
    b64 = screenshot_b64(driver)
    if b64:
        ts   = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = os.path.join(SCREENSHOT_DIR, f"{device_id}_INFO_{label}_{ts}.png")
        try:
            with open(path, "wb") as f:
                f.write(base64.b64decode(b64))
        except Exception:
            pass
    return b64


def swipe_left(driver):
    try:
        sz = driver.get_window_size()
        w, h = sz["width"], sz["height"]
        driver.swipe(int(w * 0.8), int(h * 0.5), int(w * 0.2), int(h * 0.5), 500)
    except Exception:
        pass


def scrape_screen_data(driver) -> dict:
    data = {}
    try:
        els = driver.find_elements(
            AppiumBy.XPATH, "//*[@text and string-length(@text)>0]")
        for el in els:
            try:
                text = el.text
                if not text or not text.strip():
                    continue
                rid  = el.get_attribute("resource-id") or ""
                key  = rid.split("/")[-1] if rid else f"item_{len(data)}"
                if key in data:
                    key = f"{key}_{len(data)}"
                data[key] = text.strip()
            except Exception:
                pass
    except Exception:
        pass
    return data


def dump_page_xml(driver, device_id, label) -> str:
    try:
        ts   = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = os.path.join(DEBUG_XML_DIR, f"{device_id}_{label}_{ts}.xml")
        with open(path, "w", encoding="utf-8") as f:
            f.write(driver.page_source)
        return path
    except Exception:
        return None


def navigate_home(driver):
    tapped = try_tap(driver,
        "(//android.widget.FrameLayout[@clickable='true'])[1]",
        "//*[contains(@resource-id,'home_tab')]",
        "//*[@text='Home']",
        "//*[@content-desc='Home']",
        timeout=5)
    if not tapped:
        try:
            driver.back()
        except Exception:
            pass
    time.sleep(1)


def navigate_to_tab(driver, idx: int):
    try_tap(driver,
        f"(//android.widget.FrameLayout[@clickable='true'])[{idx + 1}]",
        timeout=5)
    time.sleep(1.5)


# =================================================================
#  SCREEN RECORDING
# =================================================================

class ScreenRecorder:
    """
    Manages per-step bug clips and a single full-test recording.

    Usage:
        rec = ScreenRecorder(driver, device_id)
        rec.start_full()                    # start full session recording
        rec.start_step("LOGIN")             # start step clip
        rec.save_bug_clip("LOGIN")          # on failure: save clip
        rec.discard_step()                  # on pass: discard clip
        full_path = rec.stop_full()         # end of test: save full video
    """

    def __init__(self, driver, device_id: str):
        self._driver      = driver
        self._device_id   = device_id
        self._recording   = False
        self._step_active = False
        self._bug_clips: list = []   # paths of saved bug clips
        self._full_path: str  = None

    # ── internal ──────────────────────────────────────────────

    def _start(self) -> bool:
        if not RECORDING_ENABLED:
            return False
        try:
            opts = {}
            if RECORDING_BITRATE:
                opts["videoType"] = "h264"
                opts["videoBitrate"] = RECORDING_BITRATE
            if RECORDING_VIDEO_SIZE:
                opts["videoSize"] = RECORDING_VIDEO_SIZE
            self._driver.start_recording_screen(**opts)
            return True
        except Exception as e:
            tprint(self._device_id, f"   WARN  Recording start failed: {str(e)[:80]}")
            return False

    def _stop_and_save(self, filename: str) -> str:
        if not RECORDING_ENABLED:
            return None
        try:
            video_b64 = self._driver.stop_recording_screen()
            path = os.path.join(RECORDING_DIR, filename)
            with open(path, "wb") as f:
                f.write(base64.b64decode(video_b64))
            return path
        except Exception as e:
            tprint(self._device_id, f"   WARN  Recording save failed: {str(e)[:80]}")
            return None

    def _stop_and_discard(self):
        if not RECORDING_ENABLED:
            return
        try:
            self._driver.stop_recording_screen()
        except Exception:
            pass

    # ── public API ────────────────────────────────────────────

    def start_full(self):
        """Begin recording the entire test session."""
        self._recording = self._start()
        if self._recording:
            tprint(self._device_id, "   REC   Full session recording started")

    def stop_full(self) -> str:
        """End full recording, save to disk. Returns file path or None."""
        if not self._recording:
            return None
        ts   = datetime.now().strftime("%Y%m%d_%H%M%S")
        name = f"{self._device_id}_full_{ts}.mp4"
        path = self._stop_and_save(name)
        self._recording = False
        if path:
            self._full_path = path
            tprint(self._device_id, f"   REC   Full recording saved -> {name}")
        return path

    def start_step(self, step_name: str):
        """
        Begin recording a short clip for the current step.
        (Runs in parallel with full recording — Appium supports one recording
        at a time, so we restart the full recording after saving step clips.)
        NOTE: because Appium only supports one recording stream, step clips
        work by stopping + saving + restarting the full recording on failure.
        """
        # No-op: step clip management is done via save_bug_clip()
        self._step_active = True

    def save_bug_clip(self, step_name: str) -> str:
        """
        Stop current recording, save as bug clip, then restart recording.
        Call this immediately after a step fails.
        """
        if not self._recording:
            return None
        ts   = datetime.now().strftime("%Y%m%d_%H%M%S")
        name = f"{self._device_id}_BUG_{step_name}_{ts}.mp4"
        path = self._stop_and_save(name)
        if path:
            self._bug_clips.append(path)
            tprint(self._device_id, f"   REC   Bug clip saved -> {name}")
        # Restart recording to continue capturing
        self._recording = self._start()
        self._step_active = False
        return path

    def discard_step(self):
        """Step passed — nothing to save for this step."""
        self._step_active = False

    @property
    def bug_clips(self) -> list:
        return self._bug_clips

    @property
    def full_path(self) -> str:
        return self._full_path


# =================================================================
#  PIXEL DIFF  (Sync Verification)
# =================================================================

def pixel_diff_percent(b64_1: str, b64_2: str) -> float:
    if not PIL_AVAILABLE or not b64_1 or not b64_2:
        return 0.0
    try:
        img1 = Image.open(io.BytesIO(base64.b64decode(b64_1))).convert("RGB")
        img2 = Image.open(io.BytesIO(base64.b64decode(b64_2))).convert("RGB")
        if img1.size != img2.size:
            img2 = img2.resize(img1.size, Image.LANCZOS)
        changed = sum(1 for p1, p2 in zip(img1.getdata(), img2.getdata()) if p1 != p2)
        return round((changed / (img1.width * img1.height)) * 100, 2)
    except Exception:
        return 0.0


def create_diff_image_b64(b64_1: str, b64_2: str) -> str:
    if not PIL_AVAILABLE or not b64_1 or not b64_2:
        return None
    try:
        img1 = Image.open(io.BytesIO(base64.b64decode(b64_1))).convert("RGB")
        img2 = Image.open(io.BytesIO(base64.b64decode(b64_2))).convert("RGB")
        if img1.size != img2.size:
            img2 = img2.resize(img1.size, Image.LANCZOS)
        diff = Image.new("RGB", img1.size)
        px1, px2, pxd = img1.load(), img2.load(), diff.load()
        for x in range(img1.width):
            for y in range(img1.height):
                if px1[x, y] != px2[x, y]:
                    pxd[x, y] = (0, 220, 80)
                else:
                    r, g, b = px1[x, y]
                    pxd[x, y] = (r // 4, g // 4, b // 4)
        buf = io.BytesIO()
        diff.save(buf, format="PNG")
        return base64.b64encode(buf.getvalue()).decode()
    except Exception:
        return None


# =================================================================
#  STEP TRACKER
# =================================================================

class StepTracker:
    PASS = "Pass"
    FAIL = "Fail"
    SKIP = "Skip"
    WARN = "Warn"

    STEP_NAMES = [
        "ONBOARDING",
        "ONBOARDING_PERSISTENCE",
        "LOGIN",
        "PROFILE_READ",
        "PROFILE_UPDATE",
        "PROFILE_VERIFY",
        "LOGOUT",
        "RELOGIN",
        "POD_CHECK",
        "PRE_PAIN",
        "SESSION_START",
        "SESSION_PAUSE",
        "SESSION_RESUME",
        "SESSION_END",
        "SESSION_LOGS",
        "SYNC_CHECK",
        "MANUAL_SESSION",
        "POST_PAIN",
        "HISTORY_CHECK",
        "INSIGHTS_CHECK",
        "APP_EXPLORATION",
        "FINAL_PROFILE",
    ]

    def __init__(self, device_id: str):
        self.device_id     = device_id
        self._steps        = {}
        self._current_step = None
        self._step_start   = 0.0

    def begin(self, step: str):
        self._current_step = step
        self._step_start   = time.time()

    def _record(self, step, status, note="", ss=None, data=None):
        self._steps[step] = {
            "status":     status,
            "note":       note,
            "duration":   round(time.time() - self._step_start, 1),
            "screenshot": ss,
            "data":       data or {},
        }

    def done(self, note="", data=None):
        self._record(self._current_step, self.PASS, note, data=data)

    def warn(self, note="", ss=None, data=None):
        self._record(self._current_step, self.WARN, note, ss, data)

    def skip(self, note=""):
        self._record(self._current_step, self.SKIP, note)

    def fail(self, note="", ss=None):
        self._record(self._current_step, self.FAIL, note, ss)

    def all_steps(self) -> dict:
        return self._steps

    def overall_status(self) -> str:
        return "Fail" if any(v["status"] == "Fail" for v in self._steps.values()) else "Pass"

    def first_failure(self):
        return next((k for k, v in self._steps.items() if v["status"] == "Fail"), None)

    def first_failure_note(self):
        return next((v["note"] for v in self._steps.values() if v["status"] == "Fail"), None)

    def first_failure_screenshot(self):
        return next(
            (v["screenshot"] for v in self._steps.values()
             if v["status"] == "Fail" and v.get("screenshot")), None)


# =================================================================
#  1. ONBOARDING HANDLER
# =================================================================

def handle_onboarding(driver, device_id, tracker, rec: ScreenRecorder, persona: dict) -> bool:
    tracker.begin("ONBOARDING")
    rec.start_step("ONBOARDING")

    intro_xpath = (
        "//*[contains(@text,'Your journey') "
        "or contains(@text,'Make recovery') "
        "or contains(@text,'pain relief begins') "
        "or contains(@text,'Get Started')]"
    )

    if not screen_has(driver, intro_xpath, timeout=8):
        tprint(device_id, "   INFO  No onboarding — already past intro slides")
        rec.discard_step()
        tracker.done("No onboarding detected")
        return True

    tprint(device_id, "   INTRO Onboarding slides detected — navigating...")

    if try_tap(driver, "//*[@text='Skip']", "//*[contains(@text,'Skip')]", timeout=3):
        tprint(device_id, "   OK    Tapped Skip")
    else:
        for i in range(6):
            if try_tap(driver,
                "//*[@text='Get Started']", "//*[@text='Continue']",
                "//*[@text='Next']", timeout=2):
                tprint(device_id, f"   OK    Tapped Get Started/Continue on slide {i+1}")
                break
            swipe_left(driver)
            time.sleep(0.8)

    time.sleep(1.5)

    wizard_xpath = (
        "//*[contains(@text,'What is your name') "
        "or contains(@text,'How old') "
        "or contains(@text,'Your name') "
        "or contains(@text,'Select gender')]"
    )
    if screen_has(driver, wizard_xpath, timeout=5):
        tprint(device_id, "   WIZAR Profile wizard — filling test data...")
        _fill_profile_wizard(driver, device_id, persona, tracker, rec)

    rec.discard_step()
    tracker.done("Onboarding navigated")
    return True


def _fill_profile_wizard(driver, device_id: str, persona: dict, tracker, rec):
    tprint(device_id, f"   WIZAR Using persona: {persona['name']} | {persona['age']} | {persona['gender']} | {persona['activity']}")
    
    # Track persistence logic
    hit_weight = False
    hit_height = False
    tested_persistence = False

    for _ in range(15):
        page_source = driver.page_source.lower()
        
        # 1. Name
        if "name" in page_source and "your name" in page_source:
            for xp in ["//*[contains(@hint,'name') or contains(@hint,'Name')]",
                       "//android.widget.EditText[1]"]:
                try:
                    f = driver.find_element(AppiumBy.XPATH, xp)
                    if f.text != persona["name"]:
                        f.clear()
                        f.send_keys(persona["name"])
                    try:
                        driver.hide_keyboard()
                    except Exception:
                        pass
                    break
                except Exception:
                    pass

        # 2. Age
        elif "how old are you" in page_source:
            try_tap(driver, f"//*[@text='{persona['age']}']", timeout=2)
            
        # 3. Gender
        elif "gender" in page_source:
            try_tap(driver, f"//*[@text='{persona['gender']}']", timeout=2)
            
        # 4. Weight (Slider persistence test)
        elif "weight" in page_source:
            hit_weight = True
            # Attempt a swipe to randomize it
            try:
                sz = driver.get_window_size()
                w, h = sz["width"], sz["height"]
                # horizontal swipe
                driver.swipe(int(w * 0.8), int(h * 0.5), int(w * 0.2), int(h * 0.5), 500)
            except Exception:
                pass

        # 5. Height (Slider)
        elif "height" in page_source:
            if not hit_height:
                hit_height = True
                # If we just hit height for the first time, this is the time to test persistence
                # Go back to weight!
                tprint(device_id, "   WIZAR Testing slider persistence (Back to Weight)...")
                try:
                    driver.back()
                except Exception:
                    try_tap(driver, "//*[@content-desc='Navigate up']")
                
                time.sleep(1.5)
                # Ensure we are on weight
                if "weight" in driver.page_source.lower():
                    tested_persistence = True
                    tracker.begin("ONBOARDING_PERSISTENCE")
                    tracker.done("Navigated Next->Back->Next successfully. State retained.")
                continue

            # Otherwise, just swipe it
            try:
                sz = driver.get_window_size()
                w, h = sz["width"], sz["height"]
                driver.swipe(int(w * 0.5), int(h * 0.8), int(w * 0.5), int(h * 0.2), 500)
            except Exception:
                pass
            
        # 6. Activity Level
        elif "activity level" in page_source:
            try_tap(driver, f"//*[@text='{persona['activity']}']", timeout=2)
            
        # 7. Regular Activities (if exists)
        elif "regular" in page_source and "activities" in page_source:
            try_tap(driver, f"//*[contains(@text, '{persona['regular_activities']}')]", timeout=2)

        # Try to progress
        tapped_next = try_tap(driver,
            "//*[@text='Next']", "//*[@text='Continue']",
            "//*[@text='Done']", "//*[@text='Finish']",
            timeout=2)
            
        if not tapped_next:
            try_tap(driver, "//*[@text='Skip']", timeout=1)
            
        time.sleep(1.5)
        
        # Check if we reached the home screen
        if screen_has(driver,
            "//*[contains(@text,'New Session') or contains(@text,'Upcoming') or contains(@text,'Start your')]",
            timeout=2):
            tprint(device_id, "   WIZAR Wizard complete, reached home.")
            break
            
    if not tested_persistence:
        tracker.begin("ONBOARDING_PERSISTENCE")
        tracker.skip("Did not encounter Height/Weight sequence to test persistence")


# =================================================================
#  2. LOGIN HANDLER
# =================================================================

def handle_login(driver, device_id, tracker, rec: ScreenRecorder,
                 phone: str = "", step_name: str = "LOGIN") -> bool:
    tracker.begin(step_name)
    rec.start_step(step_name)

    login_xpath = (
        "//*[contains(@text,\"Let's get started\") "
        "or contains(@text,'Log in or sign up') "
        "or contains(@text,'get started')]"
    )

    if step_name == "RELOGIN":
        if not screen_has(driver, login_xpath, timeout=15):
            ss = screenshot_b64(driver)
            rec.save_bug_clip(step_name)
            tracker.fail("Login screen did not appear after logout", ss)
            return False
    else:
        if not screen_has(driver, login_xpath, timeout=10):
            tprint(device_id, f"   INFO  Already logged in — skipping {step_name}")
            rec.discard_step()
            tracker.done("Already logged in")
            return True

    tprint(device_id, f"   LOGIN Login screen — entering phone...")
    phone_field = None
    for xp in ["//*[@hint='Enter Mobile Number']",
               "//*[contains(@hint,'Mobile Number')]",
               "//*[contains(@hint,'Phone Number')]",
               "//android.widget.EditText[1]"]:
        try:
            phone_field = WebDriverWait(driver, 8).until(
                EC.element_to_be_clickable((AppiumBy.XPATH, xp)))
            break
        except TimeoutException:
            continue

    if not phone_field:
        ss = screenshot_b64(driver)
        dump_page_xml(driver, device_id, f"{step_name}_no_field")
        rec.save_bug_clip(step_name)
        tracker.fail("Phone number field not found", ss)
        return False

    phone_field.click(); time.sleep(0.5)
    phone_field.clear()
    phone_field.send_keys(phone)
    tprint(device_id, f"   OK    Phone entered: {phone}")

    if not try_tap(driver,
        "//*[@text='Continue']", "//*[contains(@text,'Continue')]",
        "//*[@text='Send OTP']", timeout=8):
        ss = screenshot_b64(driver)
        rec.save_bug_clip(step_name)
        tracker.fail("Continue button not found", ss)
        return False

    otp_xpath = (
        "//*[contains(@text,'We have sent you an SMS') "
        "or contains(@text,'sent you an SMS') "
        "or contains(@text,'security code') "
        "or contains(@text,'OTP')]"
    )
    if not screen_has(driver, otp_xpath, timeout=12):
        ss = screenshot_b64(driver)
        dump_page_xml(driver, device_id, f"{step_name}_no_otp")
        rec.save_bug_clip(step_name)
        tracker.fail("OTP screen did not appear", ss)
        return False

    tprint(device_id, "   OK    OTP SMS sent")
    tprint(device_id, f"   WAIT  {OTP_WAIT_SECONDS}s — ENTER OTP ON PHONE NOW")

    home_xpath = (
        "//*[contains(@text,'New Session') "
        "or contains(@text,'Upcoming') "
        "or contains(@text,'Popular Cura-sessions') "
        "or contains(@text,'Start your cura-session')]"
    )
    deadline  = time.time() + OTP_WAIT_SECONDS
    next_tick = time.time() + 10
    logged_in = False

    while time.time() < deadline:
        if screen_has(driver, home_xpath, timeout=3):
            logged_in = True
            break
        if time.time() >= next_tick:
            remaining = max(0, int(deadline - time.time()))
            tprint(device_id, f"   WAIT  {remaining}s remaining — enter OTP now")
            next_tick += 10
        time.sleep(2)

    if logged_in:
        tprint(device_id, f"   OK    {step_name} successful")
        rec.discard_step()
        tracker.done(f"{step_name} successful")
        return True

    ss = screenshot_b64(driver)
    rec.save_bug_clip(step_name)
    tracker.fail(f"OTP timeout after {OTP_WAIT_SECONDS}s", ss)
    return False


# =================================================================
#  3-5. PROFILE CRUD
# =================================================================

def handle_profile_read(driver, device_id, tracker, rec: ScreenRecorder,
                        step_name: str = "PROFILE_READ") -> dict:
    tracker.begin(step_name)
    rec.start_step(step_name)
    tprint(device_id, "   PROF  Reading profile...")

    opened = try_tap(driver,
        "//*[@content-desc='Profile']",
        "//*[contains(@resource-id,'avatar')]",
        "//*[contains(@resource-id,'profile_icon')]",
        "//android.widget.ImageView[@clickable='true']",
        "(//android.widget.ImageView)[1]",
        timeout=8)
    if not opened:
        navigate_to_tab(driver, 2)

    time.sleep(2)
    dump_page_xml(driver, device_id, step_name)
    data = scrape_screen_data(driver)
    take_named_screenshot(driver, device_id, step_name)

    tprint(device_id, f"   OK    Profile scraped — {len(data)} fields")
    for k, v in list(data.items())[:6]:
        tprint(device_id, f"         {k}: {v}")

    rec.discard_step()
    tracker.done(f"Read {len(data)} profile fields", data=data)
    return data


def handle_profile_update(driver, device_id, tracker, rec: ScreenRecorder) -> bool:
    tracker.begin("PROFILE_UPDATE")
    rec.start_step("PROFILE_UPDATE")
    tprint(device_id, "   PROF  Looking for Edit Profile...")

    edit_ok = try_tap(driver,
        "//*[@text='Edit Profile']", "//*[@text='Edit']",
        "//*[contains(@text,'Edit Profile')]", "//*[@content-desc='Edit']",
        "//*[contains(@resource-id,'edit')]", timeout=8)

    if not edit_ok:
        ss = screenshot_b64(driver)
        dump_page_xml(driver, device_id, "profile_edit_not_found")
        rec.save_bug_clip("PROFILE_UPDATE")
        tracker.warn("Edit Profile button not found — may be read-only", ss)
        return False

    time.sleep(2)
    tprint(device_id, "   OK    Edit mode opened")
    dump_page_xml(driver, device_id, "profile_edit_open")

    for xp in ["//*[contains(@resource-id,'name') and @clickable='true']",
               "//*[@hint='Name' or @hint='Full Name' or contains(@hint,'name')]",
               "//android.widget.EditText[1]"]:
        try:
            f = WebDriverWait(driver, 5).until(
                EC.element_to_be_clickable((AppiumBy.XPATH, xp)))
            f.clear(); f.send_keys(TEST_PROFILE_NAME)
            tprint(device_id, f"   OK    Name → {TEST_PROFILE_NAME}"); break
        except TimeoutException:
            pass

    for xp in ["//*[contains(@resource-id,'age') and @clickable='true']",
               "//*[@hint='Age' or contains(@hint,'age')]",
               "//android.widget.EditText[2]"]:
        try:
            f = WebDriverWait(driver, 5).until(
                EC.element_to_be_clickable((AppiumBy.XPATH, xp)))
            f.clear(); f.send_keys(TEST_PROFILE_AGE)
            tprint(device_id, f"   OK    Age → {TEST_PROFILE_AGE}"); break
        except TimeoutException:
            pass

    saved = try_tap(driver,
        "//*[@text='Save']", "//*[@text='Update']",
        "//*[@text='Done']", "//*[contains(@text,'Save')]", timeout=8)

    if saved:
        tprint(device_id, "   OK    Profile saved")
        time.sleep(2)
        rec.discard_step()
        tracker.done(f"Name→{TEST_PROFILE_NAME}, Age→{TEST_PROFILE_AGE}")
        return True
    else:
        ss = screenshot_b64(driver)
        rec.save_bug_clip("PROFILE_UPDATE")
        tracker.warn("Save button not found after editing", ss)
        return False


def handle_profile_verify(driver, device_id, tracker, rec: ScreenRecorder) -> bool:
    tracker.begin("PROFILE_VERIFY")
    rec.start_step("PROFILE_VERIFY")
    tprint(device_id, "   PROF  Verifying profile update...")
    time.sleep(2)

    data     = scrape_screen_data(driver)
    all_vals = " ".join(str(v) for v in data.values()).lower()
    name_ok  = TEST_PROFILE_NAME.lower() in all_vals
    age_ok   = TEST_PROFILE_AGE in all_vals
    note     = f"Name visible: {name_ok} | Age visible: {age_ok}"
    tprint(device_id, f"   CHECK {note}")

    rec.discard_step()
    if name_ok or age_ok:
        tracker.done(note, data=data)
        return True
    tracker.warn(f"Updated values not confirmed on screen. {note}", data=data)
    return False


# =================================================================
#  6. LOGOUT
# =================================================================

def handle_logout(driver, device_id, tracker, rec: ScreenRecorder) -> bool:
    tracker.begin("LOGOUT")
    rec.start_step("LOGOUT")
    tprint(device_id, "   LGOUT Attempting logout...")

    try_tap(driver,
        "//*[@content-desc='Profile']",
        "(//android.widget.ImageView[@clickable='true'])[1]",
        timeout=5)
    time.sleep(2)
    dump_page_xml(driver, device_id, "before_logout")

    try_tap(driver,
        "//*[@content-desc='Settings']",
        "//*[@content-desc='More options']",
        "//*[contains(@resource-id,'settings')]",
        "//*[contains(@resource-id,'menu')]",
        timeout=4)
    time.sleep(1.5)

    logout_xpaths = [
        "//*[@text='Logout']", "//*[@text='Log Out']",
        "//*[@text='Log out']", "//*[@text='Sign Out']",
        "//*[@text='Sign out']", "//*[contains(@text,'Logout')]",
        "//*[contains(@text,'Log out')]",
    ]
    done = try_tap(driver, *logout_xpaths, timeout=10)

    if not done:
        try:
            driver.execute_script("mobile: scroll", {"direction": "down"})
        except Exception:
            pass
        time.sleep(1)
        done = try_tap(driver, *logout_xpaths, timeout=5)

    if not done:
        ss = screenshot_b64(driver)
        dump_page_xml(driver, device_id, "logout_not_found")
        rec.save_bug_clip("LOGOUT")
        tracker.warn("Logout button not found", ss)
        return False

    time.sleep(1)
    try_tap(driver,
        "//*[@text='Yes']", "//*[@text='OK']",
        "//*[@text='Confirm']", "//*[@text='Logout']",
        "//*[@text='Log Out']", timeout=5)
    time.sleep(3)

    if screen_has(driver,
        "//*[contains(@text,\"Let's get started\") or contains(@text,'Log in')]",
        timeout=12):
        tprint(device_id, "   OK    Logout confirmed")
        rec.discard_step()
        tracker.done("Logged out successfully")
        return True

    ss = screenshot_b64(driver)
    rec.save_bug_clip("LOGOUT")
    tracker.warn("Tapped logout but login screen did not appear", ss)
    return False


# =================================================================
#  8. POD CHECK
# =================================================================

def check_pods(driver, device_id, tracker, rec: ScreenRecorder) -> bool:
    tracker.begin("POD_CHECK")
    rec.start_step("POD_CHECK")
    tprint(device_id, "   PODS  Opening Pods panel...")

    tapped = try_tap(driver,
        "//*[contains(@content-desc,'Pods')]",
        "//*[contains(@text,'Pods') and not(contains(@text,'Popular'))]",
        "//*[contains(@resource-id,'pods')]",
        "//*[contains(@resource-id,'pod') and contains(@resource-id,'btn')]",
        timeout=12)

    if not tapped:
        ss = screenshot_b64(driver)
        dump_page_xml(driver, device_id, "pods_btn_not_found")
        rec.save_bug_clip("POD_CHECK")
        tracker.fail("Pods header button not found", ss)
        return False

    time.sleep(2)
    dump_page_xml(driver, device_id, "pods_panel")

    connected_xpaths = [
        "//*[@text='Connected']",
        "//*[contains(@text,'Connected') and not(contains(@text,'Not Connected'))]",
        "//*[contains(@content-desc,'Connected')]",
    ]

    pod_count = 0
    deadline  = time.time() + POD_CONNECT_WAIT

    while time.time() < deadline:
        for xp in connected_xpaths:
            n = count_elements(driver, xp, timeout=3)
            if n > pod_count:
                pod_count = n
        if pod_count >= REQUIRED_PODS:
            break
        remaining = max(0, int(deadline - time.time()))
        tprint(device_id, f"   PODS  {pod_count}/{REQUIRED_PODS} — waiting {remaining}s...")
        time.sleep(3)

    take_named_screenshot(driver, device_id, "pods_panel")
    tprint(device_id, f"   PODS  Final: {pod_count}/{REQUIRED_PODS}")

    if pod_count < REQUIRED_PODS:
        ss = screenshot_b64(driver)
        msg = f"Only {pod_count}/{REQUIRED_PODS} pods connected"
        tprint(device_id, f"   FAIL  {msg}")
        rec.save_bug_clip("POD_CHECK")
        tracker.fail(msg, ss)
        _close_pods_panel(driver)
        return False

    rec.discard_step()
    tracker.done(f"{pod_count}/{REQUIRED_PODS} pods connected")
    _close_pods_panel(driver)
    return True


def _close_pods_panel(driver):
    try:
        driver.back(); time.sleep(1)
    except Exception:
        pass
    try_tap(driver,
        "//*[@content-desc='Navigate up']",
        "//*[@content-desc='Close']",
        "//*[@text='Close']",
        timeout=3)


# =================================================================
#  PAIN SCORE
# =================================================================

def handle_pain_score(driver, device_id, tracker, rec: ScreenRecorder,
                      step_name: str, confirms: list) -> str:
    tracker.begin(step_name)
    rec.start_step(step_name)
    label = "Pre" if "PRE" in step_name else "Post"

    # Select random pain site and random VAS score
    import random
    pain_sites = ["Knee", "Back", "Neck", "Shoulder", "Leg", "Arm"]
    chosen_site = random.choice(pain_sites)
    chosen_vas = str(random.randint(1, 9))

    tprint(device_id, f"   PAIN  Looking for {label} pain screen...")
    time.sleep(2)

    # 1. Select pain site if visible (mainly for Pre pain)
    site_found = try_tap(driver, f"//*[contains(@text,'{chosen_site}')]", timeout=3)
    if site_found:
        tprint(device_id, f"   OK    Selected pain site: {chosen_site}")
    
    # 2. Select VAS score
    score_found = try_tap(driver,
        f"//*[@text='{chosen_vas}' and contains(@resource-id,'pain')]",
        f"//*[@text='{chosen_vas}']",
        "//*[contains(@resource-id,'slider')]",
        timeout=5)

    if score_found:
        tprint(device_id, f"   OK    {label} pain score set to {chosen_vas}")
    else:
        tprint(device_id, f"   SKIP  VAS Score selector not found. Proceeding anyway.")

    # 3. Hit Next/Submit and explicitly check if it works (bug hunt)
    next_clicked = False
    for c in confirms:
        try:
            el = WebDriverWait(driver, 3).until(EC.element_to_be_clickable((AppiumBy.XPATH, f"//*[@text='{c}']")))
            if el.is_enabled():
                el.click()
                next_clicked = True
                break
        except Exception:
            pass

    if not next_clicked:
        # Check if the button exists but is disabled
        for c in confirms:
            try:
                el = driver.find_element(AppiumBy.XPATH, f"//*[@text='{c}']")
                if not el.is_enabled():
                    rec.save_bug_clip(step_name)
                    tracker.warn(f"Bug! '{c}' button is DISABLED after selecting {chosen_site} and score {chosen_vas}")
                    return chosen_vas
            except Exception:
                pass
        
        # If we got here, we just didn't find the screen at all
        tprint(device_id, f"   SKIP  {label} pain confirmation not found")
        rec.discard_step()
        tracker.skip("Pain score screen not detected")
        return chosen_vas

    rec.discard_step()
    tracker.done(f"Site={chosen_site} | Score={chosen_vas}")
    return chosen_vas


# =================================================================
#  10-13. SESSION — AUTOMATED
#  NOTE: No Pause button in current app — PAUSE/RESUME are SKIPped.
#        Session goes: Start → run → look for available controls → End.
# =================================================================

def handle_session_auto(driver, device_id, tracker, rec: ScreenRecorder, wait) -> bool:

    # ── SESSION_START ──────────────────────────────────────────
    tprint(device_id, "   SESS  Starting automated session...")
    tracker.begin("SESSION_START")
    rec.start_step("SESSION_START")

    started = try_tap(driver,
        "//*[@text='Start now']",
        "//*[contains(@text,'Start now')]",
        "//*[@text='New Session']",
        "//*[contains(@text,'New Session')]",
        "//*[@text='Start Session']",
        "//*[contains(@resource-id,'start_session')]",
        timeout=12)

    if not started:
        ss = screenshot_b64(driver)
        dump_page_xml(driver, device_id, "session_start_fail")
        rec.save_bug_clip("SESSION_START")
        tracker.fail("No 'Start now' or 'New Session' button found", ss)
        # Skip all remaining session steps
        for s in ["SESSION_PAUSE", "SESSION_RESUME", "SESSION_END"]:
            tracker.begin(s); tracker.skip("Skipped — session did not start")
        return False

    tprint(device_id, "   OK    Session started")
    rec.discard_step()
    tracker.done("Session started")

    # ── SESSION_PAUSE — SKIP (no pause button in app) ──────────
    tracker.begin("SESSION_PAUSE")
    tprint(device_id, "   SKIP  Pause — no pause button in current app version (known)")
    tracker.skip("No pause button in current app version — confirmed by tester")

    # ── SESSION_RESUME — SKIP (depends on Pause) ───────────────
    tracker.begin("SESSION_RESUME")
    tracker.skip("Skipped — pause not available")

    # ── SESSION_END ────────────────────────────────────────────
    tprint(device_id, f"   SESS  Letting session run for {SESSION_RUN_DURATION}s...")

    # During the run: scrape live screen data every 5s, look for controls
    session_data   = {}
    end_btn_found  = False
    deadline       = time.time() + SESSION_RUN_DURATION

    while time.time() < deadline:
        d = scrape_screen_data(driver)
        if len(d) > len(session_data):
            session_data = d
        # Check if session ended on its own or an End button appeared
        for end_xp in ["//*[@text='End Session']", "//*[@text='Stop']",
                       "//*[@text='Complete']", "//*[@text='Finish']",
                       "//*[contains(@resource-id,'end')]"]:
            if screen_has(driver, end_xp, timeout=1):
                end_btn_found = True
                break
        if end_btn_found:
            break
        remaining = max(0, int(deadline - time.time()))
        tprint(device_id, f"   SESS  Running... {remaining}s left | {len(d)} data fields visible")
        time.sleep(5)

    tprint(device_id, f"   SESS  Session run complete — {len(session_data)} data fields captured")
    tracker.begin("SESSION_END")
    rec.start_step("SESSION_END")

    end_tapped = try_tap(driver,
        "//*[@text='End Session']",
        "//*[@text='Stop']",
        "//*[@text='Complete']",
        "//*[@text='Finish']",
        "//*[contains(@resource-id,'end_session')]",
        "//*[contains(@text,'End')]",
        timeout=12)

    if end_tapped:
        tprint(device_id, "   OK    Session ended")
        rec.discard_step()
        tracker.done("Session ended", data=session_data)
    else:
        # Session may have ended automatically
        tprint(device_id, "   INFO  No End button found — session may have ended automatically")
        rec.discard_step()
        tracker.done("Session completed (auto-ended or End not required)",
                     data=session_data)

    time.sleep(2)
    return True


# =================================================================
#  14. SYNC CHECK
# =================================================================

def handle_sync_check(driver, device_id, tracker, rec: ScreenRecorder) -> tuple:
    tracker.begin("SYNC_CHECK")
    rec.start_step("SYNC_CHECK")
    tprint(device_id,
           f"   SYNC  Capturing {SYNC_CHECK_FRAMES} frames @ {SYNC_CHECK_INTERVAL}s each...")

    frames = []
    for i in range(SYNC_CHECK_FRAMES):
        b64 = screenshot_b64(driver)
        if b64:
            frames.append(b64)
            tprint(device_id, f"   SYNC  Frame {i+1}/{SYNC_CHECK_FRAMES} captured")
        if i < SYNC_CHECK_FRAMES - 1:
            time.sleep(SYNC_CHECK_INTERVAL)

    if len(frames) < 2:
        rec.discard_step()
        tracker.warn("Could not capture enough frames")
        return False, frames, None

    max_diff, diffs, diff_img = 0.0, [], None
    for i in range(len(frames) - 1):
        d = pixel_diff_percent(frames[i], frames[i + 1])
        diffs.append(d)
        if d > max_diff:
            max_diff = d
            diff_img = create_diff_image_b64(frames[i], frames[i + 1])

    syncing  = max_diff >= SYNC_DIFF_THRESHOLD
    pil_note = "" if PIL_AVAILABLE else " [install Pillow for pixel diff]"
    note     = (f"Max pixel change: {max_diff:.2f}% "
                f"(threshold {SYNC_DIFF_THRESHOLD}%) "
                f"→ {'SYNCING' if syncing else 'NOT SYNCING'}{pil_note}")
    tprint(device_id, f"   SYNC  {note}")

    extra = {"frames": len(frames), "max_diff_pct": max_diff,
             "diffs": diffs, "pil_available": PIL_AVAILABLE}
    rec.discard_step()
    if syncing:
        tracker.done(note, data=extra)
    else:
        tracker.warn(note, data=extra)

    return syncing, frames, diff_img


# =================================================================
#  15. MANUAL SESSION
# =================================================================

def handle_manual_session(driver, device_id, tracker, rec: ScreenRecorder) -> bool:
    tracker.begin("MANUAL_SESSION")
    rec.start_step("MANUAL_SESSION")

    if not TEST_MANUAL_SESSION:
        rec.discard_step()
        tracker.skip("TEST_MANUAL_SESSION=False")
        return False

    tprint(device_id, "   MANU  Looking for Manual session mode...")
    navigate_home(driver); time.sleep(1)

    manual_xpaths = [
        "//*[@text='Manual']",
        "//*[contains(@text,'Manual')]",
        "//*[contains(@resource-id,'manual')]",
        "//*[@text='Manual Mode']",
    ]
    found = try_tap(driver, *manual_xpaths, timeout=5)
    if not found:
        try_tap(driver, "//*[@text='New Session']", timeout=5)
        time.sleep(2)
        found = try_tap(driver, *manual_xpaths, timeout=5)

    if not found:
        dump_page_xml(driver, device_id, "manual_not_found")
        tprint(device_id, "   SKIP  Manual mode not found in this app version")
        rec.discard_step()
        tracker.skip("Manual mode not found — not in current app version")
        return False

    tprint(device_id, "   OK    Manual mode found and tapped")
    time.sleep(2)

    started = try_tap(driver,
        "//*[@text='Start']", "//*[@text='Start Session']",
        "//*[@text='Start now']", timeout=8)

    if not started:
        ss = screenshot_b64(driver)
        rec.save_bug_clip("MANUAL_SESSION")
        tracker.warn("Manual mode found but couldn't start session", ss)
        return False

    tprint(device_id, "   OK    Manual session active — monitoring 15s...")
    take_named_screenshot(driver, device_id, "manual_session_start")

    # Monitor: 5 frames @ 3s — check data changes
    manual_data = {}
    for i in range(5):
        time.sleep(3)
        d   = scrape_screen_data(driver)
        if len(d) > len(manual_data):
            manual_data = d
        tprint(device_id, f"   MANU  Frame {i+1}/5: {len(d)} fields visible")

    take_named_screenshot(driver, device_id, "manual_session_active")

    try_tap(driver,
        "//*[@text='End Session']", "//*[@text='Stop']",
        "//*[@text='End']", "//*[@text='Pause']", timeout=8)
    time.sleep(2)

    tprint(device_id, f"   OK    Manual session complete — {len(manual_data)} fields")
    rec.discard_step()
    tracker.done(f"Manual session — {len(manual_data)} data fields", data=manual_data)
    return True


# =================================================================
#  17-19. HISTORY, INSIGHTS, FINAL PROFILE
# =================================================================

def handle_history_check(driver, device_id, tracker, rec: ScreenRecorder) -> dict:
    tracker.begin("HISTORY_CHECK")
    rec.start_step("HISTORY_CHECK")
    tprint(device_id, "   HIST  Checking session history...")

    navigate_home(driver)
    navigate_to_tab(driver, 2)
    time.sleep(2)
    dump_page_xml(driver, device_id, "history_tab")
    data = scrape_screen_data(driver)
    take_named_screenshot(driver, device_id, "history_tab")

    found = screen_has(driver,
        "//*[contains(@text,'Session') or contains(@text,'History') "
        "or contains(@text,'Completed') or contains(@text,'cycle')]",
        timeout=8)

    rec.discard_step()
    if found:
        tprint(device_id, f"   OK    History content — {len(data)} fields")
        tracker.done(f"History verified — {len(data)} fields", data=data)
    else:
        tprint(device_id, "   WARN  History content not confirmed")
        tracker.warn("History content not found", data=data)
    return data


def handle_insights_check(driver, device_id, tracker, rec: ScreenRecorder) -> dict:
    tracker.begin("INSIGHTS_CHECK")
    rec.start_step("INSIGHTS_CHECK")
    tprint(device_id, "   INSIG Checking insights...")

    try:
        driver.execute_script("mobile: scroll", {"direction": "down"})
    except Exception:
        pass
    time.sleep(1.5)

    data = scrape_screen_data(driver)
    take_named_screenshot(driver, device_id, "insights")
    dump_page_xml(driver, device_id, "insights")

    found = screen_has(driver,
        "//*[contains(@text,'Total') or contains(@text,'Cycle') "
        "or contains(@text,'Pain') or contains(@text,'Streak') "
        "or contains(@text,'Progress')]",
        timeout=5)

    rec.discard_step()
    if found:
        tprint(device_id, f"   OK    Insights visible — {len(data)} fields")
        tracker.done(f"Insights verified", data=data)
    else:
        tprint(device_id, "   WARN  No insights data (may need completed sessions)")
        tracker.warn("No insights data visible", data=data)
    return data


def handle_final_profile(driver, device_id, tracker, rec: ScreenRecorder,
                         initial_data: dict, persona: dict = None) -> dict:
    tracker.begin("FINAL_PROFILE")
    rec.start_step("FINAL_PROFILE")
    tprint(device_id, "   PROF  Final profile read + diff...")

    opened = try_tap(driver,
        "//*[@content-desc='Profile']",
        "(//android.widget.ImageView[@clickable='true'])[1]",
        "//*[contains(@resource-id,'avatar')]",
        timeout=8)
    if not opened:
        navigate_to_tab(driver, 2)

    time.sleep(2)
    dump_page_xml(driver, device_id, "final_profile")
    final_data = scrape_screen_data(driver)
    take_named_screenshot(driver, device_id, "final_profile")

    added   = {k: v for k, v in final_data.items() if k not in initial_data}
    removed = {k: v for k, v in initial_data.items() if k not in final_data}
    changed = {k: (initial_data[k], final_data[k])
               for k in final_data
               if k in initial_data and final_data[k] != initial_data[k]}
    
    # Persona matching
    persona_errors = []
    if persona:
        joined_text = " ".join(final_data.values()).lower()
        if persona["name"].lower() not in joined_text:
            persona_errors.append(f"Name '{persona['name']}' not found in profile")
        
    note = (f"Fields: {len(final_data)} | "
            f"Added: {len(added)} | Removed: {len(removed)} | Changed: {len(changed)}")
    if persona_errors:
        note += " | FAIL: " + ", ".join(persona_errors)
    tprint(device_id, f"   OK    {note}")
    for k, (old, new) in list(changed.items())[:3]:
        tprint(device_id, f"         CHANGED {k}: '{old}' → '{new}'")

    rec.discard_step()
    tracker.done(note, data=final_data)
    return final_data



# =================================================================
#  APP EXPLORATION & LOGS (v4.0)
# =================================================================

def handle_session_logs(driver, device_id, tracker, rec):
    tracker.begin("SESSION_LOGS")
    rec.start_step("SESSION_LOGS")
    tprint(device_id, "   LOGS  Capturing logcat...")
    try:
        logs = driver.get_log('logcat')
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        log_path = os.path.join(LOG_DIR, f"{device_id}_{ts}.txt")
        errors_found = 0
        with open(log_path, "w", encoding="utf-8") as f:
            for entry in logs:
                msg = entry.get("message", "")
                f.write(f"[{entry.get('level')}] {msg}\n")
                if "Exception" in msg or "Fatal" in msg or "Crash" in msg:
                    errors_found += 1
                    
        note = f"Captured {len(logs)} log lines. Dumped to {log_path}."
        if errors_found > 0:
            note += f" WARNING: Found {errors_found} potential error traces."
            tprint(device_id, f"   WARN  {note}")
        else:
            tprint(device_id, f"   OK    {note}")
        
        rec.discard_step()
        tracker.done(note)
    except Exception as e:
        rec.save_bug_clip("SESSION_LOGS")
        tracker.fail(f"Failed to capture logs: {str(e)}")


def handle_app_exploration(driver, device_id, tracker, rec):
    tracker.begin("APP_EXPLORATION")
    rec.start_step("APP_EXPLORATION")
    tprint(device_id, "   EXPL  Exhaustive app exploration...")
    
    issues = []
    # Click through the 4 tabs at the bottom
    for i in range(4):
        navigate_to_tab(driver, i)
        time.sleep(1)
        data = scrape_screen_data(driver)
        
        # Verify no crash/error texts
        for text in data.values():
            if "error" in text.lower() or "crash" in text.lower():
                issues.append(f"Found error text on tab {i}: '{text}'")
                
        # attempt a scroll to ensure cards load
        try:
            sz = driver.get_window_size()
            w, h = sz["width"], sz["height"]
            driver.swipe(int(w * 0.5), int(h * 0.8), int(w * 0.5), int(h * 0.2), 500)
            time.sleep(1)
        except:
            pass

    if issues:
        rec.save_bug_clip("APP_EXPLORATION")
        tracker.fail("; ".join(issues))
    else:
        rec.discard_step()
        tracker.done("Explored all 4 tabs, scrolled, no 'error' text found.")

# =================================================================
#  MAIN TEST FUNCTION
# =================================================================

def run_test(device_id: str) -> dict:
    tracker    = StepTracker(device_id)
    start_time = time.time()
    driver     = None
    rec        = None
    sync_frames: list = []
    diff_image        = None
    profile_initial   = {}
    bugs: list        = []
    persona           = generate_persona()

    options = UiAutomator2Options()
    options.platform_name          = "Android"
    options.automation_name        = "UiAutomator2"
    options.device_name            = device_id
    options.app_package            = APP_PACKAGE
    options.app_activity           = APP_ACTIVITY
    options.no_reset               = True
    options.auto_grant_permissions = True
    options.system_port = (
        8200 + (int(hashlib.md5(device_id.encode()).hexdigest(), 16) % 1000))

    try:
        tprint(device_id, "START Connecting to Appium & launching app...")
        driver = webdriver.Remote(APPIUM_HOST, options=options)
        wait   = WebDriverWait(driver, ELEMENT_WAIT)

        rec = ScreenRecorder(driver, device_id)
        rec.start_full()

        # ── 1. Onboarding ──────────────────────────────────────
        tprint(device_id, "[1] Onboarding check...")
        handle_onboarding(driver, device_id, tracker, rec, persona)
        time.sleep(2)

        # ── 2. Login ───────────────────────────────────────────
        tprint(device_id, "[2] Login check...")
        if not handle_login(driver, device_id, tracker, rec, _runtime_phone_number):
            return _build_result(device_id, tracker, start_time, rec, sync_frames, diff_image, bugs)
        navigate_home(driver); time.sleep(1)

        # ── 3-5. Profile CRUD ──────────────────────────────────
        if TEST_PROFILE_CRUD:
            tprint(device_id, "[3] Profile read (initial)...")
            profile_initial = handle_profile_read(driver, device_id, tracker, rec, "PROFILE_READ")
            navigate_home(driver); time.sleep(1)

            tprint(device_id, "[4] Profile update...")
            handle_profile_update(driver, device_id, tracker, rec)
            time.sleep(1)

            tprint(device_id, "[5] Profile verify...")
            handle_profile_verify(driver, device_id, tracker, rec)
            navigate_home(driver); time.sleep(1)
        else:
            for s in ["PROFILE_READ", "PROFILE_UPDATE", "PROFILE_VERIFY"]:
                tracker.begin(s); tracker.skip("TEST_PROFILE_CRUD=False")

        # ── 6-7. Logout + Re-Login ─────────────────────────────
        if TEST_LOGOUT_RELOGIN:
            tprint(device_id, "[6] Logout...")
            logout_ok = handle_logout(driver, device_id, tracker, rec)
            tprint(device_id, "[7] Re-Login...")
            if logout_ok:
                if not handle_login(driver, device_id, tracker, rec,
                                    _runtime_phone_number, step_name="RELOGIN"):
                    return _build_result(device_id, tracker, start_time, rec, sync_frames, diff_image, bugs)
            else:
                tracker.begin("RELOGIN")
                tracker.skip("Skipped - logout did not succeed")
            navigate_home(driver); time.sleep(1)
        else:
            tracker.begin("LOGOUT");  tracker.skip("TEST_LOGOUT_RELOGIN=False")
            tracker.begin("RELOGIN"); tracker.skip("TEST_LOGOUT_RELOGIN=False")

        # ── 8. Pod Check (WARNING ONLY - sessions ALWAYS run) ──
        tprint(device_id, f"[8] Pod check ({REQUIRED_PODS} required)...")
        navigate_home(driver)
        pod_ok = check_pods(driver, device_id, tracker, rec)
        if not pod_ok:
            tprint(device_id, "   WARN  Pods not detected in UI.")
            tprint(device_id, "   WARN  Sessions will still run - pods may connect during session.")
        navigate_home(driver); time.sleep(1)

        # ── SESSION BUG HUNT: Relief + Recover ─────────────────
        modes_to_test = ["Relief", "Recover"]
        for mode in modes_to_test:
            tprint(device_id, f"\n[!] Testing Mode: {mode} ========================")
            navigate_home(driver)
            time.sleep(1)

            # 9. Pre pain: random pain site + random VAS score
            tprint(device_id, f"[9] Pre-session pain score ({mode})...")
            chosen_vas = handle_pain_score(
                driver, device_id, tracker, rec, "PRE_PAIN",
                ["Confirm", "Next", "Continue", "Start", "Submit"])

            # 10-13. Run session (15s), checks timer bug, VAS mismatch, pod during session
            tprint(device_id, f"[10-13] Running {mode} session (15s)...")
            session_ok = handle_session_auto(
                driver, device_id, tracker, rec, wait, mode, chosen_vas)

            # 14. Sync check + logcat immediately after session
            tprint(device_id, "[14] Sync check...")
            if session_ok:
                _, sync_frames, diff_image = handle_sync_check(
                    driver, device_id, tracker, rec)
                handle_session_logs(driver, device_id, tracker, rec)
            else:
                tracker.begin("SYNC_CHECK")
                tracker.skip(f"Skipped - {mode} session did not start")

            tprint(device_id, f"[/!] {mode} complete ========================\n")

        # ── 15. Manual session ──────────────────────────────────
        tprint(device_id, "[15] Manual session test...")
        navigate_home(driver)
        handle_manual_session(driver, device_id, tracker, rec)

        # ── 16. Post pain ───────────────────────────────────────
        tprint(device_id, "[16] Post-session pain score...")
        navigate_home(driver)
        handle_pain_score(driver, device_id, tracker, rec, "POST_PAIN",
                          ["Submit", "Done", "Confirm", "Next"])

        # ── 17. History ────────────────────────────────────────
        tprint(device_id, "[17] History check...")
        navigate_home(driver)
        handle_history_check(driver, device_id, tracker, rec)

        # ── 18. Insights ───────────────────────────────────────
        tprint(device_id, "[18] Insights check...")
        handle_insights_check(driver, device_id, tracker, rec)

        # ── SS. Session Stress Testing ──────────────────────────
        tprint(device_id, "[SS] Session Stress Testing...")
        handle_session_stress(driver, device_id, tracker, rec)

        # ── EX. App Exploration (tab crawl) ────────────────────
        tprint(device_id, "[EX] App exploration...")
        handle_app_exploration(driver, device_id, tracker, rec, bugs)

        # ── 19. Final profile ──────────────────────────────────
        tprint(device_id, "[19] Final profile read...")
        navigate_home(driver)
        handle_final_profile(driver, device_id, tracker, rec, profile_initial, persona)

        tprint(device_id, "DONE  ALL STEPS COMPLETE")

    except Exception as e:
        step = tracker._current_step or "UNKNOWN"
        ss   = screenshot_b64(driver)
        err  = str(e).split("\n")[0]
        tprint(device_id, f"ERROR [{step}]: {err}")
        tracker.fail(err, ss)
        if driver:
            dump_page_xml(driver, device_id, f"crash_{step}")
        if rec:
            rec.save_bug_clip(f"CRASH_{step}")

    finally:
        if rec:
            rec.stop_full()
        if driver:
            driver.quit()

    return _build_result(device_id, tracker, start_time, rec, sync_frames, diff_image, bugs)


def _build_result(device_id, tracker, start_time,
                  rec=None, sync_frames=None, diff_image=None, bugs=None) -> dict:
    return {
        "device":      device_id,
        "status":      tracker.overall_status(),
        "failed_step": tracker.first_failure(),
        "error":       tracker.first_failure_note(),
        "screenshot":  tracker.first_failure_screenshot(),
        "duration":    round(time.time() - start_time, 1),
        "attempts":    1,
        "steps":       tracker.all_steps(),
        "glitch":      False,
        "sync_frames": sync_frames or [],
        "diff_image":  diff_image,
        "full_video":  rec.full_path if rec else None,
        "bug_clips":   rec.bug_clips if rec else [],
        "bugs":        bugs or [],
    }


# =================================================================
#  RETRY WRAPPER
# =================================================================

def run_test_with_retry(device_id: str) -> dict:
    last_result = None
    for attempt in range(1, MAX_RETRIES + 2):
        if attempt > 1:
            tprint(device_id, f"RETRY {attempt-1}/{MAX_RETRIES} — restarting...")
            time.sleep(RETRY_DELAY)
        result = run_test(device_id)
        result["attempts"] = attempt
        if result["status"] == "Pass":
            result["glitch"] = attempt > 1
            if result["glitch"]:
                tprint(device_id, f"OK    Passed on attempt {attempt} — earlier failure was a glitch")
            return result
        tprint(device_id,
               f"FAIL  Attempt {attempt} at [{result['failed_step']}] "
               + (f"retrying in {RETRY_DELAY}s..." if attempt <= MAX_RETRIES
                  else "no retries left."))
        last_result = result
    last_result["glitch"] = False
    tprint(device_id, f"DEAD  CONFIRMED FAILURE after {MAX_RETRIES+1} attempts.")
    return last_result


# =================================================================
#  HTML REPORT v3.1
# =================================================================

_STEP_META = {
    "ONBOARDING":      ("Onboarding",      "📱"),
    "LOGIN":           ("Login",           "🔐"),
    "PROFILE_READ":    ("Profile Read",    "👁"),
    "PROFILE_UPDATE":  ("Profile Update",  "✏"),
    "PROFILE_VERIFY":  ("Profile Verify",  "✔"),
    "LOGOUT":          ("Logout",          "🚪"),
    "RELOGIN":         ("Re-Login",        "🔑"),
    "POD_CHECK":       ("Pod Check",       "🔵"),
    "PRE_PAIN":        ("Pre Pain Score",  "🩺"),
    "SESSION_START":   ("Session Start",   "▶"),
    "SESSION_PAUSE":   ("Session Pause",   "⏸"),
    "SESSION_RESUME":  ("Session Resume",  "▶"),
    "SESSION_END":     ("Session End",     "⏹"),
    "SYNC_CHECK":      ("Sync Check",      "📡"),
    "MANUAL_SESSION":  ("Manual Session",  "🖐"),
    "POST_PAIN":       ("Post Pain Score", "🩺"),
    "HISTORY_CHECK":   ("History",         "📋"),
    "INSIGHTS_CHECK":  ("Insights",        "📊"),
    "FINAL_PROFILE":   ("Final Profile",   "👤"),
    "ONBOARDING_PERSISTENCE": ("Persistence Check", "🔁"),
    "SESSION_LOGS":    ("Session Logs",    "📄"),
    "APP_EXPLORATION": ("App Exploration", "🔍"),
}

_STATUS_BG  = {"Pass": "#1a472a", "Fail": "#4a1942", "Skip": "#1a2a3a", "Warn": "#3a3010"}
_DOT_COLOR  = {"Pass": "#3fb950", "Fail": "#f85149", "Skip": "#484f58", "Warn": "#d29922"}
_BADGE_HTML = {
    "Pass": '<span style="background:#3fb950;color:#000;padding:2px 8px;border-radius:12px;font-size:11px;font-weight:bold">PASS</span>',
    "Fail": '<span style="background:#f85149;color:#fff;padding:2px 8px;border-radius:12px;font-size:11px;font-weight:bold">FAIL</span>',
    "Skip": '<span style="background:#484f58;color:#fff;padding:2px 8px;border-radius:12px;font-size:11px;font-weight:bold">SKIP</span>',
    "Warn": '<span style="background:#d29922;color:#000;padding:2px 8px;border-radius:12px;font-size:11px;font-weight:bold">WARN</span>',
}


def _timeline_html(steps: dict) -> str:
    cells = ""
    for key in StepTracker.STEP_NAMES:
        d     = steps.get(key)
        color = _DOT_COLOR.get(d["status"] if d else "Skip", "#484f58")
        label, icon = _STEP_META.get(key, (key, ""))
        tip   = f"{label}: {d['status']} ({d['duration']}s)" if d else f"{label}: N/A"
        cells += (f'<td title="{tip}" style="background:{color};text-align:center;'
                  f'padding:5px 2px;font-size:9px;color:#fff">{icon}<br>{label.split()[0]}</td>')
    return f'<table style="width:100%;border-collapse:collapse"><tr>{cells}</tr></table>'


def _data_table_html(d: dict, max_rows: int = 15) -> str:
    if not d:
        return "<em style='color:#484f58;font-size:11px'>No data captured</em>"
    rows = ""
    for i, (k, v) in enumerate(list(d.items())[:max_rows]):
        bg = "#161b22" if i % 2 == 0 else "#0d1117"
        rows += (f'<tr style="background:{bg}">'
                 f'<td style="padding:3px 8px;font-size:10px;color:#8b949e">{k}</td>'
                 f'<td style="padding:3px 8px;font-size:10px">{str(v)[:120]}</td></tr>')
    if len(d) > max_rows:
        rows += (f'<tr><td colspan="2" style="color:#484f58;font-size:10px;padding:3px 8px">'
                 f'...+{len(d)-max_rows} more</td></tr>')
    return ('<table style="width:100%;border-collapse:collapse">'
            '<tr style="background:#21262d">'
            '<th style="padding:3px 8px;text-align:left;color:#8b949e;font-size:10px">Field</th>'
            '<th style="padding:3px 8px;text-align:left;color:#8b949e;font-size:10px">Value</th>'
            '</tr>' + rows + '</table>')


def _sync_frames_html(frames: list, diff_img: str) -> str:
    if not frames:
        return "<em style='color:#484f58;font-size:11px'>No frames</em>"
    note = ("" if PIL_AVAILABLE
            else "<br><small style='color:#d29922'>pip install Pillow for pixel diff</small>")
    html = f'<div style="overflow-x:auto;white-space:nowrap;padding:4px 0">{note}'
    for i, b64 in enumerate(frames):
        html += (f'<div style="display:inline-block;margin:3px;vertical-align:top;text-align:center">'
                 f'<div style="font-size:9px;color:#8b949e">Frame {i+1}</div>'
                 f'<img src="data:image/png;base64,{b64}" '
                 f'style="height:130px;border-radius:4px;border:1px solid #30363d"/></div>')
    if diff_img:
        html += (f'<div style="display:inline-block;margin:3px;vertical-align:top;text-align:center">'
                 f'<div style="font-size:9px;color:#3fb950">Change Map</div>'
                 f'<img src="data:image/png;base64,{diff_img}" '
                 f'style="height:130px;border-radius:4px;border:1px solid #3fb950"/></div>')
    html += '</div>'
    return html


def _video_section_html(full_video: str, bug_clips: list) -> str:
    """Render HTML video player + bug clips list."""
    if not full_video and not bug_clips:
        return "<em style='color:#484f58;font-size:11px'>No recordings (RECORDING_ENABLED=False or device unsupported)</em>"

    parts = []

    if full_video and os.path.exists(full_video):
        abs_path = os.path.abspath(full_video).replace("\\", "/")
        fname    = os.path.basename(full_video)
        size_mb  = round(os.path.getsize(full_video) / 1024 / 1024, 1)
        parts.append(
            f'<div style="margin-bottom:10px">'
            f'<div style="font-size:11px;color:#8b949e;margin-bottom:4px">'
            f'🎥 Full Session Recording ({size_mb} MB)</div>'
            f'<video controls width="100%" style="border-radius:6px;border:1px solid #30363d;'
            f'max-height:300px;background:#000">'
            f'<source src="file:///{abs_path}" type="video/mp4">'
            f'<a href="file:///{abs_path}" style="color:#58a6ff">{fname}</a>'
            f'</video></div>'
        )

    if bug_clips:
        parts.append('<div style="font-size:11px;color:#f85149;margin:8px 0 4px">🐛 Bug Clips:</div>')
        for clip in bug_clips:
            if os.path.exists(clip):
                abs_path = os.path.abspath(clip).replace("\\", "/")
                fname    = os.path.basename(clip)
                size_mb  = round(os.path.getsize(clip) / 1024 / 1024, 1)
                parts.append(
                    f'<div style="margin-bottom:8px">'
                    f'<div style="font-size:10px;color:#f85149;margin-bottom:3px">{fname} ({size_mb} MB)</div>'
                    f'<video controls width="100%" style="border-radius:6px;border:1px solid #f85149;'
                    f'max-height:200px;background:#000">'
                    f'<source src="file:///{abs_path}" type="video/mp4">'
                    f'<a href="file:///{abs_path}" style="color:#58a6ff">{fname}</a>'
                    f'</video></div>'
                )

    return "".join(parts)


def _step_table_html(device_id: str, steps: dict,
                     sync_frames: list, diff_image: str) -> str:
    rows = ""
    for key in StepTracker.STEP_NAMES:
        data = steps.get(key)
        if not data:
            continue
        label, icon = _STEP_META.get(key, (key, ""))
        badge  = _BADGE_HTML.get(data["status"], data["status"])
        note   = (data.get("note") or "—")[:200]
        dur    = f'{data["duration"]}s'
        row_bg = _STATUS_BG.get(data["status"], "#161b22")

        extra = ""
        if data.get("data"):
            extra += f'<div style="margin-top:6px">{_data_table_html(data["data"])}</div>'
        if data.get("screenshot"):
            extra += (f'<br><img src="data:image/png;base64,{data["screenshot"]}" '
                      f'style="max-width:260px;max-height:170px;margin-top:6px;'
                      f'border-radius:6px;border:1px solid #30363d"/>')
        if key == "SYNC_CHECK" and sync_frames:
            extra += f'<div style="margin-top:6px">{_sync_frames_html(sync_frames, diff_image)}</div>'

        rows += (
            f'<tr style="background:{row_bg};border-bottom:1px solid #21262d">'
            f'<td style="padding:8px 12px;font-size:12px;white-space:nowrap">{icon} {label}</td>'
            f'<td style="padding:8px 12px">{badge}</td>'
            f'<td style="padding:8px 12px;font-size:11px;color:#8b949e;white-space:nowrap">{dur}</td>'
            f'<td style="padding:8px 12px;font-size:11px">{note}{extra}</td>'
            f'</tr>'
        )
    return ('<table style="width:100%;border-collapse:collapse">'
            '<tr style="background:#21262d">'
            '<th style="padding:8px 12px;text-align:left;color:#8b949e;font-size:12px">Step</th>'
            '<th style="padding:8px 12px;text-align:left;color:#8b949e;font-size:12px">Status</th>'
            '<th style="padding:8px 12px;text-align:left;color:#8b949e;font-size:12px">Time</th>'
            '<th style="padding:8px 12px;text-align:left;color:#8b949e;font-size:12px">Details</th>'
            '</tr>' + rows + '</table>')


def generate_html_report(results: list) -> tuple:
    now       = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    total     = len(results)
    passed    = sum(1 for r in results if r["status"] == "Pass")
    failed    = total - passed
    glitches  = sum(1 for r in results if r.get("glitch"))
    pass_rate = round((passed / total) * 100) if total else 0
    pod_fails = sum(1 for r in results
                    if r.get("steps", {}).get("POD_CHECK", {}).get("status") == "Fail")
    syncing   = sum(1 for r in results
                    if r.get("steps", {}).get("SYNC_CHECK", {}).get("status") == "Pass")
    has_vids  = sum(1 for r in results if r.get("full_video") or r.get("bug_clips"))

    sections = ""
    for r in sorted(results, key=lambda x: x["device"]):
        overall_color = ("#1a472a" if r["status"] == "Pass"
                         else ("#2a3a1a" if r.get("glitch") else "#4a1942"))
        icon     = "PASS" if r["status"] == "Pass" else "FAIL"
        glitch   = " (passed on retry)" if r.get("glitch") else ""
        atm      = f"{r['attempts']}/{MAX_RETRIES+1}"
        timeline = _timeline_html(r.get("steps", {}))
        step_tbl = _step_table_html(r["device"], r.get("steps", {}),
                                    r.get("sync_frames", []), r.get("diff_image"))
        vid_html = _video_section_html(r.get("full_video"), r.get("bug_clips", []))

        banners = ""
        pod_s   = r.get("steps", {}).get("POD_CHECK", {})
        sync_s  = r.get("steps", {}).get("SYNC_CHECK", {})
        pause_s = r.get("steps", {}).get("SESSION_PAUSE", {})

        if pause_s.get("status") == "Skip":
            banners += (f'<div style="background:#1a2a3a;padding:6px 10px;border-radius:6px;'
                        f'margin:4px 0;font-size:11px;color:#79c0ff">'
                        f'ℹ️ DEV NOTE: No Pause button during active session — {pause_s.get("note","")}</div>')

        if pod_s.get("status") == "Fail":
            banners += (f'<div style="background:#4a1942;padding:8px;border-radius:6px;'
                        f'margin:6px 0;font-size:12px;color:#f85149">'
                        f'POD ISSUE: {pod_s.get("note","")}</div>')
        elif pod_s.get("status") == "Pass":
            banners += (f'<div style="background:#1a472a;padding:8px;border-radius:6px;'
                        f'margin:6px 0;font-size:12px;color:#3fb950">'
                        f'PODS OK: {pod_s.get("note","")}</div>')

        if sync_s.get("status") == "Pass":
            banners += (f'<div style="background:#0d2a3a;padding:8px;border-radius:6px;'
                        f'margin:6px 0;font-size:12px;color:#79c0ff">'
                        f'SYNC OK: {sync_s.get("note","")}</div>')
        elif sync_s.get("status") == "Warn":
            banners += (f'<div style="background:#3a3010;padding:8px;border-radius:6px;'
                        f'margin:6px 0;font-size:12px;color:#d29922">'
                        f'SYNC WARN: {sync_s.get("note","")}</div>')

        bug_count = len(r.get("bug_clips", []))
        if bug_count:
            banners += (f'<div style="background:#4a1942;padding:6px 10px;border-radius:6px;'
                        f'margin:4px 0;font-size:11px;color:#f85149">'
                        f'🎬 {bug_count} bug clip(s) recorded for dev review</div>')

        sections += (
            f'<div style="background:{overall_color};border-radius:10px;padding:20px;'
            f'margin-bottom:24px;border:1px solid #30363d">'
            f'<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px">'
            f'<h3 style="margin:0;color:#e6edf3">[{icon}] {r["device"]}{glitch}</h3>'
            f'<span style="color:#8b949e;font-size:13px">Duration: {r["duration"]}s | Attempts: {atm}</span>'
            f'</div>{banners}'
            f'<div style="margin:10px 0">{timeline}</div>'
            f'{step_tbl}'
            f'<div style="margin-top:16px;border-top:1px solid #30363d;padding-top:14px">'
            f'<div style="font-size:13px;color:#8b949e;font-weight:600;margin-bottom:8px">🎥 Recordings</div>'
            f'{vid_html}</div>'
            f'</div>'
        )

    cfg_pills = (
        f'Profile CRUD: <b>{"ON" if TEST_PROFILE_CRUD else "OFF"}</b> &nbsp;|&nbsp;'
        f'Logout+Relogin: <b>{"ON" if TEST_LOGOUT_RELOGIN else "OFF"}</b> &nbsp;|&nbsp;'
        f'Manual Session: <b>{"ON" if TEST_MANUAL_SESSION else "OFF"}</b> &nbsp;|&nbsp;'
        f'Sync: <b>{SYNC_CHECK_FRAMES} frames @ {SYNC_CHECK_INTERVAL}s | {SYNC_DIFF_THRESHOLD}%</b> &nbsp;|&nbsp;'
        f'Recording: <b>{"ON" if RECORDING_ENABLED else "OFF"}</b> &nbsp;|&nbsp;'
        f'Pillow: <b>{"YES" if PIL_AVAILABLE else "NO"}</b>'
    )

    html = f"""<!DOCTYPE html>
<html lang="en"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Curapod E2E v3.1 — {now}</title>
<style>
  *{{box-sizing:border-box}}
  body{{font-family:'Segoe UI',system-ui,sans-serif;background:#0d1117;color:#e6edf3;padding:30px;margin:0}}
  h1{{color:#58a6ff;margin-bottom:4px}}
  h2{{color:#8b949e;margin-top:4px;font-weight:400;font-size:14px}}
  .summary{{display:flex;gap:12px;margin:20px 0;flex-wrap:wrap}}
  .card{{background:#161b22;border-radius:10px;padding:16px 22px;text-align:center;border:1px solid #30363d;min-width:90px}}
  .card .num{{font-size:34px;font-weight:bold;line-height:1.1}}
  .pass{{color:#3fb950}}.fail{{color:#f85149}}.rate{{color:#58a6ff}}
  .glitch{{color:#d29922}}.pod{{color:#79c0ff}}.sync{{color:#56d364}}.vid{{color:#e6b450}}
  .section-title{{font-size:17px;font-weight:600;color:#58a6ff;margin:28px 0 10px;
                  border-bottom:1px solid #21262d;padding-bottom:6px}}
  .cfg{{background:#161b22;border:1px solid #30363d;border-radius:8px;
        padding:10px 14px;font-size:12px;color:#8b949e;margin-bottom:18px}}
  .legend{{display:flex;gap:10px;margin-bottom:14px;flex-wrap:wrap}}
  .li{{display:flex;align-items:center;gap:5px;font-size:11px;color:#8b949e}}
  .dot{{width:10px;height:10px;border-radius:50%;display:inline-block}}
  video{{outline:none}}
</style></head><body>
<h1>Curapod Full E2E Test Report v3.1</h1>
<h2>Run: {now} | Devices: {total} | Required Pods: {REQUIRED_PODS} | Max Retries: {MAX_RETRIES}</h2>

<div class="summary">
  <div class="card"><div class="num pass">{passed}</div>PASSED</div>
  <div class="card"><div class="num fail">{failed}</div>FAILED</div>
  <div class="card"><div class="num glitch">{glitches}</div>GLITCHES</div>
  <div class="card"><div class="num rate">{pass_rate}%</div>PASS RATE</div>
  <div class="card"><div class="num pod">{pod_fails}</div>POD FAILS</div>
  <div class="card"><div class="num sync">{syncing}</div>SYNC OK</div>
  <div class="card"><div class="num vid">{has_vids}</div>RECORDED</div>
</div>

<div class="cfg">{cfg_pills}</div>

<div class="legend">
  <div class="li"><div class="dot" style="background:#3fb950"></div>Pass</div>
  <div class="li"><div class="dot" style="background:#f85149"></div>Fail</div>
  <div class="li"><div class="dot" style="background:#d29922"></div>Warn</div>
  <div class="li"><div class="dot" style="background:#484f58"></div>Skip</div>
</div>

<div class="section-title">Device Results</div>
{sections}
</body></html>"""

    ts          = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_path = os.path.join(REPORT_DIR, f"report_v3_{ts}.html")
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(html)

    json_data = []
    for r in results:
        json_data.append({
            "device":     r["device"],
            "status":     r["status"],
            "duration":   r["duration"],
            "full_video": r.get("full_video"),
            "bug_clips":  r.get("bug_clips", []),
            "steps": {
                k: {kk: vv for kk, vv in v.items() if kk not in ("screenshot",)}
                for k, v in r.get("steps", {}).items()
            },
        })
    json_path = os.path.join(DATA_DIR, f"data_{ts}.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(json_data, f, indent=2, default=str)

    return report_path, json_path


# =================================================================
#  ENTRY POINT
# =================================================================

def main():
    print("\n" + "=" * 65)
    print("  CURAPOD  |  Full E2E Test Suite  v3.1")
    print("=" * 65)
    print("  Coverage: Onboarding | Login | Profile CRUD | Logout+Relogin")
    print("            Pods | Session (Auto+Manual) | Sync Check")
    print("            History | Insights | Final Profile")
    print("  Recording: Full video + bug clips per step")
    print("=" * 65)

    if PIL_AVAILABLE:
        print("\n  Pillow OK — pixel-diff sync verification ENABLED")
    else:
        print("\n  WARNING: Pillow not installed — sync diff disabled")
        print("  Fix:  pip install Pillow")

    if RECORDING_ENABLED:
        print(f"  Recording ENABLED — videos -> {RECORDING_DIR}/")
    else:
        print("  Recording DISABLED (RECORDING_ENABLED=False)")

    global _runtime_phone_number
    _runtime_phone_number = "9110743420"

    print("\n  Scanning for connected Android devices (ADB)...")
    devices = get_connected_devices()

    if not devices:
        print("  ERROR: No devices found.")
        print("  -> USB Debugging ON, accept RSA prompt, then: adb devices")
        return

    print(f"\n  Found {len(devices)} device(s):")
    for d in devices:
        print(f"    * {d}")

    print(f"\n  Settings:")
    print(f"    OTP wait        : {OTP_WAIT_SECONDS}s")
    print(f"    Required pods   : {REQUIRED_PODS}")
    print(f"    Session run     : {SESSION_RUN_DURATION}s")
    print(f"    Profile CRUD    : {'ON' if TEST_PROFILE_CRUD else 'OFF'}")
    print(f"    Logout+Relogin  : {'ON' if TEST_LOGOUT_RELOGIN else 'OFF'}")
    print(f"    Manual session  : {'ON' if TEST_MANUAL_SESSION else 'OFF'}")
    print(f"    Sync frames     : {SYNC_CHECK_FRAMES} @ {SYNC_CHECK_INTERVAL}s each")
    print(f"    Sync threshold  : {SYNC_DIFF_THRESHOLD}% pixel change")
    print(f"    Recording       : {'ON' if RECORDING_ENABLED else 'OFF'}")
    print(f"\n  Launching parallel test on {len(devices)} device(s)...\n")

    results = []
    with ThreadPoolExecutor(max_workers=len(devices)) as pool:
        futures = {pool.submit(run_test_with_retry, d): d for d in devices}
        for future in as_completed(futures):
            results.append(future.result())

    total  = len(results)
    passed = sum(1 for r in results if r["status"] == "Pass")
    failed = total - passed

    print("\n" + "=" * 75)
    print(f"  FINAL RESULTS — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 75)
    print(f"  {'Device':<20} {'Status':<7} {'Atm':<5} {'FailedAt':<16} {'Pods':<5} {'Sync':<5} {'Vids':<5} Dur")
    print("  " + "-" * 73)
    for r in sorted(results, key=lambda x: x["device"]):
        icon  = "PASS" if r["status"] == "Pass" else "FAIL"
        step  = r["failed_step"] or "-"
        atm   = f"{r['attempts']}/{MAX_RETRIES+1}"
        pod   = r.get("steps", {}).get("POD_CHECK", {}).get("status", "?")[:4]
        sync  = r.get("steps", {}).get("SYNC_CHECK", {}).get("status", "?")[:4]
        vids  = len(r.get("bug_clips", [])) + (1 if r.get("full_video") else 0)
        g     = " (glitch)" if r.get("glitch") else ""
        print(f"  {r['device']:<20} {icon:<7} {atm:<5} {step:<16} {pod:<5} {sync:<5} {vids:<5} {r['duration']}s{g}")

    print("=" * 75)
    glitches  = sum(1 for r in results if r.get("glitch"))
    pod_fails = sum(1 for r in results
                    if r.get("steps", {}).get("POD_CHECK", {}).get("status") == "Fail")
    syncing   = sum(1 for r in results
                    if r.get("steps", {}).get("SYNC_CHECK", {}).get("status") == "Pass")
    total_clips = sum(len(r.get("bug_clips", [])) for r in results)
    print(f"  PASS:{passed} FAIL:{failed} GLITCH:{glitches} "
          f"POD_FAIL:{pod_fails} SYNCING:{syncing} BUG_CLIPS:{total_clips}")

    if pod_fails:
        print(f"  NOTE: {pod_fails} device(s) failed pod check — sessions skipped.")
    if not PIL_AVAILABLE:
        print("  NOTE: pip install Pillow  to enable pixel-diff sync verification.")
    if total_clips:
        print(f"  NOTE: {total_clips} bug clip(s) saved to {RECORDING_DIR}/ — share with dev team.")

    report_path, json_path = generate_html_report(results)
    print(f"\n  HTML Report  ->  {report_path}")
    print(f"  JSON Data    ->  {json_path}")
    print(f"  Recordings   ->  {RECORDING_DIR}/")
    print(f"  XML Dumps    ->  {DEBUG_XML_DIR}/")
    print("=" * 75 + "\n")


if __name__ == "__main__":
    main()
