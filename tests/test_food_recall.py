from __future__ import annotations


def lot(client, code="LOT-R001", quantity=500):
    response = client.post("/api/food/lots", json={"lot_code": code, "product_name": "菠菜", "category": "叶菜", "supplier": "安心农场", "origin": "山东寿光", "harvest_date": "2026-09-20", "quantity_kg": quantity, "trace_code": code + "-TRACE"})
    assert response.status_code == 201, response.text
    return response.json()


def shipment(client, lot_id, code, destination, quantity=None):
    body = {"shipment_code": code, "carrier": "冷链物流", "vehicle_no": "鲁A001", "departure_at": "2026-09-22T01:00:00+00:00", "arrival_due_at": "2026-09-22T10:00:00+00:00", "destination": destination, "target_temp_min": 0, "target_temp_max": 8}
    if quantity is not None:
        body["quantity_kg"] = quantity
    response = client.post(f"/api/food/lots/{lot_id}/shipments", json=body)
    assert response.status_code == 201, response.text
    return response.json()


def recall(client, lot_id, code="RC-001", **extra):
    body = {"recall_code": code, "reason": "毒死蜱超标确认", "operator": "监管员"}
    body.update(extra)
    response = client.post(f"/api/food/lots/{lot_id}/recalls", json=body)
    assert response.status_code == 201, response.text
    return response.json()


def test_recall_closed_loop_with_snapshot_and_receipts(client):
    created = lot(client)
    shipment(client, created["id"], "SHIP-R1", "惠民商户", 200)
    shipment(client, created["id"], "SHIP-R2", "惠民商户", 50)
    shipment(client, created["id"], "SHIP-R3", "机关食堂", 250)

    opened = recall(client, created["id"])
    detail = client.get(f"/api/food/recalls/{opened['recall']['id']}").json()
    assert detail["recall"]["status"] == "open"
    assert detail["recall"]["reason"] == "毒死蜱超标确认"
    assert detail["recall"]["operator"] == "监管员"
    assert detail["recall"]["created_at"]
    assert client.get(f"/api/food/lots/{created['id']}").json()["status"] == "recalled"
    # 同一目的地的运输单合并为一个下游节点，数量取运输单合计
    assert [(n["node_name"], n["quantity_kg"]) for n in detail["nodes"]] == [("惠民商户", 250), ("机关食堂", 250)]
    assert detail["summary"]["total_quantity_kg"] == 500
    assert detail["summary"]["remaining_kg"] == 500
    assert {n["node_name"] for n in detail["unacknowledged_nodes"]} == {"惠民商户", "机关食堂"}
    assert detail["closure"]["closable"] is False

    merchant, canteen = detail["nodes"]
    # 通知生成幂等：重复生成不重复计数
    first = client.post(f"/api/food/recalls/{opened['recall']['id']}/notifications", json={"operator": "监管员", "channel": "短信"})
    assert first.status_code == 200 and first.json()["created_count"] == 2
    again = client.post(f"/api/food/recalls/{opened['recall']['id']}/notifications", json={"operator": "监管员"})
    assert again.json()["created_count"] == 0 and again.json()["existing_count"] == 2
    assert len(again.json()["notifications"]) == 2

    # 未通知的节点不能登记回执；通知可重试并留痕
    retry = client.post(f"/api/food/recalls/{opened['recall']['id']}/nodes/{merchant['id']}/notification/retry", json={"operator": "监管员", "result": "delivered", "note": "二次拨打接通"})
    assert retry.status_code == 200 and retry.json()["attempt_no"] == 2
    assert retry.json()["notification"]["status"] == "delivered"

    # 回执登记前不能确认处置
    early = client.post(f"/api/food/recalls/{opened['recall']['id']}/nodes/{merchant['id']}/disposals", json={"quantity_kg": 10, "operator": "商户负责人"})
    assert early.status_code == 409 and early.json()["detail"] == "node_not_acknowledged"

    receipt = client.post(f"/api/food/recalls/{opened['recall']['id']}/nodes/{merchant['id']}/receipt", json={"acknowledged_by": "商户负责人", "operator": "监管员"})
    assert receipt.status_code == 200 and receipt.json()["status"] == "acknowledged"
    assert receipt.json()["acknowledged_at"] and receipt.json()["acknowledged_by"] == "商户负责人"
    # 重复回执不重复计数，状态不变
    duplicate = client.post(f"/api/food/recalls/{opened['recall']['id']}/nodes/{merchant['id']}/receipt", json={"acknowledged_by": "商户负责人", "operator": "监管员"})
    assert duplicate.status_code == 200 and duplicate.json()["acknowledged_at"] == receipt.json()["acknowledged_at"]

    # 部分处置后仍有差额；超额处置被拒绝
    partial = client.post(f"/api/food/recalls/{opened['recall']['id']}/nodes/{merchant['id']}/disposals", json={"quantity_kg": 100, "operator": "商户负责人", "method": "destroy"})
    assert partial.status_code == 201 and partial.json()["disposed_kg"] == 100 and partial.json()["status"] == "acknowledged"
    over = client.post(f"/api/food/recalls/{opened['recall']['id']}/nodes/{merchant['id']}/disposals", json={"quantity_kg": 200, "operator": "商户负责人"})
    assert over.status_code == 409 and over.json()["detail"] == "disposal_exceeds_quantity"
    done = client.post(f"/api/food/recalls/{opened['recall']['id']}/nodes/{merchant['id']}/disposals", json={"quantity_kg": 150, "operator": "商户负责人"})
    assert done.json()["status"] == "disposed" and done.json()["confirmed_at"] and done.json()["confirmed_by"] == "商户负责人"

    # 食堂节点尚未回执，召回不能关闭
    blocked = client.post(f"/api/food/recalls/{opened['recall']['id']}/close", json={"operator": "监管员"})
    assert blocked.status_code == 409 and blocked.json()["detail"] == "recall_not_closable"
    progress = client.get(f"/api/food/recalls/{opened['recall']['id']}").json()
    assert [n["node_name"] for n in progress["unacknowledged_nodes"]] == ["机关食堂"]
    assert progress["summary"]["disposed_kg"] == 250 and progress["summary"]["remaining_kg"] == 250
    conditions = {c["code"]: c for c in progress["closure"]["conditions"]}
    assert conditions["all_acknowledged"]["satisfied"] is False
    assert conditions["all_disposed"]["satisfied"] is False

    client.post(f"/api/food/recalls/{opened['recall']['id']}/notifications", json={"operator": "监管员"})
    client.post(f"/api/food/recalls/{opened['recall']['id']}/nodes/{canteen['id']}/receipt", json={"acknowledged_by": "食堂管理员", "operator": "监管员"})
    client.post(f"/api/food/recalls/{opened['recall']['id']}/nodes/{canteen['id']}/disposals", json={"quantity_kg": 250, "operator": "食堂管理员", "method": "return"})

    ready = client.get(f"/api/food/recalls/{opened['recall']['id']}").json()
    assert ready["closure"]["closable"] is True
    assert ready["summary"]["remaining_kg"] == 0
    closed = client.post(f"/api/food/recalls/{opened['recall']['id']}/close", json={"operator": "监管员"})
    assert closed.status_code == 200
    assert closed.json()["recall"]["status"] == "closed"
    assert closed.json()["recall"]["closed_at"] and closed.json()["recall"]["closed_by"] == "监管员"
    again_close = client.post(f"/api/food/recalls/{opened['recall']['id']}/close", json={"operator": "监管员"})
    assert again_close.status_code == 409 and again_close.json()["detail"] == "recall_already_closed"


def test_recall_explicit_nodes_and_progress_query(client):
    created = lot(client, "LOT-R002")
    opened = recall(client, created["id"], "RC-002", nodes=[{"node_name": "城东商户", "node_type": "merchant", "quantity_kg": 120}, {"node_name": "希望小学食堂", "node_type": "canteen", "quantity_kg": 80}])
    detail = client.get(f"/api/food/recalls/{opened['recall']['id']}").json()
    assert [(n["node_name"], n["node_type"]) for n in detail["nodes"]] == [("城东商户", "merchant"), ("希望小学食堂", "canteen")]
    assert detail["summary"]["node_count"] == 2
    assert detail["summary"]["total_quantity_kg"] == 200
    assert detail["summary"]["unacknowledged_count"] == 2

    added = client.post(f"/api/food/recalls/{opened['recall']['id']}/nodes", json={"node_name": "临时摊点", "node_type": "other", "quantity_kg": 30, "operator": "监管员"})
    assert added.status_code == 201 and added.json()["status"] == "pending"
    duplicate = client.post(f"/api/food/recalls/{opened['recall']['id']}/nodes", json={"node_name": "临时摊点", "quantity_kg": 10, "operator": "监管员"})
    assert duplicate.status_code == 409

    generated = client.post(f"/api/food/recalls/{opened['recall']['id']}/notifications", json={"operator": "监管员"})
    assert generated.json()["created_count"] == 3
    progress = client.get(f"/api/food/recalls/{opened['recall']['id']}").json()
    assert progress["summary"]["notification_count"] == 3
    assert progress["summary"]["attempt_count"] == 3
    assert progress["summary"]["remaining_kg"] == 230
    assert len(progress["unacknowledged_nodes"]) == 3


def test_recall_guards(client):
    created = lot(client, "LOT-R003")
    opened = recall(client, created["id"], "RC-003", nodes=[{"node_name": "城西商户", "quantity_kg": 100}])
    recall_id = opened["recall"]["id"]
    node_id = opened["nodes"][0]["id"]

    second = client.post(f"/api/food/lots/{created['id']}/recalls", json={"recall_code": "RC-003B", "reason": "重复发起", "operator": "监管员"})
    assert second.status_code == 409 and second.json()["detail"] == "recall_already_open"

    retry_without_notice = client.post(f"/api/food/recalls/{recall_id}/nodes/{node_id}/notification/retry", json={"operator": "监管员"})
    assert retry_without_notice.status_code == 409 and retry_without_notice.json()["detail"] == "notification_not_found"
    receipt_without_notice = client.post(f"/api/food/recalls/{recall_id}/nodes/{node_id}/receipt", json={"acknowledged_by": "商户", "operator": "监管员"})
    assert receipt_without_notice.status_code == 409 and receipt_without_notice.json()["detail"] == "notification_not_found"

    missing = client.get("/api/food/recalls/99999")
    assert missing.status_code == 404


def test_split_inherits_recall_reason_with_separate_confirmation(client):
    created = lot(client, "LOT-R004", 500)
    opened = recall(client, created["id"], "RC-004", nodes=[{"node_name": "批发商户", "quantity_kg": 500}])
    parent_recall_id = opened["recall"]["id"]

    split = client.post(f"/api/food/lots/{created['id']}/splits", json={"operator": "监管员", "splits": [
        {"lot_code": "LOT-R004-A", "trace_code": "LOT-R004-A-TRACE", "quantity_kg": 200, "nodes": [{"node_name": "城东商户", "quantity_kg": 200}]},
        {"lot_code": "LOT-R004-B", "trace_code": "LOT-R004-B-TRACE", "quantity_kg": 300, "nodes": [{"node_name": "职工食堂", "node_type": "canteen", "quantity_kg": 300}]},
    ]})
    assert split.status_code == 201, split.text
    body = split.json()
    assert [child["parent_lot_id"] for child in body["children"]] == [created["id"], created["id"]]
    assert {child["status"] for child in body["children"]} == {"recalled"}
    assert len(body["recalls"]) == 2
    for child_recall in body["recalls"]:
        assert child_recall["reason"] == "毒死蜱超标确认"
        assert child_recall["parent_recall_id"] == parent_recall_id
        assert child_recall["status"] == "open"

    # 子批次召回分别确认：先闭环 A，B 仍处于未确认状态
    child_a, child_b = body["recalls"]
    detail_a = client.get(f"/api/food/recalls/{child_a['id']}").json()
    node_a = detail_a["nodes"][0]
    client.post(f"/api/food/recalls/{child_a['id']}/notifications", json={"operator": "监管员"})
    client.post(f"/api/food/recalls/{child_a['id']}/nodes/{node_a['id']}/receipt", json={"acknowledged_by": "商户负责人", "operator": "监管员"})
    client.post(f"/api/food/recalls/{child_a['id']}/nodes/{node_a['id']}/disposals", json={"quantity_kg": 200, "operator": "商户负责人"})
    closed_a = client.post(f"/api/food/recalls/{child_a['id']}/close", json={"operator": "监管员"})
    assert closed_a.status_code == 200 and closed_a.json()["recall"]["status"] == "closed"

    detail_b = client.get(f"/api/food/recalls/{child_b['id']}").json()
    assert detail_b["recall"]["status"] == "open"
    assert detail_b["closure"]["closable"] is False
    assert [n["node_name"] for n in detail_b["unacknowledged_nodes"]] == ["职工食堂"]
    # 父批次召回不受子批次影响，仍各自闭环
    parent = client.get(f"/api/food/recalls/{parent_recall_id}").json()
    assert parent["recall"]["status"] == "open"

    # 拆分数量累计不得超过原批次数量
    overflow = client.post(f"/api/food/lots/{created['id']}/splits", json={"operator": "监管员", "splits": [{"lot_code": "LOT-R004-C", "trace_code": "LOT-R004-C-TRACE", "quantity_kg": 1}]})
    assert overflow.status_code == 409 and overflow.json()["detail"] == "split_quantity_exceeds"


def test_recall_audit_trail(client):
    created = lot(client, "LOT-R005")
    opened = recall(client, created["id"], "RC-005", nodes=[{"node_name": "城北商户", "quantity_kg": 60}])
    recall_id = opened["recall"]["id"]
    node_id = opened["nodes"][0]["id"]
    client.post(f"/api/food/recalls/{recall_id}/notifications", json={"operator": "监管员"})
    client.post(f"/api/food/recalls/{recall_id}/nodes/{node_id}/notification/retry", json={"operator": "监管员", "result": "failed", "note": "电话无人接听"})
    client.post(f"/api/food/recalls/{recall_id}/nodes/{node_id}/notification/retry", json={"operator": "监管员", "result": "delivered"})
    client.post(f"/api/food/recalls/{recall_id}/nodes/{node_id}/receipt", json={"acknowledged_by": "商户负责人", "operator": "监管员"})
    client.post(f"/api/food/recalls/{recall_id}/nodes/{node_id}/disposals", json={"quantity_kg": 60, "operator": "商户负责人"})
    client.post(f"/api/food/recalls/{recall_id}/close", json={"operator": "监管员"})

    from app.database import get_connection
    connection = get_connection()
    actions = [row[0] for row in connection.execute("SELECT action FROM food_audit WHERE lot_id=? ORDER BY id", (created["id"],)).fetchall()]
    for expected in ("recall.create", "recall.notify", "recall.notify_retry", "recall.receipt", "recall.disposal", "recall.close"):
        assert expected in actions
    attempts = connection.execute("SELECT attempt_no,result,operator,created_at FROM food_recall_notification_attempts ORDER BY notification_id,attempt_no").fetchall()
    assert [(row[0], row[1]) for row in attempts] == [(1, "sent"), (2, "failed"), (3, "delivered")]
    assert all(row[2] and row[3] for row in attempts)
    disposals = connection.execute("SELECT quantity_kg,operator,created_at FROM food_recall_disposals").fetchall()
    assert len(disposals) == 1 and disposals[0][0] == 60 and disposals[0][1] and disposals[0][2]
    notification = connection.execute("SELECT attempts,status FROM food_recall_notifications").fetchone()
    assert notification[0] == 3 and notification[1] == "acknowledged"
