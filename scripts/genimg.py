# -*- coding: utf-8 -*-
"""
杨悦新小红书日更 · 配图生成
pollinations(flux) 取图 -> 裁底部水印带 -> 归一 3:4 -> 轻锐化 -> 压缩
图零文字铁律：prompt 强制 no people/no hands/no text/no letters
用法:
  python genimg.py today        仅生成今天
  python genimg.py 2026-10-30   指定日期
  python genimg.py all          全部日期（缺图才补）
  python genimg.py all --force  强制重生成
"""
import io, os, sys, time, json, urllib.parse
import requests
from PIL import Image, ImageFilter

IMG_BASE = (
    "editorial still life photography, Kinfolk magazine aesthetic, "
    "warm natural window light, soft shadows, muted earth tones, calm minimal composition, "
    "no people, no hands, no text, no letters, no watermark, "
)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCHED = os.path.join(ROOT, "data", "schedule.js")


def load_days():
    txt = open(SCHED, encoding="utf-8").read()
    js = txt.split("window.XHS_SCHEDULE =", 1)[1].rstrip()
    if js.endswith(";"):
        js = js[:-1]
    return json.loads(js).get("days", [])


def make(prompt, seed, out_path, retry=3):
    p = urllib.parse.quote(IMG_BASE + prompt)
    url = ("https://image.pollinations.ai/prompt/%s?width=810&height=1080"
           "&nologo=true&seed=%d&model=flux" % (p, seed))
    data = None
    for i in range(retry):
        try:
            r = requests.get(url, timeout=150)
            if r.status_code == 200 and len(r.content) > 8000:
                data = r.content
                break
        except Exception:
            pass
        time.sleep(4 + i * 4)
    if not data:
        return False
    im = Image.open(io.BytesIO(data)).convert("RGB")
    w, h = im.size
    im = im.crop((0, 0, w, int(h * 0.92)))            # 裁掉底部水印带
    im = im.resize((810, 1080), Image.LANCZOS)         # 归一 3:4 竖版
    im = im.filter(ImageFilter.UnsharpMask(radius=1.2, percent=65, threshold=3))
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    im.save(out_path, "JPEG", quality=78, optimize=True, progressive=True)
    return True


def gen_day(date_str, prompt, n=3, force=False):
    ok = 0
    for i in range(1, n + 1):
        out = os.path.join(ROOT, "images", date_str, "%d.jpg" % i)
        if (not force) and os.path.exists(out) and os.path.getsize(out) > 8000:
            ok += 1
            continue
        seed = (abs(hash(date_str)) % 70000) + i * 137
        if make(prompt, seed, out):
            ok += 1
            print("[ok] %s/%d  %dKB" % (date_str, i, os.path.getsize(out) // 1024), flush=True)
        else:
            print("[fail] %s/%d" % (date_str, i), flush=True)
        time.sleep(2)
    return ok


def today_str():
    import datetime
    # 小红书日更按北京时间取日
    return (datetime.datetime.utcnow() + datetime.timedelta(hours=8)).strftime("%Y-%m-%d")


def main():
    arg = sys.argv[1] if len(sys.argv) > 1 else "today"
    force = "--force" in sys.argv
    days = load_days()
    target = today_str() if arg == "today" else arg
    total_ok = 0
    for d in days:
        if target != "all" and d.get("date") != target:
            continue
        pr = d.get("imagePrompt") or d.get("main", {}).get("theme", "singing bowl still life")
        print("== %s | %s" % (d["date"], d.get("main", {}).get("theme", "")), flush=True)
        total_ok += gen_day(d["date"], pr, force=force)
    print("DONE ok=%d" % total_ok, flush=True)


if __name__ == "__main__":
    main()
