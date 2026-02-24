import os
import json
import subprocess
import re
import cloudinary
import cloudinary.uploader
import requests

# ─── الإعدادات ───────────────────────────────────────────
PAGE_URL = "https://www.facebook.com/profile.php?id=61584143603071&sk=reels_tab"
LAST_IDS_FILE = "processed_ids.json"
COOKIES_FILE = "/tmp/cookies.txt"
WATERMARK_PUBLIC_ID = "fes_ceel2l"
WEBHOOK_URL = os.environ["WEBHOOK_URL"]

cloudinary.config(
    cloud_name = os.environ["CLOUDINARY_CLOUD_NAME"],
    api_key    = os.environ["CLOUDINARY_API_KEY"],
    api_secret = os.environ["CLOUDINARY_API_SECRET"],
)

# ─── قائمة الفيديوهات المعالجة ───────────────────────────
def load_processed_ids():
    try:
        with open(LAST_IDS_FILE, "r") as f:
            return json.load(f)
    except:
        return []

def save_processed_ids(ids):
    with open(LAST_IDS_FILE, "w") as f:
        json.dump(ids[-50:], f)

# ─── جلب روابط الفيديوهات عبر Selenium ──────────────────
def get_latest_videos():
    print("🔍 جلب الفيديوهات عبر Selenium...")

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
time.sleep(5)

page_source = driver.page_source
driver.quit()

patterns = [
    r'href="(https://www\\.facebook\\.com/reel/[^"]+)"',
    r'href="(/reel/[^"]+)"',
    r'"url":"(https://www\\.facebook\\.com/reel/[^"]+)"',
    r'(https://www\\.facebook\\.com/share/r/[^"\\\\]+)',
]

videos = []
seen = set()
for pattern in patterns:
    matches = re.findall(pattern, page_source)
    for m in matches:
        url = m if m.startswith("http") else "https://www.facebook.com" + m
        url = url.replace("\\\\u0025", "%").replace("\\\\", "")
        vid_id = re.sub(r"[^0-9a-zA-Z]", "", url.split("/")[-1] or url.split("/")[-2])
        if vid_id and vid_id not in seen:
            seen.add(vid_id)
            videos.append({"id": vid_id, "title": "reel", "url": url})

print(json.dumps(videos[:5]))
"""

    with open("/tmp/selenium_script.py", "w") as f:
        f.write(script)

    result = subprocess.run(
        ["python", "/tmp/selenium_script.py"],
        capture_output=True, text=True, timeout=60
    )

    print(f"stdout: {result.stdout[:500]}")
    if result.stderr:
        print(f"stderr: {result.stderr[:300]}")

    try:
        lines = result.stdout.strip().split("\n")
        for line in reversed(lines):
            if line.startswith("["):
                videos = json.loads(line)
                print(f"✅ تم جلب {len(videos)} فيديو")
                return videos
    except Exception as e:
        print(f"❌ خطأ في تحليل النتائج: {e}")

    return []

# ─── تحميل الفيديو وإضافة القالب ─────────────────────────
def process_video(video):
    print(f"⬇️ تحميل: {video['url']}")

    result = subprocess.run([
        "yt-dlp",
        "--cookies", COOKIES_FILE,
        "-o", "/tmp/video.mp4",
        "--format", "best[ext=mp4]/best",
        "--no-warnings",
        video["url"]
    ], capture_output=True, text=True, timeout=300)

    if not os.path.exists("/tmp/video.mp4"):
        print(f"❌ فشل التحميل: {result.stderr[:200]}")
        return None

    print("🎨 إضافة القالب الشفاف...")

    probe = subprocess.run([
        "ffprobe", "-v", "quiet",
        "-print_format", "json",
        "-show_streams", "/tmp/video.mp4"
    ], capture_output=True, text=True)

    try:
        info = json.loads(probe.stdout)
        vstream = next((s for s in info["streams"] if s["codec_type"] == "video"), None)
        w = vstream["width"] if vstream else 1080
        h = vstream["height"] if vstream else 1920
    except:
        w, h = 1080, 1920

    print(f"📐 أبعاد الفيديو: {w}x{h}")

    watermark_url = f"https://res.cloudinary.com/{os.environ['CLOUDINARY_CLOUD_NAME']}/image/upload/{WATERMARK_PUBLIC_ID}.png"
    subprocess.run(["wget", "-q", "-O", "/tmp/watermark.png", watermark_url], timeout=30)

    subprocess.run([
        "ffmpeg", "-y",
        "-i", "/tmp/video.mp4",
        "-i", "/tmp/watermark.png",
        "-filter_complex", f"[1:v]scale={w}:{h}[wm];[0:v][wm]overlay=0:0",
        "-codec:a", "copy",
        "-preset", "fast",
        "/tmp/output.mp4"
    ], timeout=600)

    if not os.path.exists("/tmp/output.mp4"):
        print("❌ فشل ffmpeg")
        return None

    print("☁️ رفع على Cloudinary...")
    upload_result = cloudinary.uploader.upload(
        "/tmp/output.mp4",
        resource_type="video",
        public_id="processed_video",
        overwrite=True,
    )

    for f in ["/tmp/video.mp4", "/tmp/output.mp4", "/tmp/watermark.png"]:
        if os.path.exists(f):
            os.remove(f)

    return upload_result["secure_url"]

# ─── إرسال للـ Webhook ────────────────────────────────────
def send_to_webhook(video_url, title):
    print("📤 إرسال للـ Webhook...")
    response = requests.post(WEBHOOK_URL, json={
        "video_url": video_url,
        "title": title
    }, timeout=30)
    print(f"✅ تم الإرسال: {response.status_code}")

# ─── التنفيذ الرئيسي ──────────────────────────────────────
print("🤖 بدء تشغيل البوت...")
processed_ids = load_processed_ids()
print(f"📋 فيديوهات معالجة سابقاً: {len(processed_ids)}")

videos = get_latest_videos()

if not videos:
    print("❌ لم يتم جلب أي فيديو")
else:
    new_video = None
    for v in videos:
        if v["id"] not in processed_ids:
            new_video = v
            break

    if not new_video:
        print("ℹ️ لا يوجد فيديو جديد")
    else:
        print(f"🆕 فيديو جديد: {new_video['url']}")
        final_url = process_video(new_video)
        if final_url:
            send_to_webhook(final_url, new_video["title"])
            processed_ids.append(new_video["id"])
            save_processed_ids(processed_ids)
            print("🎉 اكتمل بنجاح!")
        else:
            print("❌ فشلت معالجة الفيديو")
