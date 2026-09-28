"""应急备品业务规则：状态流转、领用记录、字段校验与并发占用控制都收在这里。

状态主线（每一步都留时间与经手人）：
    储备充足 ──领用登记──▶ 已领用 ──确认消耗──▶ 储备不足 ──补充储备──▶ 储备充足
储备充足/储备不足可申请报废，已报废为终态。
"""
from __future__ import annotations

import threading
from datetime import datetime
from typing import Any

from app.store import store

MODULE = "emergencyresp"
REQUIRED_FIELDS = ["备品编号", "备品名称", "规格型号"]

STATUS_READY = "储备充足"
STATUS_TAKEN = "已领用"
STATUS_LOW = "储备不足"
STATUS_SCRAPPED = "已报废"
STATUS_ORDER = [STATUS_READY, STATUS_TAKEN, STATUS_LOW, STATUS_SCRAPPED]

ACTION_ISSUE = "领用登记"
ACTION_CONSUME = "确认消耗"
ACTION_RESTOCK = "补充储备"
ACTION_SCRAP = "申请报废"

# 动作 -> (允许的起始状态集合, 目标状态)
ACTION_FLOW: dict[str, tuple[tuple[str, ...], str]] = {
    ACTION_ISSUE: ((STATUS_READY,), STATUS_TAKEN),
    ACTION_CONSUME: ((STATUS_TAKEN,), STATUS_LOW),
    ACTION_RESTOCK: ((STATUS_LOW,), STATUS_READY),
    ACTION_SCRAP: ((STATUS_READY, STATUS_LOW), STATUS_SCRAPPED),
}

# 各动作登记时必须填写的信息；缺一项都不允许保存
ACTION_REQUIRED_FIELDS: dict[str, list[str]] = {
    ACTION_ISSUE: ["经手人", "领用数量", "领用用途"],
    ACTION_CONSUME: ["经手人"],
    ACTION_RESTOCK: ["经手人", "补充数量"],
    ACTION_SCRAP: ["经手人"],
}

# 同一件备品在两个页面同时操作时，靠这把锁串行化，配合 version 做乐观占用判断
_mutation_lock = threading.Lock()


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _as_positive_int(values: dict[str, Any], field: str) -> tuple[int | None, str]:
    """把领用/补充数量解析成正整数，解析失败时指明是哪一项、错在哪。"""
    raw = str(values.get(field) or "").strip()
    if not raw:
        return None, f"「{field}」未填写"
    try:
        number = int(raw)
    except ValueError:
        return None, f"「{field}」必须是正整数，当前填写为「{raw}」"
    if number <= 0:
        return None, f"「{field}」必须大于 0，当前填写为 {number}"
    return number, ""


def _stock_of(entry: dict[str, Any]) -> int:
    try:
        return max(int(entry.get("保有数量") or 0), 0)
    except (TypeError, ValueError):
        return 0


def _timeline_entry(action: str, operator: str, source: str, target: str, note: str = "") -> dict[str, str]:
    """状态轨迹只追加、不改写，交接班后历史经手人原样保留。"""
    return {
        "时间": _now(),
        "动作": action,
        "经手人": operator,
        "由状态": source,
        "到状态": target,
        "备注": note,
    }


class EmergencyrespService:
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
            rows = [row for row in rows if keyword in str(row.get("备品编号", ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        return store.find(MODULE, entry_id)

    def create_entry(
        self, values: dict[str, Any], operator: str | None = None
    ) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing
        with _mutation_lock:
            rows = store.rows(MODULE)
            entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
            for field in ["备品编号", "备品名称", "规格型号", "适用场景", "存放地点"]:
                entry[field] = str(values.get(field) or "").strip()
            stock, error = _as_positive_int(values, "保有数量")
            entry["保有数量"] = stock if not error else 1
            entry["status"] = STATUS_READY
            entry["备品状态"] = STATUS_READY
            entry["pending"] = True
            entry["abnormal"] = False
            entry["version"] = 0
            # 领用记录挂在备品编号下面，全程追加
            entry["领用记录"]: list[dict[str, Any]] = []
            entry["状态轨迹"] = [
                _timeline_entry("登记入账", operator or "建账登记", "—", STATUS_READY)
            ]
            rows.append(entry)
        return entry, []

    def run_action(
        self,
        entry_id: int,
        action: str,
        values: dict[str, Any] | None = None,
        operator: str | None = None,
    ) -> tuple[dict[str, Any] | None, str]:
        values = values or {}
        operator = str(operator or values.get("经手人") or "").strip()
        submitted = {**values, "经手人": operator}

        if action not in ACTION_FLOW:
            return None, f"动作「{action}」不属于应急备品可执行范围"

        missing = [
            field
            for field in ACTION_REQUIRED_FIELDS.get(action, [])
            if not str(submitted.get(field) or "").strip()
        ]
        if missing:
            return None, f"{action}信息不完整，缺少：{'、'.join(missing)}，请补全后再保存"

        with _mutation_lock:
            entry = store.find(MODULE, entry_id)
            if entry is None:
                return None, f"应急备品 {entry_id} 不存在或已归档"

            code = str(entry.get("备品编号") or entry_id)
            current = str(entry.get("status") or "")
            allowed_sources, target = ACTION_FLOW[action]

            # 乐观锁：另一页面已抢先操作过，当前页持有的是旧版本
            client_version = values.get("version")
            if client_version is not None:
                try:
                    if int(client_version) != int(entry.get("version", 0)):
                        return (
                            None,
                            f"备品「{code}」刚被其他人操作过，状态已变为「{current}」，"
                            "请刷新页面确认后再试，本次操作未生效",
                        )
                except (TypeError, ValueError):
                    return None, "提交的版本号无效，请刷新页面后重试，本次操作未生效"

            if current not in allowed_sources:
                occupied = self._occupied_hint(entry, action, current)
                allowed = "、".join(allowed_sources)
                return (
                    None,
                    occupied
                    or f"备品「{code}」当前为「{current}」，不能执行{action}"
                    f"（仅「{allowed}」状态可执行），请刷新后查看最新状态",
                )

            if action == ACTION_ISSUE:
                return self._issue(entry, submitted, current)
            if action == ACTION_CONSUME:
                return self._consume(entry, submitted, current)
            if action == ACTION_RESTOCK:
                return self._restock(entry, submitted, current)
            return self._scrap(entry, submitted, current)

    # ---- 各动作的具体落账逻辑 -------------------------------------------------

    def _issue(
        self, entry: dict[str, Any], submitted: dict[str, Any], current: str
    ) -> tuple[dict[str, Any] | None, str]:
        quantity, error = _as_positive_int(submitted, "领用数量")
        if error:
            return None, f"领用登记信息不完整：{error}，请补全后再保存"
        stock = _stock_of(entry)
        if quantity > stock:
            return None, (
                f"领用数量 {quantity} 大于当前保有数量 {stock}，备品「{entry.get('备品编号')}」不能登记领用"
            )

        operator = submitted["经手人"]
        purpose = str(submitted.get("领用用途") or "").strip()
        remark = str(submitted.get("备注") or "").strip()
        records: list[dict[str, Any]] = entry.setdefault("领用记录", [])
        record = {
            "记录编号": max((int(item.get("记录编号", 0)) for item in records), default=0) + 1,
            "领用时间": _now(),
            "经手人": operator,  # 原始经手人，后续任何动作都不改写
            "领用数量": quantity,
            "领用用途": purpose,
            "备注": remark,
            "消耗时间": None,
            "消耗确认人": None,
        }
        records.append(record)

        new_stock = stock - quantity
        entry["保有数量"] = new_stock
        note = f"领用 {quantity} 件，用途：{purpose}" + (f"；备注：{remark}" if remark else "")
        self._advance(entry, ACTION_ISSUE, operator, current, STATUS_TAKEN, note)
        return entry, (
            f"领用登记已生效：{operator} 领用备品「{entry.get('备品编号')}」{quantity} 件，"
            f"状态由「{current}」变更为「{STATUS_TAKEN}」"
        )

    def _consume(
        self, entry: dict[str, Any], submitted: dict[str, Any], current: str
    ) -> tuple[dict[str, Any] | None, str]:
        operator = submitted["经手人"]
        # 补记最近一条尚未确认消耗的领用记录，原经手人字段保持不动
        open_record = next(
            (item for item in reversed(entry.get("领用记录", [])) if not item.get("消耗时间")),
            None,
        )
        if open_record is not None:
            open_record["消耗时间"] = _now()
            open_record["消耗确认人"] = operator
        note = (
            f"领用备品已实际消耗（原领用人：{open_record.get('经手人')}）"
            if open_record
            else "领用备品已实际消耗"
        )
        self._advance(entry, ACTION_CONSUME, operator, current, STATUS_LOW, note)
        return entry, (
            f"已确认消耗，备品「{entry.get('备品编号')}」状态由「{current}」变更为「{STATUS_LOW}」，"
            "盘点不再计入储备，请尽快安排补充储备"
        )

    def _restock(
        self, entry: dict[str, Any], submitted: dict[str, Any], current: str
    ) -> tuple[dict[str, Any] | None, str]:
        quantity, error = _as_positive_int(submitted, "补充数量")
        if error:
            return None, f"补充储备信息不完整：{error}，请补全后再保存"

        operator = submitted["经手人"]
        stock = _stock_of(entry) + quantity
        entry["保有数量"] = stock
        note = f"补充 {quantity} 件，保有数量恢复为 {stock}"
        self._advance(entry, ACTION_RESTOCK, operator, current, STATUS_READY, note)
        return entry, (
            f"补充储备已生效：{operator} 补充备品「{entry.get('备品编号')}」{quantity} 件，"
            f"状态由「{current}」恢复为「{STATUS_READY}」"
        )

    def _scrap(
        self, entry: dict[str, Any], submitted: dict[str, Any], current: str
    ) -> tuple[dict[str, Any] | None, str]:
        operator = submitted["经手人"]
        reason = str(submitted.get("报废原因") or submitted.get("备注") or "").strip()
        self._advance(entry, ACTION_SCRAP, operator, current, STATUS_SCRAPPED, reason)
        return entry, f"备品「{entry.get('备品编号')}」已申请报废，状态变更为「{STATUS_SCRAPPED}」"

    # ---- 公共落账 -------------------------------------------------------------

    def _advance(
        self,
        entry: dict[str, Any],
        action: str,
        operator: str,
        source: str,
        target: str,
        note: str,
    ) -> None:
        entry["status"] = target
        entry["备品状态"] = target
        entry["pending"] = target != STATUS_SCRAPPED
        entry["abnormal"] = target == STATUS_LOW
        entry["version"] = int(entry.get("version", 0)) + 1
        entry.setdefault("状态轨迹", []).append(_timeline_entry(action, operator, source, target, note))

    def _occupied_hint(
        self, entry: dict[str, Any], action: str, current: str
    ) -> str | None:
        """重复领用 / 已被占用时，指出占用人与时间，而不是只报状态不符。"""
        if action == ACTION_ISSUE and current == STATUS_TAKEN:
            latest = next(
                (item for item in reversed(entry.get("领用记录", [])) if not item.get("消耗时间")),
                entry.get("领用记录", [{}])[-1] if entry.get("领用记录") else None,
            )
            if latest:
                return (
                    f"备品「{entry.get('备品编号')}」已被 {latest.get('经手人')} 于 "
                    f"{latest.get('领用时间')} 领用占用，同一件备品只能生效一次，"
                    "本次领用未保存；请刷新页面查看最新状态"
                )
            return (
                f"备品「{entry.get('备品编号')}」已处于「{STATUS_TAKEN}」状态，"
                "同一件备品只能领用一次，本次领用未保存"
            )
        return None
