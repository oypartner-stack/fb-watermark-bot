import os
import json
import subprocess
import re
import urllib.request
from xml.etree import ElementTree as ET
import cloudinary
import cloudinary.uploader
import requests

# ─── الإعدادات ───────────────────────────────────────────
PAGE_ID = "61584143603071"
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

# ─── جلب الفيديوهات عبر RSS ──────────────────────────────
def get_latest_videos():
    print("🔍 جلب الفيديوهات عبر RSS...")

    rss_url = f"https://www.facebook.com/feeds/page.php?id={PAGE_ID}&format=rss20"

    videos = []
    try:
        req = urllib.request.Request(
            rss_url,
            headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
        )
        with urllib.request.urlopen(req, timeout=15) as r:
            content = r.read()

        root = ET.fromstring(content)
        items = root.findall('.//item')
        print(f"✅ RSS: وجدنا {len(items)} عنصر")

        for item in items[:5]:
            link = item.findtext('link') or ''
            title = item.findtext('title') or 'بدون عنوان'
            guid = item.findtext('guid') or link
            description = item.findtext('description') or ''

            # استخراج معرّف الفيديو
            vid_id = None
            # بحث عن video_id في الرابط
            match = re.search(r'videos?/(\d+)', link)
            if match:
                vid_id = match.group(1)
            else:
                match = re.search(r'v=(\d+)', link)
                if match:
                    vid_id = match.group(1)
                else:
                    # استخدام guid كمعرف
                    nums = re.sub(r'[^0-9]', '', guid)
                    if len(nums) > 5:
                        vid_id = nums[-15:]

            if vid_id and link:
                videos.append({
                    "id": vid_id,
                    "title": title.strip(),
                    "url": link.strip(),
                })
                print(f"  📹 {vid_id} | {title[:40]}")

    except Exception as e:
        print(f"❌ خطأ RSS: {str(e)[:200]}")

    # إذا لم ينجح RSS نجرب جلب الفيديو مباشرة عبر yt-dlp مع cookies
    if not videos:
        print("🔄 جرب yt-dlp مع cookies...")
        urls_to_try = [
            f"https://www.facebook.com/{PAGE_ID}/videos",
            f"https://www.facebook.com/profile.php?id={PAGE_ID}",
        ]
        for url in urls_to_try:
            result = subprocess.run([
                "yt-dlp",
                "--cookies", COOKIES_FILE,
                "--flat-playlist",
                "--playlist-items", "1:5",
                "--print", "%(id)s|%(title)s|%(webpage_url)s",
                "--no-warnings",
                url
            ], capture_output=True, text=True, timeout=60)

            for line in result.stdout.strip().split("\n"):
                if "|" in line:
                    parts = line.split("|", 2)
                    if len(parts) == 3:
                        vid_id, title, vid_url = parts
                        if vid_id and vid_url:
                            videos.append({
                                "id": vid_id.strip(),
                                "title": title.strip() or "بدون عنوان",
                                "url": vid_url.strip(),
                            })

            if videos:
                print(f"✅ yt-dlp: تم جلب {len(videos)} فيديو")
                break

    print(f"📊 إجمالي الفيديوهات: {len(videos)}")
    return videos

# ─── تحميل الفيديو وإضافة القالب ─────────────────────────
def process_video(video):
    print(f"⬇️ تحميل: {video['title'][:50]}")

    # تحميل الفيديو
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

    # جلب أبعاد الفيديو
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

    # تحميل القالب من Cloudinary
    watermark_url = f"https://res.cloudinary.com/{os.environ['CLOUDINARY_CLOUD_NAME']}/image/upload/{WATERMARK_PUBLIC_ID}.png"
    subprocess.run(
        ["wget", "-q", "-O", "/tmp/watermark.png", watermark_url],
        timeout=30
    )

    # إضافة القالب بنفس حجم الفيديو
    result = subprocess.run([
        "ffmpeg", "-y",
        "-i", "/tmp/video.mp4",
        "-i", "/tmp/watermark.png",
        "-filter_complex", f"[1:v]scale={w}:{h}[wm];[0:v][wm]overlay=0:0",
        "-codec:a", "copy",
        "-preset", "fast",
        "/tmp/output.mp4"
    ], capture_output=True, text=True, timeout=600)

    if not os.path.exists("/tmp/output.mp4"):
        print(f"❌ فشل ffmpeg: {result.stderr[:200]}")
        return None

    print("☁️ رفع الفيديو المعدّل على Cloudinary...")
    upload_result = cloudinary.uploader.upload(
        "/tmp/output.mp4",
        resource_type="video",
        public_id="processed_video",
        overwrite=True,
    )

    # تنظيف الملفات المؤقتة
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
        print(f"🆕 فيديو جديد: {new_video['title'][:60]}")
        final_url = process_video(new_video)
        if final_url:
            send_to_webhook(final_url, new_video["title"])
            processed_ids.append(new_video["id"])
            save_processed_ids(processed_ids)
            print("🎉 اكتمل بنجاح!")
        else:
            print("❌ فشلت معالجة الفيديو")
