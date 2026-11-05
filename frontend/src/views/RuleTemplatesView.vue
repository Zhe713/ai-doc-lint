<template>
  <div>
    <!-- 顶部：这份页面到底是干什么的 -->
    <el-card shadow="never" class="hero">
      <div class="hero-title">审查规则：系统就是按这些规则，逐条检查你的合同</div>
      <div class="hero-desc">
        规则分四类 —— <b>格式</b>（排版长什么样）、<b>条款</b>（必须有哪些内容）、
        <b>字段</b>（要自动提取哪些信息）、<b>勾稽</b>（几处数字/日期对不对得上）。
        每条规则都会标注判定方式：<el-tag size="small" type="info">规则判定</el-tag>
        不花钱、可离线；<el-tag size="small" type="warning">规则 + AI 复核</el-tag>
        <el-tag size="small" type="success">AI 语义判定</el-tag> 只在规则拿不准时才调用大模型。
      </div>
    </el-card>

    <el-tabs v-model="tab" class="main-tabs">
      <!-- ========== ① 看规则 ========== -->
      <el-tab-pane label="① 看规则（每条在查什么）" name="read">
        <el-row :gutter="16">
          <el-col :span="9">
            <el-card shadow="never">
              <template #header><b>选择要查看的规则包</b></template>
              <div class="sub-title">内置规则（随系统提供）</div>
              <div
                v-for="b in builtins"
                :key="b.file"
                class="pack-row"
                :class="{ active: selected?.kind === 'builtin' && selected.file === b.file }"
                @click="selectBuiltin(b)"
              >
                <div class="pack-name">{{ b.name }}</div>
                <el-tag size="small">{{ packTypeLabel(b.pack_type) }}</el-tag>
                <el-button
                  size="small"
                  link
                  type="primary"
                  style="margin-left: auto"
                  @click.stop="onCopyBuiltin(b)"
                >
                  复制为自定义
                </el-button>
              </div>
              <div class="sub-title" style="margin-top: 14px">
                我创建的规则（{{ packs.length }}）
              </div>
              <div
                v-for="p in packs"
                :key="p.id"
                class="pack-row"
                :class="{ active: selected?.kind === 'custom' && selected.id === p.id }"
                @click="selectCustom(p)"
              >
                <div class="pack-name">
                  {{ p.name }}
                  <el-tag v-if="!p.enabled" size="small" type="info">已停用</el-tag>
                </div>
                <el-tag size="small" effect="plain">{{ packTypeLabel(p.pack_type) }}</el-tag>
              </div>
              <el-empty v-if="!packs.length" description="还没有自定义规则包" :image-size="50" />
            </el-card>
          </el-col>

          <el-col :span="15">
            <el-card shadow="never" v-loading="explainLoading">
              <template #header>
                <div class="explain-head">
                  <b>{{ explain?.title || '规则说明' }}</b>
                  <span v-if="selectedName" class="explain-source">{{ selectedName }}</span>
                </div>
              </template>

              <el-empty
                v-if="!explain"
                description="从左侧选一个规则包，这里会用大白话列出它到底在查什么"
                :image-size="70"
              />
              <template v-else>
                <div class="explain-summary">
                  共 <b>{{ explain.total }}</b> 条规则 ·
                  <span class="badge rule">纯规则 {{ explain.counts.rule }}</span>
                  <span class="badge hybrid">规则 + AI {{ explain.counts.hybrid }}</span>
                  <span class="badge llm">AI 判定 {{ explain.counts.llm }}</span>
                </div>
                <div class="explain-list">
                  <div v-for="(it, i) in explain.items" :key="i" class="explain-item">
                    <div class="explain-item-head">
                      <span class="idx">{{ i + 1 }}</span>
                      <span class="explain-title">{{ it.title }}</span>
                      <el-tag size="small" :type="sevTagType(it.severity)">{{ it.severity_label }}</el-tag>
                      <el-tag size="small" :type="BASIS_TAG_TYPE[it.basis]" effect="plain">
                        {{ BASIS_LABELS[it.basis] }}
                      </el-tag>
                      <el-button
                        v-if="it.rule_id && selected?.kind === 'builtin' && selected.pack_type"
                        size="small"
                        link
                        type="danger"
                        style="margin-left: auto"
                        @click="onDisableRule(selected.pack_type, it.rule_id, it.title)"
                      >
                        停用
                      </el-button>
                    </div>
                    <div class="explain-detail">{{ it.detail }}</div>
                  </div>
                </div>
                <el-alert
                  style="margin-top: 14px"
                  type="info"
                  :closable="false"
                  title="规则说明由系统根据规则包内容实时生成，改了参数这里会跟着变——所以你不需要读懂 JSON。"
                />
              </template>
            </el-card>
          </el-col>
        </el-row>
      </el-tab-pane>

      <!-- ========== ② 新增 / 修改 ========== -->
      <el-tab-pane label="② 新增 / 修改规则" name="edit">
        <!-- 一句话生成 -->
        <el-card shadow="never" style="margin-bottom: 16px">
          <template #header>
            <b>懒人模式：用一句话生成规则（AI）</b>
            <span class="head-note">不会填参数？把需求说清楚即可，生成后还能继续改</span>
          </template>
          <el-row :gutter="12">
            <el-col :span="5">
              <el-select v-model="nlPackType" style="width: 100%">
                <el-option v-for="t in packTypes" :key="t" :label="packTypeLabel(t)" :value="t" />
              </el-select>
            </el-col>
            <el-col :span="13">
              <el-input v-model="nlText" type="textarea" :rows="2" :placeholder="nlPlaceholder" />
            </el-col>
            <el-col :span="6">
              <el-button type="primary" :loading="generating" @click="onGenerate">
                生成规则并填入表单
              </el-button>
              <el-button @click="nlText = ''">清空</el-button>
            </el-col>
          </el-row>
          <el-alert
            style="margin-top: 12px"
            type="success"
            :closable="false"
            title="生成结果会自动填进下方表单，你可以逐条改；保存前系统会校验，不合法的规则不会入库。"
          />
        </el-card>

        <el-row :gutter="16">
          <el-col :span="14">
            <el-card shadow="never">
              <template #header>
                <div class="explain-head">
                  <b v-if="editingId">正在编辑：{{ form.name || '未命名规则包' }}</b>
                  <b v-else>可视化配置（不用写代码）</b>
                  <span v-if="editingId" class="head-note">保存会覆盖原规则包，类型不可更改</span>
                  <el-button link type="primary" @click="fillExample">填入一个示例</el-button>
                </div>
              </template>

              <el-form label-position="top" :model="form" size="default">
                <el-row :gutter="12">
                  <el-col :span="14">
                    <el-form-item label="规则包名称">
                      <el-input v-model="form.name" placeholder="如：本公司付款条款审查包" />
                    </el-form-item>
                  </el-col>
                  <el-col :span="10">
                    <el-form-item label="规则类型">
                      <el-select
                        v-model="form.pack_type"
                        style="width: 100%"
                        :disabled="!!editingId"
                        @change="onPackTypeChange"
                      >
                        <el-option v-for="t in packTypes" :key="t" :label="packTypeLabel(t)" :value="t" />
                      </el-select>
                    </el-form-item>
                  </el-col>
                </el-row>
                <div class="type-hint">{{ packTypeHint(form.pack_type) }}</div>

                <el-row :gutter="12">
                  <el-col :span="12">
                    <el-form-item label="适用文档类型">
                      <el-select
                        v-model="form.doc_type"
                        style="width: 100%"
                        filterable
                        allow-create
                        default-first-option
                      >
                        <el-option label="contract（合同类文档）" value="contract" />
                        <el-option label="global（所有文档都适用）" value="global" />
                      </el-select>
                      <div class="hint">格式规则一般选 global；条款/字段/勾稽规则选 contract。</div>
                    </el-form-item>
                  </el-col>
                  <el-col :span="12">
                    <el-form-item label="一句话说明（可选）">
                      <el-input v-model="form.description" placeholder="给同事看的备注，如：适用于我方作为甲方的采购合同" />
                    </el-form-item>
                  </el-col>
                </el-row>

                <!-- 格式规则：分组渲染 -->
                <template v-if="form.pack_type === 'format'">
                  <div v-for="g in formatGroups" :key="g.key" class="field-group">
                    <div class="field-group-head">
                      <span class="field-group-title">{{ g.title }}</span>
                      <span class="field-group-desc">{{ g.desc }}</span>
                    </div>
                    <el-form-item v-for="f in g.fields" :key="f.key" :label="f.label">
                      <el-input
                        v-if="f.type === 'string'"
                        v-model="formatModel[f.key]"
                        :placeholder="f.example || ''"
                      />
                      <el-input
                        v-else-if="f.type === 'number'"
                        v-model.number="formatModel[f.key]"
                        :placeholder="f.example || ''"
                        style="width: 180px"
                      />
                      <el-input
                        v-else-if="f.type === 'string[]'"
                        :model-value="arrToText(formatModel[f.key])"
                        :placeholder="f.example || '逗号分隔'"
                        @update:model-value="(v: string) => (formatModel[f.key] = textToArr(v))"
                      />
                      <el-input
                        v-else-if="f.type === 'number[]'"
                        :model-value="arrToText(formatModel[f.key])"
                        :placeholder="f.example || '逗号分隔，如 210, 297'"
                        style="width: 220px"
                        @update:model-value="(v: string) => (formatModel[f.key] = numArr(v))"
                      />
                      <el-switch v-else-if="f.type === 'boolean'" v-model="formatModel[f.key]" />
                      <el-select v-else-if="f.type === 'select'" v-model="formatModel[f.key]" style="width: 180px">
                        <el-option v-for="o in f.options" :key="o" :label="o" :value="o" />
                      </el-select>
                      <div v-if="f.help" class="hint">{{ f.help }}</div>
                    </el-form-item>
                  </div>
                </template>

                <!-- 条款规则 -->
                <div v-if="form.pack_type === 'clause'" class="row-editor">
                  <div class="row-head">
                    <span style="width: 170px">条款名称</span>
                    <span style="flex: 1">必备关键词（出现即认定存在）</span>
                    <span style="width: 130px">弱信号词（可选）</span>
                    <span style="width: 85px">严重度</span>
                    <span style="width: 48px"></span>
                  </div>
                  <div class="row-tip">
                    例：条款名称填「付款期限」，必备关键词填「付款期限、支付期限、付款时间」。
                    只填弱信号词时，系统会请大模型结合上下文确认——这正是「换个说法也不误报」的原因。
                  </div>
                  <div v-for="(c, i) in visualClauses" :key="i" class="row-line">
                    <el-input v-model="c.name" size="default" placeholder="付款期限" style="width: 170px" />
                    <el-input v-model="c.strong" size="default" placeholder="付款期限, 支付期限, 付款时间" />
                    <el-input v-model="c.weak" size="default" placeholder="逾期, 结算" style="width: 130px" />
                    <el-select v-model="c.severity" size="default" style="width: 85px">
                      <el-option label="错误" value="error" />
                      <el-option label="警告" value="warning" />
                      <el-option label="提示" value="info" />
                    </el-select>
                    <el-button size="small" type="danger" plain @click="visualClauses.splice(i, 1)">删除</el-button>
                  </div>
                  <el-button size="small" @click="visualClauses.push({ name: '', strong: '', weak: '', severity: 'error' })">
                    + 添加一条条款
                  </el-button>
                </div>

                <!-- 字段抽取 -->
                <div v-if="form.pack_type === 'field'" class="row-editor">
                  <div class="row-head">
                    <span style="width: 150px">字段键（英文）</span>
                    <span style="width: 120px">中文名</span>
                    <span style="width: 100px">值类型</span>
                    <span style="flex: 1">识别写法</span>
                    <span style="width: 48px"></span>
                  </div>
                  <div class="row-tip">
                    例：要自动提取合同金额，字段键填 contract_amount、中文名填「合同金额」、类型选 money、
                    识别写法填「合同总价, 合同金额, 总价款」。提取结果会出现在报告与跨文档比对里。
                  </div>
                  <div v-for="(c, i) in fieldRows" :key="i" class="row-line">
                    <el-input v-model="c.key" size="default" placeholder="contract_amount" style="width: 150px" />
                    <el-input v-model="c.label" size="default" placeholder="合同金额" style="width: 120px" />
                    <el-select v-model="c.type" size="default" style="width: 100px">
                      <el-option v-for="o in fieldTypes" :key="o.value" :label="o.label" :value="o.value" />
                    </el-select>
                    <el-input v-model="c.patterns" size="default" placeholder="合同总价, 合同金额, 总价款" />
                    <el-button size="small" type="danger" plain @click="fieldRows.splice(i, 1)">删除</el-button>
                  </div>
                  <el-button size="small" @click="fieldRows.push({ key: '', label: '', type: 'text', required: true, patterns: '' })">
                    + 添加一个字段
                  </el-button>
                </div>

                <!-- 交叉勾稽 -->
                <div v-if="form.pack_type === 'cross'" class="row-editor">
                  <div class="row-head">
                    <span style="width: 160px">规则 ID</span>
                    <span style="width: 160px">规则名称</span>
                    <span style="flex: 1">要互相对照的字段键</span>
                    <span style="width: 85px">严重度</span>
                    <span style="width: 48px"></span>
                  </div>
                  <div class="row-tip">
                    例：核对大写金额与小写金额是否一致，规则 ID 填 amount.consistency、名称填「金额大小写一致」、
                    字段填 amount_words, amount_digits。这类核对是纯计算，不调用大模型。
                  </div>
                  <div v-for="(c, i) in crossRows" :key="i" class="row-line">
                    <el-input v-model="c.id" size="default" placeholder="amount.consistency" style="width: 160px" />
                    <el-input v-model="c.name" size="default" placeholder="金额大小写一致" style="width: 160px" />
                    <el-input v-model="c.fields" size="default" placeholder="amount_words, amount_digits" />
                    <el-select v-model="c.severity" size="default" style="width: 85px">
                      <el-option label="错误" value="error" />
                      <el-option label="警告" value="warning" />
                      <el-option label="提示" value="info" />
                    </el-select>
                    <el-button size="small" type="danger" plain @click="crossRows.splice(i, 1)">删除</el-button>
                  </div>
                  <el-button size="small" @click="crossRows.push({ id: '', name: '', fields: '', severity: 'error', description: '' })">
                    + 添加一条勾稽规则
                  </el-button>
                </div>

                <div class="form-actions">
                  <el-button type="primary" :loading="uploading" @click="onUpload">保存并启用</el-button>
                  <el-button @click="resetForm">清空表单</el-button>
                </div>
              </el-form>
            </el-card>
          </el-col>

          <!-- 实时预览 -->
          <el-col :span="10">
            <el-card shadow="never" class="preview-card" v-loading="previewLoading">
              <template #header>
                <b>当前规则在检查什么（实时预览）</b>
              </template>
              <div class="preview-summary" v-if="preview">
                共 <b>{{ preview.total }}</b> 条 ·
                <span class="badge rule">纯规则 {{ preview.counts.rule }}</span>
                <span class="badge hybrid">规则 + AI {{ preview.counts.hybrid }}</span>
                <span class="badge llm">AI 判定 {{ preview.counts.llm }}</span>
              </div>
              <el-empty
                v-if="!preview || !preview.items.length"
                description="填好左侧内容，这里会实时显示「这条规则到底在查什么」"
                :image-size="60"
              />
              <div v-else class="preview-list">
                <div v-for="(it, i) in preview.items" :key="i" class="preview-item">
                  <div class="preview-title">
                    <span class="idx">{{ i + 1 }}</span>{{ it.title }}
                    <el-tag size="small" :type="BASIS_TAG_TYPE[it.basis]" effect="plain">
                      {{ BASIS_LABELS[it.basis] }}
                    </el-tag>
                  </div>
                  <div class="preview-detail">{{ it.detail }}</div>
                </div>
              </div>
              <el-alert
                v-if="preview"
                style="margin-top: 12px"
                type="info"
                :closable="false"
                title="保存后立即生效（只影响你自己的文档），无需重启；停用旧包会自动回落到内置规则。"
              />
            </el-card>
          </el-col>
        </el-row>
      </el-tab-pane>

      <!-- ========== ③ 我的规则包 ========== -->
      <el-tab-pane label="③ 我的规则包" name="mine">
        <el-card shadow="never">
          <template #header><b>自定义规则包（{{ packs.length }}）</b></template>
          <el-table :data="packs" size="small" border>
            <el-table-column prop="name" label="名称" min-width="160" />
            <el-table-column label="类型" width="110">
              <template #default="{ row }">
                <el-tag size="small">{{ packTypeLabel(row.pack_type) }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="doc_type" label="适用文档" width="100" />
            <el-table-column label="状态" width="90">
              <template #default="{ row }">
                <el-tag :type="row.enabled ? 'success' : 'info'" size="small">
                  {{ row.enabled ? '启用' : '停用' }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="version" label="版本" width="70" />
            <el-table-column prop="description" label="说明" min-width="160" show-overflow-tooltip />
            <el-table-column label="操作" width="300" fixed="right">
              <template #default="{ row }">
                <el-button size="small" link type="primary" @click="editPack(row as RulePack)">编辑</el-button>
                <el-button size="small" link type="primary" @click="selectCustom(row as RulePack)">看说明</el-button>
                <el-button size="small" @click="onToggle(row as RulePack)">
                  {{ (row as RulePack).enabled ? '停用' : '启用' }}
                </el-button>
                <el-button size="small" type="danger" plain @click="onDelete(row as RulePack)">删除</el-button>
              </template>
            </el-table-column>
          </el-table>
          <el-alert
            style="margin-top: 12px"
            type="info"
            :closable="false"
            title="启用的自定义包优先生效，且只作用于你自己上传的文档；停用或删除后自动回落内置规则。"
          />

          <!-- 单条规则停用：内置规则也能真停用，不必停掉整个包 -->
          <el-card shadow="never" style="margin-top: 16px">
            <template #header>
              <div class="explain-head">
                <b>已停用的单条规则（{{ disabledRules.length }}）</b>
                <span class="explain-source">
                  停用后该规则不再参与检查；报告页会注明「已停用规则」，不会伪装成「查过没问题」
                </span>
              </div>
            </template>
            <el-empty v-if="!disabledRules.length" :image-size="50"
              description="没有停用任何单条规则" />
            <el-table v-else :data="disabledRules" size="small">
              <el-table-column prop="rule_id" label="规则" min-width="220" show-overflow-tooltip />
              <el-table-column label="类型" width="110">
                <template #default="{ row }">
                  {{ packTypeLabel(row.pack_type as PackType) }}                </template>
              </el-table-column>
              <el-table-column label="范围" width="90">
                <template #default="{ row }">
                  <el-tag size="small" :type="row.scope === 'global' ? 'danger' : 'info'" effect="plain">
                    {{ row.scope === 'global' ? '全员' : '仅自己' }}
                  </el-tag>
                </template>
              </el-table-column>
              <el-table-column prop="reason" label="停用原因" min-width="200" show-overflow-tooltip />
              <el-table-column label="操作" width="100">
                <template #default="{ row }">
                  <el-button size="small" link type="primary" @click="onEnableRule(row as DisabledRuleItem)">恢复</el-button>
                </template>
              </el-table-column>
            </el-table>
          </el-card>
        </el-card>
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'

import type { TagType } from '@/api/findings'
import {
  BASIS_LABELS,
  BASIS_TAG_TYPE,
  type BuiltinPack,
  type DisabledRuleItem,
  type ExplainResult,
  type PackType,
  type RulePack,
  type SchemaField,
  createRulePack,
  deleteRulePack,
  disableRule,
  enableRule,
  explainBuiltinPack,
  explainRulePack,
  generateRulePack,
  getBuiltinPackContent,
  listBuiltinPacks,
  listDisabledRules,
  listRulePacks,
  listRuleSchemas,
  packTypeLabel,
  toggleRulePack,
  updateRulePack
} from '@/api/rules'

const tab = ref('read')
const packTypes: PackType[] = ['format', 'clause', 'field', 'cross']
const builtins = ref<BuiltinPack[]>([])
const packs = ref<RulePack[]>([])
const disabledRules = ref<DisabledRuleItem[]>([])
const uploading = ref(false)
const formatFields = ref<SchemaField[]>([])

// ---------- ① 看规则 ----------
const selected = ref<
  | { kind: 'builtin'; file: string; name: string; pack_type: PackType }
  | { kind: 'custom'; id: string; name: string; pack_type: PackType }
  | null
>(null)
const explain = ref<ExplainResult | null>(null)
const explainLoading = ref(false)
const selectedName = computed(() => selected.value?.name ?? '')

async function selectBuiltin(b: BuiltinPack) {
  selected.value = { kind: 'builtin', file: b.file, name: b.name, pack_type: b.pack_type }
  explainLoading.value = true
  try {
    explain.value = await explainBuiltinPack(b.file)
  } catch {
    ElMessage.error('读取规则说明失败')
    explain.value = null
  } finally {
    explainLoading.value = false
  }
}

async function selectCustom(p: RulePack) {
  selected.value = { kind: 'custom', id: p.id, name: p.name, pack_type: p.pack_type }
  // 说明在「① 看规则」页签里，必须切过去，否则用户点了「看说明」看不出任何变化
  tab.value = 'read'
  explainLoading.value = true
  try {
    const content = parseContent(p.yaml_content)
    explain.value = await explainRulePack(p.pack_type, content)
  } catch {
    ElMessage.error('该规则包内容无法解析，可能已损坏')
    explain.value = null
  } finally {
    explainLoading.value = false
  }
}

function parseContent(raw: string): Record<string, unknown> {
  if (!raw) return {}
  const v = typeof raw === 'string' ? JSON.parse(raw) : raw
  return (v ?? {}) as Record<string, unknown>
}

function sevTagType(sev: string | null): TagType {
  if (sev === 'error') return 'danger'
  if (sev === 'warning') return 'warning'
  return 'info'
}

// ---------- ② 编辑 ----------
interface VisualClause { name: string; strong: string; weak: string; severity: string }
interface FieldRow { key: string; label: string; type: string; required: boolean; patterns: string }
interface CrossRow { id: string; name: string; fields: string; severity: string; description: string }

const visualClauses = ref<VisualClause[]>([])
const fieldRows = ref<FieldRow[]>([])
const crossRows = ref<CrossRow[]>([])
const formatModel = ref<Record<string, any>>({})

const fieldTypes = [
  { value: 'text', label: '文字' },
  { value: 'number', label: '数字' },
  { value: 'date', label: '日期' },
  { value: 'money', label: '金额' },
  { value: 'party', label: '当事人' }
]

const form = ref({
  name: '',
  pack_type: 'clause' as PackType,
  doc_type: 'contract',
  description: '',
  yaml_content: ''
})
// 非空表示正在编辑已有包（保存时走更新而不是新建）
const editingId = ref<string | null>(null)

const PACK_TYPE_HINTS: Record<PackType, string> = {
  format: '管排版：纸张大小、页边距、字体字号、缩进、标题层级。全部是客观测量，纯规则判定，不花 token。',
  clause: '管内容完整性：合同必须包含哪些条款。关键词直接命中算存在；拿不准的交大模型结合上下文判断。',
  field: '管信息提取：自动抓出合同金额、签订日期、甲乙方等。正则先抓，抓不到再让大模型补。',
  cross: '管前后一致：大小写金额、单价×数量、起止日期等互相对照，属于确定性计算。'
}
const packTypeHint = (t: PackType) => PACK_TYPE_HINTS[t] || ''

// 格式规则按语义分组，避免一长串裸参数
const FORMAT_GROUPS: { key: string; title: string; desc: string }[] = [
  { key: 'page.size', title: '① 纸张尺寸', desc: '规定文档用多大的纸，以及允许的尺寸误差。' },
  { key: 'page.margin_cm', title: '② 页边距', desc: '正文与纸张四边应保持的距离，避免装订遮挡。' },
  { key: 'font', title: '③ 字体与字号', desc: '正文允许的字体和字号范围。' },
  { key: 'paragraph', title: '④ 段落排版', desc: '首行缩进，以及为短段落预留的容错。' },
  { key: 'heading', title: '⑤ 标题层级', desc: '标题编号是否跳级。' }
]

function groupOf(key: string): string {
  const parts = key.split('.')
  return key.startsWith('page.') ? parts.slice(0, 2).join('.') : parts[0]
}

const formatGroups = computed(() =>
  FORMAT_GROUPS.map((g) => ({
    ...g,
    fields: formatFields.value.filter((f) => groupOf(f.key) === g.key)
  })).filter((g) => g.fields.length)
)

const split = (s: string) => s.split(/[,，、;\s]+/).map((x) => x.trim()).filter(Boolean)
const arrToText = (v: unknown) => (Array.isArray(v) ? v.join(', ') : v === undefined || v === null ? '' : String(v))
const textToArr = (v: string) => v.split(/[,，、;\s]+/).map((x) => x.trim()).filter(Boolean)
const numArr = (v: string) => textToArr(v).map((x) => Number(x)).filter((n) => !Number.isNaN(n))

function setPath(obj: Record<string, unknown>, path: string, value: unknown) {
  const keys = path.split('.')
  let cur = obj
  for (let i = 0; i < keys.length - 1; i += 1) {
    if (typeof cur[keys[i]] !== 'object' || cur[keys[i]] === null) cur[keys[i]] = {}
    cur = cur[keys[i]] as Record<string, unknown>
  }
  cur[keys[keys.length - 1]] = value
}

function getPath(obj: Record<string, unknown>, path: string): unknown {
  return path.split('.').reduce<unknown>((acc, k) => {
    if (acc && typeof acc === 'object') return (acc as Record<string, unknown>)[k]
    return undefined
  }, obj)
}

function onPackTypeChange() {
  resetEditors()
}

function resetEditors() {
  visualClauses.value = [{ name: '', strong: '', weak: '', severity: 'error' }]
  fieldRows.value = [{ key: '', label: '', type: 'text', required: true, patterns: '' }]
  crossRows.value = [{ id: '', name: '', fields: '', severity: 'error', description: '' }]
  formatModel.value = {}
  fillFormatDefaults()
}

function fillFormatDefaults() {
  for (const f of formatFields.value) {
    if (f.default !== undefined) formatModel.value[f.key] = f.default
  }
}

function resetForm() {
  editingId.value = null
  form.value = { name: '', pack_type: 'clause', doc_type: 'contract', description: '', yaml_content: '' }
  resetEditors()
}

/** 把「我的规则包」回填进编辑器，实现真正的「修改」（原来只有新增/启停/删除） */
function editPack(p: RulePack) {
  let content: Record<string, any> = {}
  try {
    content = parseContent(p.yaml_content)
  } catch {
    ElMessage.error('该规则包内容无法解析，无法载入编辑器')
    return
  }
  resetForm()
  editingId.value = p.id
  form.value.name = p.name
  form.value.pack_type = p.pack_type
  form.value.doc_type = p.doc_type
  form.value.description = p.description ?? ''

  if (p.pack_type === 'clause') {
    visualClauses.value = (content.clauses ?? []).map((c: any) => ({
      name: String(c.name ?? ''),
      strong: Array.isArray(c.strong) ? c.strong.join(', ') : String(c.strong ?? ''),
      weak: Array.isArray(c.weak) ? c.weak.join(', ') : String(c.weak ?? ''),
      severity: c.severity || 'error'
    }))
  } else if (p.pack_type === 'field') {
    fieldRows.value = (content.fields ?? []).map((f: any) => ({
      key: String(f.key ?? ''),
      label: String(f.label ?? ''),
      type: f.type || 'text',
      required: f.required !== false,
      patterns: Array.isArray(f.patterns) ? f.patterns.join(', ') : String(f.patterns ?? '')
    }))
  } else if (p.pack_type === 'cross') {
    crossRows.value = (content.checks ?? []).map((c: any) => ({
      id: String(c.id ?? ''),
      name: String(c.name ?? ''),
      fields: Array.isArray(c.fields) ? c.fields.join(', ') : String(c.fields ?? ''),
      severity: c.severity || 'error',
      description: String(c.description ?? '')
    }))
  } else {
    // 格式包：把已知键回填，未识别的键保留在预览里即可
    const model: Record<string, unknown> = {}
    for (const f of formatFields.value) {
      if (content[f.key] !== undefined) model[f.key] = content[f.key]
    }
    formatModel.value = model
  }
  tab.value = 'edit'
  ElMessage.success(`已载入「${p.name}」，修改后点「保存并启用」覆盖原包`)
}

/** 一键填入示例，解决「不知道怎么填」 */
function fillExample() {
  resetEditors()
  if (form.value.pack_type === 'clause') {
    form.value.name = form.value.name || '付款条款审查包'
    visualClauses.value = [
      { name: '付款期限', strong: '付款期限, 支付期限, 付款时间, 结算期限', weak: '逾期', severity: 'error' },
      { name: '当事人信息', strong: '甲方, 乙方, 名称, 住所', weak: '', severity: 'error' }
    ]
  } else if (form.value.pack_type === 'field') {
    form.value.name = form.value.name || '关键字段抽取包'
    fieldRows.value = [
      { key: 'contract_amount', label: '合同金额', type: 'money', required: true, patterns: '合同总价, 合同金额, 总价款' },
      { key: 'sign_date', label: '签订日期', type: 'date', required: true, patterns: '签订日期, 签署日期, 签订时间' }
    ]
  } else if (form.value.pack_type === 'cross') {
    form.value.name = form.value.name || '金额一致性勾稽包'
    crossRows.value = [
      { id: 'amount.consistency', name: '金额大小写一致', fields: 'amount_words, amount_digits', severity: 'error', description: '核对大写金额与小写金额是否相等' }
    ]
  } else {
    form.value.name = form.value.name || '我方排版规范'
    form.value.doc_type = 'global'
    fillFormatDefaults()
  }
  ElMessage.success('已填入示例，可在此基础上修改')
}

/** 可视化表单 → JSON 内容 */
function buildJsonContent(): string {
  if (form.value.pack_type === 'clause') {
    const clauses = visualClauses.value
      .filter((r) => r.name.trim() && split(r.strong).length)
      .map((r, i) => ({
        id: `custom_${i + 1}`,
        name: r.name.trim(),
        required: true,
        severity: r.severity || 'error',
        strong: split(r.strong),
        weak: split(r.weak)
      }))
    return JSON.stringify({ version: 1, doc_types: [form.value.doc_type || 'contract'], clauses }, null, 2)
  }
  if (form.value.pack_type === 'field') {
    const fields = fieldRows.value
      .filter((r) => r.key.trim() && r.label.trim())
      .map((r) => ({
        key: r.key.trim(),
        label: r.label.trim(),
        type: r.type,
        required: r.required,
        patterns: split(r.patterns)
      }))
    return JSON.stringify({ version: 1, doc_types: [form.value.doc_type || 'contract'], fields }, null, 2)
  }
  if (form.value.pack_type === 'cross') {
    const checks = crossRows.value
      .filter((r) => r.id.trim() && r.fields.trim())
      .map((r) => ({
        id: r.id.trim(),
        name: r.name.trim(),
        fields: split(r.fields),
        severity: r.severity || 'error',
        description: r.description.trim() || undefined
      }))
    return JSON.stringify({ version: 1, doc_types: [form.value.doc_type || 'contract'], checks }, null, 2)
  }
  const root: Record<string, unknown> = { version: 1 }
  for (const f of formatFields.value) {
    const v = formatModel.value[f.key]
    if (v !== undefined && v !== '' && !(Array.isArray(v) && !v.length)) setPath(root, f.key, v)
  }
  return JSON.stringify(root, null, 2)
}

// 实时预览：内容变化 500ms 后请求后端「翻译成大白话」
const preview = ref<ExplainResult | null>(null)
const previewLoading = ref(false)
let previewTimer: number | undefined
const previewKey = computed(() => `${form.value.pack_type}::${buildJsonContent()}`)

watch(
  previewKey,
  () => {
    if (previewTimer) window.clearTimeout(previewTimer)
    previewTimer = window.setTimeout(loadPreview, 500)
  },
  { immediate: false }
)

async function loadPreview() {
  const json = buildJsonContent()
  let content: Record<string, unknown> = {}
  try {
    content = parseContent(json)
  } catch {
    return
  }
  previewLoading.value = true
  try {
    preview.value = await explainRulePack(form.value.pack_type, content)
  } catch {
    preview.value = null
  } finally {
    previewLoading.value = false
  }
}

// ---------- 一句话生成 ----------
const nlText = ref('')
const nlPackType = ref<PackType>('clause')
const generating = ref(false)
const nlPlaceholder = computed(() => {
  const map: Record<PackType, string> = {
    clause: '例如：合同必须有验收条款和质保条款，验收要写清验收标准和期限',
    field: '例如：帮我自动提取合同金额、签订日期和甲方名称',
    cross: '例如：核对大写金额和小写金额是否一致，单价乘以数量是否等于总价',
    format: '例如：要求 A4 纸，正文用宋体小四，行距和页边距按公文标准'
  }
  return map[nlPackType.value]
})

async function onGenerate() {
  if (!nlText.value.trim()) {
    ElMessage.warning('先用一句话说说你想检查什么')
    return
  }
  generating.value = true
  try {
    const res = await generateRulePack({
      description: nlText.value.trim(),
      pack_type: nlPackType.value,
      doc_type: form.value.doc_type || 'contract'
    })
    form.value.pack_type = res.pack_type
    if (!form.value.name.trim()) form.value.name = `AI 生成：${nlText.value.trim().slice(0, 12)}`
    applyGenerated(res.content)
    ElMessage.success('已填入表单，请检查后保存')
    loadPreview()
  } catch (e: unknown) {
    const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
    ElMessage.error(detail || '生成失败，请换个说法再试')
  } finally {
    generating.value = false
  }
}

function applyGenerated(content: Record<string, unknown>) {
  if (form.value.pack_type === 'clause') {
    const clauses = (content.clauses as Array<Record<string, unknown>>) || []
    visualClauses.value = clauses.length
      ? clauses.map((c) => ({
          name: String(c.name || ''),
          strong: (c.strong as string[])?.join(', ') || '',
          weak: (c.weak as string[])?.join(', ') || '',
          severity: String(c.severity || 'error')
        }))
      : [{ name: '', strong: '', weak: '', severity: 'error' }]
  } else if (form.value.pack_type === 'field') {
    const fields = (content.fields as Array<Record<string, unknown>>) || []
    fieldRows.value = fields.length
      ? fields.map((f) => ({
          key: String(f.key || ''),
          label: String(f.label || ''),
          type: String(f.type || 'text'),
          required: Boolean(f.required),
          patterns: (f.patterns as string[])?.join(', ') || ''
        }))
      : fieldRows.value
  } else if (form.value.pack_type === 'cross') {
    const checks = (content.checks as Array<Record<string, unknown>>) || []
    crossRows.value = checks.length
      ? checks.map((c) => ({
          id: String(c.id || ''),
          name: String(c.name || ''),
          fields: (c.fields as string[])?.join(', ') || '',
          severity: String(c.severity || 'error'),
          description: String(c.description || '')
        }))
      : crossRows.value
  } else {
    for (const f of formatFields.value) {
      const v = getPath(content, f.key)
      if (v !== undefined) formatModel.value[f.key] = v
    }
  }
}

// ---------- 载入内置包到编辑器（复制为自定义） ----------
async function onCopyBuiltin(row: BuiltinPack) {
  try {
    const resp = await getBuiltinPackContent(row.file)
    const content = parseContent(typeof resp.content === 'string' ? resp.content : JSON.stringify(resp.content))
    form.value.name = `我的${row.name}`
    form.value.pack_type = row.pack_type
    form.value.doc_type = row.doc_type
    form.value.description = ''
    resetEditors()
    applyGenerated(content)
    tab.value = 'edit'
    loadPreview()
    ElMessage.success(`已载入「${row.name}」，可在下方修改后保存`)
  } catch {
    ElMessage.error('载入内置规则包失败')
  }
}

async function load() {
  const [b, p, d] = await Promise.all([
    listBuiltinPacks(),
    listRulePacks(),
    listDisabledRules().catch(() => [])
  ])
  builtins.value = b
  packs.value = p
  disabledRules.value = d
  formatFields.value = (await listRuleSchemas()).format.fields
  fillFormatDefaults()
}

async function onEnableRule(row: DisabledRuleItem) {
  await enableRule({ pack_type: row.pack_type, rule_id: row.rule_id, scope: row.scope })
  ElMessage.success('已恢复该规则')
  await load()
}

async function onDisableRule(packType: PackType, ruleId: string, title: string) {
  try {
    await ElMessageBox.confirm(
      `停用「${title}」这条规则？停用后它不再参与检查，报告页会注明「已停用规则」，不会伪装成「查过没问题」。`,
      '停用规则',
      { type: 'warning', confirmButtonText: '停用', cancelButtonText: '取消' }
    )
  } catch {
    return
  }
  await disableRule({ pack_type: packType, rule_id: ruleId })
  ElMessage.success('已停用该规则')
  await load()
}

function onUpload() {
  if (!form.value.name.trim()) {
    ElMessage.warning('请填写规则包名称')
    return
  }
  const json = buildJsonContent()
  // 按实际数组长度校验：原先用 json.includes('"clauses": [') 判断，
  // 空数组同样包含这个子串，导致空规则包也能保存。
  const listKey = ({ clause: 'clauses', field: 'fields', cross: 'checks' } as Partial<Record<PackType, string>>)[form.value.pack_type]
  if (listKey) {
    let parsed: Record<string, unknown>
    try {
      parsed = JSON.parse(json)
    } catch {
      ElMessage.error('生成的规则内容不是合法 JSON，请检查填写')
      return
    }
    const list = parsed[listKey]
    if (!Array.isArray(list) || list.length === 0) {
      const hints: Record<string, string> = {
        clause: '请至少填写一条条款：条款名称 + 必备关键词',
        field: '请至少添加一个字段：字段键 + 中文名',
        cross: '请至少添加一条勾稽规则：规则 ID + 要对照的字段'
      }
      ElMessage.warning(hints[form.value.pack_type] ?? '规则内容不能为空')
      return
    }
  }
  uploading.value = true
  const payload = {
    name: form.value.name.trim(),
    pack_type: form.value.pack_type,
    doc_type: form.value.doc_type.trim() || 'contract',
    yaml_content: json,
    description: form.value.description.trim() || undefined
  }
  const req = editingId.value
    ? updateRulePack(editingId.value, {
        name: payload.name,
        description: payload.description,
        yaml_content: payload.yaml_content
      })
    : createRulePack(payload)
  req
    .then(() => {
      ElMessage.success(editingId.value ? '已更新，立即生效' : '保存成功，已生效')
      resetForm()
      preview.value = null
      load()
    })
    .catch((e: { response?: { data?: { detail?: string } } }) => {
      ElMessage.error(e.response?.data?.detail || '保存失败')
    })
    .finally(() => {
      uploading.value = false
    })
}

async function onToggle(row: RulePack) {
  await toggleRulePack(row.id, !row.enabled)
  ElMessage.success(row.enabled ? '已停用' : '已启用')
  load()
}

async function onDelete(row: RulePack) {
  try {
    await ElMessageBox.confirm(`确认删除规则包「${row.name}」？`, '提示', { type: 'warning' })
  } catch {
    return
  }
  await deleteRulePack(row.id)
  ElMessage.success('已删除')
  load()
}

onMounted(async () => {
  resetForm()
  await load()
  // 默认展示第一个内置规则包的人话说明，页面一进来就有内容
  if (builtins.value.length) selectBuiltin(builtins.value[0])
})
</script>

<style scoped>
.hero {
  margin-bottom: 12px;
  border: none;
  background: linear-gradient(90deg, #ecf5ff 0%, #f5f7fa 100%);
}
.hero-title {
  font-size: 16px;
  font-weight: 700;
  color: #303133;
  margin-bottom: 6px;
}
.hero-desc {
  font-size: 13px;
  color: #606266;
  line-height: 1.8;
}
.main-tabs {
  margin-top: 4px;
}
.head-note {
  margin-left: 10px;
  font-size: 12px;
  color: #909399;
  font-weight: 400;
}
.sub-title {
  font-size: 12px;
  color: #909399;
  margin-bottom: 6px;
}
.pack-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 9px 10px;
  border-radius: 6px;
  cursor: pointer;
  border: 1px solid transparent;
}
.pack-row:hover {
  background: #f5f7fa;
}
.pack-row.active {
  background: #ecf5ff;
  border-color: #b3d8ff;
}
.pack-name {
  font-size: 13px;
  color: #303133;
  display: flex;
  align-items: center;
  gap: 6px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.explain-head {
  display: flex;
  align-items: center;
  gap: 10px;
}
.explain-source {
  font-size: 12px;
  color: #909399;
}
.explain-summary {
  font-size: 13px;
  color: #606266;
  margin-bottom: 10px;
}
.badge {
  display: inline-block;
  padding: 1px 8px;
  border-radius: 10px;
  font-size: 12px;
  margin-left: 4px;
}
.badge.rule {
  background: #f4f4f5;
  color: #909399;
}
.badge.hybrid {
  background: #fdf6ec;
  color: #e6a23c;
}
.badge.llm {
  background: #f0f9eb;
  color: #67c23a;
}
.explain-list,
.preview-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
  max-height: 60vh;
  overflow-y: auto;
}
.explain-item,
.preview-item {
  border: 1px solid #ebeef5;
  border-left: 3px solid #409eff;
  border-radius: 6px;
  padding: 10px 12px;
}
.explain-item-head {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 4px;
}
.idx {
  display: inline-block;
  width: 18px;
  height: 18px;
  line-height: 18px;
  text-align: center;
  border-radius: 50%;
  background: #e9eef5;
  color: #606266;
  font-size: 11px;
  margin-right: 6px;
}
.explain-title {
  font-weight: 600;
  font-size: 14px;
  color: #303133;
}
.explain-detail,
.preview-detail {
  font-size: 13px;
  color: #606266;
  line-height: 1.75;
}
.preview-summary {
  font-size: 13px;
  color: #606266;
  margin-bottom: 10px;
}
.preview-card {
  position: sticky;
  top: 0;
}
.type-hint {
  font-size: 12px;
  color: #909399;
  line-height: 1.7;
  margin: -8px 0 14px;
  padding: 8px 10px;
  background: #f5f7fa;
  border-radius: 6px;
}
.field-group {
  border-top: 1px dashed #ebeef5;
  padding-top: 10px;
  margin-bottom: 6px;
}
.field-group-head {
  display: flex;
  align-items: baseline;
  gap: 10px;
  margin-bottom: 8px;
}
.field-group-title {
  font-weight: 600;
  font-size: 14px;
  color: #303133;
}
.field-group-desc {
  font-size: 12px;
  color: #909399;
}
.row-editor {
  display: flex;
  flex-direction: column;
  gap: 8px;
  border-top: 1px dashed #ebeef5;
  padding-top: 12px;
}
.row-head {
  display: flex;
  gap: 8px;
  font-size: 12px;
  color: #909399;
  padding: 0 2px;
}
.row-tip {
  font-size: 12px;
  color: #909399;
  background: #f5f7fa;
  border-radius: 6px;
  padding: 8px 10px;
  line-height: 1.7;
}
.row-line {
  display: flex;
  gap: 8px;
  align-items: center;
  flex-wrap: wrap;
}
.hint {
  font-size: 12px;
  color: #909399;
  line-height: 1.6;
  width: 100%;
}
.form-actions {
  margin-top: 16px;
  display: flex;
  gap: 8px;
}
</style>
