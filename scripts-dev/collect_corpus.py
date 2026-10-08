"""采集真实公开合同语料并生成 manifest。

来源：
  1. 中国政府采购网·合同公告（htgs.ccgp.gov.cn）：法定公开的真实合同 HTML，
     原样保存 html，并做确定性 HTML→txt 转换（非 AI 生成）；
  2. CUAD（The Atticus Project，GitHub）：510 份真实商业合同 txt，CC BY 4.0。

用法（容器内）：
    python collect_corpus.py /corpus --pages 5
其中 /corpus 为挂载或后续 docker cp 的语料根目录。
"""

import csv
import hashlib
import html as html_mod
import re
import sys
import time
from html.parser import HTMLParser
from pathlib import Path

import httpx

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")
BASE = "http://htgs.ccgp.gov.cn/GS8/contractpublish"
DETAIL_RE = re.compile(r'href="\./detail/([0-9a-f\-]+)\?contractSign=0"')
TITLE_RE = re.compile(r"<title>(.*?)</title>", re.S)


class TextExtractor(HTMLParser):
    """确定性 HTML→文本：去脚本/样式，块级标签换行。"""

    BLOCK = {"p", "div", "br", "tr", "li", "h1", "h2", "h3", "h4",
             "table", "section"}
    SKIP = {"script", "style", "head"}

    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag, attrs) -> None:
        if tag in self.SKIP:
            self._skip_depth += 1
        if tag in self.BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag) -> None:
        if tag in self.SKIP and self._skip_depth:
            self._skip_depth -= 1
        if tag in self.BLOCK:
            self.parts.append("\n")

    def handle_data(self, data) -> None:
        if not self._skip_depth:
            self.parts.append(data)

    def text(self) -> str:
        out = html_mod.unescape("".join(self.parts))
        out = re.sub(r"[ \t]+", " ", out)
        out = re.sub(r"\n\s*\n+", "\n\n", out)
        return out.strip()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def fetch(client: httpx.Client, url: str, tries: int = 3) -> bytes:
    last: Exception | None = None
    for i in range(tries):
        try:
            r = client.get(url, timeout=30)
            r.raise_for_status()
            return r.content
        except Exception as exc:  # noqa: BLE001
            last = exc
            time.sleep(1.5 * (i + 1))
    raise RuntimeError(f"fetch failed {url}: {last}")


def collect_ccgp(root: Path, pages: int) -> list[dict]:
    html_dir = root / "ccgp" / "html"
    txt_dir = root / "ccgp" / "txt"
    html_dir.mkdir(parents=True, exist_ok=True)
    txt_dir.mkdir(parents=True, exist_ok=True)

    rows: list[dict] = []
    with httpx.Client(headers={
        "User-Agent": UA,
        "Accept": ("text/html,application/xhtml+xml,application/xml;q=0.9,"
                   "*/*;q=0.8"),
        "Referer": f"{BASE}/search",
        "Origin": "http://htgs.ccgp.gov.cn",
    }, follow_redirects=True) as c:
        ids: list[str] = []
        for page in range(1, pages + 1):
            try:
                r = c.post(f"{BASE}/search",
                           data={"currentPage": str(page - 1)}, timeout=30)
                r.raise_for_status()
                content = r.text
            except Exception as exc:  # noqa: BLE001
                print(f"search page {page} failed, skipping: {exc}")
                continue
            found = DETAIL_RE.findall(content)
            ids.extend(found)
            print(f"search page {page}: {len(found)} links, "
                  f"first={found[0] if found else '-'}")
            time.sleep(2.5)

        ids = list(dict.fromkeys(ids))
        print(f"total detail ids: {len(ids)}")

        for n, cid in enumerate(ids):
            url = f"{BASE}/detail/{cid}?contractSign=0"
            try:
                raw = fetch(c, url)
            except RuntimeError as exc:
                print(f"detail {cid} failed, skipping: {exc}")
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
                "title": (title_m.group(1).strip() if title_m else ""),
                "license": "中国政府采购网·法定公开信息",
                "sha256": sha256_bytes(raw),
                "txt_chars": len(text),
            })
            if (n + 1) % 10 == 0:
                print(f"  fetched {n + 1}/{len(ids)}")
            time.sleep(0.6)
    return rows


def manifest_cuad(root: Path) -> list[dict]:
    cuad_dir = root / "cuad"
    rows: list[dict] = []
    if not cuad_dir.exists():
        return rows
    for path in sorted(cuad_dir.glob("*.txt")):
        data = path.read_bytes()
        rows.append({
            "id": path.stem,
            "source": "cuad",
            "url": "https://github.com/The-Atticus-Project/cuad",
            "title": path.stem,
            "license": "CC BY 4.0 (The Atticus Project)",
            "sha256": sha256_bytes(data),
            "txt_chars": len(data.decode("utf-8", "ignore")),
        })
    return rows


def main() -> None:
    root = Path(sys.argv[1])
    pages = int(sys.argv[2]) if len(sys.argv) > 2 else 5
    root.mkdir(parents=True, exist_ok=True)

    ccgp_rows = collect_ccgp(root, pages)
    cuad_rows = manifest_cuad(root)
    rows = ccgp_rows + cuad_rows

    manifest = root / "manifest.csv"
    with open(manifest, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f, fieldnames=["id", "source", "url", "title", "license",
                           "sha256", "txt_chars"])
        writer.writeheader()
        writer.writerows(rows)

    print(f"manifest rows: {len(rows)} "
          f"(ccgp={len(ccgp_rows)}, cuad={len(cuad_rows)})")
    print("written", manifest)


if __name__ == "__main__":
    main()
