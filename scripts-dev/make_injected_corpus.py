# -*- coding: utf-8 -*-
"""构造「已知错误注入」评测集：每份合同都埋入可枚举的错误，真值精确到条。

与 corpus/acceptance_golden（真实合同、自动近似真值）互补：
- acceptance_golden 回答「在真实语料上表现如何」（真值近似）；
- injected_errors 回答「埋进去的错误能不能查出来」（真值是人工标注，精确）。

生成物：
  corpus/injected_errors/*.txt / *.pdf / *.docx   8 份合同，覆盖 txt/pdf/docx 三种载体
  corpus/injected_errors/ground_truth.json       逐条错误真值（checker + rule_id + 关键词）

用法：
  python scripts-dev/make_injected_corpus.py
"""

from __future__ import annotations

import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.environ.get("INJECTED_OUT") or os.path.join(ROOT, "corpus", "injected_errors")

# ---------------------------------------------------------------- 合同正文模板

HEAD = """合同编号：{no}
合同名称：{title}
甲方：{party_a}
乙方：{party_b}
合同签订日期：{sign_date}
"""

BODY = """
合同标的：{subject}
数量：{qty} 台
主要标的单价：{price} 元
合同金额：{total} 元
合同金额（大写）：{upper}
交付地点：{deliver_place}
交付日期：{deliver_date}
付款方式：{pay_method}

一、合同标的与数量
乙方按本合同约定的规格型号向甲方提供{subject}，数量{qty}台，具体规格以附件清单为准。

（一）质量标准
乙方交付的标的物应符合国家标准及本合同附件约定的技术要求，并随货提供合格证明文件。

二、价款与支付
本合同价款为{total}元，已包含税费、运输费及装卸费用。甲方按约定的付款方式支付款项，乙方应开具增值税专用发票。

三、履行期限、地点和方式
乙方应于{deliver_date}前将全部标的物送达{deliver_place}，并完成安装调试。甲方应在到货验收合格后按约定付款。

四、违约责任
任何一方不履行本合同义务的，应向守约方承担违约责任并赔偿损失，违约金按合同金额的百分之五计算。

五、争议解决
因本合同发生的争议，双方应协商解决；协商不成的，提交{arbitration}仲裁委员会仲裁。

六、其他
本合同自双方法定代表人或授权代表签字并盖章之日起生效，一式两份，双方各执一份。
"""

CLEAN = dict(
    no="HT-2024-0100",
    title="办公设备采购合同",
    party_a="北京示例科技有限公司",
    party_b="上海样例办公设备有限公司",
    sign_date="2024年5月1日",
    subject="商用激光打印机",
    qty="100",
    price="1,200.00",
    total="120,000.00",
    upper="人民币壹拾贰万元整",
    deliver_place="北京市海淀区示例路1号",
    deliver_date="2024年6月1日",
    pay_method="验收合格后30日内电汇支付",
    arbitration="北京",
)


def build_clean() -> str:
    return HEAD.format(**CLEAN) + BODY.format(**CLEAN)


def build_typo() -> str:
    """3 处错别字：签定/陪偿/防碍（均为混淆集内词对）。"""
    text = build_clean()
    text = text.replace("合同签订日期", "合同签定日期")
    text = text.replace("承担违约责任并赔偿损失", "承担违约责任并陪偿损失")
    text = text.replace("并随货提供合格证明文件", "不得防碍甲方验收，并随货提供合格证明文件")
    return text


def build_clause_missing() -> str:
    """删掉「违约责任」「争议解决」两节，且不留弱信号词。"""
    text = build_clean()
    text = text.replace(
        "四、违约责任\n任何一方不履行本合同义务的，应向守约方承担违约责任并赔偿损失，违约金按合同金额的百分之五计算。\n\n",
        "",
    )
    text = text.replace(
        "五、争议解决\n因本合同发生的争议，双方应协商解决；协商不成的，提交北京仲裁委员会仲裁。\n\n",
        "",
    )
    text = text.replace("六、其他", "四、其他")
    return text


def build_cross_amount() -> str:
    """大写与小写不一致：小写 120,000.00，大写写成壹拾万元整（=100,000）。"""
    text = build_clean()
    return text.replace("人民币壹拾贰万元整", "人民币壹拾万元整")


def build_cross_formula() -> str:
    """单价×数量≠总价：1,200×100=120,000，但合同金额写成 130,000.00。

    大写金额同步改成壹拾叁万元整，保证「大写=小写」，让本篇只剩一处错误
    （勾稽不成立）。否则会连带触发 upper_vs_lower_amount，把一次注入变成两个错误，
    评测得不出干净的单错误召回。
    """
    text = build_clean()
    text = text.replace("合同金额：120,000.00 元", "合同金额：130,000.00 元")
    text = text.replace("本合同价款为120,000.00元", "本合同价款为130,000.00元")
    text = text.replace("人民币壹拾贰万元整", "人民币壹拾叁万元整")
    return text


def build_cross_date() -> str:
    """签订日期晚于交付日期：签订 2024-06-01，交付 2024-05-01。"""
    text = build_clean()
    text = text.replace("合同签订日期：2024年5月1日", "合同签订日期：2024年6月1日")
    text = text.replace("交付日期：2024年6月1日", "交付日期：2024年5月1日")
    text = text.replace("乙方应于2024年6月1日前", "乙方应于2024年5月1日前")
    return text


def build_format_heading_skip() -> str:
    """标题层级跳级：一、之后直接出现 1.（缺 （一） 层）。"""
    text = build_clean()
    text = text.replace("（一）质量标准", "1. 质量标准")
    return text


# ---------------------------------------------------------------- 文件写出

def write_txt(name: str, text: str) -> None:
    with open(os.path.join(OUT, name), "w", encoding="utf-8") as f:
        f.write(text)


def write_pdf(name: str, text: str, *, a3: bool = False) -> None:
    """用 reportlab + STSong-Light（无需外部字体）把文本排成 PDF。"""
    from reportlab.lib.pagesizes import A3, A4
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.cidfonts import UnicodeCIDFont
    from reportlab.pdfgen import canvas

    try:
        pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
    except Exception:
        pass  # 已注册

    size = A3 if a3 else A4
    c = canvas.Canvas(os.path.join(OUT, name), pagesize=size)
    width, height = size
    c.setFont("STSong-Light", 10.5)
    y = height - 60
    for raw in text.splitlines():
        if y < 60:
            c.showPage()
            c.setFont("STSong-Light", 10.5)
            y = height - 60
        c.drawString(56, y, raw)
        y -= 17
    c.save()


def write_docx(name: str, text: str, *, bad_font: bool = True,
               no_indent: bool = True) -> None:
    """生成 docx：故意用非白名单字体 + 不设首行缩进，触发格式检查。

    纸张显式设成 A4：python-docx 默认模板是 US Letter（216×279mm），
    不设的话格式检查会多报一条「非 A4 纸张」，把单错误注入变成两个问题。
    """
    from docx import Document as DocxDocument
    from docx.oxml.ns import qn
    from docx.shared import Mm, Pt

    doc = DocxDocument()
    for section in doc.sections:
        section.page_width = Mm(210)
        section.page_height = Mm(297)
    for raw in text.splitlines():
        p = doc.add_paragraph()
        run = p.add_run(raw)
        if bad_font and raw.strip():
            run.font.name = "微软雅黑"
            run.font.size = Pt(12)
            run._element.rPr.rFonts.set(qn("w:eastAsia"), "微软雅黑")
        if no_indent:
            p.paragraph_format.first_line_indent = None
    doc.save(os.path.join(OUT, name))


# ---------------------------------------------------------------- 真值

GT: list[dict] = [
    {
        "file": "INJ-01_clean.txt", "desc": "对照组：完全合规，不应用报出任何问题",
        "expect": [],
    },
    {
        "file": "INJ-02_typo.txt", "desc": "注入 3 处错别字：签定/陪偿/防碍",
        "expect": [
            {"type": "typo", "checker": "typo", "rule_id": "typo.correction",
             "keyword": "签定", "note": "签定→签订"},
            {"type": "typo", "checker": "typo", "rule_id": "typo.correction",
             "keyword": "陪偿", "note": "陪偿→赔偿"},
            {"type": "typo", "checker": "typo", "rule_id": "typo.correction",
             "keyword": "防碍", "note": "防碍→妨碍"},
        ],
    },
    {
        "file": "INJ-03_clause_missing.txt", "desc": "删除违约责任、争议解决两节",
        "expect": [
            {"type": "clause", "checker": "clause", "rule_id": "clause.breach",
             "keyword": "违约责任", "note": "违约责任缺失"},
            {"type": "clause", "checker": "clause", "rule_id": "clause.dispute",
             "keyword": "争议解决", "note": "争议解决缺失"},
        ],
    },
    {
        "file": "INJ-04_cross_amount.txt", "desc": "金额大写与小写不一致（120,000 vs 壹拾万）",
        "expect": [
            {"type": "cross", "checker": "cross", "rule_id": "upper_vs_lower_amount",
             "also_rule_ids": ["clause.amount.consistency"],
             "also_keywords": ["大写"], "note": "大小写金额不一致"},
        ],
    },
    {
        "file": "INJ-05_cross_formula.txt", "desc": "单价×数量≠总价（1,200×100 vs 130,000）",
        "expect": [
            {"type": "cross", "checker": "cross", "rule_id": "price_times_qty_total",
             "also_keywords": ["单价"], "note": "勾稽不成立"},
        ],
    },
    {
        "file": "INJ-06_cross_date.pdf", "desc": "PDF 载体：签订日期晚于交付日期",
        "expect": [
            {"type": "cross", "checker": "cross", "rule_id": "sign_before_delivery",
             "also_keywords": ["签订日期", "交付日期"], "note": "日期倒挂"},
        ],
    },
    {
        "file": "INJ-07_format_a3.pdf", "desc": "PDF 载体：A3 纸张 + 标题层级跳级",
        "expect": [
            {"type": "format", "checker": "format", "rule_id": "format.page.size",
             "note": "非 A4 纸张"},
            {"type": "format", "checker": "format", "rule_id": "format.heading.sequence",
             "note": "标题跳级"},
        ],
    },
    {
        "file": "INJ-08_format.docx", "desc": "docx 载体：非白名单字体 + 无首行缩进",
        "expect": [
            {"type": "format", "checker": "format", "rule_id": "format.font.body",
             "note": "字体不在白名单"},
            {"type": "format", "checker": "format", "rule_id": "format.paragraph.indent",
             "note": "首行未缩进"},
        ],
    },
]


def main() -> None:
    os.makedirs(OUT, exist_ok=True)

    write_txt("INJ-01_clean.txt", build_clean())
    write_txt("INJ-02_typo.txt", build_typo())
    write_txt("INJ-03_clause_missing.txt", build_clause_missing())
    write_txt("INJ-04_cross_amount.txt", build_cross_amount())
    write_txt("INJ-05_cross_formula.txt", build_cross_formula())
    write_pdf("INJ-06_cross_date.pdf", build_cross_date())
    write_pdf("INJ-07_format_a3.pdf", build_format_heading_skip(), a3=True)
    write_docx("INJ-08_format.docx", build_clean())

    payload = {
        "version": "1.1.0",
        "note": (
            "人工注入已知错误的评测集，真值逐条精确标注；用于证明检出能力，非拟合语料。"
            "keyword/also_rule_ids/also_keywords 声明等价命中口径：自定义规则包可能把 "
            "rule_id 改名，同一处错误也可能被多个检查器各自报出，这两种情况都不应算漏报或误报。"
        ),
        "files": GT,
    }
    with open(os.path.join(OUT, "ground_truth.json"), "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    total = sum(len(g["expect"]) for g in GT)
    print(f"写入 {len(GT)} 份文件到 {OUT}")
    print(f"期望检出错误共 {total} 条：", {
        t: sum(len(x["expect"]) for x in GT if x["file"].endswith(t)) or "-"
        for t in ("txt", "pdf", "docx")
    })
    for g in GT:
        print(f"  {g['file']:32s} {len(g['expect'])} 条  {g['desc']}")


if __name__ == "__main__":
    main()
