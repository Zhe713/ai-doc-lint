"""扫描件 OCR 端到端：合成图片型 PDF → 首次挂起 ocr_required → 人工选 OCR 重试 → parsed。

在 api 容器内运行（需先把字体放到 /tmp/msyh.ttc）：
    python /tmp/ocr_e2e.py
"""
import io
import time

import httpx
from PIL import Image, ImageDraw, ImageFont

BASE = "http://localhost:8000/api/v1"
ADMIN_USER = "boss_admin"
ADMIN_PWD = "AdminPass123"


def make_scan_pdf() -> bytes:
    img = Image.new("RGB", (1240, 1754), "white")
    draw = ImageDraw.Draw(img)
    font_big = ImageFont.truetype("/tmp/msyh.ttc", 56)
    font_mid = ImageFont.truetype("/tmp/msyh.ttc", 40)
    lines = [
        "货物买卖合同",
        "甲方：石家庄测试科技有限公司",
        "乙方：北京示例贸易有限公司",
        "第一条 标的物与数量",
        "甲方向乙方供应测试设备共计一百套。",
        "第二条 合同金额",
        "本合同总金额为人民币壹拾万元整。",
        "第三条 交付时间",
        "乙方应于收到预付款后三十日内完成交付。",
    ]
    y = 120
    for i, line in enumerate(lines):
        font = font_big if i == 0 else font_mid
        draw.text((120, y), line, fill="black", font=font)
        y += 150 if i == 0 else 120
    buf = io.BytesIO()
    img.save(buf, "PDF", resolution=150.0)
    return buf.getvalue()


def main():
    r = httpx.post(f"{BASE}/auth/login", json={"username": ADMIN_USER, "password": ADMIN_PWD})
    r.raise_for_status()
    headers = {"Authorization": f"Bearer {r.json()['access_token']}"}

    pdf = make_scan_pdf()
    print("scan.pdf bytes:", len(pdf))
    r = httpx.post(
        f"{BASE}/documents/upload",
        headers=headers,
        files={"files": ("scan.pdf", io.BytesIO(pdf), "application/pdf")},
        timeout=60,
    )
    print("upload:", r.status_code)
    r.raise_for_status()
    tid = r.json()["tasks"][0]["task_id"]

    # 等待闸门
    for _ in range(60):
        d = httpx.get(f"{BASE}/tasks/{tid}", headers=headers).json()
        if d["status"] == "awaiting_decision":
            break
        if d["status"] in ("parsed", "failed"):
            break
        time.sleep(2)
    print("after attempt0:", d["status"], d.get("gate_reason"))
    assert d["status"] == "awaiting_decision" and d["gate_reason"] == "ocr_required"

    # 人工选择 OCR 重试
    r = httpx.post(
        f"{BASE}/tasks/{tid}/decision", headers=headers, json={"action": "retry_ocr"}
    )
    print("decision:", r.status_code)
    r.raise_for_status()

    for _ in range(90):
        d = httpx.get(f"{BASE}/tasks/{tid}", headers=headers).json()
        if d["status"] in ("parsed", "failed", "awaiting_decision"):
            break
        print("  ", d["status"])
        time.sleep(2)
    print("final:", d["status"], d.get("stats"))
    assert d["status"] == "parsed", f"OCR 后未成功: {d}"
    assert d["stats"] and d["stats"].get("ocr_used") is True

    pv = httpx.get(f"{BASE}/tasks/{tid}/preview", headers=headers).json()
    text = pv["plaintext"]
    print("---- preview ----")
    print(text[:500])
    assert "买卖" in text or "合同" in text, "OCR 未识别出关键文字"
    print("OCR E2E OK")


if __name__ == "__main__":
    main()

