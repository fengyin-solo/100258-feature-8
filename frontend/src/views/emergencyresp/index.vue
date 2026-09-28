<template>
  <section class="page" data-module="emergencyresp">
    <header class="page-head">
      <div>
        <h2>应急备品管理</h2>
        <p class="page-desc">
          备品状态按「储备充足 → 已领用 → 储备不足 →（补充储备）储备充足」逐步流转；
          领用记录挂在备品编号下，每次状态切换都留下时间与经手人。
        </p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">登记应急备品</button>
        <button class="btn" type="button" @click="exportRows">导出应急备品清单</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <form class="filter-bar" @submit.prevent="reload">
      <label class="filter-item">
        <span>备品编号</span>
        <input v-model="keyword" placeholder="按备品编号检索" />
      </label>
      <label class="filter-item">
        <span>备品状态</span>
        <select v-model="statusFilter">
          <option value="">全部状态</option>
          <option v-for="status in statuses" :key="status" :value="status">{{ status }}</option>
        </select>
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
    </form>

    <table class="data-table">
      <thead>
        <tr>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th>状态/领用明细</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)">
          <td v-for="column in columns" :key="column">
            <template v-if="column === '领用记录'">
              <button class="link" type="button" @click="openDetail(row)">
                {{ issueSummary(row) }}
              </button>
            </template>
            <template v-else-if="column === '备品状态'">
              <span class="status-tag" :class="statusClass(row.status)">{{ row['备品状态'] ?? row.status }}</span>
            </template>
            <template v-else>{{ row[column] ?? '—' }}</template>
          </td>
          <td>
            <button class="link" type="button" @click="openDetail(row)">查看状态轨迹与领用记录</button>
          </td>
          <td class="row-actions">
            <button
              v-for="action in allowedActions(row.status)"
              :key="action"
              class="link"
              type="button"
              @click="openAction(action, row)"
            >
              {{ action }}
            </button>
            <span v-if="!allowedActions(row.status).length" class="muted-text">已报废，无可执行动作</span>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 2" class="empty-state">暂无应急备品数据，可先登记应急备品</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条应急备品记录</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>

    <!-- 动作表单：领用登记 / 确认消耗 / 补充储备 / 申请报废 -->
    <div v-if="actionDialog.open" class="modal-mask" @click.self="closeAction">
      <div class="modal">
        <h3 class="modal-title">{{ actionDialog.action }} · {{ actionDialog.row?.['备品编号'] }}</h3>
        <p class="modal-sub">
          当前状态「{{ actionDialog.row?.status }}」，当前经手：{{ session.operator }}（{{ session.shiftLabel }}）
        </p>
        <div v-if="actionDialog.action === '领用登记'" class="modal-tip">
          领用登记只允许在「储备充足」时执行；同一件备品在两个页面同时领用，只有一次生效，另一次会提示已被占用。
        </div>
        <div v-else-if="actionDialog.action === '确认消耗'" class="modal-tip">
          备品实际消耗后盘点不再计入储备，状态由「已领用」变更为「储备不足」，请尽快安排补充储备。
        </div>
        <div v-else-if="actionDialog.action === '补充储备'" class="modal-tip">
          补充后状态由「储备不足」恢复为「储备充足」。
        </div>
        <form class="modal-form" @submit.prevent="submitAction">
          <template v-for="field in actionFields" :key="field.key">
            <label v-if="field.type !== 'readonly'" class="form-item">
              <span>{{ field.label }}<em v-if="field.required">*</em></span>
              <textarea
                v-if="field.type === 'textarea'"
                v-model="actionForm[field.key]"
                rows="2"
                :placeholder="`请填写${field.label}`"
              ></textarea>
              <input
                v-else
                v-model="actionForm[field.key]"
                :type="field.type === 'number' ? 'number' : 'text'"
                :placeholder="`请填写${field.label}`"
              />
            </label>
          </template>
          <p v-if="actionDialog.error" class="error-text form-error">{{ actionDialog.error }}</p>
          <div class="modal-actions">
            <button class="btn" type="button" :disabled="actionDialog.submitting" @click="closeAction">取消</button>
            <button class="btn primary" type="submit" :disabled="actionDialog.submitting">
              {{ actionDialog.submitting ? '提交中…' : '确认保存' }}
            </button>
          </div>
        </form>
      </div>
    </div>

    <!-- 登记新备品 -->
    <div v-if="createDialog.open" class="modal-mask" @click.self="closeCreate">
      <div class="modal">
        <h3 class="modal-title">登记应急备品</h3>
        <form class="modal-form" @submit.prevent="submitCreate">
          <label v-for="field in createFields" :key="field.key" class="form-item">
            <span>{{ field.label }}<em v-if="field.required">*</em></span>
            <input v-model="createForm[field.key]" :type="field.type === 'number' ? 'number' : 'text'" />
          </label>
          <p v-if="createDialog.error" class="error-text form-error">{{ createDialog.error }}</p>
          <div class="modal-actions">
            <button class="btn" type="button" @click="closeCreate">取消</button>
            <button class="btn primary" type="submit">保存登记</button>
          </div>
        </form>
      </div>
    </div>

    <!-- 明细抽屉：领用记录 + 状态轨迹（历史经手人原样保留） -->
    <div v-if="detailRow" class="modal-mask" @click.self="detailRow = null">
      <div class="modal modal-wide">
        <h3 class="modal-title">{{ detailRow['备品编号'] }} · {{ detailRow['备品名称'] }}</h3>
        <p class="modal-sub">
          当前状态「{{ detailRow['备品状态'] ?? detailRow.status }}」 ·
          保有数量 {{ detailRow['保有数量'] }} · 存放地点 {{ detailRow['存放地点'] || '—' }}
        </p>

        <h4 class="section-title">领用记录（挂在备品编号下，原始经手人不被覆盖）</h4>
        <table class="data-table sub-table">
          <thead>
            <tr>
              <th>领用时间</th><th>经手人</th><th>数量</th><th>领用用途</th>
              <th>消耗时间</th><th>消耗确认人</th><th>备注</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="record in issueRecords(detailRow)" :key="String(record['记录编号'])">
              <td>{{ record['领用时间'] }}</td>
              <td>{{ record['经手人'] }}</td>
              <td>{{ record['领用数量'] }}</td>
              <td>{{ record['领用用途'] }}</td>
              <td>{{ record['消耗时间'] || '占用中，尚未确认消耗' }}</td>
              <td>{{ record['消耗确认人'] || '—' }}</td>
              <td>{{ record['备注'] || '—' }}</td>
            </tr>
            <tr v-if="!issueRecords(detailRow).length">
              <td colspan="7" class="empty-state">该备品暂无领用记录</td>
            </tr>
          </tbody>
        </table>

        <h4 class="section-title">状态轨迹（每一步切换的时间与经手人）</h4>
        <ul class="timeline">
          <li v-for="(node, index) in timelineOf(detailRow)" :key="index" class="timeline-item">
            <span class="timeline-time">{{ node['时间'] }}</span>
            <span class="timeline-action">{{ node['动作'] }}</span>
            <span class="timeline-flow">{{ node['由状态'] }} → {{ node['到状态'] }}</span>
            <span class="timeline-operator">经手人：{{ node['经手人'] }}</span>
            <span v-if="node['备注']" class="timeline-note">{{ node['备注'] }}</span>
          </li>
        </ul>

        <div class="modal-actions">
          <button class="btn primary" type="button" @click="detailRow = null">关闭</button>
        </div>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'

import { request } from '@/api/client'
import { useSessionStore } from '@/stores/session'

type Scalar = string | number | null
type Row = Record<string, Scalar>
type Detail = Record<string, unknown>
interface IssueRecord {
  记录编号: number
  领用时间: string
  经手人: string
  领用数量: number
  领用用途: string
  备注: string
  消耗时间: string | null
  消耗确认人: string | null
}
interface TimelineNode {
  时间: string
  动作: string
  经手人: string
  由状态: string
  到状态: string
  备注: string
}
interface FormField {
  key: string
  label: string
  required?: boolean
  type?: 'text' | 'number' | 'textarea' | 'readonly'
}

const ENDPOINT = '/api/emergencyresp'
const columns = ['备品编号', '备品名称', '规格型号', '适用场景', '存放地点', '保有数量', '领用记录', '备品状态']
const statuses = ['储备充足', '已领用', '储备不足', '已报废']

// 状态机口径与后端保持一致：储备充足 → 已领用 → 储备不足 → 储备充足（循环），报废为终态
const ACTION_BY_STATUS: Record<string, string[]> = {
  储备充足: ['领用登记', '申请报废'],
  已领用: ['确认消耗'],
  储备不足: ['补充储备', '申请报废'],
  已报废: [],
}
const ACTION_FIELDS: Record<string, FormField[]> = {
  领用登记: [
    { key: '经手人', label: '经手人', required: true },
    { key: '领用数量', label: '领用数量（件）', required: true, type: 'number' },
    { key: '领用用途', label: '领用用途', required: true, type: 'textarea' },
    { key: '备注', label: '备注' },
  ],
  确认消耗: [
    { key: '经手人', label: '经手人（确认消耗人）', required: true },
  ],
  补充储备: [
    { key: '经手人', label: '经手人', required: true },
    { key: '补充数量', label: '补充数量（件）', required: true, type: 'number' },
  ],
  申请报废: [
    { key: '经手人', label: '经手人', required: true },
    { key: '报废原因', label: '报废原因', type: 'textarea' },
  ],
}
const CREATE_FIELDS: FormField[] = [
  { key: '备品编号', label: '备品编号', required: true },
  { key: '备品名称', label: '备品名称', required: true },
  { key: '规格型号', label: '规格型号', required: true },
  { key: '适用场景', label: '适用场景' },
  { key: '存放地点', label: '存放地点' },
  { key: '保有数量', label: '保有数量（件）', type: 'number' },
  { key: '经手人', label: '登记经手人' },
]

const session = useSessionStore()
const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const keyword = ref('')
const statusFilter = ref('')
const detailRow = ref<Detail | null>(null)

const stats = computed(() => [
  { label: '备品种类', value: rows.value.length },
  { label: '已领用（占用中）', value: rows.value.filter((row) => row.status === '已领用').length },
  { label: '储备不足', value: rows.value.filter((row) => row.status === '储备不足').length },
])

const actionDialog = reactive({
  open: false,
  action: '',
  row: null as Row | null,
  submitting: false,
  error: '',
})
const actionForm = reactive<Record<string, string>>({})
const actionFields = computed<FormField[]>(() => ACTION_FIELDS[actionDialog.action] ?? [])

const createDialog = reactive({ open: false, error: '' })
const createForm = reactive<Record<string, string>>({})
const createFields = CREATE_FIELDS

function allowedActions(status: Scalar): string[] {
  return ACTION_BY_STATUS[String(status)] ?? []
}

function issueRecords(row: Detail): IssueRecord[] {
  const value = row['领用记录']
  return Array.isArray(value) ? (value as IssueRecord[]) : []
}

function timelineOf(row: Detail): TimelineNode[] {
  const value = row['状态轨迹']
  return Array.isArray(value) ? (value as TimelineNode[]) : []
}

function issueSummary(row: Row): string {
  const detail = row as unknown as Detail
  const records = issueRecords(detail)
  if (!records.length) return '暂无领用记录'
  const open = records.filter((item) => !item['消耗时间']).length
  return open ? `共 ${records.length} 条，${open} 条占用中` : `共 ${records.length} 条，均已消耗`
}

function statusClass(status: Scalar): string {
  return {
    储备充足: 'tag-ready',
    已领用: 'tag-taken',
    储备不足: 'tag-low',
    已报废: 'tag-scrapped',
  }[String(status)] ?? ''
}

function resetFilters() {
  keyword.value = ''
  statusFilter.value = ''
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

function openCreate() {
  createDialog.error = ''
  for (const key of Object.keys(createForm)) delete createForm[key]
  createForm['经手人'] = session.operator
  createDialog.open = true
}

function closeCreate() {
  createDialog.open = false
}

async function submitCreate() {
  createDialog.error = ''
  try {
    const response = await request(ENDPOINT, {
      method: 'POST',
      body: JSON.stringify({ values: { ...createForm } }),
    })
    const payload = await response.json()
    if (!response.ok || !payload.ok) {
      createDialog.error = payload.detail || payload.message || '应急备品登记失败'
      return
    }
    createDialog.open = false
    await reload()
  } catch (error) {
    createDialog.error = error instanceof Error ? error.message : '应急备品登记失败'
  }
}

function openAction(action: string, row: Row) {
  actionDialog.open = true
  actionDialog.action = action
  actionDialog.row = row
  actionDialog.submitting = false
  actionDialog.error = ''
  for (const key of Object.keys(actionForm)) delete actionForm[key]
  actionForm['经手人'] = session.operator
}

function closeAction() {
  actionDialog.open = false
  actionDialog.row = null
}

async function submitAction() {
  const row = actionDialog.row
  if (!row) return
  actionDialog.submitting = true
  actionDialog.error = ''
  try {
    // version 做乐观占用：另一页面若已抢先操作，这里会拿到「已被占用」提示
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({
        values: {
          action: actionDialog.action,
          version: row.version ?? 0,
          ...actionForm,
        },
      }),
    })
    const payload = await response.json().catch(() => null)
    if (!response.ok || !payload?.ok) {
      actionDialog.error = payload?.detail || payload?.message || '应急备品动作未生效，请稍后重试'
      await reload()
      const latest = rows.value.find((item) => String(item.id) === String(row.id))
      if (latest) actionDialog.row = latest
      return
    }
    closeAction()
    errorMessage.value = ''
    await reload()
  } catch (error) {
    actionDialog.error = error instanceof Error ? error.message : '应急备品操作失败'
  } finally {
    actionDialog.submitting = false
  }
}

async function openDetail(row: Row) {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}`)
    const payload = await response.json()
    if (!response.ok) {
      throw new Error(payload?.detail || '备品明细读取失败')
    }
    detailRow.value = payload as Detail
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '备品明细读取失败'
  }
}

async function reload() {
  errorMessage.value = ''
  const query = new URLSearchParams()
  if (keyword.value.trim()) query.set('keyword', keyword.value.trim())
  if (statusFilter.value) query.set('status', statusFilter.value)
  const suffix = query.toString()
  try {
    const response = await request(`${ENDPOINT}${suffix ? `?${suffix}` : ''}`)
    const payload = await response.json()
    if (!response.ok) {
      throw new Error(payload?.detail || '应急备品列表读取失败')
    }
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
    // 抽屉若开着也同步最新记录，保证交接班后接手人看到上一步领用情况
    if (detailRow.value) {
      const current = detailRow.value as Row
      const latest = rows.value.find((item) => String(item.id) === String(current.id))
      if (latest) void openDetail(latest)
    }
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '应急备品列表读取失败'
  }
}

// 另一个浏览器页面完成领用后，切回本页即可看到最新状态，避免基于过期页面重复领用
function onWindowFocus() {
  void reload()
}

onMounted(() => {
  void reload()
  window.addEventListener('focus', onWindowFocus)
})
onBeforeUnmount(() => {
  window.removeEventListener('focus', onWindowFocus)
})
</script>

<style scoped>
.muted-text {
  color: var(--muted);
  font-size: 12px;
}
.status-tag {
  display: inline-block;
  padding: 2px 8px;
  border-radius: 10px;
  font-size: 12px;
  border: 1px solid var(--border);
  white-space: nowrap;
}
.tag-ready { color: #067647; background: #ecfdf3; border-color: #abefc6; }
.tag-taken { color: #b54708; background: #fffaeb; border-color: #fedf89; }
.tag-low { color: #b42318; background: #fef3f2; border-color: #fecdca; }
.tag-scrapped { color: #475467; background: #f2f4f7; border-color: #d0d5dd; }

.modal-mask {
  position: fixed;
  inset: 0;
  background: rgba(16, 24, 40, 0.45);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 50;
  padding: 24px;
}
.modal {
  background: #fff;
  border-radius: 10px;
  width: 460px;
  max-width: 100%;
  max-height: 88vh;
  overflow-y: auto;
  padding: 20px 22px;
  box-shadow: 0 12px 32px rgba(16, 24, 40, 0.2);
}
.modal-wide { width: 860px; }
.modal-title { margin: 0; font-size: 16px; }
.modal-sub { margin: 6px 0 12px; color: var(--muted); font-size: 12px; }
.modal-tip {
  background: #f8fafc;
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 8px 10px;
  font-size: 12px;
  color: #475467;
  margin-bottom: 12px;
}
.modal-form { display: flex; flex-direction: column; gap: 10px; }
.form-item { display: flex; flex-direction: column; gap: 4px; font-size: 13px; }
.form-item em { color: #b42318; font-style: normal; margin-left: 2px; }
.form-item input,
.form-item textarea {
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 6px 8px;
  font: inherit;
}
.form-error { margin: 0; }
.modal-actions { display: flex; justify-content: flex-end; gap: 8px; margin-top: 4px; }
.section-title { font-size: 14px; margin: 16px 0 8px; }
.sub-table th, .sub-table td { font-size: 12px; padding: 6px 8px; }
.timeline { list-style: none; margin: 0; padding: 0; border-left: 2px solid var(--border); }
.timeline-item {
  position: relative;
  padding: 6px 0 10px 16px;
  font-size: 12px;
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: baseline;
}
.timeline-item::before {
  content: '';
  position: absolute;
  left: -5px;
  top: 10px;
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--brand);
}
.timeline-time { color: var(--muted); }
.timeline-action { font-weight: 600; }
.timeline-flow { color: #475467; }
.timeline-operator { color: #067647; }
.timeline-note { flex-basis: 100%; color: var(--muted); }
</style>
