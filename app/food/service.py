from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from typing import Any

from app.database import get_connection, transaction


SCHEMA = """
CREATE TABLE IF NOT EXISTS food_lots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    lot_code TEXT NOT NULL UNIQUE,
    product_name TEXT NOT NULL,
    category TEXT NOT NULL,
    supplier TEXT NOT NULL,
    origin TEXT NOT NULL,
    harvest_date TEXT NOT NULL,
    quantity_kg REAL NOT NULL,
    trace_code TEXT NOT NULL UNIQUE,
    parent_lot_id INTEGER REFERENCES food_lots(id),
    root_lot_id INTEGER,
    status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','testing','released','held','recalled','destroyed')),
    risk_level TEXT NOT NULL DEFAULT 'unknown' CHECK(risk_level IN ('unknown','low','medium','high','critical')),
    version INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS food_samples (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    lot_id INTEGER NOT NULL REFERENCES food_lots(id) ON DELETE RESTRICT,
    sample_code TEXT NOT NULL UNIQUE,
    collected_at TEXT NOT NULL,
    collector TEXT NOT NULL,
    location TEXT NOT NULL,
    sample_weight_g REAL NOT NULL,
    status TEXT NOT NULL DEFAULT 'collected' CHECK(status IN ('collected','in_lab','complete','void')),
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS food_test_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sample_id INTEGER NOT NULL REFERENCES food_samples(id) ON DELETE RESTRICT,
    analyte TEXT NOT NULL,
    method TEXT NOT NULL,
    value_mg_kg REAL NOT NULL,
    limit_mg_kg REAL NOT NULL,
    unit TEXT NOT NULL,
    lab_operator TEXT NOT NULL,
    tested_at TEXT NOT NULL,
    certificate_no TEXT NOT NULL DEFAULT '',
    verdict TEXT NOT NULL CHECK(verdict IN ('pass','fail')),
    result_hash TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(sample_id, analyte, method, tested_at)
);
CREATE TABLE IF NOT EXISTS food_shipments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    lot_id INTEGER NOT NULL REFERENCES food_lots(id) ON DELETE RESTRICT,
    shipment_code TEXT NOT NULL UNIQUE,
    carrier TEXT NOT NULL,
    vehicle_no TEXT NOT NULL,
    departure_at TEXT NOT NULL,
    arrival_due_at TEXT NOT NULL,
    destination TEXT NOT NULL,
    target_temp_min REAL NOT NULL,
    target_temp_max REAL NOT NULL,
    status TEXT NOT NULL DEFAULT 'planned' CHECK(status IN ('planned','in_transit','arrived','delayed','cancelled')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS food_temperatures (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    shipment_id INTEGER NOT NULL REFERENCES food_shipments(id) ON DELETE CASCADE,
    recorded_at TEXT NOT NULL,
    temperature_c REAL NOT NULL,
    source TEXT NOT NULL,
    in_range INTEGER NOT NULL CHECK(in_range IN (0,1)),
    created_at TEXT NOT NULL,
    UNIQUE(shipment_id, recorded_at)
);
CREATE TABLE IF NOT EXISTS food_risk_actions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    lot_id INTEGER NOT NULL REFERENCES food_lots(id) ON DELETE RESTRICT,
    decision TEXT NOT NULL CHECK(decision IN ('release','hold','recall','destroy')),
    reason TEXT NOT NULL,
    operator TEXT NOT NULL,
    previous_status TEXT NOT NULL,
    new_status TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS food_deliveries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    lot_id INTEGER NOT NULL REFERENCES food_lots(id) ON DELETE RESTRICT,
    shipment_id INTEGER REFERENCES food_shipments(id) ON DELETE SET NULL,
    delivery_code TEXT NOT NULL UNIQUE,
    node_type TEXT NOT NULL CHECK(node_type IN ('merchant','canteen','warehouse','other')),
    node_name TEXT NOT NULL,
    contact TEXT NOT NULL DEFAULT '',
    address TEXT NOT NULL DEFAULT '',
    delivered_quantity_kg REAL NOT NULL CHECK(delivered_quantity_kg >= 0),
    delivered_at TEXT NOT NULL,
    operator TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS food_recalls (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    recall_code TEXT NOT NULL UNIQUE,
    root_lot_id INTEGER NOT NULL REFERENCES food_lots(id) ON DELETE RESTRICT,
    trigger_sample_id INTEGER REFERENCES food_samples(id),
    analyte TEXT NOT NULL DEFAULT '',
    value_mg_kg REAL,
    limit_mg_kg REAL,
    reason TEXT NOT NULL,
    level TEXT NOT NULL DEFAULT 'secondary' CHECK(level IN ('primary','secondary','tertiary')),
    status TEXT NOT NULL DEFAULT 'open' CHECK(status IN ('open','closed','cancelled')),
    initiated_by TEXT NOT NULL,
    closed_by TEXT NOT NULL DEFAULT '',
    close_remark TEXT NOT NULL DEFAULT '',
    initiated_at TEXT NOT NULL,
    closed_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS food_recall_lots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    recall_id INTEGER NOT NULL REFERENCES food_recalls(id) ON DELETE RESTRICT,
    lot_id INTEGER NOT NULL REFERENCES food_lots(id) ON DELETE RESTRICT,
    inherited_from_lot_id INTEGER REFERENCES food_lots(id),
    inherited_reason TEXT NOT NULL DEFAULT '',
    quantity_kg REAL NOT NULL CHECK(quantity_kg >= 0),
    lot_status TEXT NOT NULL DEFAULT 'pending' CHECK(lot_status IN ('pending','confirmed','exempted','closed')),
    confirmed_by TEXT NOT NULL DEFAULT '',
    confirmed_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(recall_id, lot_id)
);
CREATE TABLE IF NOT EXISTS food_recall_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    recall_id INTEGER NOT NULL REFERENCES food_recalls(id) ON DELETE RESTRICT,
    delivery_id INTEGER NOT NULL REFERENCES food_deliveries(id) ON DELETE RESTRICT,
    lot_id INTEGER NOT NULL REFERENCES food_lots(id) ON DELETE RESTRICT,
    node_type TEXT NOT NULL,
    node_name TEXT NOT NULL,
    contact TEXT NOT NULL DEFAULT '',
    address TEXT NOT NULL DEFAULT '',
    delivered_quantity_kg REAL NOT NULL,
    delivered_at TEXT NOT NULL,
    snapshot_at TEXT NOT NULL,
    UNIQUE(recall_id, delivery_id)
);
CREATE TABLE IF NOT EXISTS food_recall_notices (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    recall_id INTEGER NOT NULL REFERENCES food_recalls(id) ON DELETE RESTRICT,
    snapshot_id INTEGER NOT NULL REFERENCES food_recall_snapshots(id) ON DELETE RESTRICT,
    notice_code TEXT NOT NULL UNIQUE,
    channel TEXT NOT NULL DEFAULT 'sms' CHECK(channel IN ('sms','phone','paper','onsite','system')),
    attempt_count INTEGER NOT NULL DEFAULT 0,
    first_sent_at TEXT,
    last_attempt_at TEXT,
    max_attempts INTEGER NOT NULL DEFAULT 5,
    delivery_status TEXT NOT NULL DEFAULT 'pending' CHECK(delivery_status IN ('pending','delivered','failed')),
    receipt_status TEXT NOT NULL DEFAULT 'pending' CHECK(receipt_status IN ('pending','acknowledged','rejected')),
    acknowledged_by TEXT NOT NULL DEFAULT '',
    acknowledged_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(recall_id, snapshot_id)
);
CREATE TABLE IF NOT EXISTS food_recall_notice_attempts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    notice_id INTEGER NOT NULL REFERENCES food_recall_notices(id) ON DELETE CASCADE,
    attempt_no INTEGER NOT NULL,
    channel TEXT NOT NULL,
    result TEXT NOT NULL CHECK(result IN ('delivered','failed','acknowledged')),
    detail TEXT NOT NULL DEFAULT '',
    operator TEXT NOT NULL,
    attempted_at TEXT NOT NULL,
    UNIQUE(notice_id, attempt_no)
);
CREATE TABLE IF NOT EXISTS food_recall_receipts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    notice_id INTEGER NOT NULL UNIQUE REFERENCES food_recall_notices(id) ON DELETE RESTRICT,
    recall_id INTEGER NOT NULL REFERENCES food_recalls(id) ON DELETE RESTRICT,
    snapshot_id INTEGER NOT NULL REFERENCES food_recall_snapshots(id) ON DELETE RESTRICT,
    acknowledged_by TEXT NOT NULL,
    contact TEXT NOT NULL DEFAULT '',
    on_hand_quantity_kg REAL NOT NULL DEFAULT 0 CHECK(on_hand_quantity_kg >= 0),
    disposed_quantity_kg REAL NOT NULL DEFAULT 0 CHECK(disposed_quantity_kg >= 0),
    returned_quantity_kg REAL NOT NULL DEFAULT 0 CHECK(returned_quantity_kg >= 0),
    sold_quantity_kg REAL NOT NULL DEFAULT 0 CHECK(sold_quantity_kg >= 0),
    note TEXT NOT NULL DEFAULT '',
    received_at TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS food_audit (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    lot_id INTEGER,
    action TEXT NOT NULL,
    actor TEXT NOT NULL,
    payload_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_food_samples_lot ON food_samples(lot_id, collected_at);
CREATE INDEX IF NOT EXISTS idx_food_results_sample ON food_test_results(sample_id, tested_at);
CREATE INDEX IF NOT EXISTS idx_food_shipments_lot ON food_shipments(lot_id, departure_at);
CREATE INDEX IF NOT EXISTS idx_food_deliveries_lot ON food_deliveries(lot_id, delivered_at);
CREATE INDEX IF NOT EXISTS idx_food_lots_root ON food_lots(root_lot_id);
CREATE INDEX IF NOT EXISTS idx_food_recall_lots_recall ON food_recall_lots(recall_id);
CREATE INDEX IF NOT EXISTS idx_food_snapshots_recall ON food_recall_snapshots(recall_id);
CREATE INDEX IF NOT EXISTS idx_food_notices_recall ON food_recall_notices(recall_id, delivery_status, receipt_status);
CREATE INDEX IF NOT EXISTS idx_food_attempts_notice ON food_recall_notice_attempts(notice_id, attempted_at);
CREATE INDEX IF NOT EXISTS idx_food_receipts_recall ON food_recall_receipts(recall_id);
"""

# 既有数据库（food_lots 已建表）需要补齐批次拆分列；全新库由 SCHEMA 直接创建。
MIGRATIONS = (
    "ALTER TABLE food_lots ADD COLUMN parent_lot_id INTEGER REFERENCES food_lots(id)",
    "ALTER TABLE food_lots ADD COLUMN root_lot_id INTEGER",
)


def ensure_schema() -> None:
    connection = get_connection()
    connection.executescript(SCHEMA)
    existing = {row[1] for row in connection.execute("PRAGMA table_info(food_lots)").fetchall()}
    for statement in MIGRATIONS:
        column = statement.split("ADD COLUMN", 1)[1].strip().split()[0]
        if column not in existing:
            connection.execute(statement)
    connection.execute("UPDATE food_lots SET root_lot_id=id WHERE root_lot_id IS NULL")
    connection.execute("CREATE INDEX IF NOT EXISTS idx_food_lots_root ON food_lots(root_lot_id)")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _result_hash(payload: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def _dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    return dict(row) if row else None


class FoodService:
    """食品批次、检测与运输流程的事务边界。"""

    def __init__(self, connection: sqlite3.Connection | None = None):
        self.connection = connection or get_connection()
        ensure_schema()

    def create_lot(self, payload: dict[str, Any], actor: str = "system") -> dict[str, Any]:
        now = _now()
        with transaction(immediate=True) as connection:
            cursor = connection.execute(
                "INSERT INTO food_lots(lot_code,product_name,category,supplier,origin,harvest_date,quantity_kg,trace_code,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                (payload["lot_code"], payload["product_name"], payload["category"], payload["supplier"], payload["origin"], payload["harvest_date"], payload["quantity_kg"], payload["trace_code"], now, now),
            )
            lot_id = cursor.lastrowid
            connection.execute("UPDATE food_lots SET root_lot_id=id WHERE id=?", (lot_id,))
            connection.execute("INSERT INTO food_audit(lot_id,action,actor,payload_json,created_at) VALUES(?,?,?,?,?)", (lot_id, "lot.create", actor, json.dumps(payload, ensure_ascii=False), now))
            return _dict(connection.execute("SELECT * FROM food_lots WHERE id=?", (lot_id,)).fetchone()) or {}

    def get_lot(self, lot_id: int, details: bool = True) -> dict[str, Any] | None:
        lot = self.connection.execute("SELECT * FROM food_lots WHERE id=?", (lot_id,)).fetchone()
        if lot is None:
            return None
        result = dict(lot)
        if details:
            samples = self.connection.execute("SELECT * FROM food_samples WHERE lot_id=? ORDER BY collected_at,id", (lot_id,)).fetchall()
            shipments = self.connection.execute("SELECT * FROM food_shipments WHERE lot_id=? ORDER BY departure_at,id", (lot_id,)).fetchall()
            result["samples"] = []
            for sample in samples:
                item = dict(sample)
                item["results"] = [dict(row) for row in self.connection.execute("SELECT * FROM food_test_results WHERE sample_id=? ORDER BY tested_at,id", (sample["id"],)).fetchall()]
                result["samples"].append(item)
            result["shipments"] = [dict(row) for row in shipments]
        return result

    def add_sample(self, lot_id: int, payload: dict[str, Any], actor: str = "inspector") -> dict[str, Any]:
        if self.connection.execute("SELECT id FROM food_lots WHERE id=?", (lot_id,)).fetchone() is None:
            raise KeyError("lot_not_found")
        now = _now()
        with transaction(immediate=True) as connection:
            cursor = connection.execute("INSERT INTO food_samples(lot_id,sample_code,collected_at,collector,location,sample_weight_g,status,created_at) VALUES(?,?,?,?,?,?,?,?)", (lot_id, payload["sample_code"], payload["collected_at"], payload["collector"], payload["location"], payload["sample_weight_g"], "collected", now))
            connection.execute("UPDATE food_lots SET status='testing',version=version+1,updated_at=? WHERE id=? AND status='pending'", (now, lot_id))
            connection.execute("INSERT INTO food_audit(lot_id,action,actor,payload_json,created_at) VALUES(?,?,?,?,?)", (lot_id, "sample.collect", actor, json.dumps(payload, ensure_ascii=False), now))
            return _dict(connection.execute("SELECT * FROM food_samples WHERE id=?", (cursor.lastrowid,)).fetchone()) or {}

    def add_result(self, sample_id: int, payload: dict[str, Any], actor: str = "lab") -> dict[str, Any]:
        sample = self.connection.execute("SELECT * FROM food_samples WHERE id=?", (sample_id,)).fetchone()
        if sample is None:
            raise KeyError("sample_not_found")
        verdict = "pass" if payload["value_mg_kg"] <= payload["limit_mg_kg"] else "fail"
        result_hash = _result_hash({**payload, "verdict": verdict, "sample_id": sample_id})
        now = _now()
        with transaction(immediate=True) as connection:
            existing = connection.execute("SELECT * FROM food_test_results WHERE sample_id=? AND analyte=? AND method=? AND tested_at=?", (sample_id, payload["analyte"], payload["method"], payload["tested_at"])).fetchone()
            if existing:
                return dict(existing)
            cursor = connection.execute("INSERT INTO food_test_results(sample_id,analyte,method,value_mg_kg,limit_mg_kg,unit,lab_operator,tested_at,certificate_no,verdict,result_hash,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)", (sample_id, payload["analyte"], payload["method"], payload["value_mg_kg"], payload["limit_mg_kg"], payload["unit"], payload["lab_operator"], payload["tested_at"], payload["certificate_no"], verdict, result_hash, now))
            connection.execute("UPDATE food_samples SET status='complete' WHERE id=?", (sample_id,))
            lot_id = sample["lot_id"]
            failed = connection.execute("SELECT COUNT(*) FROM food_test_results WHERE sample_id=? AND verdict='fail'", (sample_id,)).fetchone()[0]
            if failed:
                connection.execute("UPDATE food_lots SET risk_level='high',status='held',version=version+1,updated_at=? WHERE id=?", (now, lot_id))
            connection.execute("INSERT INTO food_audit(lot_id,action,actor,payload_json,created_at) VALUES(?,?,?,?,?)", (lot_id, "test.result", actor, json.dumps({**payload, "verdict": verdict}, ensure_ascii=False), now))
            return _dict(connection.execute("SELECT * FROM food_test_results WHERE id=?", (cursor.lastrowid,)).fetchone()) or {}

    def create_shipment(self, lot_id: int, payload: dict[str, Any], actor: str = "dispatcher") -> dict[str, Any]:
        lot = self.connection.execute("SELECT * FROM food_lots WHERE id=?", (lot_id,)).fetchone()
        if lot is None:
            raise KeyError("lot_not_found")
        if lot["status"] in {"held", "recalled", "destroyed"}:
            raise ValueError("lot_not_releasable")
        if payload["target_temp_min"] > payload["target_temp_max"]:
            raise ValueError("temperature_range_invalid")
        now = _now()
        with transaction(immediate=True) as connection:
            cursor = connection.execute("INSERT INTO food_shipments(lot_id,shipment_code,carrier,vehicle_no,departure_at,arrival_due_at,destination,target_temp_min,target_temp_max,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)", (lot_id, payload["shipment_code"], payload["carrier"], payload["vehicle_no"], payload["departure_at"], payload["arrival_due_at"], payload["destination"], payload["target_temp_min"], payload["target_temp_max"], now, now))
            connection.execute("INSERT INTO food_audit(lot_id,action,actor,payload_json,created_at) VALUES(?,?,?,?,?)", (lot_id, "shipment.plan", actor, json.dumps(payload, ensure_ascii=False), now))
            return _dict(connection.execute("SELECT * FROM food_shipments WHERE id=?", (cursor.lastrowid,)).fetchone()) or {}

    def add_temperature(self, shipment_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        shipment = self.connection.execute("SELECT * FROM food_shipments WHERE id=?", (shipment_id,)).fetchone()
        if shipment is None:
            raise KeyError("shipment_not_found")
        in_range = int(shipment["target_temp_min"] <= payload["temperature_c"] <= shipment["target_temp_max"])
        now = _now()
        with transaction(immediate=True) as connection:
            existing = connection.execute("SELECT * FROM food_temperatures WHERE shipment_id=? AND recorded_at=?", (shipment_id, payload["recorded_at"])).fetchone()
            if existing:
                return dict(existing)
            cursor = connection.execute("INSERT INTO food_temperatures(shipment_id,recorded_at,temperature_c,source,in_range,created_at) VALUES(?,?,?,?,?,?)", (shipment_id, payload["recorded_at"], payload["temperature_c"], payload["source"], in_range, now))
            if not in_range:
                connection.execute("UPDATE food_shipments SET status='delayed',updated_at=? WHERE id=? AND status IN ('planned','in_transit')", (now, shipment_id))
            return _dict(connection.execute("SELECT * FROM food_temperatures WHERE id=?", (cursor.lastrowid,)).fetchone()) or {}

    def decide_risk(self, lot_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        with transaction(immediate=True) as connection:
            lot = connection.execute("SELECT * FROM food_lots WHERE id=?", (lot_id,)).fetchone()
            if lot is None:
                raise KeyError("lot_not_found")
            mapping = {"release": "released", "hold": "held", "recall": "recalled", "destroy": "destroyed"}
            new_status = mapping[payload["decision"]]
            now = _now()
            connection.execute("UPDATE food_lots SET status=?,version=version+1,updated_at=? WHERE id=?", (new_status, now, lot_id))
            connection.execute("INSERT INTO food_risk_actions(lot_id,decision,reason,operator,previous_status,new_status,created_at) VALUES(?,?,?,?,?,?,?)", (lot_id, payload["decision"], payload["reason"], payload["operator"], lot["status"], new_status, now))
            connection.execute("INSERT INTO food_audit(lot_id,action,actor,payload_json,created_at) VALUES(?,?,?,?,?)", (lot_id, "risk." + payload["decision"], payload["operator"], json.dumps(payload, ensure_ascii=False), now))
            return _dict(connection.execute("SELECT * FROM food_lots WHERE id=?", (lot_id,)).fetchone()) or {}

    def summary(self, lot_id: int) -> dict[str, Any]:
        lot = self.get_lot(lot_id, details=False)
        if lot is None:
            raise KeyError("lot_not_found")
        sample_count = self.connection.execute("SELECT COUNT(*) FROM food_samples WHERE lot_id=?", (lot_id,)).fetchone()[0]
        result_count = self.connection.execute("SELECT COUNT(*) FROM food_test_results r JOIN food_samples s ON s.id=r.sample_id WHERE s.lot_id=?", (lot_id,)).fetchone()[0]
        failed_count = self.connection.execute("SELECT COUNT(*) FROM food_test_results r JOIN food_samples s ON s.id=r.sample_id WHERE s.lot_id=? AND r.verdict='fail'", (lot_id,)).fetchone()[0]
        temperature_count = self.connection.execute("SELECT COUNT(*) FROM food_temperatures t JOIN food_shipments s ON s.id=t.shipment_id WHERE s.lot_id=?", (lot_id,)).fetchone()[0]
        return {"lot": lot, "sample_count": sample_count, "result_count": result_count, "failed_count": failed_count, "temperature_count": temperature_count}

    # ------------------------------------------------------------------
    # 批次拆分与下游送达
    # ------------------------------------------------------------------

    def split_lot(self, lot_id: int, payload: dict[str, Any], actor: str = "dispatcher") -> dict[str, Any]:
        """把批次拆成子批次；子批次挂到同一批次族（root_lot_id），继承状态与风险等级。"""
        with transaction(immediate=True) as connection:
            parent = connection.execute("SELECT * FROM food_lots WHERE id=?", (lot_id,)).fetchone()
            if parent is None:
                raise KeyError("lot_not_found")
            if payload["quantity_kg"] <= 0:
                raise ValueError("quantity_invalid")
            total_children = connection.execute("SELECT COALESCE(SUM(quantity_kg),0) FROM food_lots WHERE parent_lot_id=?", (lot_id,)).fetchone()[0]
            if total_children + payload["quantity_kg"] > parent["quantity_kg"] + 1e-9:
                raise ValueError("split_quantity_exceeds_lot")
            now = _now()
            cursor = connection.execute(
                "INSERT INTO food_lots(lot_code,product_name,category,supplier,origin,harvest_date,quantity_kg,trace_code,parent_lot_id,root_lot_id,status,risk_level,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (payload["lot_code"], parent["product_name"], parent["category"], parent["supplier"], parent["origin"], parent["harvest_date"], payload["quantity_kg"], payload["trace_code"], lot_id, parent["root_lot_id"], parent["status"], parent["risk_level"], now, now),
            )
            child_id = cursor.lastrowid
            connection.execute("UPDATE food_lots SET version=version+1,updated_at=? WHERE id=?", (now, lot_id))
            connection.execute("INSERT INTO food_audit(lot_id,action,actor,payload_json,created_at) VALUES(?,?,?,?,?)", (lot_id, "lot.split", actor, json.dumps({"child_lot_id": child_id, **payload}, ensure_ascii=False), now))
            # 若批次族存在进行中的召回，新拆出的子批次自动加入召回范围并继承召回原因。
            open_recall = connection.execute(
                "SELECT r.id, r.reason FROM food_recalls r JOIN food_recall_lots rl ON rl.recall_id=r.id WHERE r.root_lot_id=? AND r.status='open' AND rl.lot_id=?",
                (parent["root_lot_id"], lot_id),
            ).fetchone()
            if open_recall is not None:
                connection.execute(
                    "INSERT INTO food_recall_lots(recall_id,lot_id,inherited_from_lot_id,inherited_reason,quantity_kg,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",
                    (open_recall["id"], child_id, lot_id, open_recall["reason"], payload["quantity_kg"], now, now),
                )
                connection.execute(
                    "INSERT INTO food_audit(lot_id,action,actor,payload_json,created_at) VALUES(?,?,?,?,?)",
                    (child_id, "recall.initiate", actor, json.dumps({"recall_id": open_recall["id"], "reason": open_recall["reason"], "inherited": True}, ensure_ascii=False), now),
                )
            return _dict(connection.execute("SELECT * FROM food_lots WHERE id=?", (child_id,)).fetchone()) or {}

    def register_delivery(self, lot_id: int, payload: dict[str, Any], actor: str = "dispatcher") -> dict[str, Any]:
        """登记货物实际送达的下游节点（商户、食堂等）。"""
        with transaction(immediate=True) as connection:
            lot = connection.execute("SELECT id,root_lot_id FROM food_lots WHERE id=?", (lot_id,)).fetchone()
            if lot is None:
                raise KeyError("lot_not_found")
            shipment_id = None
            if payload.get("shipment_code"):
                shipment = connection.execute("SELECT id FROM food_shipments WHERE shipment_code=?", (payload["shipment_code"],)).fetchone()
                if shipment is None:
                    raise KeyError("shipment_not_found")
                shipment_id = shipment["id"]
            if payload["delivered_quantity_kg"] < 0:
                raise ValueError("quantity_invalid")
            now = _now()
            cursor = connection.execute(
                "INSERT INTO food_deliveries(lot_id,shipment_id,delivery_code,node_type,node_name,contact,address,delivered_quantity_kg,delivered_at,operator,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (lot_id, shipment_id, payload["delivery_code"], payload["node_type"], payload["node_name"], payload.get("contact", ""), payload.get("address", ""), payload["delivered_quantity_kg"], payload["delivered_at"], payload.get("operator", actor), now),
            )
            delivery_id = cursor.lastrowid
            connection.execute("INSERT INTO food_audit(lot_id,action,actor,payload_json,created_at) VALUES(?,?,?,?,?)", (lot_id, "delivery.register", payload.get("operator", actor), json.dumps(payload, ensure_ascii=False), now))
            return _dict(connection.execute("SELECT * FROM food_deliveries WHERE id=?", (delivery_id,)).fetchone()) or {}

    # ------------------------------------------------------------------
    # 召回事件与召回闭环
    # ------------------------------------------------------------------

    def initiate_recall(self, lot_id: int, payload: dict[str, Any], actor: str = "regulator") -> dict[str, Any]:
        """确认农残超标后发起召回：覆盖整个批次族（含已拆分子批次），冻结下游节点快照并生成通知。"""
        operator = payload.get("operator", actor)
        with transaction(immediate=True) as connection:
            lot = connection.execute("SELECT * FROM food_lots WHERE id=?", (lot_id,)).fetchone()
            if lot is None:
                raise KeyError("lot_not_found")
            root_id = lot["root_lot_id"] or lot_id
            open_recall = connection.execute("SELECT id FROM food_recalls WHERE root_lot_id=? AND status='open'", (root_id,)).fetchone()
            if open_recall is not None:
                raise ValueError("recall_already_open")

            trigger = connection.execute(
                "SELECT r.analyte,r.value_mg_kg,r.limit_mg_kg,r.sample_id FROM food_test_results r JOIN food_samples s ON s.id=r.sample_id WHERE s.lot_id=? AND r.verdict='fail' ORDER BY r.tested_at DESC,r.id DESC LIMIT 1",
                (lot_id,),
            ).fetchone()
            analyte = payload.get("analyte") or (trigger["analyte"] if trigger else "")
            value_mg_kg = payload.get("value_mg_kg") if payload.get("value_mg_kg") is not None else (trigger["value_mg_kg"] if trigger else None)
            limit_mg_kg = payload.get("limit_mg_kg") if payload.get("limit_mg_kg") is not None else (trigger["limit_mg_kg"] if trigger else None)
            trigger_sample_id = trigger["sample_id"] if trigger else None

            now = _now()
            cursor = connection.execute(
                "INSERT INTO food_recalls(recall_code,root_lot_id,trigger_sample_id,analyte,value_mg_kg,limit_mg_kg,reason,level,initiated_by,initiated_at,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                (payload["recall_code"], root_id, trigger_sample_id, analyte, value_mg_kg, limit_mg_kg, payload["reason"], payload.get("level", "secondary"), operator, now, now, now),
            )
            recall_id = cursor.lastrowid

            family = connection.execute("SELECT * FROM food_lots WHERE root_lot_id=? ORDER BY id", (root_id,)).fetchall()
            for family_lot in family:
                inherited_from = None if family_lot["id"] == root_id else (family_lot["parent_lot_id"] or root_id)
                inherited_reason = "" if family_lot["id"] == root_id else payload["reason"]
                connection.execute(
                    "INSERT INTO food_recall_lots(recall_id,lot_id,inherited_from_lot_id,inherited_reason,quantity_kg,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",
                    (recall_id, family_lot["id"], inherited_from, inherited_reason, family_lot["quantity_kg"], now, now),
                )
                connection.execute("UPDATE food_lots SET status='recalled',risk_level='critical',version=version+1,updated_at=? WHERE id=?", (now, family_lot["id"]))
                connection.execute(
                    "INSERT INTO food_audit(lot_id,action,actor,payload_json,created_at) VALUES(?,?,?,?,?)",
                    (family_lot["id"], "recall.initiate", operator, json.dumps({"recall_id": recall_id, "reason": payload["reason"], "inherited": inherited_from is not None}, ensure_ascii=False), now),
                )

            self._sync_recall_nodes(connection, recall_id, root_id, operator, now)
            return _dict(connection.execute("SELECT * FROM food_recalls WHERE id=?", (recall_id,)).fetchone()) or {}

    @staticmethod
    def _sync_recall_nodes(connection: sqlite3.Connection, recall_id: int, root_lot_id: int, operator: str, now: str) -> dict[str, int]:
        """把批次族当前全部下游送达冻结为快照并补建通知；已存在的快照与通知保持不动、不重复计数。"""
        deliveries = connection.execute(
            "SELECT d.* FROM food_deliveries d JOIN food_lots l ON l.id=d.lot_id WHERE l.root_lot_id=? ORDER BY d.id",
            (root_lot_id,),
        ).fetchall()
        snapshot_count = 0
        notice_count = 0
        for delivery in deliveries:
            snapshot = connection.execute("SELECT id FROM food_recall_snapshots WHERE recall_id=? AND delivery_id=?", (recall_id, delivery["id"])).fetchone()
            if snapshot is None:
                snapshot_cursor = connection.execute(
                    "INSERT INTO food_recall_snapshots(recall_id,delivery_id,lot_id,node_type,node_name,contact,address,delivered_quantity_kg,delivered_at,snapshot_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                    (recall_id, delivery["id"], delivery["lot_id"], delivery["node_type"], delivery["node_name"], delivery["contact"], delivery["address"], delivery["delivered_quantity_kg"], delivery["delivered_at"], now),
                )
                snapshot_id = snapshot_cursor.lastrowid
                snapshot_count += 1
            else:
                snapshot_id = snapshot["id"]
            notice = connection.execute("SELECT id FROM food_recall_notices WHERE recall_id=? AND snapshot_id=?", (recall_id, snapshot_id)).fetchone()
            if notice is None:
                notice_code = f"NOTICE-R{recall_id}-S{snapshot_id}"
                connection.execute(
                    "INSERT INTO food_recall_notices(recall_id,snapshot_id,notice_code,channel,created_at,updated_at) VALUES(?,?,?,?,?,?)",
                    (recall_id, snapshot_id, notice_code, "sms", now, now),
                )
                notice_count += 1
        connection.execute(
            "INSERT INTO food_audit(lot_id,action,actor,payload_json,created_at) VALUES(?,?,?,?,?)",
            (root_lot_id, "recall.sync_nodes", operator, json.dumps({"recall_id": recall_id, "new_snapshots": snapshot_count, "new_notices": notice_count}, ensure_ascii=False), now),
        )
        return {"snapshots": snapshot_count, "notices": notice_count}

    def sync_recall_nodes(self, recall_id: int, actor: str = "regulator") -> dict[str, int]:
        """召回发起后又发现新的送达节点时补录；重复调用不会重复生成或重复计数。"""
        with transaction(immediate=True) as connection:
            recall = connection.execute("SELECT * FROM food_recalls WHERE id=?", (recall_id,)).fetchone()
            if recall is None:
                raise KeyError("recall_not_found")
            if recall["status"] != "open":
                raise ValueError("recall_not_open")
            return self._sync_recall_nodes(connection, recall_id, recall["root_lot_id"], actor, _now())

    def record_notice_attempt(self, notice_id: int, payload: dict[str, Any], actor: str = "dispatcher") -> dict[str, Any]:
        """记录一次通知投递（首发或重试）。已送达/已回执的通知重复投递不再计数。"""
        operator = payload.get("operator", actor)
        result = payload["result"]
        if result not in {"delivered", "failed"}:
            raise ValueError("notice_result_invalid")
        with transaction(immediate=True) as connection:
            notice = connection.execute("SELECT * FROM food_recall_notices WHERE id=?", (notice_id,)).fetchone()
            if notice is None:
                raise KeyError("notice_not_found")
            recall = connection.execute("SELECT status FROM food_recalls WHERE id=?", (notice["recall_id"],)).fetchone()
            if recall["status"] != "open":
                raise ValueError("recall_not_open")
            # 幂等：已经实际送达或已回执的通知，重复提交直接返回，attempt_count 不增加。
            if notice["delivery_status"] == "delivered" or notice["receipt_status"] != "pending":
                return _dict(notice) or {}
            if notice["delivery_status"] == "failed":
                raise ValueError("notice_delivery_exhausted")
            channel = payload.get("channel") or notice["channel"]
            now = _now()
            attempt_no = notice["attempt_count"] + 1
            connection.execute(
                "INSERT INTO food_recall_notice_attempts(notice_id,attempt_no,channel,result,detail,operator,attempted_at) VALUES(?,?,?,?,?,?,?)",
                (notice_id, attempt_no, channel, result, payload.get("detail", ""), operator, now),
            )
            if result == "delivered":
                connection.execute(
                    "UPDATE food_recall_notices SET attempt_count=?,delivery_status='delivered',first_sent_at=COALESCE(first_sent_at,?),last_attempt_at=?,updated_at=? WHERE id=?",
                    (attempt_no, now, now, now, notice_id),
                )
            else:
                final_status = "failed" if attempt_no >= notice["max_attempts"] else "pending"
                connection.execute(
                    "UPDATE food_recall_notices SET attempt_count=?,delivery_status=?,first_sent_at=COALESCE(first_sent_at,?),last_attempt_at=?,updated_at=? WHERE id=?",
                    (attempt_no, final_status, now, now, now, notice_id),
                )
            snapshot = connection.execute("SELECT lot_id FROM food_recall_snapshots WHERE id=?", (notice["snapshot_id"],)).fetchone()
            connection.execute(
                "INSERT INTO food_audit(lot_id,action,actor,payload_json,created_at) VALUES(?,?,?,?,?)",
                (snapshot["lot_id"], "notice.attempt", operator, json.dumps({"recall_id": notice["recall_id"], "notice_id": notice_id, "attempt_no": attempt_no, "result": result}, ensure_ascii=False), now),
            )
            return _dict(connection.execute("SELECT * FROM food_recall_notices WHERE id=?", (notice_id,)).fetchone()) or {}

    def acknowledge_receipt(self, notice_id: int, payload: dict[str, Any], actor: str = "node") -> dict[str, Any]:
        """下游节点回执：确认收到召回通知，并上报现场尚存、已销毁、已退回、已售出数量。"""
        acknowledged_by = payload.get("acknowledged_by", actor)
        with transaction(immediate=True) as connection:
            notice = connection.execute("SELECT * FROM food_recall_notices WHERE id=?", (notice_id,)).fetchone()
            if notice is None:
                raise KeyError("notice_not_found")
            recall = connection.execute("SELECT status FROM food_recalls WHERE id=?", (notice["recall_id"],)).fetchone()
            if recall["status"] != "open":
                raise ValueError("recall_not_open")
            existing = connection.execute("SELECT * FROM food_recall_receipts WHERE notice_id=?", (notice_id,)).fetchone()
            if existing is not None:
                # 回执幂等：重复提交直接返回原回执，已处置数量不重复累加。
                return dict(existing)
            snapshot = connection.execute("SELECT * FROM food_recall_snapshots WHERE id=?", (notice["snapshot_id"],)).fetchone()
            for key in ("on_hand_quantity_kg", "disposed_quantity_kg", "returned_quantity_kg", "sold_quantity_kg"):
                if payload.get(key, 0) < 0:
                    raise ValueError("quantity_invalid")
            now = _now()
            received_at = payload.get("received_at") or now
            cursor = connection.execute(
                "INSERT INTO food_recall_receipts(notice_id,recall_id,snapshot_id,acknowledged_by,contact,on_hand_quantity_kg,disposed_quantity_kg,returned_quantity_kg,sold_quantity_kg,note,received_at,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                (notice_id, notice["recall_id"], notice["snapshot_id"], acknowledged_by, payload.get("contact", ""), payload.get("on_hand_quantity_kg", 0), payload.get("disposed_quantity_kg", 0), payload.get("returned_quantity_kg", 0), payload.get("sold_quantity_kg", 0), payload.get("note", ""), received_at, now),
            )
            connection.execute(
                "UPDATE food_recall_notices SET delivery_status='delivered',receipt_status='acknowledged',acknowledged_by=?,acknowledged_at=?,updated_at=? WHERE id=?",
                (acknowledged_by, now, now, notice_id),
            )
            connection.execute(
                "INSERT INTO food_audit(lot_id,action,actor,payload_json,created_at) VALUES(?,?,?,?,?)",
                (snapshot["lot_id"], "receipt.acknowledge", acknowledged_by, json.dumps({"recall_id": notice["recall_id"], "notice_id": notice_id, "snapshot_id": snapshot["id"], **payload}, ensure_ascii=False), now),
            )
            return _dict(connection.execute("SELECT * FROM food_recall_receipts WHERE id=?", (cursor.lastrowid,)).fetchone()) or {}

    def confirm_recall_lot(self, recall_id: int, lot_id: int, payload: dict[str, Any] | None = None, actor: str = "regulator") -> dict[str, Any]:
        """分别确认召回范围内的某个（子）批次；该批次下游节点全部回执后方可确认。"""
        payload = payload or {}
        operator = payload.get("operator", actor)
        with transaction(immediate=True) as connection:
            recall = connection.execute("SELECT status FROM food_recalls WHERE id=?", (recall_id,)).fetchone()
            if recall is None:
                raise KeyError("recall_not_found")
            if recall["status"] != "open":
                raise ValueError("recall_not_open")
            recall_lot = connection.execute("SELECT * FROM food_recall_lots WHERE recall_id=? AND lot_id=?", (recall_id, lot_id)).fetchone()
            if recall_lot is None:
                raise KeyError("recall_lot_not_found")
            if recall_lot["lot_status"] in {"confirmed", "exempted"}:
                return dict(recall_lot)
            if payload.get("exempt"):
                now = _now()
                connection.execute("UPDATE food_recall_lots SET lot_status='exempted',confirmed_by=?,confirmed_at=?,updated_at=? WHERE id=?", (operator, now, now, recall_lot["id"]))
                connection.execute("INSERT INTO food_audit(lot_id,action,actor,payload_json,created_at) VALUES(?,?,?,?,?)", (lot_id, "recall_lot.exempt", operator, json.dumps({"recall_id": recall_id, "reason": payload.get("reason", "")}, ensure_ascii=False), now))
                return _dict(connection.execute("SELECT * FROM food_recall_lots WHERE id=?", (recall_lot["id"],)).fetchone()) or {}
            pending = connection.execute(
                "SELECT COUNT(*) FROM food_recall_snapshots s LEFT JOIN food_recall_notices n ON n.snapshot_id=s.id WHERE s.recall_id=? AND s.lot_id=? AND (n.id IS NULL OR n.receipt_status!='acknowledged')",
                (recall_id, lot_id),
            ).fetchone()[0]
            if pending:
                raise ValueError("receipts_pending")
            now = _now()
            connection.execute("UPDATE food_recall_lots SET lot_status='confirmed',confirmed_by=?,confirmed_at=?,updated_at=? WHERE id=?", (operator, now, now, recall_lot["id"]))
            connection.execute("INSERT INTO food_audit(lot_id,action,actor,payload_json,created_at) VALUES(?,?,?,?,?)", (lot_id, "recall_lot.confirm", operator, json.dumps({"recall_id": recall_id}, ensure_ascii=False), now))
            return _dict(connection.execute("SELECT * FROM food_recall_lots WHERE id=?", (recall_lot["id"],)).fetchone()) or {}

    def get_recall(self, recall_id: int) -> dict[str, Any] | None:
        recall = self.connection.execute("SELECT * FROM food_recalls WHERE id=?", (recall_id,)).fetchone()
        return dict(recall) if recall else None

    def recall_progress(self, recall_id: int) -> dict[str, Any]:
        """召回闭环查询：未确认节点、数量差额、通知重试情况与最终关闭条件。"""
        recall = self.connection.execute("SELECT * FROM food_recalls WHERE id=?", (recall_id,)).fetchone()
        if recall is None:
            raise KeyError("recall_not_found")
        recall = dict(recall)

        lots = [dict(row) for row in self.connection.execute(
            """
            SELECT rl.*, l.lot_code, l.parent_lot_id,
                   (SELECT COUNT(*) FROM food_recall_snapshots s WHERE s.recall_id=rl.recall_id AND s.lot_id=rl.lot_id) AS node_count,
                   (SELECT COUNT(*) FROM food_recall_snapshots s
                      JOIN food_recall_notices n ON n.snapshot_id=s.id
                    WHERE s.recall_id=rl.recall_id AND s.lot_id=rl.lot_id AND n.receipt_status='acknowledged') AS acknowledged_count
            FROM food_recall_lots rl JOIN food_lots l ON l.id=rl.lot_id
            WHERE rl.recall_id=? ORDER BY rl.id
            """,
            (recall_id,),
        ).fetchall()]
        lot_status = {lot["lot_id"]: lot["lot_status"] for lot in lots}

        nodes = []
        rows = self.connection.execute(
            """
            SELECT s.id AS snapshot_id, s.lot_id, s.node_type, s.node_name, s.contact, s.address,
                   s.delivered_quantity_kg, s.delivered_at, s.snapshot_at,
                   n.id AS notice_id, n.notice_code, n.attempt_count, n.max_attempts,
                   n.delivery_status, n.receipt_status, n.last_attempt_at, n.acknowledged_at,
                   r.acknowledged_by, r.received_at, r.on_hand_quantity_kg, r.disposed_quantity_kg,
                   r.returned_quantity_kg, r.sold_quantity_kg
            FROM food_recall_snapshots s
            LEFT JOIN food_recall_notices n ON n.snapshot_id = s.id
            LEFT JOIN food_recall_receipts r ON r.notice_id = n.id
            WHERE s.recall_id=?
            ORDER BY s.delivered_at, s.id
            """,
            (recall_id,),
        ).fetchall()
        # 已豁免批次视为转线下处置，其下游节点不再计入未确认清单、数量差额与关闭条件。
        totals = {"delivered_kg": 0.0, "on_hand_kg": 0.0, "disposed_kg": 0.0, "returned_kg": 0.0, "sold_kg": 0.0}
        unacknowledged: list[dict[str, Any]] = []
        retry_pending: list[dict[str, Any]] = []
        active_nodes: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            item["lot_status"] = lot_status.get(item["lot_id"], "pending")
            delivered = float(item["delivered_quantity_kg"] or 0)
            on_hand = float(item.get("on_hand_quantity_kg") or 0)
            disposed = float(item.get("disposed_quantity_kg") or 0)
            returned = float(item.get("returned_quantity_kg") or 0)
            sold = float(item.get("sold_quantity_kg") or 0)
            item["accounted_quantity_kg"] = round(on_hand + disposed + returned + sold, 3)
            item["quantity_gap_kg"] = round(delivered - item["accounted_quantity_kg"], 3)
            receipt_ok = item["receipt_status"] == "acknowledged"
            item["confirmed"] = bool(receipt_ok)
            nodes.append(item)
            if item["lot_status"] == "exempted":
                continue
            active_nodes.append(item)
            totals["delivered_kg"] += delivered
            totals["on_hand_kg"] += on_hand
            totals["disposed_kg"] += disposed
            totals["returned_kg"] += returned
            totals["sold_kg"] += sold
            if not receipt_ok:
                unacknowledged.append({
                    "snapshot_id": item["snapshot_id"],
                    "notice_id": item["notice_id"],
                    "lot_id": item["lot_id"],
                    "node_type": item["node_type"],
                    "node_name": item["node_name"],
                    "delivered_quantity_kg": delivered,
                    "delivery_status": item["delivery_status"],
                    "receipt_status": item["receipt_status"],
                    "attempt_count": item["attempt_count"] or 0,
                    "quantity_gap_kg": item["quantity_gap_kg"],
                })
            if item["delivery_status"] in {"pending", "failed"}:
                retry_pending.append({
                    "notice_id": item["notice_id"],
                    "node_name": item["node_name"],
                    "delivery_status": item["delivery_status"],
                    "attempt_count": item["attempt_count"] or 0,
                    "max_attempts": item["max_attempts"],
                    "can_retry": item["delivery_status"] == "pending" and (item["attempt_count"] or 0) < (item["max_attempts"] or 0),
                })

        totals = {key: round(value, 3) for key, value in totals.items()}
        totals["accounted_kg"] = round(totals["on_hand_kg"] + totals["disposed_kg"] + totals["returned_kg"] + totals["sold_kg"], 3)
        totals["gap_kg"] = round(totals["delivered_kg"] - totals["accounted_kg"], 3)

        total_nodes = len(active_nodes)
        delivered_nodes = sum(1 for item in active_nodes if item["delivery_status"] == "delivered")
        acknowledged_nodes = sum(1 for item in active_nodes if item["receipt_status"] == "acknowledged")
        failed_notices = sum(1 for item in active_nodes if item["delivery_status"] == "failed")
        confirmed_lots = sum(1 for lot in lots if lot["lot_status"] in {"confirmed", "exempted"})

        conditions = [
            {"code": "all_notices_delivered", "label": "全部下游通知已送达", "satisfied": delivered_nodes == total_nodes and failed_notices == 0, "detail": f"已送达 {delivered_nodes}/{total_nodes}，投递失败 {failed_notices}"},
            {"code": "all_receipts_acknowledged", "label": "全部下游节点已回执确认", "satisfied": acknowledged_nodes == total_nodes, "detail": f"已回执 {acknowledged_nodes}/{total_nodes}"},
            {"code": "all_lots_confirmed", "label": "召回范围内批次（含子批次）已分别确认", "satisfied": bool(lots) and confirmed_lots == len(lots), "detail": f"已确认 {confirmed_lots}/{len(lots)}"},
            {"code": "quantity_reconciled", "label": "送达数量与处置/退回/售出/存量数量核对一致", "satisfied": abs(totals["gap_kg"]) < 1e-6, "detail": f"送达 {totals['delivered_kg']}kg，已核对 {totals['accounted_kg']}kg，差额 {totals['gap_kg']}kg"},
        ]
        closable = all(condition["satisfied"] for condition in conditions) and recall["status"] == "open"

        attempts = [dict(row) for row in self.connection.execute(
            """
            SELECT a.notice_id, a.attempt_no, a.channel, a.result, a.detail, a.operator, a.attempted_at, n.notice_code
            FROM food_recall_notice_attempts a JOIN food_recall_notices n ON n.id=a.notice_id
            WHERE n.recall_id=? ORDER BY a.attempted_at, a.id
            """,
            (recall_id,),
        ).fetchall()]
        # 召回相关操作时间线：审计 payload 中带有该 recall_id 的记录（发起、节点同步、通知投递、回执、批次确认、关闭）。
        events = []
        for row in self.connection.execute(
            "SELECT lot_id,action,actor,payload_json,created_at FROM food_audit WHERE action IN ('recall.initiate','recall.sync_nodes','recall_lot.confirm','recall_lot.exempt','recall.close','notice.attempt','receipt.acknowledge') ORDER BY created_at,id",
        ).fetchall():
            try:
                payload = json.loads(row["payload_json"])
            except (TypeError, ValueError):
                continue
            if payload.get("recall_id") == recall_id:
                events.append(dict(row))

        return {
            "recall": recall,
            "lots": lots,
            "nodes": nodes,
            "unacknowledged_nodes": unacknowledged,
            "retry_pending": retry_pending,
            "notice_attempts": attempts,
            "quantities": totals,
            "exempted_node_count": len(nodes) - len(active_nodes),
            "close_conditions": conditions,
            "closable": closable,
            "timeline": events,
        }

    def close_recall(self, recall_id: int, payload: dict[str, Any] | None = None, actor: str = "regulator") -> dict[str, Any]:
        """满足全部关闭条件后关闭召回事件。"""
        payload = payload or {}
        operator = payload.get("operator", actor)
        progress = self.recall_progress(recall_id)
        if progress["recall"]["status"] != "open":
            raise ValueError("recall_not_open")
        unsatisfied = [condition["code"] for condition in progress["close_conditions"] if not condition["satisfied"]]
        if unsatisfied:
            raise ValueError("recall_close_conditions_unsatisfied:" + ",".join(unsatisfied))
        now = _now()
        with transaction(immediate=True) as connection:
            connection.execute(
                "UPDATE food_recalls SET status='closed',closed_by=?,close_remark=?,closed_at=?,updated_at=? WHERE id=?",
                (operator, payload.get("remark", ""), now, now, recall_id),
            )
            connection.execute(
                "UPDATE food_recall_lots SET lot_status='closed',updated_at=? WHERE recall_id=? AND lot_status='confirmed'",
                (now, recall_id),
            )
            connection.execute(
                "INSERT INTO food_audit(lot_id,action,actor,payload_json,created_at) VALUES(?,?,?,?,?)",
                (progress["recall"]["root_lot_id"], "recall.close", operator, json.dumps({"recall_id": recall_id, "remark": payload.get("remark", "")}, ensure_ascii=False), now),
            )
            return _dict(connection.execute("SELECT * FROM food_recalls WHERE id=?", (recall_id,)).fetchone()) or {}

    def delete_lot(self, lot_id: int) -> bool:
        """移除尚未关联记录的批次；关联记录的错误映射由上层负责。"""
        with transaction(immediate=True) as connection:
            cursor = connection.execute("DELETE FROM food_lots WHERE id=?", (lot_id,))
            if cursor.rowcount == 0:
                raise KeyError("lot_not_found")
            return True
