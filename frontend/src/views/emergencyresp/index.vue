<template>
  <section class="page" data-module="emergencyresp">
    <header class="page-head">
      <div>
        <h2>应急备品管理</h2>
        <p class="page-desc">围绕备品编号做登记、领用与补充：储备充足 → 已领用/储备不足 → 补充后回到储备充足，每步留时间与经手人。</p>
      </div>
      <div class="page-actions">
        <label class="operator-box">
          <span>当前经手人</span>
          <input v-model="currentOperator" placeholder="交班后填写接手人" />
        </label>
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
        <span>备品编号 / 名称</span>
        <input v-model="keyword" placeholder="按备品编号或名称检索" />
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
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <template v-for="row in rows" :key="String(row.id)">
          <tr>
            <td>{{ row['备品编号'] }}</td>
            <td>{{ row['备品名称'] }}</td>
            <td>{{ row['规格型号'] }}</td>
            <td>{{ row['适用场景'] }}</td>
            <td>{{ row['存放地点'] }}</td>
            <td>{{ row['保有数量'] }}</td>
            <td>
              <button class="link" type="button" @click="toggleDetail(row.id)">
                {{ row['领用记录摘要'] }}（查看）
              </button>
            </td>
            <td>
              <span class="status-tag" :class="statusClass(row.status)">{{ row.status }}</span>
            </td>
            <td class="row-actions">
              <button
                v-for="action in availableActions(row.status)"
                :key="action"
                class="link"
                type="button"
                @click="openAction(action, row)"
              >
                {{ action }}
              </button>
            </td>
          </tr>
          <tr v-if="expandedId === row.id" class="detail-row">
            <td :colspan="columns.length + 1">
              <div class="detail-grid">
                <div class="detail-block">
                  <h4>领用记录（挂在备品编号 {{ row['备品编号'] }} 下）</h4>
                  <table v-if="row['领用记录']?.length" class="sub-table">
                    <thead>
                      <tr>
                        <th>记录编号</th><th>领用时间</th><th>经手人</th><th>领用数量</th><th>领用事由</th>
                      </tr>
                    </thead>
                    <tbody>
                      <tr v-for="record in row['领用记录']" :key="record['记录编号']">
                        <td>{{ record['记录编号'] }}</td>
                        <td>{{ record['时间'] }}</td>
                        <td>{{ record['经手人'] }}</td>
                        <td>{{ record['领用数量'] }}</td>
                        <td>{{ record['领用事由'] }}</td>
                      </tr>
                    </tbody>
                  </table>
                  <p v-else class="empty-hint">暂无领用记录</p>
                </div>
                <div class="detail-block">
                  <h4>状态流水（每步留时间与经手人）</h4>
                  <table class="sub-table">
                    <thead>
                      <tr>
                        <th>时间</th><th>动作</th><th>原状态</th><th>新状态</th><th>经手人</th>
                      </tr>
                    </thead>
                    <tbody>
                      <tr v-for="(log, index) in row['状态流水']" :key="index">
                        <td>{{ log['时间'] }}</td>
                        <td>{{ log['动作'] }}</td>
                        <td>{{ log['原状态'] }}</td>
                        <td>{{ log['新状态'] }}</td>
                        <td>{{ log['经手人'] }}</td>
                      </tr>
                    </tbody>
                  </table>
                </div>
              </div>
            </td>
          </tr>
        </template>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 1" class="empty-state">暂无应急备品数据，可先登记应急备品</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条应急备品记录</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>

    <!-- 动作弹窗：领用登记 / 补充储备 / 申请报废 -->
    <div v-if="dialog.open" class="modal-mask" @click.self="closeDialog">
      <div class="modal">
        <h3>{{ dialog.action }} · {{ dialog.row?.['备品编号'] }}</h3>
        <p class="modal-tip" v-if="dialog.action === '领用登记'">
          保存后库存即时扣减；库存为 0 置「已领用」，仍有余额置「储备不足」。两个页面同时领用只生效一次。
        </p>
        <p class="modal-tip" v-else-if="dialog.action === '补充储备'">补充后状态回到「储备充足」。</p>
        <p class="modal-tip" v-else>报废后备品不可再领用或补充。</p>

        <label class="form-item">
          <span>经手人 *</span>
          <input v-model="dialog.form.operator" placeholder="请填写实际经手人" />
        </label>
        <label v-if="dialog.action === '领用登记'" class="form-item">
          <span>领用数量 *</span>
          <input v-model="dialog.form.amount" type="number" min="1" placeholder="正整数" />
        </label>
        <label v-if="dialog.action === '领用登记'" class="form-item">
          <span>领用事由 *</span>
          <textarea v-model="dialog.form.reason" rows="3" placeholder="如：K128 区间红光带应急抢修"></textarea>
        </label>
        <label v-if="dialog.action === '补充储备'" class="form-item">
          <span>补充数量 *</span>
          <input v-model="dialog.form.amount" type="number" min="1" placeholder="正整数" />
        </label>

        <p v-if="dialog.error" class="error-text">{{ dialog.error }}</p>
        <div class="modal-actions">
          <button class="btn ghost" type="button" :disabled="dialog.submitting" @click="closeDialog">取消</button>
          <button class="btn primary" type="button" :disabled="dialog.submitting" @click="submitDialog">
            {{ dialog.submitting ? '提交中…' : '保存' }}
          </button>
        </div>
      </div>
    </div>

    <!-- 登记弹窗 -->
    <div v-if="createOpen" class="modal-mask" @click.self="createOpen = false">
      <div class="modal">
        <h3>登记应急备品</h3>
        <label v-for="field in createFields" :key="field.key" class="form-item">
          <span>{{ field.label }}<i v-if="field.required">*</i></span>
          <input v-model="createForm[field.key]" :type="field.type || 'text'" :placeholder="`请填写${field.label}`" />
        </label>
        <p v-if="createError" class="error-text">{{ createError }}</p>
        <div class="modal-actions">
          <button class="btn ghost" type="button" :disabled="createSubmitting" @click="createOpen = false">取消</button>
          <button class="btn primary" type="button" :disabled="createSubmitting" @click="submitCreate">
            {{ createSubmitting ? '提交中…' : '保存' }}
          </button>
        </div>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'

import { request } from '@/api/client'
import { useSessionStore } from '@/stores/session'

const ENDPOINT = '/api/emergencyresp'
const columns = ['备品编号', '备品名称', '规格型号', '适用场景', '存放地点', '保有数量', '领用记录', '备品状态']
const statuses = ['储备充足', '储备不足', '已领用', '已报废']

type ClaimRecord = {
  记录编号: string
  时间: string
  经手人: string
  领用数量: number
  领用事由: string
  关联备品: string
}
type StatusLog = { 时间: string; 动作: string; 原状态: string; 新状态: string; 经手人: string }
type Row = {
  id: number
  version: number
  status: string
  保有数量: number
  领用记录: ClaimRecord[]
  状态流水: StatusLog[]
  领用记录摘要: string
  [key: string]: string | number | ClaimRecord[] | StatusLog[]
}

const session = useSessionStore()

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const keyword = ref('')
const statusFilter = ref('')
const expandedId = ref<number | null>(null)
const currentOperator = ref(session.operator)

const stats = computed(() => [
  { label: '备品种类', value: total.value },
  { label: '不足备品', value: rows.value.filter((row) => row.status === '储备不足').length },
  { label: '已领用备品', value: rows.value.filter((row) => row.status === '已领用').length },
])

function availableActions(status: string): string[] {
  switch (status) {
    case '储备充足':
      return ['领用登记', '申请报废']
    case '储备不足':
      return ['领用登记', '补充储备', '申请报废']
    case '已领用':
      return ['补充储备', '申请报废']
    default:
      return []
  }
}

function statusClass(status: string): string {
  return {
    储备充足: 'tag-ready',
    储备不足: 'tag-low',
    已领用: 'tag-claimed',
    已报废: 'tag-scrapped',
  }[status] ?? ''
}

function toggleDetail(id: number) {
  expandedId.value = expandedId.value === id ? null : id
}

function resetFilters() {
  keyword.value = ''
  statusFilter.value = ''
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

async function readError(response: Response, fallback: string): Promise<string> {
  try {
    const payload = (await response.json()) as { detail?: string }
    return payload.detail || fallback
  } catch {
    return fallback
  }
}

async function reload() {
  errorMessage.value = ''
  const query = new URLSearchParams()
  if (keyword.value.trim()) query.set('keyword', keyword.value.trim())
  if (statusFilter.value) query.set('status', statusFilter.value)
  try {
    const response = await request(`${ENDPOINT}?${query.toString()}`)
    if (!response.ok) {
      throw new Error(await readError(response, '应急备品列表读取失败'))
    }
    const payload = (await response.json()) as { items?: Row[]; total?: number }
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '应急备品列表读取失败'
  }
}

// ---------- 动作弹窗 ----------
const dialog = reactive({
  open: false,
  submitting: false,
  action: '',
  error: '',
  row: null as Row | null,
  form: { operator: '', amount: '', reason: '' },
})

function openAction(action: string, row: Row) {
  dialog.open = true
  dialog.action = action
  dialog.row = row
  dialog.error = ''
  dialog.form = { operator: currentOperator.value, amount: '', reason: '' }
}

function closeDialog() {
  dialog.open = false
  dialog.row = null
}

async function submitDialog() {
  if (!dialog.row) return
  dialog.error = ''

  const missing: string[] = []
  if (!dialog.form.operator.trim()) missing.push('经手人')
  if (dialog.action !== '申请报废' && !dialog.form.amount.trim()) {
    missing.push(dialog.action === '领用登记' ? '领用数量' : '补充数量')
  }
  if (dialog.action === '领用登记' && !dialog.form.reason.trim()) missing.push('领用事由')
  if (missing.length) {
    dialog.error = `资料不全，不允许保存，缺少：${missing.join('、')}`
    return
  }

  const values: Record<string, string | number> = {
    action: dialog.action,
    经手人: dialog.form.operator.trim(),
    expected_version: dialog.row.version,
  }
  if (dialog.action === '领用登记') {
    values['领用数量'] = dialog.form.amount
    values['领用事由'] = dialog.form.reason.trim()
  } else if (dialog.action === '补充储备') {
    values['补充数量'] = dialog.form.amount
  }

  dialog.submitting = true
  try {
    const response = await request(`${ENDPOINT}/${dialog.row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ values }),
    })
    if (!response.ok) {
      const message = await readError(response, '应急备品动作未生效，请稍后重试')
      dialog.error = message
      // 已被占用或状态已被其他页面改动：刷新列表，让接手人看到最新领用记录
      if (response.status === 409 || response.status === 400) {
        await reload()
        if (dialog.row) {
          dialog.row = rows.value.find((item) => item.id === dialog.row?.id) ?? dialog.row
        }
      }
      return
    }
    closeDialog()
    await reload()
  } catch (error) {
    dialog.error = error instanceof Error ? error.message : '应急备品操作失败'
  } finally {
    dialog.submitting = false
  }
}

// ---------- 登记弹窗 ----------
const createFields: { key: string; label: string; required?: boolean; type?: string }[] = [
  { key: '备品编号', label: '备品编号', required: true },
  { key: '备品名称', label: '备品名称', required: true },
  { key: '规格型号', label: '规格型号', required: true },
  { key: '适用场景', label: '适用场景' },
  { key: '存放地点', label: '存放地点' },
  { key: '保有数量', label: '保有数量', type: 'number' },
  { key: '经手人', label: '经手人' },
]

const createOpen = ref(false)
const createSubmitting = ref(false)
const createError = ref('')
const createForm = reactive<Record<string, string>>({})

function openCreate() {
  createFields.forEach((field) => {
    createForm[field.key] = field.key === '经手人' ? currentOperator.value : ''
  })
  createError.value = ''
  createOpen.value = true
}

async function submitCreate() {
  createError.value = ''
  const missing = createFields
    .filter((field) => field.required && !createForm[field.key]?.trim())
    .map((field) => field.label)
  if (missing.length) {
    createError.value = `资料不全，不允许保存，缺少：${missing.join('、')}`
    return
  }
  createSubmitting.value = true
  try {
    const response = await request(ENDPOINT, {
      method: 'POST',
      body: JSON.stringify({
        values: { ...createForm, 保有数量: createForm['保有数量'] || '1' },
      }),
    })
    if (!response.ok) {
      createError.value = await readError(response, '应急备品登记失败')
      return
    }
    createOpen.value = false
    await reload()
  } catch (error) {
    createError.value = error instanceof Error ? error.message : '应急备品登记失败'
  } finally {
    createSubmitting.value = false
  }
}

// 交接班后重新进入页面（或切回标签页）时刷新，确保看到上一步的领用记录
function refreshOnVisible() {
  if (document.visibilityState === 'visible') {
    void reload()
  }
}

onMounted(() => {
  void reload()
  document.addEventListener('visibilitychange', refreshOnVisible)
})
</script>

<style scoped>
.page-actions {
  display: flex;
  gap: 8px;
  align-items: flex-end;
}
.operator-box {
  display: flex;
  flex-direction: column;
  gap: 2px;
  font-size: 12px;
  color: var(--muted);
}
.operator-box input {
  padding: 6px 8px;
  border: 1px solid var(--border);
  border-radius: 6px;
}
.filter-item select {
  padding: 4px 8px;
  border: 1px solid var(--border);
  border-radius: 6px;
}
.status-tag {
  display: inline-block;
  padding: 2px 8px;
  border-radius: 10px;
  font-size: 12px;
}
.tag-ready { background: #dcfce7; color: #166534; }
.tag-low { background: #fef3c7; color: #92400e; }
.tag-claimed { background: #fee2e2; color: #991b1b; }
.tag-scrapped { background: #e5e7eb; color: #4b5563; }
.detail-row td { background: #fafbfd; }
.detail-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
  padding: 8px;
}
.detail-block h4 { margin: 4px 0 8px; font-size: 13px; }
.sub-table { width: 100%; border-collapse: collapse; background: #fff; }
.sub-table th, .sub-table td { border: 1px solid var(--border); padding: 5px 8px; font-size: 12px; text-align: left; }
.empty-hint { color: var(--muted); font-size: 12px; }
.modal-mask {
  position: fixed;
  inset: 0;
  background: rgba(15, 23, 42, 0.45);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 20;
}
.modal {
  width: 460px;
  max-height: 85vh;
  overflow: auto;
  background: #fff;
  border-radius: 10px;
  padding: 18px 20px;
}
.modal h3 { margin: 0 0 8px; font-size: 16px; }
.modal-tip { margin: 0 0 10px; color: var(--muted); font-size: 12px; }
.form-item { display: flex; flex-direction: column; gap: 4px; margin-bottom: 10px; font-size: 13px; }
.form-item i { color: #b42318; font-style: normal; margin-left: 2px; }
.form-item input,
.form-item textarea {
  padding: 6px 8px;
  border: 1px solid var(--border);
  border-radius: 6px;
  font-family: inherit;
  font-size: 13px;
}
.modal-actions { display: flex; justify-content: flex-end; gap: 8px; margin-top: 6px; }
.btn:disabled { opacity: 0.6; cursor: not-allowed; }
</style>
