# -*- coding: utf-8 -*-
"""D-2 修复回填：专项核查结论 + 前端加固修复（预刷新/失败引导），更新 JSON 与 HTML。"""
import json

BASE = r"D:\projects\ai-doc-lint\ux-review"
JSON_PATH = BASE + r"\ai-doc-lint-ux-review.json"
HTML_PATH = BASE + r"\ai-doc-lint-新用户视角体验测试报告.html"

with open(JSON_PATH, encoding="utf-8") as f:
    doc = json.load(f)

# ---- 1) D-2 fix 更新为已修复 ----
d2 = next(i for i in doc["retest_findings"] if i["id"] == "D-2")
d2["severity"] = "已修复"
d2["detail"] = (
    "ACCESS_TOKEN_EXPIRE_MINUTES=15。会话停留 >15 分钟后发送文档助手消息返回 401，"
    "nginx 未见 /auth/refresh 重试请求；刷新页面后自动续期恢复。"
    "专项核查：登录/刷新链路代码完整（store 双 token 恢复、401 拦截器静默刷新、"
    "后端 refresh 轮换正常、SECRET_KEY 固定）；干净环境 1 分钟过期实测自动刷新成功，"
    "确认旧环境偶发（容器重建+页面长驻边界）。"
    "同时发现体验缺口：刷新失败时仅清 token 无任何用户引导（页面静默，只能整页重载）。"
)
d2["fix"] = {
    "change": (
        "前端加固三处：① auth store 新增 expires_at 过期时间追踪（登录/刷新时记录并持久化），"
        "新增 refreshIfExpiringSoon 预刷新方法；② MainLayout 挂载定时检查（每 60 秒，"
        "仅当剩余有效期 <2 分钟才真正发起刷新请求）与 visibilitychange 标签页切回检查；"
        "③ client.ts 401 静默刷新失败时 ElMessage 提示“登录已过期，请重新登录”"
        "并跳转 /login?redirect=原页面（原来静默清 token 无引导）。"
    ),
    "improve": (
        "token 过期前自动续期，页面内操作不再出现 401 卡死；刷新失败时用户收到明确提示"
        "并回到登录页，消除“整页重载才恢复”的死界面体验。"
    ),
    "optimize": (
        "预刷新零开销：定时器仅本地计算（0 请求），仅临过期才发一次 refresh；"
        "不引入额外模型/接口调用，不砍任何技术能力。"
    ),
    "verified": (
        "1 分钟有效期实测：过期后页面内选文档正常（自动刷新恢复，14:59/15:03）；"
        "预刷新实测：1 分钟 token 登录后停留 3 分钟页面操作始终正常（自动续期，15:10）；"
        "恢复 15 分钟（expires_in=900 冒烟通过）+ 浏览器 F5 回归正常。"
    ),
}

# ---- 2) 结论与统计更新 ----
doc["retest_summary"]["result"] = (
    "P1-4 补测通过（条号条款定位+归一化）；P2-7/P3-1 注册校验通过；"
    "发现并修复模型缓存权限故障（D-1）；优化模型重复下载（D-3）；"
    "D-2 401 刷新观察项专项核查并完成前端加固（预刷新+失败引导）。"
)
doc["report"]["conclusion"] = (
    "24 项体验问题全部修复并回归验证；补测轮完成 P1-4 深度修复实证与全链路回归，"
    "另发现并修复 1 项部署级故障（模型缓存权限）、1 项优化（模型重复下载）、"
    "D-2 401 刷新时序完成专项核查与前端加固（全部收口）。"
)
doc["report"]["severity_summary"]["fixed"] = 26  # 24 + D-1 + D-2
doc["report"]["severity_summary"]["remaining"] = 0  # D-2 已修复

with open(JSON_PATH, "w", encoding="utf-8") as f:
    json.dump(doc, f, ensure_ascii=False, indent=2)

# ---- 3) HTML 更新 D-2 行 ----
with open(HTML_PATH, encoding="utf-8") as f:
    html = f.read()

old_d2_row = (
    "<tr><td style=\"border:1px solid #c7d8f2;padding:6px;\">D-2</td>"
    "<td style=\"border:1px solid #c7d8f2;padding:6px;\">观察项</td>"
    "<td style=\"border:1px solid #c7d8f2;padding:6px;\">access token 15 分钟过期后页面内未自动刷新（401 后无 refresh 请求）；整页重载后自动恢复。待专项核查刷新链路时序。</td>"
    "<td style=\"border:1px solid #c7d8f2;padding:6px;color:#a15c00;\">已记录待核</td></tr>"
)
new_d2_row = (
    "<tr><td style=\"border:1px solid #c7d8f2;padding:6px;\">D-2</td>"
    "<td style=\"border:1px solid #c7d8f2;padding:6px;\">已修复</td>"
    "<td style=\"border:1px solid #c7d8f2;padding:6px;\">专项核查：链路代码完整，干净环境实测自动刷新正常（旧环境偶发）；并加固体验——①登录/刷新记录过期时间；②到期前自动预刷新（每 60 秒检查，仅临期发请求，零开销）；③刷新失败时明确提示并跳转登录页（不再静默死界面）。</td>"
    "<td style=\"border:1px solid #c7d8f2;padding:6px;color:#0a7d32;\">已修复并实证</td></tr>"
)
if old_d2_row not in html:
    raise SystemExit("old D-2 row not found")
html = html.replace(old_d2_row, new_d2_row)

note_anchor = "P1-4 深度修复：L3 search_in_document"
if note_anchor in html:
    extra = (
        "<p style=\"margin:8px 0 0;font-size:13px;color:#555;\">"
        "D-2 深度修复：401 刷新专项核查（链路完整、干净环境实测自动刷新成功，原观察为旧环境偶发），"
        "前端加固——token 过期前自动预刷新 + 刷新失败明确提示跳登录，实测 1 分钟有效期下页面长期操作无 401。</p>"
    )
    html = html.replace(note_anchor, extra + note_anchor)

with open(HTML_PATH, "w", encoding="utf-8") as f:
    f.write(html)

print("d2 backfill ok: json + html")
