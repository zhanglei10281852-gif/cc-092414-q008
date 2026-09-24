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
    status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','testing','released','held','recalled','destroyed')),
    risk_level TEXT NOT NULL DEFAULT 'unknown' CHECK(risk_level IN ('unknown','low','medium','high','critical')),
    parent_lot_id INTEGER REFERENCES food_lots(id),
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
    quantity_kg REAL,
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
CREATE TABLE IF NOT EXISTS food_audit (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    lot_id INTEGER,
    action TEXT NOT NULL,
    actor TEXT NOT NULL,
    payload_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS food_recalls (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    recall_code TEXT NOT NULL UNIQUE,
    lot_id INTEGER NOT NULL REFERENCES food_lots(id) ON DELETE RESTRICT,
    parent_recall_id INTEGER REFERENCES food_recalls(id),
    reason TEXT NOT NULL,
    level TEXT NOT NULL DEFAULT 'high' CHECK(level IN ('low','medium','high','critical')),
    status TEXT NOT NULL DEFAULT 'open' CHECK(status IN ('open','closed')),
    operator TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    closed_at TEXT,
    closed_by TEXT
);
CREATE TABLE IF NOT EXISTS food_recall_nodes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    recall_id INTEGER NOT NULL REFERENCES food_recalls(id) ON DELETE CASCADE,
    node_name TEXT NOT NULL,
    node_type TEXT NOT NULL DEFAULT 'merchant' CHECK(node_type IN ('merchant','canteen','other')),
    shipment_id INTEGER REFERENCES food_shipments(id),
    quantity_kg REAL NOT NULL DEFAULT 0,
    disposed_kg REAL NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','notified','acknowledged','disposed')),
    acknowledged_at TEXT,
    acknowledged_by TEXT,
    confirmed_at TEXT,
    confirmed_by TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(recall_id, node_name)
);
CREATE TABLE IF NOT EXISTS food_recall_notifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    recall_id INTEGER NOT NULL REFERENCES food_recalls(id) ON DELETE CASCADE,
    node_id INTEGER NOT NULL REFERENCES food_recall_nodes(id) ON DELETE CASCADE,
    channel TEXT NOT NULL DEFAULT 'manual',
    status TEXT NOT NULL DEFAULT 'sent' CHECK(status IN ('sent','delivered','failed','acknowledged')),
    attempts INTEGER NOT NULL DEFAULT 0,
    last_attempt_at TEXT,
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(recall_id, node_id)
);
CREATE TABLE IF NOT EXISTS food_recall_notification_attempts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    notification_id INTEGER NOT NULL REFERENCES food_recall_notifications(id) ON DELETE CASCADE,
    attempt_no INTEGER NOT NULL,
    result TEXT NOT NULL CHECK(result IN ('sent','delivered','failed')),
    operator TEXT NOT NULL,
    note TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    UNIQUE(notification_id, attempt_no)
);
CREATE TABLE IF NOT EXISTS food_recall_disposals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    recall_id INTEGER NOT NULL REFERENCES food_recalls(id) ON DELETE CASCADE,
    node_id INTEGER NOT NULL REFERENCES food_recall_nodes(id) ON DELETE CASCADE,
    quantity_kg REAL NOT NULL,
    method TEXT NOT NULL DEFAULT 'destroy' CHECK(method IN ('destroy','return','seal','other')),
    operator TEXT NOT NULL,
    note TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_food_samples_lot ON food_samples(lot_id, collected_at);
CREATE INDEX IF NOT EXISTS idx_food_results_sample ON food_test_results(sample_id, tested_at);
CREATE INDEX IF NOT EXISTS idx_food_shipments_lot ON food_shipments(lot_id, departure_at);
CREATE INDEX IF NOT EXISTS idx_food_recalls_lot ON food_recalls(lot_id, status);
CREATE INDEX IF NOT EXISTS idx_food_recall_nodes_recall ON food_recall_nodes(recall_id, status);
CREATE INDEX IF NOT EXISTS idx_food_recall_disposals_node ON food_recall_disposals(node_id, created_at);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


QUANTITY_EPSILON = 1e-6


def _ensure_column(connection: sqlite3.Connection, table: str, column: str, definition: str) -> None:
    columns = {row[1] for row in connection.execute(f"PRAGMA table_info({table})")}
    if column not in columns:
        connection.execute(f"ALTER TABLE {table} ADD COLUMN {definition}")


def ensure_schema() -> None:
    connection = get_connection()
    connection.executescript(SCHEMA)
    _ensure_column(connection, "food_lots", "parent_lot_id", "parent_lot_id INTEGER REFERENCES food_lots(id)")
    _ensure_column(connection, "food_shipments", "quantity_kg", "quantity_kg REAL")


def _dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    return dict(row) if row else None


def _result_hash(payload: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


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
            result["recalls"] = [dict(row) for row in self.connection.execute("SELECT * FROM food_recalls WHERE lot_id=? ORDER BY id", (lot_id,)).fetchall()]
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
            cursor = connection.execute("INSERT INTO food_shipments(lot_id,shipment_code,carrier,vehicle_no,departure_at,arrival_due_at,destination,target_temp_min,target_temp_max,quantity_kg,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)", (lot_id, payload["shipment_code"], payload["carrier"], payload["vehicle_no"], payload["departure_at"], payload["arrival_due_at"], payload["destination"], payload["target_temp_min"], payload["target_temp_max"], payload.get("quantity_kg"), now, now))
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

    def _snapshot_nodes(self, connection: sqlite3.Connection, lot_id: int) -> list[dict[str, Any]]:
        """按运输目的地合并生成下游节点快照；运输单未登记数量时节点数量为 0。"""
        rows = connection.execute("SELECT destination, COUNT(*) AS shipment_count, MIN(id) AS first_shipment_id, COALESCE(SUM(quantity_kg),0) AS total_quantity FROM food_shipments WHERE lot_id=? AND status!='cancelled' GROUP BY destination ORDER BY destination", (lot_id,)).fetchall()
        return [{"node_name": row["destination"], "node_type": "other", "shipment_id": row["first_shipment_id"] if row["shipment_count"] == 1 else None, "quantity_kg": row["total_quantity"]} for row in rows]

    def _insert_recall_nodes(self, connection: sqlite3.Connection, recall_id: int, nodes: list[dict[str, Any]], now: str) -> None:
        for node in nodes:
            connection.execute("INSERT INTO food_recall_nodes(recall_id,node_name,node_type,shipment_id,quantity_kg,created_at,updated_at) VALUES(?,?,?,?,?,?,?)", (recall_id, node["node_name"], node.get("node_type", "merchant"), node.get("shipment_id"), node.get("quantity_kg", 0), now, now))

    def create_recall(self, lot_id: int, payload: dict[str, Any], actor: str = "regulator") -> dict[str, Any]:
        """确认农残超标后创建召回事件，同时冻结批次并生成下游节点快照。"""
        now = _now()
        with transaction(immediate=True) as connection:
            lot = connection.execute("SELECT * FROM food_lots WHERE id=?", (lot_id,)).fetchone()
            if lot is None:
                raise KeyError("lot_not_found")
            if lot["status"] == "destroyed":
                raise ValueError("lot_destroyed")
            if connection.execute("SELECT id FROM food_recalls WHERE lot_id=? AND status='open'", (lot_id,)).fetchone():
                raise ValueError("recall_already_open")
            level = payload.get("level") or (lot["risk_level"] if lot["risk_level"] in {"low", "medium", "high", "critical"} else "high")
            cursor = connection.execute("INSERT INTO food_recalls(recall_code,lot_id,parent_recall_id,reason,level,operator,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)", (payload["recall_code"], lot_id, payload.get("parent_recall_id"), payload["reason"], level, payload["operator"], now, now))
            recall_id = cursor.lastrowid
            nodes = payload.get("nodes") or self._snapshot_nodes(connection, lot_id)
            self._insert_recall_nodes(connection, recall_id, nodes, now)
            connection.execute("UPDATE food_lots SET status='recalled',version=version+1,updated_at=? WHERE id=?", (now, lot_id))
            connection.execute("INSERT INTO food_risk_actions(lot_id,decision,reason,operator,previous_status,new_status,created_at) VALUES(?,?,?,?,?,?,?)", (lot_id, "recall", payload["reason"], payload["operator"], lot["status"], "recalled", now))
            connection.execute("INSERT INTO food_audit(lot_id,action,actor,payload_json,created_at) VALUES(?,?,?,?,?)", (lot_id, "recall.create", actor, json.dumps({**payload, "recall_id": recall_id, "node_count": len(nodes)}, ensure_ascii=False), now))
            return self.get_recall(recall_id) or {}

    def list_recalls(self, lot_id: int) -> list[dict[str, Any]]:
        if self.connection.execute("SELECT id FROM food_lots WHERE id=?", (lot_id,)).fetchone() is None:
            raise KeyError("lot_not_found")
        return [dict(row) for row in self.connection.execute("SELECT * FROM food_recalls WHERE lot_id=? ORDER BY id", (lot_id,)).fetchall()]

    def get_recall(self, recall_id: int) -> dict[str, Any] | None:
        """召回进度视图：节点回执、数量差额与关闭条件一并返回。"""
        recall = self.connection.execute("SELECT * FROM food_recalls WHERE id=?", (recall_id,)).fetchone()
        if recall is None:
            return None
        node_items = []
        for node in self.connection.execute("SELECT * FROM food_recall_nodes WHERE recall_id=? ORDER BY id", (recall_id,)).fetchall():
            item = dict(node)
            item["remaining_kg"] = round(node["quantity_kg"] - node["disposed_kg"], 6)
            notification = self.connection.execute("SELECT * FROM food_recall_notifications WHERE recall_id=? AND node_id=?", (recall_id, node["id"])).fetchone()
            item["notification"] = dict(notification) if notification else None
            node_items.append(item)
        total_quantity = round(sum(item["quantity_kg"] for item in node_items), 6)
        disposed = round(sum(item["disposed_kg"] for item in node_items), 6)
        remaining = round(total_quantity - disposed, 6)
        unacknowledged = [item for item in node_items if item["acknowledged_at"] is None]
        all_acknowledged = not unacknowledged
        all_disposed = remaining <= QUANTITY_EPSILON
        attempt_count = self.connection.execute("SELECT COALESCE(SUM(attempts),0) FROM food_recall_notifications WHERE recall_id=?", (recall_id,)).fetchone()[0]
        return {
            "recall": dict(recall),
            "nodes": node_items,
            "summary": {
                "node_count": len(node_items),
                "acknowledged_count": len(node_items) - len(unacknowledged),
                "unacknowledged_count": len(unacknowledged),
                "disposed_node_count": sum(1 for item in node_items if item["status"] == "disposed"),
                "total_quantity_kg": total_quantity,
                "disposed_kg": disposed,
                "remaining_kg": remaining,
                "notification_count": sum(1 for item in node_items if item["notification"]),
                "attempt_count": attempt_count,
            },
            "unacknowledged_nodes": [{"id": item["id"], "node_name": item["node_name"], "quantity_kg": item["quantity_kg"], "notification_status": (item["notification"] or {}).get("status")} for item in unacknowledged],
            "closure": {
                "closable": recall["status"] == "open" and all_acknowledged and all_disposed,
                "conditions": [
                    {"code": "all_acknowledged", "satisfied": all_acknowledged, "unacknowledged_nodes": [item["node_name"] for item in unacknowledged]},
                    {"code": "all_disposed", "satisfied": all_disposed, "remaining_kg": remaining},
                ],
            },
        }

    def _open_recall(self, connection: sqlite3.Connection, recall_id: int) -> sqlite3.Row:
        recall = connection.execute("SELECT * FROM food_recalls WHERE id=?", (recall_id,)).fetchone()
        if recall is None:
            raise KeyError("recall_not_found")
        if recall["status"] != "open":
            raise ValueError("recall_closed")
        return recall

    def _recall_node(self, connection: sqlite3.Connection, recall_id: int, node_id: int) -> sqlite3.Row:
        node = connection.execute("SELECT * FROM food_recall_nodes WHERE id=? AND recall_id=?", (node_id, recall_id)).fetchone()
        if node is None:
            raise KeyError("node_not_found")
        return node

    def add_recall_node(self, recall_id: int, payload: dict[str, Any], actor: str = "regulator") -> dict[str, Any]:
        """召回创建后补充新发现的下游节点。"""
        now = _now()
        with transaction(immediate=True) as connection:
            recall = self._open_recall(connection, recall_id)
            cursor = connection.execute("INSERT INTO food_recall_nodes(recall_id,node_name,node_type,shipment_id,quantity_kg,created_at,updated_at) VALUES(?,?,?,?,?,?,?)", (recall_id, payload["node_name"], payload.get("node_type", "merchant"), payload.get("shipment_id"), payload["quantity_kg"], now, now))
            connection.execute("UPDATE food_recalls SET updated_at=? WHERE id=?", (now, recall_id))
            connection.execute("INSERT INTO food_audit(lot_id,action,actor,payload_json,created_at) VALUES(?,?,?,?,?)", (recall["lot_id"], "recall.node_add", actor, json.dumps({**payload, "recall_id": recall_id}, ensure_ascii=False), now))
            return _dict(connection.execute("SELECT * FROM food_recall_nodes WHERE id=?", (cursor.lastrowid,)).fetchone()) or {}

    def generate_notifications(self, recall_id: int, payload: dict[str, Any], actor: str = "regulator") -> dict[str, Any]:
        """为尚未通知的节点生成通知；重复调用只补新节点，不重复计数。"""
        now = _now()
        with transaction(immediate=True) as connection:
            recall = self._open_recall(connection, recall_id)
            channel = payload.get("channel", "manual")
            operator = payload["operator"]
            created, existing = [], []
            for node in connection.execute("SELECT * FROM food_recall_nodes WHERE recall_id=? ORDER BY id", (recall_id,)).fetchall():
                cursor = connection.execute("INSERT OR IGNORE INTO food_recall_notifications(recall_id,node_id,channel,status,attempts,last_attempt_at,created_by,created_at,updated_at) VALUES(?,?,?,'sent',1,?,?,?,?)", (recall_id, node["id"], channel, now, operator, now, now))
                if cursor.rowcount:
                    connection.execute("INSERT INTO food_recall_notification_attempts(notification_id,attempt_no,result,operator,note,created_at) VALUES(?,?,?,?,?,?)", (cursor.lastrowid, 1, "sent", operator, "首次生成", now))
                    connection.execute("UPDATE food_recall_nodes SET status='notified',updated_at=? WHERE id=? AND status='pending'", (now, node["id"]))
                    created.append(node["id"])
                else:
                    existing.append(node["id"])
            connection.execute("UPDATE food_recalls SET updated_at=? WHERE id=?", (now, recall_id))
            connection.execute("INSERT INTO food_audit(lot_id,action,actor,payload_json,created_at) VALUES(?,?,?,?,?)", (recall["lot_id"], "recall.notify", actor, json.dumps({"recall_id": recall_id, "operator": operator, "created_node_ids": created, "existing_node_ids": existing}, ensure_ascii=False), now))
            notifications = [dict(row) for row in connection.execute("SELECT * FROM food_recall_notifications WHERE recall_id=? ORDER BY id", (recall_id,)).fetchall()]
            return {"recall_id": recall_id, "created_count": len(created), "existing_count": len(existing), "notifications": notifications}

    def retry_notification(self, recall_id: int, node_id: int, payload: dict[str, Any], actor: str = "regulator") -> dict[str, Any]:
        """通知重试：追加一次投递尝试并更新通知状态，全部留痕。"""
        now = _now()
        with transaction(immediate=True) as connection:
            recall = self._open_recall(connection, recall_id)
            self._recall_node(connection, recall_id, node_id)
            notification = connection.execute("SELECT * FROM food_recall_notifications WHERE recall_id=? AND node_id=?", (recall_id, node_id)).fetchone()
            if notification is None:
                raise ValueError("notification_not_found")
            if notification["status"] == "acknowledged":
                raise ValueError("notification_already_acknowledged")
            result = payload.get("result", "delivered")
            attempt_no = notification["attempts"] + 1
            connection.execute("INSERT INTO food_recall_notification_attempts(notification_id,attempt_no,result,operator,note,created_at) VALUES(?,?,?,?,?,?)", (notification["id"], attempt_no, result, payload["operator"], payload.get("note", ""), now))
            connection.execute("UPDATE food_recall_notifications SET status=?,attempts=?,last_attempt_at=?,updated_at=? WHERE id=?", (result, attempt_no, now, now, notification["id"]))
            connection.execute("UPDATE food_recalls SET updated_at=? WHERE id=?", (now, recall_id))
            connection.execute("INSERT INTO food_audit(lot_id,action,actor,payload_json,created_at) VALUES(?,?,?,?,?)", (recall["lot_id"], "recall.notify_retry", actor, json.dumps({"recall_id": recall_id, "node_id": node_id, "attempt_no": attempt_no, "result": result, "operator": payload["operator"]}, ensure_ascii=False), now))
            return {"notification": _dict(connection.execute("SELECT * FROM food_recall_notifications WHERE id=?", (notification["id"],)).fetchone()), "attempt_no": attempt_no, "result": result}

    def acknowledge_node(self, recall_id: int, node_id: int, payload: dict[str, Any], actor: str = "regulator") -> dict[str, Any]:
        """登记节点回执；重复登记返回现状，不重复计数。"""
        now = _now()
        with transaction(immediate=True) as connection:
            recall = self._open_recall(connection, recall_id)
            node = self._recall_node(connection, recall_id, node_id)
            notification = connection.execute("SELECT * FROM food_recall_notifications WHERE recall_id=? AND node_id=?", (recall_id, node_id)).fetchone()
            if notification is None:
                raise ValueError("notification_not_found")
            if node["acknowledged_at"] is not None:
                return dict(node)
            connection.execute("UPDATE food_recall_nodes SET status='acknowledged',acknowledged_at=?,acknowledged_by=?,updated_at=? WHERE id=?", (now, payload["acknowledged_by"], now, node_id))
            connection.execute("UPDATE food_recall_notifications SET status='acknowledged',updated_at=? WHERE id=?", (now, notification["id"]))
            connection.execute("UPDATE food_recalls SET updated_at=? WHERE id=?", (now, recall_id))
            connection.execute("INSERT INTO food_audit(lot_id,action,actor,payload_json,created_at) VALUES(?,?,?,?,?)", (recall["lot_id"], "recall.receipt", actor, json.dumps({"recall_id": recall_id, "node_id": node_id, "acknowledged_by": payload["acknowledged_by"], "operator": payload["operator"]}, ensure_ascii=False), now))
            return _dict(connection.execute("SELECT * FROM food_recall_nodes WHERE id=?", (node_id,)).fetchone()) or {}

    def record_disposal(self, recall_id: int, node_id: int, payload: dict[str, Any], actor: str = "regulator") -> dict[str, Any]:
        """登记节点已处置数量；须先收到回执，累计不得超过节点应收数量。"""
        now = _now()
        with transaction(immediate=True) as connection:
            recall = self._open_recall(connection, recall_id)
            node = self._recall_node(connection, recall_id, node_id)
            if node["acknowledged_at"] is None:
                raise ValueError("node_not_acknowledged")
            new_disposed = node["disposed_kg"] + payload["quantity_kg"]
            if new_disposed - node["quantity_kg"] > QUANTITY_EPSILON:
                raise ValueError("disposal_exceeds_quantity")
            connection.execute("INSERT INTO food_recall_disposals(recall_id,node_id,quantity_kg,method,operator,note,created_at) VALUES(?,?,?,?,?,?,?)", (recall_id, node_id, payload["quantity_kg"], payload.get("method", "destroy"), payload["operator"], payload.get("note", ""), now))
            if new_disposed >= node["quantity_kg"] - QUANTITY_EPSILON:
                connection.execute("UPDATE food_recall_nodes SET disposed_kg=?,status='disposed',confirmed_at=?,confirmed_by=?,updated_at=? WHERE id=?", (new_disposed, now, payload["operator"], now, node_id))
            else:
                connection.execute("UPDATE food_recall_nodes SET disposed_kg=?,updated_at=? WHERE id=?", (new_disposed, now, node_id))
            connection.execute("UPDATE food_recalls SET updated_at=? WHERE id=?", (now, recall_id))
            connection.execute("INSERT INTO food_audit(lot_id,action,actor,payload_json,created_at) VALUES(?,?,?,?,?)", (recall["lot_id"], "recall.disposal", actor, json.dumps({"recall_id": recall_id, "node_id": node_id, "quantity_kg": payload["quantity_kg"], "operator": payload["operator"]}, ensure_ascii=False), now))
            return _dict(connection.execute("SELECT * FROM food_recall_nodes WHERE id=?", (node_id,)).fetchone()) or {}

    def close_recall(self, recall_id: int, payload: dict[str, Any], actor: str = "regulator") -> dict[str, Any]:
        """全部节点已回执且数量全部处置到位后才允许关闭召回。"""
        now = _now()
        with transaction(immediate=True) as connection:
            recall = connection.execute("SELECT * FROM food_recalls WHERE id=?", (recall_id,)).fetchone()
            if recall is None:
                raise KeyError("recall_not_found")
            if recall["status"] == "closed":
                raise ValueError("recall_already_closed")
            progress = self.get_recall(recall_id) or {}
            if not progress["closure"]["closable"]:
                raise ValueError("recall_not_closable")
            connection.execute("UPDATE food_recalls SET status='closed',closed_at=?,closed_by=?,updated_at=? WHERE id=?", (now, payload["operator"], now, recall_id))
            connection.execute("INSERT INTO food_audit(lot_id,action,actor,payload_json,created_at) VALUES(?,?,?,?,?)", (recall["lot_id"], "recall.close", actor, json.dumps({"recall_id": recall_id, "operator": payload["operator"]}, ensure_ascii=False), now))
            return self.get_recall(recall_id) or {}

    def split_lot(self, lot_id: int, payload: dict[str, Any], actor: str = "system") -> dict[str, Any]:
        """拆分子批次；存在未关闭召回时子批次继承召回原因并各自独立确认。"""
        now = _now()
        with transaction(immediate=True) as connection:
            parent = connection.execute("SELECT * FROM food_lots WHERE id=?", (lot_id,)).fetchone()
            if parent is None:
                raise KeyError("lot_not_found")
            if parent["status"] == "destroyed":
                raise ValueError("lot_destroyed")
            splits = payload["splits"]
            existing_total = connection.execute("SELECT COALESCE(SUM(quantity_kg),0) FROM food_lots WHERE parent_lot_id=?", (lot_id,)).fetchone()[0]
            new_total = sum(item["quantity_kg"] for item in splits)
            if existing_total + new_total - parent["quantity_kg"] > QUANTITY_EPSILON:
                raise ValueError("split_quantity_exceeds")
            open_recall = connection.execute("SELECT * FROM food_recalls WHERE lot_id=? AND status='open' ORDER BY id DESC LIMIT 1", (lot_id,)).fetchone()
            children, recalls = [], []
            for item in splits:
                cursor = connection.execute("INSERT INTO food_lots(lot_code,product_name,category,supplier,origin,harvest_date,quantity_kg,trace_code,status,risk_level,parent_lot_id,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)", (item["lot_code"], parent["product_name"], parent["category"], parent["supplier"], parent["origin"], parent["harvest_date"], item["quantity_kg"], item["trace_code"], parent["status"], parent["risk_level"], lot_id, now, now))
                child_id = cursor.lastrowid
                children.append(child_id)
                if open_recall is not None:
                    child_recall_code = f"{open_recall['recall_code']}-{item['lot_code']}"
                    recall_cursor = connection.execute("INSERT INTO food_recalls(recall_code,lot_id,parent_recall_id,reason,level,operator,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)", (child_recall_code, child_id, open_recall["id"], open_recall["reason"], open_recall["level"], payload["operator"], now, now))
                    child_recall_id = recall_cursor.lastrowid
                    self._insert_recall_nodes(connection, child_recall_id, item.get("nodes") or [], now)
                    connection.execute("INSERT INTO food_audit(lot_id,action,actor,payload_json,created_at) VALUES(?,?,?,?,?)", (child_id, "recall.create", payload["operator"], json.dumps({"recall_id": child_recall_id, "parent_recall_id": open_recall["id"], "reason": open_recall["reason"], "inherited": True}, ensure_ascii=False), now))
                    recalls.append(child_recall_id)
            connection.execute("INSERT INTO food_audit(lot_id,action,actor,payload_json,created_at) VALUES(?,?,?,?,?)", (lot_id, "lot.split", actor, json.dumps({"operator": payload["operator"], "children": children, "recalls": recalls, "quantities": [item["quantity_kg"] for item in splits]}, ensure_ascii=False), now))
            return {
                "parent_lot_id": lot_id,
                "children": [_dict(connection.execute("SELECT * FROM food_lots WHERE id=?", (child_id,)).fetchone()) for child_id in children],
                "recalls": [_dict(connection.execute("SELECT * FROM food_recalls WHERE id=?", (recall_id,)).fetchone()) for recall_id in recalls],
            }

    def summary(self, lot_id: int) -> dict[str, Any]:
        lot = self.get_lot(lot_id, details=False)
        if lot is None:
            raise KeyError("lot_not_found")
        sample_count = self.connection.execute("SELECT COUNT(*) FROM food_samples WHERE lot_id=?", (lot_id,)).fetchone()[0]
        result_count = self.connection.execute("SELECT COUNT(*) FROM food_test_results r JOIN food_samples s ON s.id=r.sample_id WHERE s.lot_id=?", (lot_id,)).fetchone()[0]
        failed_count = self.connection.execute("SELECT COUNT(*) FROM food_test_results r JOIN food_samples s ON s.id=r.sample_id WHERE s.lot_id=? AND r.verdict='fail'", (lot_id,)).fetchone()[0]
        temperature_count = self.connection.execute("SELECT COUNT(*) FROM food_temperatures t JOIN food_shipments s ON s.id=t.shipment_id WHERE s.lot_id=?", (lot_id,)).fetchone()[0]
        return {"lot": lot, "sample_count": sample_count, "result_count": result_count, "failed_count": failed_count, "temperature_count": temperature_count}

    def delete_lot(self, lot_id: int) -> bool:
        """移除尚未关联记录的批次；关联记录的错误映射由上层负责。"""
        with transaction(immediate=True) as connection:
            cursor = connection.execute("DELETE FROM food_lots WHERE id=?", (lot_id,))
            if cursor.rowcount == 0:
                raise KeyError("lot_not_found")
            return True
