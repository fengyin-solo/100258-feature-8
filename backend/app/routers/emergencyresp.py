"""应急备品接口：维护应急备品，覆盖领用登记、确认消耗、补充储备、申请报废等动作。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.emergencyresp import EmergencyrespService

router = APIRouter(prefix="/api/emergencyresp", tags=["应急备品"])

service = EmergencyrespService()

LIST_FIELDS = ["备品编号", "备品名称", "规格型号", "适用场景", "存放地点", "保有数量", "领用记录", "备品状态"]
STATUSES = ["储备充足", "已领用", "储备不足", "已报废"]


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按备品编号检索"),
    status: str | None = Query(default=None, description="储备充足、已领用、储备不足、已报废"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """按备品编号与状态过滤应急备品列表；没有数据时返回空页，不报错。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    if status and status not in STATUSES:
        raise HTTPException(
            status_code=400,
            detail=f"备品状态「{status}」不合法，可选：{'、'.join(STATUSES)}",
        )
    items, total = service.list_entries(keyword=keyword, status=status, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条应急备品明细（含领用记录与状态轨迹）；不存在时给出可读的错误说明。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"应急备品 {entry_id} 不存在或已归档")
    return entry


@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload) -> ActionResult:
    """登记一条应急备品，缺字段时说明缺的是哪一项，而不是静默丢弃。"""
    operator = str(payload.values.get("经手人") or "").strip() or None
    entry, missing = service.create_entry(payload.values, operator=operator)
    if missing:
        return ActionResult(
            ok=False, message=f"应急备品登记信息不完整，缺少必填项：{'、'.join(missing)}，请补全后再保存"
        )
    return ActionResult(ok=True, message="应急备品已登记入账", entry=entry)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: EntryPayload) -> ActionResult:
    """对单条应急备品执行动作：信息不全不保存、重复占用只生效一次、每次切换都留经手人与时间。"""
    action = str(payload.values.get("action") or "").strip()
    operator = str(payload.values.get("经手人") or "").strip() or None
    entry, message = service.run_action(entry_id, action, payload.values, operator=operator)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)


@router.get("/export")
def export_entries() -> dict[str, Any]:
    """导出应急备品清单：返回当前全量数据（含领用记录与状态轨迹）。"""
    items, total = service.list_entries(page=1, size=10000)
    return {"module": "emergencyresp", "total": total, "items": items}
