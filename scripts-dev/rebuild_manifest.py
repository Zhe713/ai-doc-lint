"""扫描语料目录重建 manifest.csv：ccgp html/txt + cuad txt。"""

import csv
import hashlib
import re
import sys
from pathlib import Path

TITLE_RE = re.compile(r"<title>(.*?)</title>", re.S)


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def main() -> None:
    root = Path(sys.argv[1])
    rows: list[dict] = []

    ccgp_dir = root / "ccgp"
    if ccgp_dir.exists():
        for path in sorted(ccgp_dir.glob("*.txt")):
            data = path.read_bytes()
            cid = path.stem
            rows.append({
                "id": cid,
                "source": "ccgp_contract",
                "url": (f"http://htgs.ccgp.gov.cn/GS8/contractpublish/detail/"
                        f"{cid}?contractSign=0"),
                "title": cid,
                "license": "中国政府采购网·法定公开信息",
                "sha256": sha(data),
                "txt_chars": len(data.decode("utf-8", "ignore")),
            })

    tpl_dir = root / "templates"
    if tpl_dir.exists():
        for path in sorted(tpl_dir.glob("*.pdf")):
            data = path.read_bytes()
            rows.append({
                "id": path.stem,
                "source": "official_template",
                "url": "http://shujj.xjbt.gov.cn/upload/resources/file/"
                       "2025/07/16/593672.pdf",
                "title": path.stem,
                "license": "国家机关发布的示范文本·公开文件",
                "sha256": sha(data),
                "txt_chars": len(data),
            })

    cuad_dir = root / "cuad"
    if cuad_dir.exists():
        for path in sorted(cuad_dir.glob("*.txt")):
            data = path.read_bytes()
            rows.append({
                "id": path.stem,
                "source": "cuad",
                "url": "https://github.com/The-Atticus-Project/cuad",
                "title": path.stem,
                "license": "CC BY 4.0 (The Atticus Project)",
                "sha256": sha(data),
                "txt_chars": len(data.decode("utf-8", "ignore")),
            })

    with open(root / "manifest.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f, fieldnames=["id", "source", "url", "title", "license",
                           "sha256", "txt_chars"])
        writer.writeheader()
        writer.writerows(rows)

    ccgp = sum(1 for r in rows if r["source"] == "ccgp_contract")
    tpl = sum(1 for r in rows if r["source"] == "official_template")
    print(f"manifest rows: {len(rows)} (ccgp={ccgp}, templates={tpl}, "
          f"cuad={len(rows) - ccgp - tpl})")


if __name__ == "__main__":
    main()
