# -*- coding: utf-8 -*-
"""
杨悦新小红书日更 · 每日流水线（GitHub Actions 内运行，全免费链路）
流程：轻量对标检索 -> LLM 生成主/备文案 -> 生成 3 张配图 -> 写 data/today.js 与 data/schedule.js
降级：任何环节失败都保留原有排期内容，页面始终有东西可发
"""
import io, os, re, sys, json, time, html, random, datetime, urllib.parse
import requests

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IMG_BASE = (
    "editorial still life photography, Kinfolk magazine aesthetic, "
    "warm natural window light, soft shadows, muted earth tones, calm minimal composition, "
    "no people, no hands, no text, no letters, no watermark, "
)
SIGN = "我是杨悦新，做正念疗愈和女性成长。慢慢来。"
FIXED_TAGS = ["#女性成长", "#情绪疗愈", "#自我关怀", "#正念冥想"]
GH_TOKEN = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")

# 选题池：40% 常青方法 / 30% 人设叙事 / 20% 热点借力 / 10% 转化轻种草
TOPICS = [
    ("常青方法", "睡前脑子停不下来，试试这 3 步"),
    ("常青方法", "呼吸乱的时候，身体先知道的 4 个信号"),
    ("常青方法", "颂钵声里，怎么让肩膀真正松下来"),
    ("常青方法", "情绪上来时，给自己 90 秒的方法"),
    ("常青方法", "早晨的第一分钟内，做一件小事"),
    ("人设叙事", "做了三年正念，我最想撤回的一句话"),
    ("人设叙事", "第一次敲响颂钵那天，我手抖了"),
    ("人设叙事", "带过最累的一个女生，后来怎么样了"),
    ("人设叙事", "我把钵放在窗边，是因为一个学员"),
    ("热点借力", "换季这几天，身体比情绪更早知道"),
    ("热点借力", "都说要爱自己，可第一步常常是错的"),
    ("热点借力", "入秋后不想动，是身体在提要求"),
    ("热点借力", "手机放下却睡不着，中间少了什么"),
    ("转化轻种草", "一个人也能做的 5 分钟收心练习"),
    ("转化轻种草", "我把每天的开场，写成了一张卡片"),
]


def today():
    return (datetime.datetime.utcnow() + datetime.timedelta(hours=8)).strftime("%Y-%m-%d")


# ---------- 1. 轻量对标信号 ----------
# 站点导航/占位标题，不是真实笔记标题，必须过滤
NOISE = ("生活兴趣社区", "小红书 -", "rednote", "Xiaohongshu", "创作服务平台",
         "官网", "下载", "登录", "首页", "百度百科", "知乎")

SOURCES = [
    ("bing", "https://www.bing.com/search?q=", re.compile(r"<h2[^>]*>(.*?)</h2>", re.S)),
    ("ddg", "https://lite.duckduckgo.com/lite/?q=", re.compile(r'class="result-link"[^>]*>(.*?)</a>', re.S)),
]


def clean_titles(raw_list):
    out = []
    for t in raw_list:
        t = html.unescape(re.sub(r"<[^>]+>", "", t)).strip()
        if not t or len(t) < 6 or len(t) > 42:
            continue
        if any(n.lower() in t.lower() for n in NOISE):
            continue
        # 小红书笔记标题以中文为主，纯英文多为站点导航/SSO 占位页，丢弃
        if not any("\u4e00" <= ch <= "\u9fff" for ch in t):
            continue
        if t.count("|") or t.count(" - "):
            continue
        if t not in out:
            out.append(t)
    return out[:5]


def duibiao(keyword):
    """多源轻量检索，取真实笔记标题作为对标信号；全部失败则返回空，由 LLM 按季节自行判断"""
    for name, base, pat in SOURCES:
        try:
            u = base + urllib.parse.quote("小红书 " + keyword)
            r = requests.get(u, timeout=25, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
            if r.status_code != 200:
                continue
            got = clean_titles(pat.findall(r.text)[:12])
            if got:
                print("[duibiao] 来源=%s 条数=%d : %s" % (name, len(got), "；".join(got)[:100]), flush=True)
                return "；".join(got[:4])
        except Exception as e:
            print("[duibiao] %s 异常: %s" % (name, str(e)[:80]), flush=True)
    print("[duibiao] 全部检索源无有效结果，交由 LLM 按季节判断", flush=True)
    return ""


# ---------- 2. LLM 生成文案 ----------
SYS = (
    "你是小红书博主「杨悦新」的撰稿助手。赛道：正念疗愈 / 女性身心成长；锚点：正念冥想 + 颂钵。"
    "要求：口语化、有画面感、具体到可执行的动作；禁止医疗断言、禁止绝对化用词、禁止导流话术；"
    "禁止编造数据或百分比。结尾必须原样附上署名。"
)


def llm(user):
    """多引擎回退：GitHub Models -> pollinations OpenAI 兼容。
    每一步失败原因都打印到日志，避免异常被吞掉无法排查。"""
    attempts = []

    if GH_TOKEN:
        for model in ["gpt-4o-mini", "gpt-4o", "Phi-3.5-mini-instruct"]:
            try:
                r = requests.post(
                    "https://models.inference.ai.azure.com/chat/completions",
                    headers={"Authorization": "Bearer " + GH_TOKEN,
                             "Content-Type": "application/json"},
                    json={"model": model,
                          "messages": [{"role": "system", "content": SYS},
                                       {"role": "user", "content": user}],
                          "temperature": 0.85, "max_tokens": 1600},
                    timeout=90)
                if r.status_code == 200:
                    c = r.json()["choices"][0]["message"]["content"]
                    if c and len(c.strip()) > 50:
                        print("[llm ok] model=%s len=%d" % (model, len(c)), flush=True)
                        return c
                    attempts.append("%s->EMPTY(len=%d)" % (model, len(c or "")))
                else:
                    attempts.append("%s->HTTP%d:%s" % (model, r.status_code,
                                                       (r.text or "")[:100].replace("\n", " ")))
            except Exception as e:
                attempts.append("%s->EXC:%s" % (model, str(e)[:100]))

    try:
        r = requests.post(
            "https://text.pollinations.ai/openai/chat/completions",
            headers={"Content-Type": "application/json"},
            json={"model": "openai",
                  "messages": [{"role": "system", "content": SYS},
                               {"role": "user", "content": user}],
                  "temperature": 0.85, "max_tokens": 1600},
            timeout=90)
        if r.status_code == 200:
            c = r.json()["choices"][0]["message"]["content"]
            if c and len(c.strip()) > 50:
                print("[llm ok] pollinations len=%d" % len(c), flush=True)
                return c
            attempts.append("pollinations->EMPTY")
        else:
            attempts.append("pollinations->HTTP%d:%s" % (r.status_code, (r.text or "")[:100]))
    except Exception as e:
        attempts.append("pollinations->EXC:%s" % str(e)[:100])

    print("[llm FAIL] " + " | ".join(attempts)[:700], flush=True)
    return None


PROMPT = """请围绕选题「{topic}」写一篇小红书笔记，并同时写一篇备选。

对标信号（仅供参考，不要照抄）：{db}

严格按以下行格式输出，每行一个字段，不要输出多余解释：
THEME: 一句话概括选题
COLUMN: {column}
TITLE1: 标题（<=20字，有钩子）
TITLE2: 标题备选（<=20字）
TITLE3: 标题备选（<=20字）
BODY: 正文（300-500字，段落用换行分隔，口语化，有具体动作，结尾原样包含：{sign}）
TAGS: 标签，空格分隔，必须以 {fixed} 开头
KEYWORD: 评论区引导关键词，2-4字
ALT_THEME: 备选笔记选题
ALT_TITLE: 备选标题（<=20字）
ALT_BODY: 备选正文（200-400字，结尾同样包含署名）
ALT_TAGS: 备选标签
IMAGE: 配图英文描述（静物/光影/自然质感，不要出现文字与人）
"""


def parse(txt):
    f = {}
    key = None
    for line in (txt or "").splitlines():
        m = re.match(r"^([A-Z_0-9]+):\s*(.*)$", line.strip())
        if m:
            key = m.group(1)
            f[key] = m.group(2).strip()
        elif key and line.strip():
            f[key] += "\n" + line.strip()
    return f


def norm_body(s, sign=SIGN):
    s = (s or "").strip().rstrip("；;")
    s = re.sub(r"[\d.]+\s*%", "", s)          # 去掉可能的编造百分数
    if sign not in s:
        s += "\n\n" + sign
    return s.strip()


# ---------- 3. 配图 ----------
def make_image(prompt, seed, out):
    p = urllib.parse.quote(IMG_BASE + prompt)
    url = ("https://image.pollinations.ai/prompt/%s?width=810&height=1080"
           "&nologo=true&seed=%d&model=flux" % (p, seed))
    try:
        from PIL import Image, ImageFilter
    except Exception:
        return False
    for i in range(5):
        try:
            r = requests.get(url, timeout=150)
            if r.status_code == 200 and len(r.content) > 8000:
                im = Image.open(io.BytesIO(r.content)).convert("RGB")
                w, h = im.size
                im = im.crop((0, 0, w, int(h * 0.92)))
                im = im.resize((810, 1080), Image.LANCZOS)
                im = im.filter(ImageFilter.UnsharpMask(radius=1.2, percent=65, threshold=3))
                os.makedirs(os.path.dirname(out), exist_ok=True)
                im.save(out, "JPEG", quality=78, optimize=True, progressive=True)
                return True
        except Exception:
            pass
        time.sleep(5 + i * 5)
    return False


# ---------- 4. 主流程 ----------
def load_schedule():
    p = os.path.join(ROOT, "data", "schedule.js")
    txt = open(p, encoding="utf-8").read()
    js = txt.split("window.XHS_SCHEDULE =", 1)[1].rstrip().rstrip(";")
    return json.loads(js)


def save_schedule(obj):
    p = os.path.join(ROOT, "data", "schedule.js")
    open(p, "w", encoding="utf-8").write("window.XHS_SCHEDULE = " + json.dumps(obj, ensure_ascii=False) + ";\n")


def main():
    d = today()
    sched = load_schedule()
    # 每天重新生成（对标当天的信号），失败时保留原有排期内容作为降级
    print("目标日期: %s" % d)

    column, topic = random.choice(TOPICS)
    print("选题:", column, topic)
    db = duibiao(topic)
    print("对标:", db[:120])

    raw = llm(PROMPT.format(
        topic=topic,
        db=db or "（外部检索未取到有效结果，请结合当季气候、节气与女性日常处境自行判断当下热点）",
        column=column, sign=SIGN, fixed=" ".join(FIXED_TAGS)))
    f = parse(raw) if raw else {}
    if not f.get("BODY") or len(f.get("BODY", "")) < 120:
        print("LLM 无有效输出，降级跳过文案生成")
        f = {}

    img_prompt = f.get("IMAGE") or ("singing bowl and linen on wooden table by window, warm morning light")
    imgs = []
    for i in range(1, 4):
        out = os.path.join(ROOT, "images", d, "%d.jpg" % i)
        if make_image(img_prompt, abs(hash(d)) % 70000 + i * 137, out):
            imgs.append("./images/%s/%d.jpg" % (d, i))
            print("[img ok]", d, i)
        time.sleep(2)
    # 图与文案解耦：文案照常写入，缺图由后续 genimg.py all 补齐
    if len(imgs) < 3:
        print("[warn] 本次配图仅 %d/3 张，稍后由 genimg.py 补齐；文案正常更新" % len(imgs), flush=True)

    if f.get("BODY"):
        tags = f.get("TAGS", "").split() or FIXED_TAGS
        day = {
            "date": d, "column": f.get("COLUMN", column),
            "basis": "每日云生成 · " + column,
            "duibiao": db,
            "imagePrompt": img_prompt,
            "main": {"theme": f.get("THEME", topic),
                     "titles": [f.get("TITLE1", topic), f.get("TITLE2", topic), f.get("TITLE3", topic)],
                     "body": norm_body(f.get("BODY")), "tags": tags,
                     "keyword": f.get("KEYWORD", "慢慢来"), "postTime": "12:00-13:30 或 20:00-22:00"},
            "images": ["./images/%s/%d.jpg" % (d, k) for k in (1, 2, 3)],
        }
        if f.get("ALT_BODY"):
            day["alt"] = {"theme": f.get("ALT_THEME", topic + "（备选）"),
                          "titles": [f.get("ALT_TITLE", topic)],
                          "body": norm_body(f.get("ALT_BODY")),
                          "tags": f.get("ALT_TAGS", "").split() or FIXED_TAGS,
                          "keyword": f.get("KEYWORD", "慢慢来")}
        sched["days"] = [x for x in sched["days"] if x.get("date") != d] + [day]
        sched["days"].sort(key=lambda x: x["date"])
        save_schedule(sched)
        print("[ok] 文案已写入 schedule.js")

    open(os.path.join(ROOT, "data", "today.js"), "w", encoding="utf-8").write(
        "window.TODAY_CLOUD = " + json.dumps({"date": d}, ensure_ascii=False) + ";\n")
    print("DONE", d)
    return 0


if __name__ == "__main__":
    sys.exit(main())
