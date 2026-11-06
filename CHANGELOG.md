# 更新日志（CHANGELOG）

本文件遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/) 格式。版本号遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

## [Unreleased] - 2026-11

### 新增（GitHub 门面与体验修缮）

- **品牌 logo 上架**：新增文档+对勾主题的 SVG logo，应用于侧边栏、登录页与浏览器 favicon。
- **报告页支持短 ID**：8 位以上前缀短链自动展开为完整 UUID 并替换地址，分享/手输短 ID
  不再显示空报告。
- **README 全面重写**：面向使用者重写（这是什么/为什么是它/快速开始/架构/技术栈），
  取代原先的开发过程流水账；全部界面截图更新为当前版本。
- **对外文档重写**：CONTRIBUTING（含前后端改动验证步骤）、SECURITY（安全措施清单）、
  行为准则（完整版 Contributor Covenant 2.1）、Issue/PR 模板。

### 修复（CI 与工程）

- **CI 修复全绿**：compose 服务名引用错误（`api` → `backend-api`，此前启动 5 秒即失败）；
  基础镜像预拉取加 5 次退避重试，规避 registry 匿名限流；MinIO 官方镜像 2025 起要求登录，
  改用项目自维护的 GHCR 镜像（`ghcr.io/zhe713/ai-doc-lint-minio`）+ `GHCR_TOKEN` secret 登录拉取；
  golden 语料缺失时跳过 PDF 高亮批注用例。
- **覆盖率门禁达标**：新增 `test_checkers_units.py` 12 用例（格式/错别字检查器纯逻辑、
  规则包解释器、L3 只读工具），覆盖率 67% → **73%**，通过 CI 的 `--cov-fail-under=70`。
- **chat 多轮上下文记忆测试**：新增 `test_chat_memory.py` 7 用例，锁住消息持久化、
  L3 历史窗口、本轮消息不重复拼接、跨轮槽位继承与会话隔离。
- 比对组名乱码（历史数据编码丢失）修正；`.env.example` 的 `MINIO_IMAGE` 指向 GHCR。

### 新增（第三轮全面排查）

- **内置规则包「看规则」修复并支持单条停用**：`GET /rules/packs/builtin/{file}/explain`
  此前把 JSON 字符串直接传给解释器导致**所有内置包的解释面板一直为空**（真死功能）；
  现已修复，且解释条目新增 `rule_id`，规则页每条规则可一键停用/恢复。
- **「复制内置包为自定义」入口**：内置规则包列表新增复制按钮，一键把内置包内容转成
  自己的自定义包再改，不再需要从零手写。
- **chat 助手接入语义检索兜底**：`search_in_document` 在精确匹配、条号定位、
  空白归一化都未命中时，回退到 pgvector + BM25 混合检索（bge 向量 + reranker），
  「换个说法问」也能找到原文位置。
- **chat 历史体验修缮**：修复 L3 把当前用户消息重复拼两次的问题；`streamChat` 增加
  HTTP 状态检查与错误处理；意图层级徽标映射修正（`l1_rule/l2_context/l3_agent`）。

### 安全（第三轮全面排查）

- **越权读取修复（IDOR）**：`diff.py` 的 `_get_plaintext` 原先不校验文档归属，
  任意登录用户可读他人文档全文并做放行；现已校验所有权。
- **规则包越权修复**：非管理员此前可列出并查看他人私有规则包的完整内容；
  现在列表/详情只返回自己的包（管理员可见全部），且包所有者可管理自己的包。
- **管理员重置密码后吊销全部 refresh token**：防止旧会话在改密后继续有效。
- **XSS 修复**：搜索页 `highlight()` 现先做 HTML 转义再高亮，文档原文中的
  `<script>` 等内容不再被当 HTML 渲染。
- **新增安全回归测试** `tests/test_security.py`：锁住 IDOR、规则包越权、
  令牌吊销三处修复。

### 修复（第三轮全面排查）

- **Celery 重试真正生效**：此前任务首次抛错后状态停在 RUNNING，重试进入时被
  「状态守卫」直接跳过，导致重试机制形同虚设；parse/review/annotate/embed/
  cross_compare 五个任务在重试前先回退状态，重试耗尽才落 FAILED。
- **reaper 按任务类型重投**：此前把卡死的 review/annotate/embed 等任务一律
  丢回 parse 队列；现按 `task_type` 路由到各自队列。
- **条款严重度缺省**：条款包未写 `severity` 时不再 KeyError，回退到 warning。
- **告警阈值配置对齐**：`alerting.py` 引用的 `hybrid_vector_topk` 等配置项此前
  与 config.py 字段名漂移（启动即 AttributeError），已对齐。
- **前端交互修缮**：6 处 `ElMessageBox.confirm` 点取消不再抛未处理异常；
  报告页「审查失败」警示补齐；打开助手失败有提示；删除比对组/放行/撤销放行/
  取消任务/删除规则包/退出登录等确认框均有取消兜底。

### 新增（第二轮全面排查）

- **内置规则包「看规则」修复并支持单条停用**：`GET /rules/packs/builtin/{file}/explain`
  此前把 JSON 字符串直接传给解释器导致**所有内置包的解释面板一直为空**（真死功能）；
  现已修复，且解释条目新增 `rule_id`，规则页每条规则可一键停用/恢复。
- **「复制内置包为自定义」入口**：内置规则包列表新增复制按钮，一键把内置包内容转成
  自己的自定义包再改，不再需要从零手写。
- **chat 助手接入语义检索兜底**：`search_in_document` 在精确匹配、条号定位、
  空白归一化都未命中时，回退到 pgvector + BM25 混合检索（bge 向量 + reranker），
  「换个说法问」也能找到原文位置。
- **chat 历史体验修缮**：修复 L3 把当前用户消息重复拼两次的问题；`streamChat` 增加
  HTTP 状态检查与错误处理；意图层级徽标映射修正（`l1_rule/l2_context/l3_agent`）。

### 安全（第二轮全面排查）

- **越权读取修复（IDOR）**：`diff.py` 的 `_get_plaintext` 原先不校验文档归属，
  任意登录用户可读他人文档全文并做放行；现已校验所有权。
- **规则包越权修复**：非管理员此前可列出并查看他人私有规则包的完整内容；
  现在列表/详情只返回自己的包（管理员可见全部），且包所有者可管理自己的包。
- **管理员重置密码后吊销全部 refresh token**：防止旧会话在改密后继续有效。
- **XSS 修复**：搜索页 `highlight()` 现先做 HTML 转义再高亮，文档原文中的
  `<script>` 等内容不再被当 HTML 渲染。
- **新增安全回归测试** `tests/test_security.py`：锁住 IDOR、规则包越权、
  令牌吊销三处修复。

### 修复（第二轮全面排查）

- **Celery 重试真正生效**：此前任务首次抛错后状态停在 RUNNING，重试进入时被
  「状态守卫」直接跳过，导致重试机制形同虚设；parse/review/annotate/embed/
  cross_compare 五个任务在重试前先回退状态，重试耗尽才落 FAILED。
- **reaper 按任务类型重投**：此前把卡死的 review/annotate/embed 等任务一律
  丢回 parse 队列；现按 `task_type` 路由到各自队列。
- **条款严重度缺省**：条款包未写 `severity` 时不再 KeyError，回退到 warning。
- **告警阈值配置对齐**：`alerting.py` 引用的 `hybrid_vector_topk` 等配置项此前
  与 config.py 字段名漂移（启动即 AttributeError），已对齐。
- **前端交互修缮**：6 处 `ElMessageBox.confirm` 点取消不再抛未处理异常；
  报告页「审查失败」警示补齐；打开助手失败有提示；删除比对组/放行/撤销放行/
  取消任务/删除规则包/退出登录等确认框均有取消兜底。

### 新增

- **检查覆盖度升级为一等公民（架构治理）**：新增 `GET /documents/{id}/coverage`，返回
  `checks_requested / checks_executed / checks_skipped / suppressed_rules / checker_degraded /
  review_pending / review_failed / continued_with_warning / complete / released`，
  取代原先散落在 `doc_flags` 里的碎片字段。前端的「没检查」与「查过没问题」从此是两个明确状态，
  被停用的规则会出现在 `suppressed_rules` 里，不会伪装成「查过」。
- **放行成为可审计的状态流转**：新增 `POST /compare/release` 与 `DELETE /compare/release/{doc_id}`，
  放行记录落库（`document_releases`，迁移 `0014`）。服务端会重新算一次差异，不信任前端传来的
  「无差异」；自动放行遇到差异返回 409 并给出变更比例，人工放行则记录 `kind=manual`、基线与备注，
  并写审计日志。报告页展示放行状态卡（类型/基线/说明/时间/操作人），可撤销。
- **内置规则支持单条停用且真实生效**：新增 `disabled_rules` 表（迁移 `0014`）与
  `app/services/rule_overrides.py`，作用域分 `user`（仅自己）与 `global`（管理员，全员）。
  加载规则包时按条过滤，`FindingCollector` 再兜底过滤 format/typo 这类无规则列表的检查器，
  被抑制的条目记入 `suppressed_rules`。规则页可查看与恢复已停用规则。
- **每日审查限额真实扣减**：`llm/client.py` 新增 `llm_usage_today()` 与 `LLMQuotaExceededError`，
  超限时抛专用异常，条款/错别字检查器降级为纯规则而不是整体失败；`/admin/settings` 与
  `/admin/llm-usage` 返回 `used / limit / remaining / exhausted`，设置页显示「今日已用 X / 上限 Y」。
- **用户管理补齐写操作**：新增 `PATCH /admin/users/{user_id}`，支持停用/启用、调整角色、重置密码；
  禁止停用当前登录账号，禁止移除最后一个管理员。
- **放行/覆盖率契约锁进前端类型**：`api/findings.ts` 的 `Coverage` 与后端字段一一对应，
  `vue-tsc --build` 从「基线跑不通」变为 0 错误，构建前即可发现契约漂移。

- **检查覆盖度透明化（P0）**：`GET /documents/{id}/findings` 的 `doc_flags` 新增
  `checks_requested` / `checks_skipped`（含"整类未执行"标记）/ `review_pending` / `review_failed`。
  报告页对"条款完整性、数值勾稽整类未执行"显示橙色警示，明确「本报告不是完整审查结论」；
  个别规则因格式限制跳过只做轻提示，避免噪音。修复了「没检查」被显示成「检查了没问题」的问题。
- **规则包可视化编辑**：规则页「我的规则包」新增「编辑」入口，回填表单后覆盖保存（类型锁定），
  补齐原先只有新增/启停/删除、`updateRulePack` 全仓库零调用的半成品。
- **统一错误提示**：axios 响应拦截器统一提取后端 `detail` 并区分超时/网络/403/429/5xx，
  同一提示 4 秒内去重；可用 `silent: true` 关闭。解决全站大量 `try/finally` 无 `catch`
  导致的"操作失败但毫无反应"。

- **判定来源可追溯**：`check_findings` 增加 `source`（rule / hybrid / llm）、`llm_reason`、`llm_model`
  三列（迁移 `0013_finding_source`），报告页每条问题可看到「规则命中 / 规则+AI 复核 / AI 判定」徽标，
  AI 判定可展开看理由与模型名，首页增加判定来源分布与 AI 参与环节说明。
- **规则人话解释**：`app/checkers/ruleset_explain.py` 把四类规则包翻译成「检查什么 → 具体要求 →
  不合格会怎样 → 这条要不要调用 AI」；规则页重做为「看规则 / 建规则 / 一句话生成」三段式，
  修复原「一句话生成规则」卡片悬空（模板变量未定义、接口未接入）的问题。
- **注入错误精确评测集**：`corpus/injected_errors/` 8 份合同、12 条人工埋错（txt/pdf/docx 三载体），
  配套 `make_injected_corpus.py`（reportlab 生成中文 PDF，可指定 A3）与 `eval_injected.py`
  （走完整流水线后逐条对账，输出 JSON + HTML 报告）。

### 修复

- **设置项无法改回「不限制」**：`PATCH /admin/settings` 把显式 `null` 与「没传这个字段」当成同一件事，
  限额一旦设过就再也清不掉。现用 `model_fields_set` 区分，显式 `null` 会删除该设置项，
  回到默认语义（限额不限 / 保留策略默认）。
- **`/rules/packs` 签名损坏**：函数定义被写坏成 `def list_rule_packs(    pack_type: ...`，
  列表接口实际处于半坏状态，已修正。
- **对比接口重复实现 diff**：`api/diff.py` 内联复制了一份 diff 逻辑，与 `diff_texts()` 行为分叉；
  现统一复用同一实现，放行校验与页面展示口径一致。
- **比对组创建与入队不是一件事**：`create_group` 不触发比对，用户建完组还得再点一次「开始比对」；
  现提取 `_enqueue_group_compare`，建组即入队（幂等），手动触发复用同一入口。

- **规则包跨用户污染（安全）**：`RulePack` 有 `user_id`，但 `loader._db_custom_pack` 完全不按所有者过滤，
  任何普通用户保存规则包都会替换全系统所有人的审查规则。现改为按创建者隔离；无用户上下文（后台/
  测试）只走内置包。新增 `test_custom_pack_is_scoped_to_owner` 锁住契约。
- **检查器降级警示永不触发**：`checker_warnings` 写在 review 任务的 stats，接口却从 parse 任务读取，
  `ReportsView` 的橙色告警是死代码。现从 review 任务读，并按实际内容动态显示。
- **"确认有效"语义误导**：把状态写回 `open`（正确，问题还得改）却提示「已记录，谢谢反馈」，
  用户以为已处置。现提示「已确认为真实问题；改完合同后请点「标记已修复」」。
- **空规则包能保存**：前端用 `json.includes('"clauses": [')` 判空，空数组同样包含该子串。
  现解析 JSON 判断数组长度。
- **「看说明」点了没反应**：加载说明但未切换页签，用户停在「我的规则包」看不到任何变化。
  现自动跳到「① 看规则」。
- **去重跳过的文件被静默吞掉**：后端返回 `duplicates`，前端类型缺少该字段。现提示具体文件名与数量。
- **审查未完成先给结论**：parse 完成到 review 入队之间存在空窗，前端轮询会提前停止并显示 0 问题。
  现由 `review_pending` 驱动自动续等（上限 90 秒）并提示结果可能不完整。
- **错别字误报**：混淆集把「由其」等合法结构列为「尤其」候选，改为本地出候选 → LLM 读整句裁决，
  LLM 不可用则不报（宁漏不误）；白名单补齐介词/连词 + 其/以 的恒合法结构。
- **学习闭环反噬**：`签定` 被用户当误报忽略后自动写入 `typo_whitelist_auto.txt`，等于把真错别字永久保护。
  现在混淆集中有明确正确写法的词禁止自动加白（第 0 级验证，需人工确认），并移除已误加的词。
- **条款检查崩溃**：`clause_checker` 取 plaintext 产物用 `one_or_none()`，OCR 重试产生多份产物时抛
  `MultipleResultsFound`，改为按创建时间取最新一份。
- **sha256 去重受理**：此前只存 hash 不查重，重复上传会重跑全流程；现按同用户 + 同 sha256 拦截并返回已存在任务。
- **看板规则包统计**：按 `*.yaml` 计数，内置包已 JSON 化导致数字过期，改为兼容计数。
- **LLM 返回空值崩溃**：`resp.model` 在降级路径下为空，改为安全取值。

### 质量数据（实测）

- 后端 pytest 168 用例全绿；前端 `vite build` 通过。
- 注入错误评测：12 条埋错全部命中、0 误报（精确率 1.00 / 召回率 1.00），
  其中 7 条纯规则命中、3 条规则+AI 复核、2 条 AI 语义判定。
- 评测口径校准：自定义规则包改名后按条款关键词匹配；同一处错误被多个检查器报出时只算一次误报。

## [1.0.0] - 2026-10-16

首次开源发布。项目从竞赛作品演进为完整的独立文档校验工具（W1-W8 全部完成 + P1/P2/P3 产品迭代 + UX 修复 + 零成本演示环境）。

### 新增（核心能力）

- 文档校验：格式、错别字、条款完整性、金额勾稽全自动审查，规则引擎 + LLM 双通道，全部产出可审计
- 报告体系：四段式报告工作台（总览 / 风险销项 / 条款明细 / 原文对照三色高亮）、docx 批注下载、意见书 PDF + Excel 明细 + 高管摘要导出（0 token）
- 文档助手：基于检索的对话问答，LLM 回答带原文引用（防幻觉）
- 交叉比对：多份文档字段级差异对比、版本 diff 红绿渲染、批量矩阵报告 CSV 导出
- 语义检索：本地 bge 嵌入 + pgvector + BM25 混合检索 + 重排，全部 0 token
- 规则管理：内置 4 个业务规则包，界面化配置（无需写 YAML），支持复制内置包为自定义
- 自学习闭环：反馈采集 → 诊断看板 → 自动调优 → golden 基准回归（F1）
- 工程设施：7 容器 Docker 编排、异步任务队列（parse/review/annotate/learn）、RBAC、审计、监控告警、数据保留自动清理、CI/CD

### 质量数据（实测）

- 后端测试 179 用例全绿（覆盖率 73%），CI 双 job（后端 pytest + 前端 vue-tsc 构建）+ CodeQL 安全扫描
- golden 基准集：40 份网络公开真实合同（CUAD / 政府采购 / 示范文本库），误报率 391 → 7
- 混合检索相关度 99%（golden 检索回归）
- 零成本演示：本地一键启动 / Cloudflare 免费隧道外网演示（`scripts-dev/demo_start.ps1`）

### 安全

- Nginx 安全响应头（CSP、nosniff）、上传 MIME 魔数校验、密钥不入库
