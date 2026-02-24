import os
import json
import subprocess

COOKIES_FILE = "/tmp/cookies.txt"

script = """
import json
import time
import re
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager

options = Options()
options.add_argument("--headless")
options.add_argument("--no-sandbox")
options.add_argument("--disable-dev-shm-usage")
options.add_argument("--disable-gpu")
options.add_argument("--window-size=1920,1080")
options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")

service = Service(ChromeDriverManager().install())
driver = webdriver.Chrome(service=service, options=options)

driver.get("https://www.facebook.com")
time.sleep(2)

cookies = [
    {"name": "sb",     "value": "5nyvZrV8TpxXzQrXEnpFxhLF", "domain": ".facebook.com"},
    {"name": "datr",   "value": "5nyvZv0QJ0q28NX27rB16g9z",  "domain": ".facebook.com"},
    {"name": "c_user", "value": "100069712184627",            "domain": ".facebook.com"},
    {"name": "xs",     "value": "17%3AZ3V5wuxvl1jQWg%3A2%3A1771862196%3A-1%3A-1%3A%3AAcyA0v2USDmS3jzlm_41LAhgWWM2_NNxyIdknLhPTQ", "domain": ".facebook.com"},
    {"name": "fr",     "value": "2M0aPQGPMVpMja77j.AWfTe0lOsBohnfT0vGJ6M3Dc0tRDzAE1sAm4N6Ix_ck0zH-QDSE.BpnQ5-..AAA.0.0.BpnQ5-.AWcRFIeuIxl3O5Z1pjwmf9Idaxg", "domain": ".facebook.com"},
]

for cookie in cookies:
    try:
        driver.add_cookie(cookie)
    except:
        pass

driver.get("https://www.facebook.com/profile.php?id=61584143603071&sk=reels_tab")
time.sleep(8)

page_source = driver.page_source
driver.quit()

# البحث عن كل الروابط التي تحتوي على reel أو video أو watch
all_links = re.findall(r'href="([^"]*(?:reel|video|watch|share)[^"]*)"', page_source)
print("=== روابط وجدناها ===")
for l in all_links[:20]:
    print(l)

print("=== انتهى ===")
"""

with open("/tmp/selenium_script.py", "w") as f:
    f.write(script)

result = subprocess.run(
    ["python", "/tmp/selenium_script.py"],
    capture_output=True, text=True, timeout=90
)

print("STDOUT:")
print(result.stdout)
print("STDERR:")
print(result.stderr[:500])
