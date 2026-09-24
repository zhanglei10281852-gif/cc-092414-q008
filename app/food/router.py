from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.food.schemas import (
    DeliveryCreate,
    LotCreate,
    LotSplit,
    NoticeAttempt,
    RecallClose,
    RecallInitiate,
    RecallLotConfirm,
    ReceiptAcknowledge,
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


@router.post("/lots/{lot_id}/split", status_code=201)
def split_lot(lot_id: int, payload: LotSplit):
    try:
        return service().split_lot(lot_id, payload.model_dump())
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="批次不存在") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        if "UNIQUE" in str(exc).upper():
            raise HTTPException(status_code=409, detail="批次编码或追溯码已存在") from exc
        raise


@router.post("/lots/{lot_id}/deliveries", status_code=201)
def register_delivery(lot_id: int, payload: DeliveryCreate):
    try:
        return service().register_delivery(lot_id, payload.model_dump())
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="批次或运输单不存在") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        if "UNIQUE" in str(exc).upper():
            raise HTTPException(status_code=409, detail="送达单编码已存在") from exc
        raise


@router.post("/lots/{lot_id}/recalls", status_code=201)
def initiate_recall(lot_id: int, payload: RecallInitiate):
    try:
        return service().initiate_recall(lot_id, payload.model_dump())
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="批次不存在") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        if "UNIQUE" in str(exc).upper():
            raise HTTPException(status_code=409, detail="召回编码已存在") from exc
        raise


@router.get("/recalls/{recall_id}")
def get_recall(recall_id: int):
    value = service().get_recall(recall_id)
    if value is None:
        raise HTTPException(status_code=404, detail="召回事件不存在")
    return value


@router.get("/recalls/{recall_id}/progress")
def recall_progress(recall_id: int):
    try:
        return service().recall_progress(recall_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="召回事件不存在") from exc


@router.post("/recalls/{recall_id}/sync-nodes", status_code=200)
def sync_recall_nodes(recall_id: int):
    try:
        return service().sync_recall_nodes(recall_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="召回事件不存在") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/recalls/{recall_id}/close", status_code=200)
def close_recall(recall_id: int, payload: RecallClose):
    try:
        return service().close_recall(recall_id, payload.model_dump())
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="召回事件不存在") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/recalls/{recall_id}/lots/{lot_id}/confirm", status_code=200)
def confirm_recall_lot(recall_id: int, lot_id: int, payload: RecallLotConfirm):
    try:
        return service().confirm_recall_lot(recall_id, lot_id, payload.model_dump())
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="召回批次不存在") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/notices/{notice_id}/attempts", status_code=201)
def record_notice_attempt(notice_id: int, payload: NoticeAttempt):
    try:
        return service().record_notice_attempt(notice_id, payload.model_dump())
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="通知不存在") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/notices/{notice_id}/receipt", status_code=201)
def acknowledge_receipt(notice_id: int, payload: ReceiptAcknowledge):
    try:
        return service().acknowledge_receipt(notice_id, payload.model_dump())
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="通知不存在") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
