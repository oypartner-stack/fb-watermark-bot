import os
import json
import time
import threading
import logging
import requests
import tempfile
import subprocess
from datetime import datetime
from flask import Flask, render_template, request, jsonify
from PIL import Image
import ffmpeg

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = Flask(__name__)

# ─── State ────────────────────────────────────────────────────────────────────
state = {
    "running": False,
    "page_url": "",
    "webhook_url": "",
    "interval_minutes": 10,
    "last_video_id": None,
    "last_check": None,
    "last_sent": None,
    "logs": [],
    "status": "idle",   # idle | running | error
    "watermark_path": "watermark.png",
}

def add_log(msg, level="info"):
    entry = {"time": datetime.now().strftime("%H:%M:%S"), "msg": msg, "level": level}
    state["logs"].insert(0, entry)
    state["logs"] = state["logs"][:100]   # keep last 100
    getattr(logger, level)(msg)

# ─── Video processing ─────────────────────────────────────────────────────────
def download_latest_video(page_url):
    """Use yt-dlp to grab the latest video from a public Facebook page."""
    try:
        add_log(f"🔍 جارٍ البحث عن أحدث فيديو من: {page_url}")
        result = subprocess.run(
            ["yt-dlp", "--get-id", "--get-title", "--get-url",
             "--playlist-items", "1",
             "--no-warnings",
             "--format", "best[ext=mp4]/best",
             page_url],
            capture_output=True, text=True, timeout=60
        )
        if result.returncode != 0:
            add_log(f"❌ خطأ في yt-dlp: {result.stderr[:200]}", "error")
            return None, None, None

        lines = [l.strip() for l in result.stdout.strip().split("\n") if l.strip()]
        if len(lines) < 3:
            add_log("❌ لم يتم العثور على فيديو", "error")
            return None, None, None

        video_id = lines[0]
        title = lines[1]
        video_url = lines[2]
        add_log(f"✅ تم العثور على فيديو: {title[:60]}")
        return video_id, title, video_url
    except subprocess.TimeoutExpired:
        add_log("❌ انتهت مهلة البحث عن الفيديو", "error")
        return None, None, None
    except Exception as e:
        add_log(f"❌ خطأ غير متوقع: {str(e)}", "error")
        return None, None, None


def download_video_file(video_url):
    """Download the actual video file to a temp path."""
    try:
        add_log("⬇️ جارٍ تحميل الفيديو...")
        tmp = tempfile.NamedTemporaryFile(suffix=".mp4", delete=False)
        result = subprocess.run(
            ["yt-dlp", "-o", tmp.name, "--format", "best[ext=mp4]/best",
             "--no-warnings", video_url],
            capture_output=True, text=True, timeout=300
        )
        if result.returncode != 0:
            add_log(f"❌ فشل تحميل الفيديو: {result.stderr[:200]}", "error")
            return None
        add_log("✅ تم تحميل الفيديو بنجاح")
        return tmp.name
    except Exception as e:
        add_log(f"❌ خطأ في التحميل: {str(e)}", "error")
        return None


def add_watermark(input_path, watermark_path):
    """Overlay transparent PNG watermark scaled to FULL video size."""
    try:
        add_log("🎨 جارٍ إضافة العلامة المائية بمقياس الفيديو كاملاً...")
        output_path = tempfile.mktemp(suffix="_watermarked.mp4")

        # Scale watermark to exact video dimensions, then overlay at 0,0
        filter_complex = (
            "[1:v]scale=iw:ih[wm];"          # scale watermark (placeholder, real scale below)
            "[0:v][1:v]scale2ref[wm][base];"  # scale watermark to match video
            "[base][wm]overlay=0:0"           # overlay at top-left (covers full frame)
        )

        result = subprocess.run([
            "ffmpeg", "-y",
            "-i", input_path,
            "-i", watermark_path,
            "-filter_complex",
            # Scale the watermark PNG to exactly match video W x H, then overlay
            "[1:v]scale=iw:ih[wm_orig];"
            "[0:v][wm_orig]scale2ref[wm_scaled][vid];"
            "[vid][wm_scaled]overlay=0:0",
            "-codec:a", "copy",
            "-preset", "fast",
            output_path
        ], capture_output=True, text=True, timeout=600)

        if result.returncode != 0:
            # Fallback: simpler filter that scales watermark to video size
            add_log("⚠️ جاري المحاولة بطريقة بديلة...")
            result2 = subprocess.run([
                "ffmpeg", "-y",
                "-i", input_path,
                "-i", watermark_path,
                "-filter_complex",
                "[0:v]scale=iw:ih[base];[1:v]scale=iw:ih[wm];[base][wm]overlay=0:0",
                "-codec:a", "copy",
                "-preset", "fast",
                output_path
            ], capture_output=True, text=True, timeout=600)

            if result2.returncode != 0:
                # Final fallback: get video dimensions then scale watermark explicitly
                probe = subprocess.run([
                    "ffprobe", "-v", "quiet", "-print_format", "json",
                    "-show_streams", input_path
                ], capture_output=True, text=True)
                import json as _json
                info = _json.loads(probe.stdout)
                vstream = next((s for s in info["streams"] if s["codec_type"] == "video"), None)
                w = vstream["width"] if vstream else 1080
                h = vstream["height"] if vstream else 1920

                result3 = subprocess.run([
                    "ffmpeg", "-y",
                    "-i", input_path,
                    "-i", watermark_path,
                    "-filter_complex",
                    f"[1:v]scale={w}:{h}[wm];[0:v][wm]overlay=0:0",
                    "-codec:a", "copy",
                    "-preset", "fast",
                    output_path
                ], capture_output=True, text=True, timeout=600)

                if result3.returncode != 0:
                    add_log(f"❌ فشل إضافة العلامة: {result3.stderr[:300]}", "error")
                    return None

        add_log("✅ تمت إضافة العلامة المائية على الفيديو كاملاً")
        return output_path
    except Exception as e:
        add_log(f"❌ خطأ في ffmpeg: {str(e)}", "error")
        return None


def send_to_webhook(webhook_url, video_path, title):
    """Send video file + title to Make.com webhook."""
    try:
        add_log(f"📤 جارٍ الإرسال إلى Webhook...")
        with open(video_path, "rb") as vf:
            response = requests.post(
                webhook_url,
                data={"title": title},
                files={"video": ("video.mp4", vf, "video/mp4")},
                timeout=120
            )
        if response.status_code in (200, 201, 202):
            add_log(f"✅ تم الإرسال بنجاح! كود الاستجابة: {response.status_code}")
            state["last_sent"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            return True
        else:
            add_log(f"❌ فشل الإرسال: {response.status_code} - {response.text[:100]}", "error")
            return False
    except Exception as e:
        add_log(f"❌ خطأ في الإرسال: {str(e)}", "error")
        return False


def cleanup(*paths):
    for p in paths:
        if p and os.path.exists(p):
            try:
                os.unlink(p)
            except:
                pass

# ─── Main loop ────────────────────────────────────────────────────────────────
def monitor_loop():
    while state["running"]:
        state["last_check"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        add_log(f"🔄 فحص جديد - {state['last_check']}")

        video_id, title, video_url = download_latest_video(state["page_url"])

        if video_id and video_id != state["last_video_id"]:
            add_log(f"🆕 فيديو جديد بعنوان: {title}")
            
            raw_path = download_video_file(video_url)
            if raw_path:
                wm_path = add_watermark(raw_path, state["watermark_path"])
                if wm_path:
                    sent = send_to_webhook(state["webhook_url"], wm_path, title)
                    if sent:
                        state["last_video_id"] = video_id
                cleanup(raw_path, wm_path)
        elif video_id:
            add_log("ℹ️ لا يوجد فيديو جديد")

        # wait interval
        wait_seconds = state["interval_minutes"] * 60
        for _ in range(wait_seconds):
            if not state["running"]:
                break
            time.sleep(1)

    state["status"] = "idle"
    add_log("⏹️ تم إيقاف المراقبة")

# ─── Routes ───────────────────────────────────────────────────────────────────
@app.route("/")
def index():
    return render_template("index.html")

@app.route("/api/start", methods=["POST"])
def start():
    data = request.json
    if state["running"]:
        return jsonify({"error": "البوت يعمل بالفعل"}), 400

    page_url = data.get("page_url", "").strip()
    webhook_url = data.get("webhook_url", "").strip()
    interval = int(data.get("interval", 10))

    if not page_url or not webhook_url:
        return jsonify({"error": "يرجى إدخال رابط الصفحة ورابط Webhook"}), 400

    if not os.path.exists(state["watermark_path"]):
        return jsonify({"error": "لم يتم رفع صورة العلامة المائية بعد"}), 400

    state["running"] = True
    state["status"] = "running"
    state["page_url"] = page_url
    state["webhook_url"] = webhook_url
    state["interval_minutes"] = interval
    state["last_video_id"] = None

    t = threading.Thread(target=monitor_loop, daemon=True)
    t.start()

    add_log(f"▶️ بدأت المراقبة - كل {interval} دقيقة")
    return jsonify({"ok": True})

@app.route("/api/stop", methods=["POST"])
def stop():
    state["running"] = False
    state["status"] = "idle"
    add_log("⏹️ طلب إيقاف...")
    return jsonify({"ok": True})

@app.route("/api/status")
def get_status():
    return jsonify({
        "running": state["running"],
        "status": state["status"],
        "page_url": state["page_url"],
        "last_check": state["last_check"],
        "last_sent": state["last_sent"],
        "logs": state["logs"][:30],
        "has_watermark": os.path.exists(state["watermark_path"]),
    })

@app.route("/api/upload-watermark", methods=["POST"])
def upload_watermark():
    if "file" not in request.files:
        return jsonify({"error": "لم يتم إرسال ملف"}), 400
    f = request.files["file"]
    if not f.filename.lower().endswith(".png"):
        return jsonify({"error": "يجب أن يكون الملف بصيغة PNG"}), 400
    f.save(state["watermark_path"])
    add_log("🖼️ تم رفع العلامة المائية بنجاح")
    return jsonify({"ok": True})

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
