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
    quantity_kg: float | None = Field(default=None, gt=0, le=1000000)


class TemperatureRecord(BaseModel):
    recorded_at: str = Field(..., min_length=20, max_length=40)
    temperature_c: float = Field(..., ge=-80, le=100)
    source: str = Field(default="sensor", min_length=1, max_length=40)


class RiskDecision(BaseModel):
    decision: str = Field(..., pattern="^(release|hold|recall|destroy)$")
    reason: str = Field(..., min_length=1, max_length=300)
    operator: str = Field(..., min_length=1, max_length=80)


class RecallNodeInput(BaseModel):
    node_name: str = Field(..., min_length=1, max_length=160)
    node_type: str = Field(default="merchant", pattern="^(merchant|canteen|other)$")
    quantity_kg: float = Field(..., gt=0, le=1000000)
    shipment_id: int | None = Field(default=None, ge=1)


class RecallCreate(BaseModel):
    recall_code: str = Field(..., min_length=3, max_length=64)
    reason: str = Field(..., min_length=1, max_length=300)
    level: str | None = Field(default=None, pattern="^(low|medium|high|critical)$")
    operator: str = Field(..., min_length=1, max_length=80)
    nodes: list[RecallNodeInput] = Field(default_factory=list)

    @field_validator("recall_code")
    @classmethod
    def normalize_code(cls, value: str) -> str:
        return value.strip().upper()


class RecallNodeAdd(RecallNodeInput):
    operator: str = Field(..., min_length=1, max_length=80)


class NotificationGenerate(BaseModel):
    operator: str = Field(..., min_length=1, max_length=80)
    channel: str = Field(default="manual", min_length=1, max_length=40)


class NotificationRetry(BaseModel):
    operator: str = Field(..., min_length=1, max_length=80)
    result: str = Field(default="delivered", pattern="^(sent|delivered|failed)$")
    note: str = Field(default="", max_length=300)


class ReceiptCreate(BaseModel):
    acknowledged_by: str = Field(..., min_length=1, max_length=80)
    operator: str = Field(..., min_length=1, max_length=80)
    note: str = Field(default="", max_length=300)


class DisposalCreate(BaseModel):
    quantity_kg: float = Field(..., gt=0, le=1000000)
    operator: str = Field(..., min_length=1, max_length=80)
    method: str = Field(default="destroy", pattern="^(destroy|return|seal|other)$")
    note: str = Field(default="", max_length=300)


class RecallClose(BaseModel):
    operator: str = Field(..., min_length=1, max_length=80)


class SplitItem(BaseModel):
    lot_code: str = Field(..., min_length=3, max_length=64)
    trace_code: str = Field(..., min_length=4, max_length=120)
    quantity_kg: float = Field(..., gt=0, le=1000000)
    nodes: list[RecallNodeInput] = Field(default_factory=list)

    @field_validator("lot_code", "trace_code")
    @classmethod
    def normalize_code(cls, value: str) -> str:
        return value.strip().upper()


class LotSplit(BaseModel):
    operator: str = Field(..., min_length=1, max_length=80)
    splits: list[SplitItem] = Field(..., min_length=1, max_length=100)

