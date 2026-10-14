# -*- coding: utf-8 -*-
"""补测轮回填：P1-4 深度修复实证 + 3 项补测发现（缓存权限/401刷新观察/重复下载优化）。
更新 ux-review JSON，并在 HTML 报告插入「补测回填（2026-10-14）」小节。
"""
import json
import io
import re

BASE = r"D:\projects\ai-doc-lint\ux-review"
JSON_PATH = BASE + r"\ai-doc-lint-ux-review.json"
HTML_PATH = BASE + r"\ai-doc-lint-新用户视角体验测试报告.html"

with open(JSON_PATH, encoding="utf-8") as f:
    doc = json.load(f)

# ---- 1) P1-4 深度修复补充 ----
p14 = next(i for i in doc["issues"] if i["id"] == "P1-4")
p14["fix"] = {
    "status": "已修复（补测通过）",
    "change": (
        "补测实证失败后深挖：L3 助手 search_in_document 原为精确子串匹配，"
        "“第二条付款条件”匹配不到原文“第二条 付款条件”（带空格）。"
        "新增①条号条款定位（解析“第X条”→ 返回该条正文整段）；"
        "②空格归一化匹配兜底（去除全部空白再匹配）；"
        "同时保留 l1_rule 条号意图分流与“请确认条款位置”引导话术。"
    ),
    "improve": (
        "文档助手按条号提问可准确召回对应条款原文并给出风险分析。"
        "补测实证：问“第二条付款条件有没有风险”→ 准确引用“乙方交付货物后，"
        "甲方应当在30日内支付全部货款”并分析交付认定标准缺失、验收异议期缺失、"
        "一次性付款风险三点。"
    ),
    "optimize": "0 token 确定性逻辑增强，不引入额外模型调用。",
    "verified": "浏览器实测通过（uxuser/test_bad.txt，2026-10-14 12:45）",
}

# ---- 2) 新增补测发现项 ----
discoveries = [
    {
        "id": "D-1",
        "severity": "P0(已修复)",
        "title": "模型缓存目录权限：容器重建后语义检索 500",
        "detail": (
            "Dockerfile 以 appuser(uid10001) 运行，但 modelcache 卷挂载于 "
            "/root/.cache（/root 权限 700 仅 root 可进）→ 重建容器后 embedding "
            "模型不可达，/api/v1/search 报 PermissionError 500，文档助手 L3 检索、"
            "新文档向量化全部静默失效。"
        ),
        "fix": {
            "change": "docker-compose：api/worker 卷路径 /root/.cache→/home/appuser/.cache、"
                      "/root/.pycorrector→/home/appuser/.pycorrector，并注入 "
                      "HOME=/home/appuser、MODEL_CACHE_DIR=/home/appuser/.cache。",
            "improve": "语义检索恢复，真实合同与测试文档均可命中；pycorrector 错别字模型缓存同样解封。",
            "optimize": "不改代码只改部署配置，模型文件无需迁移（卷内容直接可见）。",
            "verified": "API 实测：/search 返回命中结果；浏览器文档助手条号提问召回成功。",
        },
    },
    {
        "id": "D-2",
        "severity": "观察项",
        "title": "access token 15 分钟过期，页面内未自动刷新（重载后恢复）",
        "detail": (
            "ACCESS_TOKEN_EXPIRE_MINUTES=15。会话停留 >15 分钟后发送文档助手消息返回 401，"
            "nginx 未见 /auth/refresh 重试请求；刷新页面后自动续期恢复。"
            "前端拦截器已有 401 静默刷新，但页面内（无整页刷新）触发路径待核。"
        ),
        "fix": {
            "change": "未改动（本轮记录观察项，待专项核查刷新链路时序）。",
            "improve": "明确已知边界：重载页面即可恢复；不影响已入库数据。",
            "optimize": "避免误改导致鉴权链路不稳，先定位再改。",
            "verified": "nginx 日志 2026-10-14 04:41:58 chat 401 后无 refresh 请求；F5 后恢复。",
        },
    },
    {
        "id": "D-3",
        "severity": "优化(已完成)",
        "title": "embedding 模型每次重启容器重复下载",
        "detail": (
            "snapshot_download 落盘结构为 cache_dir/models/<repo>/snapshots/<rev>，"
            "根目录无 config.json → 原 get_model 每次进程启动都重新 snapshot_download"
            "（本地命中但多余校验与 IO）。"
        ),
        "fix": {
            "change": "embedder.py：下载后把真实快照路径写入 repo_dir/.snapshot_path，"
                      "get_model/_download_model 优先读取标记，存在即直接加载。",
            "improve": "容器重启后首次检索零下载（实测 downloading 日志 0 次），启动更快、IO 更省。",
            "optimize": "仅加一个标记文件，不改模型加载路径与并发锁逻辑。",
            "verified": "重启 api 后 /search 正常返回且日志无 downloading embedding model。",
        },
    },
]
doc.setdefault("retest_findings", []).extend(discoveries)

# ---- 3) 结论与统计更新 ----
doc.setdefault("retest_summary", {
    "date": "2026-10-14",
    "scope": "P1-4 条号提问补测 + 全链路回归（登录/文档/搜索/对话）",
    "result": "P1-4 补测通过（条号条款定位+归一化）；P2-7/P3-1 注册校验通过；"
              "发现并修复模型缓存权限故障（D-1）；优化模型重复下载（D-3）；"
              "记录 401 刷新观察项（D-2）。",
    "regression": "语义检索/文档助手/注册登录/决策流程全部通过，7 容器 healthy。",
})
doc["report"]["conclusion"] = (
    "24 项体验问题全部修复并回归验证；补测轮完成 P1-4 深度修复实证与全链路回归，"
    "另发现并修复 1 项部署级故障（模型缓存权限）、1 项优化（模型重复下载）、"
    "记录 1 项观察项（401 刷新时序）。"
)
doc["report"]["severity_summary"]["fixed"] = 25  # 24 + D-1
doc["report"]["severity_summary"]["remaining"] = 1  # D-2 观察项

with open(JSON_PATH, "w", encoding="utf-8") as f:
    json.dump(doc, f, ensure_ascii=False, indent=2)

# ---- 4) HTML 插入「补测回填」小节 ----
with open(HTML_PATH, encoding="utf-8") as f:
    html = f.read()

anchor = "修复回填（2026-10-14）"
idx = html.find(anchor)
if idx == -1:
    raise SystemExit("HTML anchor not found: " + anchor)
# 找到该章节标题行尾（</h2> 或类似）
end_title = html.find("</h", idx)
if end_title == -1:
    raise SystemExit("h tag end not found")

section = '''
<section class="retest" style="margin-top:24px;padding:18px 20px;background:#f0f7ff;border:1px solid #b3d4ff;border-radius:10px;">
<h3 style="margin:0 0 12px;font-size:17px;color:#1a56b0;">补测回填（2026-10-14）</h3>
<p style="margin:6px 0;font-size:14px;color:#333;"><b>补测结论：</b>P1-4 条号提问补测通过（<b>有风险</b>，准确召回“第二条 付款条件”原文并给出三点专业分析）；P2-7 注册禁自动填充、P3-1 密码实时校验通过；全链路回归（登录/文档/搜索/对话）通过，7 容器 healthy。</p>
<p style="margin:6px 0;font-size:14px;color:#333;"><b>补测新增发现与处理（3 项）：</b></p>
<table style="width:100%;border-collapse:collapse;font-size:13px;table-layout:fixed;">
<colgroup><col style="width:14%"><col style="width:22%"><col style="width:46%"><col style="width:18%"></colgroup>
<thead><tr style="background:#dbeafe;"><th style="border:1px solid #c7d8f2;padding:6px;text-align:left;">编号</th><th style="border:1px solid #c7d8f2;padding:6px;text-align:left;">级别</th><th style="border:1px solid #c7d8f2;padding:6px;text-align:left;">问题与处理</th><th style="border:1px solid #c7d8f2;padding:6px;text-align:left;">状态</th></tr></thead>
<tbody>
<tr><td style="border:1px solid #c7d8f2;padding:6px;">D-1</td><td style="border:1px solid #c7d8f2;padding:6px;">P0（已修复）</td><td style="border:1px solid #c7d8f2;padding:6px;">容器重建后语义检索 500：appuser 无法访问 /root/.cache（权限 700）→ 卷路径迁移至 /home/appuser/.cache 并注入 HOME/MODEL_CACHE_DIR，检索恢复。</td><td style="border:1px solid #c7d8f2;padding:6px;color:#0a7d32;">已修复并实证</td></tr>
<tr><td style="border:1px solid #c7d8f2;padding:6px;">D-2</td><td style="border:1px solid #c7d8f2;padding:6px;">观察项</td><td style="border:1px solid #c7d8f2;padding:6px;">access token 15 分钟过期后页面内未自动刷新（401 后无 refresh 请求）；整页重载后自动恢复。待专项核查刷新链路时序。</td><td style="border:1px solid #c7d8f2;padding:6px;color:#a15c00;">已记录待核</td></tr>
<tr><td style="border:1px solid #c7d8f2;padding:6px;">D-3</td><td style="border:1px solid #c7d8f2;padding:6px;">优化（已完成）</td><td style="border:1px solid #c7d8f2;padding:6px;">embedding 模型每次容器重启重复下载 → 记录真实快照路径到 .snapshot_path，重启后零下载、启动更快。</td><td style="border:1px solid #c7d8f2;padding:6px;color:#0a7d32;">已优化并实证</td></tr>
</tbody>
</table>
<p style="margin:8px 0 0;font-size:13px;color:#555;">P1-4 深度修复：L3 search_in_document 由精确子串匹配增强为「条号条款定位 + 空格归一化兜底」，0 token 确定性逻辑，浏览器实测召回成功。</p>
</section>
'''

html = html[:idx] + section + html[idx:]
with open(HTML_PATH, "w", encoding="utf-8") as f:
    f.write(html)

print("backfill ok: json + html")
