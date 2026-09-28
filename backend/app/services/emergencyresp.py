"""应急备品业务规则：状态流转、领用记录、字段校验与并发占用都收在这里。

状态序列：储备充足 → 储备不足 / 已领用 →（补充储备）→ 储备充足；另有终态已报废。
- 领用登记：保有数量扣减，余量为 0 置「已领用」，余量大于 0 置「储备不足」；
- 补充储备：保有数量回补，状态回到「储备充足」；
- 申请报废：置「已报废」。

每次状态切换都追加一条「状态流水」（时间 + 经手人），每次成功领用追加一条
「领用记录」，历史记录只追加、不改写，交接班后经手人仍以登记时为准。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from app.store import store

MODULE = "emergencyresp"

# 登记备品时的必填项
REQUIRED_FIELDS = ["备品编号", "备品名称", "规格型号"]
# 领用登记时的必填项
CLAIM_REQUIRED_FIELDS = ["经手人", "领用数量", "领用事由"]
# 补充储备时的必填项
REPLENISH_REQUIRED_FIELDS = ["经手人", "补充数量"]

STATUS_READY = "储备充足"
STATUS_LOW = "储备不足"
STATUS_CLAIMED = "已领用"
STATUS_SCRAPPED = "已报废"
STATUS_ORDER = [STATUS_READY, STATUS_LOW, STATUS_CLAIMED, STATUS_SCRAPPED]

# 各动作允许的起始状态；不在表里的状态一律拒绝
ACTION_ALLOWED_FROM = {
    "领用登记": {STATUS_READY, STATUS_LOW},
    "补充储备": {STATUS_LOW, STATUS_CLAIMED},
    "申请报废": {STATUS_READY, STATUS_LOW, STATUS_CLAIMED},
}
ACTION_TARGET = {
    "补充储备": STATUS_READY,
    "申请报废": STATUS_SCRAPPED,
}

EDITABLE_FIELDS = ["备品编号", "备品名称", "规格型号", "适用场景", "存放地点"]


class ServiceError(Exception):
    """业务校验失败：message 直接展示给用户，status 对应 HTTP 状态码。"""

    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status = status


class ConflictError(ServiceError):
    """备品已被其他人占用（重复领用或乐观锁版本冲突）。"""

    def __init__(self, message: str) -> None:
        super().__init__(message, status=409)


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _clean(values: dict[str, Any], field: str) -> str:
    return str(values.get(field) or "").strip()


def _parse_quantity(values: dict[str, Any], field: str) -> int:
    raw = _clean(values, field)
    try:
        amount = int(raw)
    except (TypeError, ValueError):
        raise ServiceError(f"「{field}」必须填写正整数，当前填写的是「{raw or '空'}」")
    if amount <= 0:
        raise ServiceError(f"「{field}」必须大于 0，当前填写的是 {amount}")
    return amount


class EmergencyrespService:
    # ---------- 查询 ----------
    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(MODULE)
        if keyword:
            key = keyword.strip()
            rows = [
                row
                for row in rows
                if key in str(row.get("备品编号", "")) or key in str(row.get("备品名称", ""))
            ]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        total = len(rows)
        start = max(page - 1, 0) * size
        return [self._serialize(row) for row in rows[start:start + size]], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        entry = store.find(MODULE, entry_id)
        return self._serialize(entry) if entry is not None else None

    def _serialize(self, entry: dict[str, Any]) -> dict[str, Any]:
        """输出给前端：补齐列表用的展示字段，领用记录/状态流水原样带出。"""
        result = dict(entry)
        result["备品状态"] = entry.get("status")
        records = entry.get("领用记录") or []
        if records:
            latest = records[-1]
            result["领用记录摘要"] = (
                f"共 {len(records)} 次，最近 {latest.get('时间')} "
                f"{latest.get('经手人')} 领用 {latest.get('领用数量')} 件"
            )
        else:
            result["领用记录摘要"] = "暂无领用记录"
        return result

    # ---------- 登记 ----------
    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in REQUIRED_FIELDS if not _clean(values, field)]
        if missing:
            return None, missing
        rows = store.rows(MODULE)
        code = _clean(values, "备品编号")
        if any(str(row.get("备品编号", "")).strip() == code for row in rows):
            raise ServiceError(f"备品编号「{code}」已存在，不能重复登记")

        entry: dict[str, Any] = {
            "id": max((int(row.get("id", 0)) for row in rows), default=0) + 1,
        }
        for field in EDITABLE_FIELDS:
            entry[field] = _clean(values, field)
        stock = _parse_quantity(values, "保有数量") if _clean(values, "保有数量") else 1
        entry["保有数量"] = stock
        entry["status"] = STATUS_READY
        entry["version"] = 1
        entry["pending"] = True
        entry["abnormal"] = False
        entry["领用记录"] = []
        entry["状态流水"] = []

        operator = _clean(values, "经手人")
        entry["状态流水"].append({
            "时间": _now(),
            "动作": "登记入库",
            "原状态": "—",
            "新状态": STATUS_READY,
            "经手人": operator or "登记人",
        })
        rows.append(entry)
        return self._serialize(entry), []

    # ---------- 动作 ----------
    def run_action(
        self,
        entry_id: int,
        action: str,
        values: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any] | None, str]:
        values = values or {}
        if action == "领用登记":
            return self._claim(entry_id, values), "领用登记已生效，备品状态与库存已同步"
        if action == "补充储备":
            return self._replenish(entry_id, values), "补充储备已登记，备品恢复为储备充足"
        if action == "申请报废":
            return self._scrap(entry_id, values), "应急备品已报废"
        return None, f"动作「{action}」不属于应急备品可执行范围"

    def _load(self, entry_id: int) -> dict[str, Any]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            raise ServiceError(f"应急备品 {entry_id} 不存在或已归档", status=404)
        return entry

    def _check_version(self, entry: dict[str, Any], values: dict[str, Any]) -> None:
        """乐观锁：两个页面同时领用时，只允许拿着最新版本号的那一次生效。"""
        raw = _clean(values, "expected_version")
        if not raw:
            return
        try:
            expected = int(raw)
        except ValueError:
            raise ServiceError("版本号格式不正确，请刷新页面后重试")
        if int(entry.get("version", 0)) != expected:
            raise ConflictError(
                f"备品「{entry.get('备品编号')}」已被占用：状态已被其他页面更新为"
                f"「{entry.get('status')}」，本次领用未生效，请刷新后查看最新记录"
            )

    def _transition(
        self,
        entry: dict[str, Any],
        action: str,
        new_status: str,
        operator: str,
    ) -> None:
        old_status = entry["status"]
        timestamp = _now()
        entry["status"] = new_status
        entry["version"] = int(entry.get("version", 1)) + 1
        entry["pending"] = new_status in {STATUS_LOW, STATUS_CLAIMED}
        entry["abnormal"] = new_status == STATUS_LOW
        entry.setdefault("状态流水", []).append({
            "时间": timestamp,
            "动作": action,
            "原状态": old_status,
            "新状态": new_status,
            "经手人": operator,
        })

    def _claim(self, entry_id: int, values: dict[str, Any]) -> dict[str, Any]:
        entry = self._load(entry_id)

        missing = [field for field in CLAIM_REQUIRED_FIELDS if not _clean(values, field)]
        if missing:
            raise ServiceError(f"领用登记资料不全，缺少必填项：{'、'.join(missing)}，请补全后再保存")

        current = entry.get("status")
        # 已被领空的备品不允许重复领用，明确提示「已被占用」
        if current == STATUS_CLAIMED:
            latest = (entry.get("领用记录") or [{}])[-1]
            raise ConflictError(
                f"备品「{entry.get('备品编号')}」已被占用：{latest.get('时间', '此前')} "
                f"由 {latest.get('经手人', '其他值班人员')} 领走最后 {latest.get('领用数量', '')} 件，"
                "不能重复领用"
            )
        if current == STATUS_SCRAPPED:
            raise ServiceError(f"备品「{entry.get('备品编号')}」已报废，不能再领用")
        if current not in ACTION_ALLOWED_FROM["领用登记"]:
            raise ServiceError(f"备品当前为「{current}」，不能执行领用登记")

        self._check_version(entry, values)

        operator = _clean(values, "经手人")
        amount = _parse_quantity(values, "领用数量")
        stock = int(entry.get("保有数量", 0))
        if amount > stock:
            raise ServiceError(
                f"领用数量不能大于保有数量：当前库存 {stock} 件，本次申请领用 {amount} 件"
            )

        new_stock = stock - amount
        entry["保有数量"] = new_stock
        new_status = STATUS_CLAIMED if new_stock == 0 else STATUS_LOW

        # 领用记录挂在备品编号下，只追加不改写，交接班后仍保留原经手人
        entry.setdefault("领用记录", []).append({
            "记录编号": f"{entry.get('备品编号')}-L{len(entry.get('领用记录', [])) + 1:03d}",
            "时间": _now(),
            "经手人": operator,
            "领用数量": amount,
            "领用事由": _clean(values, "领用事由"),
            "关联备品": entry.get("备品编号"),
        })
        self._transition(entry, "领用登记", new_status, operator)
        return self._serialize(entry)

    def _replenish(self, entry_id: int, values: dict[str, Any]) -> dict[str, Any]:
        entry = self._load(entry_id)

        missing = [field for field in REPLENISH_REQUIRED_FIELDS if not _clean(values, field)]
        if missing:
            raise ServiceError(f"补充储备资料不全，缺少必填项：{'、'.join(missing)}，请补全后再保存")

        current = entry.get("status")
        if current == STATUS_SCRAPPED:
            raise ServiceError(f"备品「{entry.get('备品编号')}」已报废，不能再补充储备")
        if current not in ACTION_ALLOWED_FROM["补充储备"]:
            raise ServiceError(f"备品当前为「{current}」，无需补充储备")

        self._check_version(entry, values)
        operator = _clean(values, "经手人")
        amount = _parse_quantity(values, "补充数量")
        entry["保有数量"] = int(entry.get("保有数量", 0)) + amount
        self._transition(entry, "补充储备", STATUS_READY, operator)
        return self._serialize(entry)

    def _scrap(self, entry_id: int, values: dict[str, Any]) -> dict[str, Any]:
        entry = self._load(entry_id)
        operator = _clean(values, "经手人")
        if not operator:
            raise ServiceError("申请报废资料不全，缺少必填项：经手人，请补全后再保存")

        current = entry.get("status")
        if current == STATUS_SCRAPPED:
            raise ServiceError(f"备品「{entry.get('备品编号')}」已是报废状态，不能重复报废")
        if current not in ACTION_ALLOWED_FROM["申请报废"]:
            raise ServiceError(f"备品当前为「{current}」，不能申请报废")

        self._check_version(entry, values)
        self._transition(entry, "申请报废", STATUS_SCRAPPED, operator)
        return self._serialize(entry)
