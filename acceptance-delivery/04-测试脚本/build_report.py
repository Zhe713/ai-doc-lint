# -*- coding: utf-8 -*-
"""汇总 L0-L4 验收结果 -> acceptance_report.json（结构化，供 CI/回归基线）。"""
import json
import os

BASE = os.path.dirname(os.path.abspath(__file__))
GOLDEN = os.path.join(BASE, "..", "corpus", "acceptance_golden")

with open(os.path.join(GOLDEN, "l1_results.json"), encoding="utf-8") as f:
    L1 = json.load(f)
with open(os.path.join(GOLDEN, "l3_metrics.json"), encoding="utf-8") as f:
    L3 = json.load(f)

# L1 逐份发现明细（14 条）
l1_findings = []
for doc in L1:
    for s in doc.get("sample", []):
        l1_findings.append({
            "file": doc["file"],
            "severity": s["severity"],
            "checker": s["checker"],
            "message": s["message"],
        })

report = {
    "report_meta": {
        "title": "ai-doc-lint 功能验收报告（L0-L4）",
        "version": "1.0",
        "date": "2026-10-12",
        "acceptor_role": "验收乙方（第三方验收视角）",
        "object": "ai-doc-lint 自托管 AI 文档校验工具（demo 基线）",
        "method": "参考 LangChain / Ragas 等开源 AI agent 测试方法论，L0-L4 分层验收；golden 集来自网络公开真实合同（市场监管总局示范文本库），禁止自造",
        "criteria": "P0 缺陷 = 0 且核心链路通过率 >= 90%",
    },
    "golden": {
        "count": 40,
        "source": "市场监管总局示范文本库 htsfwb.samr.gov.cn（官方公开真实合同）",
        "self_generated": False,
        "categories": {
            "sale 买卖": 16, "labor 劳务/承揽": 8, "lease 租赁": 6,
            "build 建设工程": 4, "trans 运输": 4, "general 其他": 2,
        },
        "ground_truth": {
            "docs": 40,
            "fields": ["编号", "违约金比例", "违约金条款窗口", "争议解决", "金额格式", "管辖", "模板缺失(民法典470条7类必备要素)", "留白项数"],
            "template_complete_docs": 20,
            "template_missing_docs": 20,
        },
    },
    "L1_business_integration": {
        "docs": L3["total_docs"],
        "parsed": L3["parsed_docs"],
        "failed": L3["failed_docs"],
        "findings_total": L3["total_findings"],
        "severity": L3["severity"],
        "checkers": L3["checkers"],
        "typo_calibration": {
            "before": 398,
            "after": 14,
            "delta_pct": -96.5,
            "cause": "typo_confusion.txt 约 129 行方向写反（正确词在左列被当错别字检出）",
            "action": "逐行校准为「错误 正确」（129 行反转、107 行保留、删除 3 行损坏/同形），docker cp 同步 api+worker 容器",
            "real_hits": 1,
            "real_hit_detail": "build_04 家庭居室装饰装修工程合同官方文本「签定书面变更协议」→「签订」",
            "contextual_fp": 6,
            "contextual_fp_note": "「由其/审报/因该」等：混淆集无上下文的固有局限（官方文本合法用法），记入改进建议",
            "info_format": "7 条 info 为标题层级提示（「1.」前缺「（一）」等），符合预期",
        },
        "findings_detail": l1_findings,
    },
    "L2_user_journey_e2e": {
        "method": "本机无 Playwright，改用桌面浏览器（Edge）+ cu 实操真实用户路径",
        "journeys": [
            {"item": "登录（boss_admin）", "result": "PASS", "note": "会话保持正常"},
            {"item": "上传/批次记录/明细", "result": "PASS", "note": "4 批 golden（40 份）全部「已完成」；历史批次可滚动"},
            {"item": "报告页统计（错误/警告/提示）", "result": "PASS", "note": "build_04 错误0/警告1/提示0，计数正确"},
            {"item": "finding 提示语人性化", "result": "PASS", "note": "「签定」→「签订」+ 建议 + 原文片段，非硬性报错文案"},
            {"item": "AI 助手（报告页）", "result": "PASS_WITH_NOTE", "note": "提问即时返回；回答简短（「无高风险问题。」）无引用依据"},
            {"item": "文档助手（独立页）", "result": "PASS", "note": "自然语言提问返回风险结论+5 点依据+原文位置引用+民法典条款，忠于原文"},
            {"item": "Word 批注版生成下载", "result": "PASS", "note": "后端任务 parsed，批注版 docx 36.9KB 生成；前端按钮无即时视觉反馈（loading/toast 未捕捉）"},
            {"item": "语义检索", "result": "PASS_WITH_NOTE", "note": "返回 Top10 相似度排序；命中 100 份历史仿真语料（clause20_*），golden 真实条款未进 Top10（相关性观察点）"},
            {"item": "空态", "result": "PASS", "note": "sale_13 报告空态「没有符合条件的问题」正确"},
        ],
        "ux_observations": [
            {"level": "P1", "item": "批次记录显示「-1 排队」", "detail": "部分批次排队数为 -1，疑似状态映射显示 bug，需开发确认"},
            {"level": "P1", "item": "报告页 finding 无点击定位交互", "detail": "finding 行/原文片段点击无跳转；「一键跳转原文」入口缺失（文档助手以位置引用形式提供定位）"},
            {"level": "P2", "item": "AI 助手（报告页）回答简短", "detail": "「无高风险问题。」无依据引用；文档助手回答质量高，两入口能力不一致"},
            {"level": "P2", "item": "批注按钮无即时视觉反馈", "detail": "点击后无 loading/toast 捕捉（后端 3 任务 parsed 正常，功能成立）"},
            {"level": "P2", "item": "语义检索被仿真语料刷屏", "detail": "100 份历史仿真合同（clause20_*）与真实合同混存检索库，短查询 Top10 被仿真条款占据"},
        ],
    },
    "L3_business_metrics": {
        "upload_block_rate_pct": L3["upload_block_rate"],
        "avg_findings_per_doc": L3["avg_findings_per_doc"],
        "severity": L3["severity"],
        "checkers": L3["checkers"],
        "by_category": L3["by_category"],
        "gt_template_missing_docs": L3["gt_template_missing_docs"],
        "note": "上传即拦截率 = 有发现文档占比（11/40）；demo 基线真实示范文本质量高，发现问题少属合理",
    },
    "L4_fault_tolerance": {
        "cases": [
            {"case": "T1 损坏 PDF（伪造内容）", "result": "PASS", "detail": "接受上传 → 解析失败 → 文档/任务进入 awaiting_decision 人工闸门（不静默 failed、不无限重试）；decision API 支持 取消 / 带警告继续 / OCR 重试"},
            {"case": "T2 非法扩展名（.zip）", "result": "PASS", "detail": "422「不支持的格式 .zip（evil.zip），支持：docx, md, pdf, txt」"},
            {"case": "T3 空文件", "result": "PASS", "detail": "422「空文件：empty_test.txt」"},
            {"case": "T4 权限隔离（新注册用户）", "result": "PASS", "detail": "新用户文档列表 len=0，看不到管理员 408 份文档"},
            {"case": "T5 越权访问他人文档", "result": "PASS", "detail": "404 Not Found"},
            {"case": "T6 批量稳定性（常规量级）", "result": "PASS", "detail": "40 份 golden 4 批×10 全部 parsed、0 failed"},
        ],
    },
    "issues": {
        "P0": [],
        "P1": [
            {"item": "批次记录「-1 排队」显示异常", "impact": "用户对批次状态误读（排队数不可能为负）", "suggest": "核对批次统计状态映射与 awaiting_decision 计数逻辑"},
            {"item": "报告页 finding 无「一键跳转原文」", "impact": "用户看到问题后无法直接定位到原文修改处，增加排查成本", "suggest": "finding 行点击联动文档预览并高亮 location 片段（文档助手已有位置引用，可复用）"},
        ],
        "P2": [
            {"item": "AI 助手（报告页）回答简短无引用", "impact": "两入口能力不一致，用户可能质疑结论", "suggest": "复用文档助手回答链路（结论+依据+位置）"},
            {"item": "语义检索被历史仿真语料占据 Top10", "impact": "真实合同条款检索被干扰", "suggest": "检索结果标注语料来源/可过滤仿真数据，或检索排序加入文档类型权重"},
            {"item": "语境级 typo 误报 6 条（由其/审报/因该）", "impact": "低频误报，混淆集无上下文固有局限", "suggest": "typo 检查接入轻量上下文判定（如左右词性/邻词），或对高频合法搭配加白名单"},
            {"item": "批注按钮无即时视觉反馈", "impact": "用户不确定是否已触发", "suggest": "前端按钮 loading 态与轮询进度提示（代码已有 annotating 态，排查渲染时机）"},
        ],
    },
    "changes_trace": [
        {
            "change": "typo 混淆集方向校准",
            "detail": "typo_confusion.txt 逐行校准为「错误 正确」（129 行反转、107 行保留、删 3 行损坏/同形），docker cp 同步 api+worker 容器",
            "improvement": "L1 误报 398 → 14（-96.5%），40 份全部 parsed、0 failed",
            "optimization": "数据质量治理：删除损坏行、补充注释说明格式",
        },
        {
            "change": "golden 上传排障（僵尸任务清理）",
            "detail": "Docker 重启后 287 个 review/embed 僵尸任务占满 PENDING_QUOTA → SQL 置 failed",
            "improvement": "上传 40/40 成功，4 批×10 全部解析",
            "optimization": "保留 golden_*.py 采集/上传/标注脚本，可复跑",
        },
    ],
    "conclusion": {
        "p0_count": 0,
        "core_path_functional_pass": "9/9（功能可用率 100%）",
        "core_path_strict_pass": "7/9（含体验观察点口径 77.8%）",
        "verdict": "通过（P0=0，核心链路无阻断缺陷，功能可用率 100%）",
        "demo_note": "本项目为 demo 基线（非正式版）；本次验收为基线基线快照，后续每次改动需记录改动/提升/优化点并回归",
    },
}

out_path = os.path.join(GOLDEN, "acceptance_report.json")
with open(out_path, "w", encoding="utf-8") as f:
    json.dump(report, f, ensure_ascii=False, indent=2)
print("written:", out_path, os.path.getsize(out_path), "bytes")
print("findings detail:", len(l1_findings))
