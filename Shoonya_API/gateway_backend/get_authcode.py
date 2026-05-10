import os
import re
import time
import pyotp
from dotenv import load_dotenv
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import InvalidSessionIdException, WebDriverException

load_dotenv()


def get_auth_code() -> str:
    """
    Log in to Shoonya via headless Chrome and return the OAuth auth code from the redirect URL.

    Reads credentials from env vars:
      SHONYA_API_KEY   - used as api_key in the OAuth login URL
      SHONYA_USER_ID   - Shoonya user ID (e.g. FN131640)
      SHONYA_PASSWORD  - Shoonya account password
      SHONYA_TWO_FA    - TOTP secret for generating the OTP during login

    Raises:
        ValueError:   If any required env var is missing.
        RuntimeError: If the auth code cannot be obtained from the redirect URL.
    """
    api_key     = os.getenv("SHONYA_VENDOR_CODE")
    user_id     = os.getenv("SHONYA_USER_ID")
    password    = os.getenv("SHONYA_PASSWORD")
    totp_secret = os.getenv("SHONYA_TWO_FA")

    missing = [k for k, v in {
        "SHONYA_VENDOR_CODE": api_key,
        "SHONYA_USER_ID":  user_id,
        "SHONYA_PASSWORD": password,
        "SHONYA_TWO_FA":   totp_secret,
    }.items() if not v]
    if missing:
        raise ValueError(
            f"Missing required credentials for browser login: {', '.join(missing)}. "
            "Please set them in your .env file."
        )

    login_url = (
        f"https://trade.shoonya.com/OAuthlogin/investor-entry-level/login"
        f"?api_key={api_key}&route_to={user_id}"
    )

    options = webdriver.ChromeOptions()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--disable-software-rasterizer")
    options.add_argument("--disable-extensions")
    options.add_argument("--disable-background-networking")
    options.add_argument("--no-first-run")
    options.add_argument("--remote-debugging-port=0")
    options.add_argument("--window-size=1920,1080")

    driver = webdriver.Chrome(options=options)
    wait   = WebDriverWait(driver, 30)

    try:
        driver.get(login_url)
        wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, "input[type='password']")))
        time.sleep(1)

        all_inputs     = driver.find_elements(By.CSS_SELECTOR, "input:not([type='hidden']):not([type='checkbox']):not([type='radio'])")
        visible_inputs = [inp for inp in all_inputs if inp.is_displayed()]

        for element, value in zip(
            visible_inputs[:3],
            [user_id, password, pyotp.TOTP(totp_secret).now()],
        ):
            element.click()
            time.sleep(0.1)
            element.clear()
            element.send_keys(value)
            time.sleep(0.1)

        wait.until(EC.element_to_be_clickable((By.XPATH, "//button[normalize-space()='LOGIN']"))).click()

        start = time.time()
        while time.time() - start < 30:
            match = re.search(r"code=([a-zA-Z0-9\-]+)", driver.current_url)
            if match:
                return match.group(1)
            time.sleep(0.5)

        raise RuntimeError(
            f"Timed out waiting for auth code redirect. Last URL: {driver.current_url}"
        )

    except (InvalidSessionIdException, WebDriverException) as e:
        raise RuntimeError(f"Browser error during auth code retrieval: {e}") from e
    finally:
        try:
            driver.quit()
        except Exception:
            pass


if __name__ == "__main__":
    try:
        code = get_auth_code()
        print(f"Auth Code: {code}")
    except Exception as e:
        print(f"[ERROR] {e}")
