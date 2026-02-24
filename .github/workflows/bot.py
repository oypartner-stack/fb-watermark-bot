import os
import json
import subprocess
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

# ─── جلب الفيديوهات من الصفحة ────────────────────────────
def get_latest_videos():
    print("🔍 جلب الفيديوهات...")
    result = subprocess.run([
        "yt-dlp",
        "--cookies", COOKIES_FILE,
        "--flat-playlist",
        "--playlist-items", "1:5",
        "--print", "%(id)s|%(title)s|%(webpage_url)s",
        "--no-warnings",
        PAGE_URL
    ], capture_output=True, text=True, timeout=60)

    videos = []
    for line in result.stdout.strip().split("\n"):
        if "|" in line:
            parts = line.split("|", 2)
            if len(parts) == 3:
                vid_id, title, url = parts
                if vid_id and url:
                    videos.append({
                        "id": vid_id.strip(),
                        "title": title.strip() or "بدون عنوان",
                        "url": url.strip(),
                    })

    print(f"✅ تم جلب {len(videos)} فيديو")
    if result.stderr:
        print(f"⚠️ stderr: {result.stderr[:300]}")
    return videos

# ─── تحميل الفيديو وإضافة القالب ─────────────────────────
def process_video(video):
    print(f"⬇️ تحميل: {video['title'][:50]}")
    subprocess.run([
        "yt-dlp",
        "--cookies", COOKIES_FILE,
        "-o", "/tmp/video.mp4",
        "--format", "best[ext=mp4]/best",
        "--no-warnings",
        video["url"]
    ], timeout=300)

    print("🎨 إضافة القالب الشفاف عبر ffmpeg...")
    # جلب أبعاد الفيديو
    probe = subprocess.run([
        "ffprobe", "-v", "quiet",
        "-print_format", "json",
        "-show_streams", "/tmp/video.mp4"
    ], capture_output=True, text=True)
    info = json.loads(probe.stdout)
    vstream = next((s for s in info["streams"] if s["codec_type"] == "video"), None)
    w = vstream["width"] if vstream else 1080
    h = vstream["height"] if vstream else 1920

    # تحميل القالب من Cloudinary
    watermark_url = f"https://res.cloudinary.com/{os.environ['CLOUDINARY_CLOUD_NAME']}/image/upload/{WATERMARK_PUBLIC_ID}.png"
    subprocess.run(["wget", "-q", "-O", "/tmp/watermark.png", watermark_url], timeout=30)

    # إضافة القالب بنفس حجم الفيديو
    subprocess.run([
        "ffmpeg", "-y",
        "-i", "/tmp/video.mp4",
        "-i", "/tmp/watermark.png",
        "-filter_complex", f"[1:v]scale={w}:{h}[wm];[0:v][wm]overlay=0:0",
        "-codec:a", "copy",
        "-preset", "fast",
        "/tmp/output.mp4"
    ], timeout=600)

    print("☁️ رفع الفيديو المعدّل على Cloudinary...")
    result = cloudinary.uploader.upload(
        "/tmp/output.mp4",
        resource_type="video",
        public_id="processed_video",
        overwrite=True,
    )
    return result["secure_url"]

# ─── إرسال للـ Webhook ────────────────────────────────────
def send_to_webhook(video_url, title):
    print("📤 إرسال للـ Webhook...")
    response = requests.post(WEBHOOK_URL, json={
        "video_url": video_url,
        "title": title
    })
    print(f"✅ تم الإرسال: {response.status_code}")

# ─── التنفيذ الرئيسي ──────────────────────────────────────
processed_ids = load_processed_ids()
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
        send_to_webhook(final_url, new_video["title"])
        processed_ids.append(new_video["id"])
        save_processed_ids(processed_ids)
        print("🎉 اكتمل بنجاح!")
