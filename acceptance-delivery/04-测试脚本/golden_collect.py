# -*- coding: utf-8 -*-
"""从市场监管总局合同示范文本库批量采集 golden 集合同（官方公开数据）。
按类型配比：买卖16 / 劳务服务8 / 租赁6 / 建设4 / 运输公用4 / 通用2。
"""
import json
import os
import re
import sys
import urllib.parse
import urllib.request

BASE = "https://htsfwb.samr.gov.cn"
OUT_DIR = r"D:\projects\ai-doc-lint\corpus\acceptance_golden"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

# 类别 -> (配额, 搜索关键词列表)
PLAN = {
    "sale": (16, ["工业品买卖合同", "钢材买卖", "化肥买卖合同", "农药买卖合同", "粮食买卖合同",
                  "棉花买卖合同", "木材买卖", "煤炭买卖合同", "水泥买卖合同", "家具买卖合同",
                  "汽车买卖合同", "二手车买卖合同", "农副产品买卖合同", "烟花爆竹", "民用爆破器材买卖合同", "生鲜乳"]),
    "labor": (8, ["劳务分包合同", "委托合同", "承揽合同", "加工合同", "定作合同", "修缮修理合同",
                  "居间合同", "养老机构服务合同"]),
    "lease": (6, ["房屋租赁合同", "建筑施工物资租赁", "柜台租赁", "人民防空工程租赁",
                  "农村土地经营权出租", "农村土地经营权入股"]),
    "build": (4, ["建设工程施工合同", "建设工程监理合同", "建设工程设计合同", "家庭居室装饰装修"]),
    "trans": (4, ["水路货物运输合同", "铁路货物运输合同", "航次租船合同", "城市供用水合同"]),
    "general": (2, ["仓储合同", "保管合同"]),
}

CAT_NAMES = {"sale": "买卖", "labor": "劳务服务", "lease": "租赁",
             "build": "建设", "trans": "运输公用", "general": "通用商业"}


def api_search(keyword, page=1):
    q = urllib.parse.quote(keyword)
    url = f"{BASE}/api/content/SearchTemplates?key={q}&loc=false&p={page}"
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def download_pdf(doc_id, out_path):
    url = f"{BASE}/api/File/DownTemplate?id={doc_id}&type=2"
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=90) as resp:
        data = resp.read()
    if data[:5] != b"%PDF-":
        raise RuntimeError(f"非 PDF 响应: {data[:20]!r}")
    with open(out_path, "wb") as f:
        f.write(data)
    return len(data)


def clean_name(title):
    t = re.sub(r"[（(].*?[)）]", "", title)          # 去括号后缀
    t = re.sub(r"[\\/:*?\"<>|\s]+", "_", t)
    return t.strip("_")[:40]


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    manifest = []
    used_ids = set()

    for cat, (quota, keywords) in PLAN.items():
        picked = []
        for kw in keywords:
            if len(picked) >= quota:
                break
            try:
                data = api_search(kw)
            except Exception as e:
                print(f"[skip] {kw}: {e}")
                continue
            best = None
            for item in data.get("Data", []):
                if item["Id"] in used_ids:
                    continue
                title = item.get("Title", "")
                if kw in title or title.startswith(kw):
                    best = item
                    break
            if best is None and data.get("Data"):
                best = data["Data"][0]
            if best and best["Id"] not in used_ids:
                picked.append(best)
                used_ids.add(best["Id"])

        print(f"[{cat}] {CAT_NAMES[cat]}: 命中 {len(picked)}/{quota}")
        for item in picked[:quota]:
            doc_id, title = item["Id"], item["Title"]
            fname = f"{cat}_{len([m for m in manifest if m['category']==cat])+1:02d}_{clean_name(title)}.pdf"
            fpath = os.path.join(OUT_DIR, fname)
            try:
                size = download_pdf(doc_id, fpath)
                manifest.append({"id": doc_id, "title": title, "category": cat,
                                 "file": fname, "size": size, "source": "samr_contract_lib"})
                print(f"  ok {fname} ({size}B)")
            except Exception as e:
                print(f"  FAIL {title}: {e}")

    with open(os.path.join(OUT_DIR, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    print(f"\n总计: {len(manifest)} 份")
    from collections import Counter
    print(Counter(m["category"] for m in manifest))


if __name__ == "__main__":
    main()
