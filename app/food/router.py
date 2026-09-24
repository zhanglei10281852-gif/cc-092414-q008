from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.food.schemas import (
    DisposalCreate,
    LotCreate,
    LotSplit,
    NotificationGenerate,
    NotificationRetry,
    RecallClose,
    RecallCreate,
    RecallNodeAdd,
    ReceiptCreate,
    RiskDecision,
    SampleCreate,
    ShipmentCreate,
    TemperatureRecord,
    TestResultCreate,
)
from app.food.service import FoodService

router = APIRouter(prefix="/api/food", tags=["食品安全"])


def service() -> FoodService:
    return FoodService()


@router.post("/lots", status_code=201)
def create_lot(payload: LotCreate):
    try:
        return service().create_lot(payload.model_dump(), actor=payload.supplier)
    except Exception as exc:
        if "UNIQUE" in str(exc).upper():
            raise HTTPException(status_code=409, detail="批次编码或追溯码已存在") from exc
        raise


@router.get("/lots/{lot_id}")
def get_lot(lot_id: int, details: bool = True):
    value = service().get_lot(lot_id, details)
    if value is None:
        raise HTTPException(status_code=404, detail="批次不存在")
    return value


@router.get("/lots/{lot_id}/summary")
def summary(lot_id: int):
    try:
        return service().summary(lot_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="批次不存在") from exc


@router.delete("/lots/{lot_id}")
def delete_lot(lot_id: int):
    try:
        service().delete_lot(lot_id)
        return {"message": "批次已删除"}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="批次不存在") from exc


@router.post("/lots/{lot_id}/samples", status_code=201)
def add_sample(lot_id: int, payload: SampleCreate):
    try:
        return service().add_sample(lot_id, payload.model_dump())
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="批次不存在") from exc


@router.post("/samples/{sample_id}/results", status_code=201)
def add_result(sample_id: int, payload: TestResultCreate):
    try:
        return service().add_result(sample_id, payload.model_dump())
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="样品不存在") from exc


@router.post("/lots/{lot_id}/shipments", status_code=201)
def create_shipment(lot_id: int, payload: ShipmentCreate):
    try:
        return service().create_shipment(lot_id, payload.model_dump())
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="批次不存在") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/shipments/{shipment_id}/temperatures", status_code=201)
def add_temperature(shipment_id: int, payload: TemperatureRecord):
    try:
        return service().add_temperature(shipment_id, payload.model_dump())
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="运输单不存在") from exc


@router.post("/lots/{lot_id}/risk", status_code=200)
def decide_risk(lot_id: int, payload: RiskDecision):
    try:
        return service().decide_risk(lot_id, payload.model_dump())
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="批次不存在") from exc


def _recall_error(exc: KeyError) -> HTTPException:
    return HTTPException(status_code=404, detail="召回事件不存在" if "recall" in str(exc) else "节点不存在")


@router.post("/lots/{lot_id}/recalls", status_code=201)
def create_recall(lot_id: int, payload: RecallCreate):
    try:
        return service().create_recall(lot_id, payload.model_dump(), actor=payload.operator)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="批次不存在") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        if "UNIQUE" in str(exc).upper():
            raise HTTPException(status_code=409, detail="召回编码已存在") from exc
        raise


@router.get("/lots/{lot_id}/recalls")
def list_recalls(lot_id: int):
    try:
        return service().list_recalls(lot_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="批次不存在") from exc


@router.post("/lots/{lot_id}/splits", status_code=201)
def split_lot(lot_id: int, payload: LotSplit):
    try:
        return service().split_lot(lot_id, payload.model_dump(), actor=payload.operator)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="批次不存在") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        if "UNIQUE" in str(exc).upper():
            raise HTTPException(status_code=409, detail="子批次编码或追溯码已存在") from exc
        raise


@router.get("/recalls/{recall_id}")
def get_recall(recall_id: int):
    value = service().get_recall(recall_id)
    if value is None:
        raise HTTPException(status_code=404, detail="召回事件不存在")
    return value


@router.post("/recalls/{recall_id}/nodes", status_code=201)
def add_recall_node(recall_id: int, payload: RecallNodeAdd):
    try:
        return service().add_recall_node(recall_id, payload.model_dump(), actor=payload.operator)
    except KeyError as exc:
        raise _recall_error(exc) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        if "UNIQUE" in str(exc).upper():
            raise HTTPException(status_code=409, detail="下游节点已存在") from exc
        raise


@router.post("/recalls/{recall_id}/notifications")
def generate_notifications(recall_id: int, payload: NotificationGenerate):
    try:
        return service().generate_notifications(recall_id, payload.model_dump(), actor=payload.operator)
    except KeyError as exc:
        raise _recall_error(exc) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/recalls/{recall_id}/nodes/{node_id}/notification/retry")
def retry_notification(recall_id: int, node_id: int, payload: NotificationRetry):
    try:
        return service().retry_notification(recall_id, node_id, payload.model_dump(), actor=payload.operator)
    except KeyError as exc:
        raise _recall_error(exc) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/recalls/{recall_id}/nodes/{node_id}/receipt")
def acknowledge_node(recall_id: int, node_id: int, payload: ReceiptCreate):
    try:
        return service().acknowledge_node(recall_id, node_id, payload.model_dump(), actor=payload.operator)
    except KeyError as exc:
        raise _recall_error(exc) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/recalls/{recall_id}/nodes/{node_id}/disposals", status_code=201)
def record_disposal(recall_id: int, node_id: int, payload: DisposalCreate):
    try:
        return service().record_disposal(recall_id, node_id, payload.model_dump(), actor=payload.operator)
    except KeyError as exc:
        raise _recall_error(exc) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/recalls/{recall_id}/close")
def close_recall(recall_id: int, payload: RecallClose):
    try:
        return service().close_recall(recall_id, payload.model_dump(), actor=payload.operator)
    except KeyError as exc:
        raise _recall_error(exc) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
