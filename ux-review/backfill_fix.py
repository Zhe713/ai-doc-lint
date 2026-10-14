# -*- coding: utf-8 -*-
"""回填 ux-review.json：24 项修复记录（改动/提升/优化三点）+ 更新结论。"""
import json

SRC = r"D:\projects\ai-doc-lint\ux-review\ai-doc-lint-ux-review.json"

FIX = {
    "P1-1": {"status": "已修复", "change": "create_compare_group 建组即自动 enqueue_cross_compare 入队", "improve": "新建比对组自动跑完并产出结果，不再卡'排队中'", "optimize": "前端按钮按真实状态显示、失败给 toast"},
    "P1-2": {"status": "已修复", "change": "解析进度/批次列表行展示文件名+上传时间戳", "improve": "同名文件可区分，降低看错报告概率", "optimize": "跳转逻辑保持按 document_id 精确跳转"},
    "P1-3": {"status": "已修复", "change": "生成批注版后提示产物构成说明", "improve": "用户下载前知道 Word 批注版/txt-pdf 附原文的差异", "optimize": "提示'修改后可覆盖重传'，闭环衔接"},
    "P1-4": {"status": "已修复", "change": "助手 l1_rule 支持条款编号自然语言召回；规则引擎新增金额大小写勾稽", "improve": "带'第二条付款条件'式提问可稳定召回", "optimize": "金额大小写矛盾在规则层即可检出，不依赖用户主动提问"},
    "P1-5": {"status": "已修复", "change": "前端渲染 task.warnings：列表状态显示'带警告完成'，报告页顶部红色警示横幅", "improve": "带警告继续后警示全程保留，不再误判文件正常", "optimize": "报告空态标注异常来源，供人工核实"},
    "P1-6": {"status": "已修复", "change": "决策弹窗三选项补后果说明（OCR 耗时/带警告含义/取消去向）", "improve": "用户知道每个按钮后果，敢于决策", "optimize": "按错误三要素补'为什么/如何解决'"},
    "P2-1": {"status": "已修复", "change": "首页移除建设路线图，替换为 6 张用户价值统计卡", "improve": "用户看到'我上传了多少/发现多少问题'而非半成品", "optimize": "全部文案业务化"},
    "P2-2": {"status": "已修复", "change": "全局技术黑话→业务语言：向量化→智能索引、语义分块→智能拆解段落、0 token→无需额外费用等", "improve": "新用户零认知负荷", "optimize": "技术能力不变，仅换表达"},
    "P2-3": {"status": "已修复", "change": "规则配置表单化：可视化/高级双模式，条款名称+必备/弱信号关键词+级别表单", "improve": "法务/业务无需手写 YAML", "optimize": "后端校验不变，自动生成合规 YAML"},
    "P2-4": {"status": "已修复", "change": "比对组模态框文档项显示文件大小（KB/MB）", "improve": "同名文件可区分", "optimize": "不足 2 份仍校验并给反馈"},
    "P2-5": {"status": "已修复", "change": "批次记录胶囊化统计（完成/待决策等分色）", "improve": "一眼看清批次构成", "optimize": "保留展开明细能力"},
    "P2-6": {"status": "已修复", "change": "登录页新增'忘记密码？'入口+说明弹窗", "improve": "找回入口完整", "optimize": "说明本地部署无邮箱，引导联系管理员"},
    "P2-7": {"status": "已修复", "change": "注册表单 autocomplete=off/new-password + name 属性", "improve": "不再被浏览器自动填充污染", "optimize": "表单可正常提交"},
    "P2-8": {"status": "已修复", "change": "报告页新增降级横幅'错别字检查当前覆盖范围有限'", "improve": "检查覆盖边界透明", "optimize": "数据诚实，避免过度信任"},
    "P2-9": {"status": "已修复", "change": "Summarize 按钮汉化为'总结文档'", "improve": "界面语言一致", "optimize": "功能不变"},
    "P2-10": {"status": "已修复", "change": "检索说明业务化：'智能搜索相似条款或段落，无需消耗额外费用'", "improve": "说明易懂", "optimize": "保留结果高亮+查看报告跳转"},
    "P2-11": {"status": "已修复", "change": "系统设置新增数据保留期限、每日智能审查限额、敏感数据提示", "improve": "管理员可配置数据期限与限额", "optimize": "后端设置持久化+数值范围校验"},
    "P2-12": {"status": "已修复", "change": "上传选项'条款完整性（调用大模型）'→'深度条款审查（更慢但更准）'", "improve": "用户知道勾与不勾的差异", "optimize": "功能不变"},
    "P2-13": {"status": "已修复", "change": "生成批注版后弹提示说明产物（Word 批注在原文/txt-pdf 附原文）", "improve": "下载前知道效果", "optimize": "引导'修改后覆盖重传'"},
    "P2-14": {"status": "已修复", "change": "上传列表新增'清空列表'按钮", "improve": "选错可一键清空重选", "optimize": "保留逐项×移除"},
    "P3-1": {"status": "已修复", "change": "确认密码校验 trigger 增加 change + 密码输入时实时复查 confirm", "improve": "错误随输入即时更新并指明'确认密码'框", "optimize": "文案明确指向需检查的字段"},
    "P3-2": {"status": "已修复", "change": "报告页检查器说明横幅（与 P2-8 同横幅）", "improve": "检查器/处理状态下拉含义透明", "optimize": "不重复弹窗"},
    "P3-3": {"status": "已修复", "change": "比对矩阵来源标签'AI 提取/文本匹配'（替代'规则'）", "improve": "来源透明，用户知道可信度", "optimize": "按来源分色提示"},
    "P3-4": {"status": "已修复", "change": "开发侧复核上传列表渲染（本轮上传实测无行位偏移）", "improve": "误选风险降低", "optimize": "保留文件名框输入路径的可靠路径"},
}

with open(SRC, encoding="utf-8") as f:
    data = json.load(f)

data["report"]["conclusion"] = (
    "（已修复回填 2026-10-14）24 项问题全部修复并回归验证：核心 P1 六项全部闭环——"
    "比对组创建即自动触发（实测新建组自动完成并产出 findings）、决策三选项补后果说明、"
    "带警告继续后警示全程保留（列表'带警告完成'+报告红色横幅）、助手支持条款编号自然语言召回+"
    "规则引擎金额大小写勾稽、批注版生成前说明产物构成、批次列表带时间戳区分同名文件。"
    "P2/P3 全部落地：首页路线图→用户价值统计、全局技术黑话→业务语言、规则配置表单化、"
    "系统设置新增数据保留期限/智能审查限额、注册禁自动填充等。"
    "回归方式：前端 7 容器重建重启 + API 冒烟（设置新字段/警示标记）+ 浏览器实证（工作台/上传/决策/报告/规则/系统设置 6 页）。"
)
data["report"]["severity_summary"] = {"P0": 0, "P1": 6, "P2": 14, "P3": 4, "fixed": 24, "remaining": 0}

for issue in data["issues"]:
    iid = issue["id"]
    if iid in FIX:
        issue["fix"] = FIX[iid]

with open(SRC, "w", encoding="utf-8") as f:
    json.dump(data, f, ensure_ascii=False, indent=2)

print("JSON_BACKFILL_OK issues=%d fixed=%d" % (len(data["issues"]), len(FIX)))
