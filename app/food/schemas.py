from __future__ import annotations

from pydantic import BaseModel, Field, field_validator


class LotCreate(BaseModel):
    lot_code: str = Field(..., min_length=3, max_length=64)
    product_name: str = Field(..., min_length=1, max_length=120)
    category: str = Field(..., min_length=1, max_length=40)
    supplier: str = Field(..., min_length=1, max_length=120)
    origin: str = Field(..., min_length=1, max_length=160)
    harvest_date: str = Field(..., min_length=10, max_length=40)
    quantity_kg: float = Field(..., gt=0, le=1000000)
    trace_code: str = Field(..., min_length=4, max_length=120)

    @field_validator("lot_code", "trace_code")
    @classmethod
    def normalize_code(cls, value: str) -> str:
        return value.strip().upper()


class SampleCreate(BaseModel):
    sample_code: str = Field(..., min_length=3, max_length=64)
    collected_at: str = Field(..., min_length=20, max_length=40)
    collector: str = Field(..., min_length=1, max_length=80)
    location: str = Field(..., min_length=1, max_length=160)
    sample_weight_g: float = Field(..., gt=0, le=10000)


class TestResultCreate(BaseModel):
    analyte: str = Field(..., min_length=1, max_length=80)
    method: str = Field(..., min_length=1, max_length=80)
    value_mg_kg: float = Field(..., ge=0, le=100000)
    limit_mg_kg: float = Field(..., ge=0, le=100000)
    unit: str = Field(default="mg/kg", min_length=1, max_length=20)
    lab_operator: str = Field(..., min_length=1, max_length=80)
    tested_at: str = Field(..., min_length=20, max_length=40)
    certificate_no: str = Field(default="", max_length=80)


class ShipmentCreate(BaseModel):
    shipment_code: str = Field(..., min_length=3, max_length=64)
    carrier: str = Field(..., min_length=1, max_length=120)
    vehicle_no: str = Field(..., min_length=1, max_length=40)
    departure_at: str = Field(..., min_length=20, max_length=40)
    arrival_due_at: str = Field(..., min_length=20, max_length=40)
    destination: str = Field(..., min_length=1, max_length=160)
    target_temp_min: float = Field(default=0, ge=-40, le=30)
    target_temp_max: float = Field(default=8, ge=-20, le=50)


class TemperatureRecord(BaseModel):
    recorded_at: str = Field(..., min_length=20, max_length=40)
    temperature_c: float = Field(..., ge=-80, le=100)
    source: str = Field(default="sensor", min_length=1, max_length=40)


class RiskDecision(BaseModel):
    decision: str = Field(..., pattern="^(release|hold|recall|destroy)$")
    reason: str = Field(..., min_length=1, max_length=300)
    operator: str = Field(..., min_length=1, max_length=80)


class LotSplit(BaseModel):
    lot_code: str = Field(..., min_length=3, max_length=64)
    trace_code: str = Field(..., min_length=4, max_length=120)
    quantity_kg: float = Field(..., gt=0, le=1000000)

    @field_validator("lot_code", "trace_code")
    @classmethod
    def normalize_code(cls, value: str) -> str:
        return value.strip().upper()


class DeliveryCreate(BaseModel):
    delivery_code: str = Field(..., min_length=3, max_length=64)
    node_type: str = Field(..., pattern="^(merchant|canteen|warehouse|other)$")
    node_name: str = Field(..., min_length=1, max_length=160)
    contact: str = Field(default="", max_length=120)
    address: str = Field(default="", max_length=200)
    delivered_quantity_kg: float = Field(..., ge=0, le=1000000)
    delivered_at: str = Field(..., min_length=20, max_length=40)
    shipment_code: str | None = Field(default=None, max_length=64)
    operator: str = Field(default="dispatcher", min_length=1, max_length=80)

    @field_validator("delivery_code")
    @classmethod
    def normalize_code(cls, value: str) -> str:
        return value.strip().upper()


class RecallInitiate(BaseModel):
    recall_code: str = Field(..., min_length=3, max_length=64)
    reason: str = Field(..., min_length=1, max_length=300)
    level: str = Field(default="secondary", pattern="^(primary|secondary|tertiary)$")
    analyte: str | None = Field(default=None, max_length=80)
    value_mg_kg: float | None = Field(default=None, ge=0, le=100000)
    limit_mg_kg: float | None = Field(default=None, ge=0, le=100000)
    operator: str = Field(default="regulator", min_length=1, max_length=80)

    @field_validator("recall_code")
    @classmethod
    def normalize_code(cls, value: str) -> str:
        return value.strip().upper()


class NoticeAttempt(BaseModel):
    result: str = Field(..., pattern="^(delivered|failed)$")
    channel: str | None = Field(default=None, pattern="^(sms|phone|paper|onsite|system)$")
    detail: str = Field(default="", max_length=300)
    operator: str = Field(default="dispatcher", min_length=1, max_length=80)


class ReceiptAcknowledge(BaseModel):
    acknowledged_by: str = Field(..., min_length=1, max_length=80)
    contact: str = Field(default="", max_length=120)
    on_hand_quantity_kg: float = Field(default=0, ge=0, le=1000000)
    disposed_quantity_kg: float = Field(default=0, ge=0, le=1000000)
    returned_quantity_kg: float = Field(default=0, ge=0, le=1000000)
    sold_quantity_kg: float = Field(default=0, ge=0, le=1000000)
    note: str = Field(default="", max_length=300)
    received_at: str | None = Field(default=None, min_length=20, max_length=40)


class RecallLotConfirm(BaseModel):
    operator: str = Field(default="regulator", min_length=1, max_length=80)
    exempt: bool = False
    reason: str = Field(default="", max_length=300)


class RecallClose(BaseModel):
    operator: str = Field(default="regulator", min_length=1, max_length=80)
    remark: str = Field(default="", max_length=300)

