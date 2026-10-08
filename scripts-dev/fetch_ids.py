"""用浏览器采集到的详情 id 列表下载政采合同，并合并 CUAD 生成 manifest。

容器内：
    python fetch_ids.py /tmp/ccgp_ids.json /tmp/corpus
"""

import csv
import re
import sys
import time
from pathlib import Path

import httpx

from collect_corpus import BASE, TITLE_RE, TextExtractor, fetch, manifest_cuad


def main() -> None:
    ids_file, root_arg = sys.argv[1], sys.argv[2]
    ids: list[str] = __import__("json").load(open(ids_file, encoding="utf-8"))
    root = Path(root_arg)
    html_dir = root / "ccgp" / "html"
    txt_dir = root / "ccgp" / "txt"
    html_dir.mkdir(parents=True, exist_ok=True)
    txt_dir.mkdir(parents=True, exist_ok=True)

    rows: list[dict] = []
    with httpx.Client(
        headers={"User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                                "AppleWebKit/537.36 (KHTML, like Gecko) "
                                "Chrome/126.0 Safari/537.36")},
        follow_redirects=True,
    ) as client:
        for n, cid in enumerate(ids):
            url = f"{BASE}/detail/{cid}?contractSign=0"
            try:
                raw = fetch(client, url)
            except RuntimeError as exc:
                print(f"skip {cid}: {exc}")
                continue
            (html_dir / f"{cid}.html").write_bytes(raw)
            parser = TextExtractor()
            parser.feed(raw.decode("utf-8", "ignore"))
            text = parser.text()
            (txt_dir / f"{cid}.txt").write_text(text, encoding="utf-8")
            title_m = TITLE_RE.search(raw.decode("utf-8", "ignore"))
            rows.append({
                "id": cid,
                "source": "ccgp_contract",
                "url": url,
                "title": title_m.group(1).strip() if title_m else "",
                "license": "中国政府采购网·法定公开信息",
                "sha256": __import__("hashlib").sha256(raw).hexdigest(),
                "txt_chars": len(text),
            })
            if (n + 1) % 20 == 0:
                print(f"fetched {n + 1}/{len(ids)}")
            time.sleep(0.4)

    rows += manifest_cuad(root)
    with open(root / "manifest.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f, fieldnames=["id", "source", "url", "title", "license",
                           "sha256", "txt_chars"])
        writer.writeheader()
        writer.writerows(rows)
    ccgp_n = sum(1 for r in rows if r["source"] == "ccgp_contract")
    print(f"manifest rows: {len(rows)} (ccgp={ccgp_n})")


if __name__ == "__main__":
    main()
