# -*- coding: utf-8 -*-
"""从官方正文半自动构造 golden ground truth（40 份）。
字段：编号/违约金/争议解决/管辖/金额格式/模板完整性/检索与对话期望。
输出 ground_truth.json，之后人工抽样核验。
"""
import json
import os
import re

GOLDEN_DIR = r"D:\projects\ai-doc-lint\corpus\acceptance_golden"
TEXT_DIR = os.path.join(GOLDEN_DIR, "texts")

# 必备条款（民法典第 470 条常用必备要素）
REQUIRED = {
    "主体": ["甲方", "乙方", "出卖人", "买受人", "出租人", "承租人", "发包人", "承包人", "委托人", "受托人"],
    "标的": ["产品", "货物", "标的", "服务", "房屋", "工程", "租赁物", "设备"],
    "数量": ["数量", "吨", "台", "套", "件", "公斤", "立方米"],
    "价款": ["价款", "金额", "价格", "租金", "费用", "报酬", "总价"],
    "履行期限": ["履行期限", "交货", "交付", "工期", "合同期", "期限", "时间"],
    "违约责任": ["违约", "违约金", "赔偿"],
    "争议解决": ["争议", "仲裁", "诉讼", "协商", "管辖"],
}

CAT_NAMES = {"sale": "买卖", "labor": "劳务服务", "lease": "租赁",
             "build": "建设", "trans": "运输公用", "general": "通用商业"}


def load_text(fname):
    p = os.path.join(TEXT_DIR, fname.replace(".pdf", ".txt"))
    with open(p, encoding="utf-8") as f:
        return f.read()


def extract(text):
    out = {}
    # 编号
    m = re.search(r"GF\s*[—\-—]\s*\d{4}\s*[—\-]\s*\d{3,4}", text)
    out["编号"] = m.group(0).replace(" ", "") if m else None
    # 违约金比例（含留白 % 格式）
    ms = re.findall(r"违约金[^。；\n]{0,40}?((?:\d+(?:\.\d+)?\s*)?%|\d+\s*%)", text)
    out["违约金比例"] = ms[:3] if ms else []
    # 违约金条款原文片段（跨行/表格取 160 字窗口）
    i = text.find("违约金")
    if i >= 0:
        frag = text[max(0, i - 30):i + 130].replace("\n", " ").strip()
        out["违约金条款"] = frag[:160]
    else:
        out["违约金条款"] = None
    # 争议解决
    ms = re.findall(r"[^\n]*(?:协商解决|仲裁委员会仲裁|依法向人民法院起诉)[^\n]{0,60}", text)
    out["争议解决"] = [x.strip()[:100] for x in ms[:3]]
    # 金额格式（大写提示）
    m = re.search(r"[^\n]*(?:金额总计|价款总计|总价)[^\n]{0,40}", text)
    out["金额格式"] = m.group(0).strip()[:100] if m else None
    # 管辖
    m = re.search(r"[^\n]*(?:管辖|签订地点)[^\n]{0,60}", text)
    out["管辖"] = m.group(0).strip()[:100] if m else None
    # 模板完整性
    missing = []
    for k, kws in REQUIRED.items():
        hit = any(kw in text for kw in kws)
        if not hit:
            missing.append(k)
    out["模板缺失"] = missing
    # 待填项（示范文本留白）
    blanks = len(re.findall(r"(?:填写|选择|空白|____|_____|〔 )", text))
    out["留白项数"] = blanks
    return out


def build_queries(cat, text, title):
    """按类型构造检索/对话期望。"""
    qs = []
    if "违约金" in text:
        qs.append({"query": "违约金比例是多少", "expect_type": "条款", "note": "违约责任条款"})
    if "争议" in text:
        qs.append({"query": "争议解决方式", "expect_type": "条款", "note": "争议解决条款"})
    if any(k in text for k in ["付款", "价款", "货款", "租金"]):
        qs.append({"query": "付款条件", "expect_type": "条款", "note": "付款/价款条款"})
    if any(k in text for k in ["交付", "交货"]):
        qs.append({"query": "交付标准", "expect_type": "条款", "note": "交付条款"})
    return qs[:3]


def main():
    with open(os.path.join(GOLDEN_DIR, "manifest.json"), encoding="utf-8") as f:
        manifest = json.load(f)
    gt = []
    for item in manifest:
        text = load_text(item["file"])
        rec = {
            "file": item["file"],
            "title": item["title"],
            "category": CAT_NAMES.get(item["category"], item["category"]),
            "source": "samr_contract_lib",
            "fields": extract(text),
            "queries": build_queries(item["category"], text, item["title"]),
            "status": "auto",
        }
        gt.append(rec)
    out = os.path.join(GOLDEN_DIR, "ground_truth.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(gt, f, ensure_ascii=False, indent=2)
    ok = sum(1 for r in gt if not r["fields"]["模板缺失"])
    print(f"total={len(gt)} 模板完整={ok} 输出={out}")


if __name__ == "__main__":
    main()
