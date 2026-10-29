# -*- coding: utf-8 -*-
"""
配图兜底：用已质检的本地静物图生成差异化变体，铺满排期每一天。
每张原图派生多个变体（翻转/色温/亮度/缩放），保证同一天 3 张来自不同底图。
已存在的真实生图不覆盖。
"""
import os, json, glob, random
from PIL import Image, ImageEnhance, ImageOps

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC_DIR = r"C:\Users\xy395\AppData\Local\wb-checkin\imgtest"
TARGET = (810, 1080)

VARIANTS = [
    ("a", lambda im: im),
    ("b", lambda im: ImageOps.mirror(im)),
    ("c", lambda im: ImageEnhance.Color(im).enhance(1.12)),
    ("d", lambda im: ImageEnhance.Brightness(im).enhance(1.06)),
    ("e", lambda im: ImageEnhance.Contrast(im).enhance(1.08)),
    ("f", lambda im: ImageOps.mirror(ImageEnhance.Color(im).enhance(0.92))),
]


def prep(im):
    w, h = im.size
    ar = TARGET[0] / TARGET[1]
    if w / h > ar:
        nw = int(h * ar)
        im = im.crop(((w - nw) // 2, 0, (w - nw) // 2 + nw, h))
    else:
        nh = int(w / ar)
        im = im.crop((0, (h - nh) // 2, w, (h - nh) // 2 + nh))
    return im.resize(TARGET, Image.LANCZOS)


def load_days():
    txt = open(os.path.join(ROOT, "data", "schedule.js"), encoding="utf-8").read()
    js = txt.split("window.XHS_SCHEDULE =", 1)[1].rstrip().rstrip(";")
    return json.loads(js)["days"]


def main():
    bases = [prep(Image.open(f).convert("RGB")) for f in sorted(glob.glob(os.path.join(SRC_DIR, "*.jpg")))]
    print("底图数量:", len(bases))
    pool = []
    for i, b in enumerate(bases):
        for tag, fn in VARIANTS:
            pool.append((i, Image.Image.copy(fn(b))))
    random.seed(20261030)
    random.shuffle(pool)
    print("可用变体:", len(pool))

    days = load_days()
    need = []
    for d in days:
        for k in (1, 2, 3):
            p = os.path.join(ROOT, "images", d["date"], "%d.jpg" % k)
            if not (os.path.exists(p) and os.path.getsize(p) > 8000):
                need.append((d["date"], k, p))
    print("待补槽位:", len(need))

    used_source = {}
    ptr = 0
    filled = 0
    for date, k, p in need:
        # 同一天尽量不用同一底图
        pick = None
        for idx in range(ptr, len(pool)):
            if pool[idx][0] not in used_source.get(date, set()):
                pick = idx
                break
        if pick is None:
            pick = ptr
        ptr = (pick + 1) % len(pool)
        src_id, im = pool[pick]
        used_source.setdefault(date, set()).add(src_id)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        im.save(p, "JPEG", quality=78, optimize=True, progressive=True)
        filled += 1
    print("已填充:", filled)
    # 校验
    miss = []
    for d in days:
        for k in (1, 2, 3):
            p = os.path.join(ROOT, "images", d["date"], "%d.jpg" % k)
            if not (os.path.exists(p) and os.path.getsize(p) > 8000):
                miss.append("%s/%d" % (d["date"], k))
    print("仍缺失:", len(miss), miss[:10])


if __name__ == "__main__":
    main()
