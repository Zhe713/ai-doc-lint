# -*- coding: utf-8 -*-
"""抓取 40 份合同官方正文（示范文本库 View 页）存文本，供 ground truth 构造。"""
import json
import os
import re
import urllib.parse
import urllib.request

BASE = "https://htsfwb.samr.gov.cn"
GOLDEN_DIR = r"D:\projects\ai-doc-lint\corpus\acceptance_golden"
TEXT_DIR = os.path.join(GOLDEN_DIR, "texts")
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}


def fetch_view(doc_id):
    url = f"{BASE}/View?id={doc_id}"
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", errors="ignore")


def extract_text(html):
    # 去掉 script/style
    html = re.sub(r"<script.*?</script>", " ", html, flags=re.S | re.I)
    html = re.sub(r"<style.*?</style>", " ", html, flags=re.S | re.I)
    # 表格单元格加分隔
    html = re.sub(r"</(td|th|tr|p|div|li|h[1-6])>", "\n", html, flags=re.I)
    html = re.sub(r"<br\s*/?>", "\n", html, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", html)
    text = re.sub(r"&nbsp;?", " ", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n", text)
    return text.strip()


def main():
    os.makedirs(TEXT_DIR, exist_ok=True)
    with open(os.path.join(GOLDEN_DIR, "manifest.json"), encoding="utf-8") as f:
        manifest = json.load(f)
    stats = []
    for item in manifest:
        out = os.path.join(TEXT_DIR, item["file"].replace(".pdf", ".txt"))
        if os.path.exists(out) and os.path.getsize(out) > 200:
            stats.append((item["file"], os.path.getsize(out)))
            continue
        try:
            html = fetch_view(item["id"])
            text = extract_text(html)
            with open(out, "w", encoding="utf-8") as f:
                f.write(f"# {item['title']}\n\n{text}")
            stats.append((item["file"], len(text.encode("utf-8"))))
            print(f"ok {item['file']} {len(text)}字")
        except Exception as e:
            print(f"FAIL {item['file']}: {e}")
    print(f"\ntotal={len(stats)}")


if __name__ == "__main__":
    main()
