from __future__ import annotations


def _lot(client, code="LOT-R01", quantity=500):
    response = client.post("/api/food/lots", json={"lot_code": code, "product_name": "菠菜", "category": "叶菜", "supplier": "安心农场", "origin": "山东寿光", "harvest_date": "2026-09-20", "quantity_kg": quantity, "trace_code": code + "-TRACE"})
    assert response.status_code == 201, response.text
    return response.json()


def _fail_lot(client, lot_id, sample_code="S-R01"):
    sample = client.post(f"/api/food/lots/{lot_id}/samples", json={"sample_code": sample_code, "collected_at": "2026-09-21T08:00:00+00:00", "collector": "监管员", "location": "批发市场", "sample_weight_g": 250}).json()
    result = client.post(f"/api/food/samples/{sample['id']}/results", json={"analyte": "毒死蜱", "method": "GB/T 5009", "value_mg_kg": 0.3, "limit_mg_kg": 0.05, "lab_operator": "实验员", "tested_at": "2026-09-21T18:00:00+00:00"})
    assert result.status_code == 201 and result.json()["verdict"] == "fail"


def _deliver(client, lot_id, code, node_type, node_name, quantity, delivered_at="2026-09-22T09:00:00+00:00"):
    response = client.post(f"/api/food/lots/{lot_id}/deliveries", json={"delivery_code": code, "node_type": node_type, "node_name": node_name, "contact": "张经理", "address": "城东市场1号", "delivered_quantity_kg": quantity, "delivered_at": delivered_at})
    assert response.status_code == 201, response.text
    return response.json()


def _recall(client, lot_id, code="RECALL-001"):
    response = client.post(f"/api/food/lots/{lot_id}/recalls", json={"recall_code": code, "reason": "毒死蜱残留超标", "level": "secondary", "operator": "监管员甲"})
    assert response.status_code == 201, response.text
    return response.json()


def test_recall_snapshot_and_notice_retry(client):
    lot = _lot(client)
    _fail_lot(client, lot["id"])
    _deliver(client, lot["id"], "DLV-1", "merchant", "城东蔬菜店", 120)
    _deliver(client, lot["id"], "DLV-2", "canteen", "第一中学食堂", 80)

    recall = _recall(client, lot["id"])
    assert recall["status"] == "open"
    assert recall["analyte"] == "毒死蜱" and recall["value_mg_kg"] == 0.3
    assert recall["initiated_by"] == "监管员甲" and recall["initiated_at"]

    progress = client.get(f"/api/food/recalls/{recall['id']}/progress").json()
    assert len(progress["nodes"]) == 2
    assert {node["node_name"] for node in progress["nodes"]} == {"城东蔬菜店", "第一中学食堂"}
    assert progress["quantities"]["delivered_kg"] == 200
    assert len(progress["unacknowledged_nodes"]) == 2

    # 重复发起召回被拒绝
    again = client.post(f"/api/food/lots/{lot['id']}/recalls", json={"recall_code": "RECALL-002", "reason": "重复"})
    assert again.status_code == 409

    # 第一次投递失败，可重试；第二次送达
    notice_id = progress["nodes"][0]["notice_id"]
    failed = client.post(f"/api/food/notices/{notice_id}/attempts", json={"result": "failed", "operator": "配送员"})
    assert failed.status_code == 201 and failed.json()["attempt_count"] == 1
    assert failed.json()["delivery_status"] == "pending"
    delivered = client.post(f"/api/food/notices/{notice_id}/attempts", json={"result": "delivered", "operator": "配送员"})
    assert delivered.status_code == 201 and delivered.json()["attempt_count"] == 2
    assert delivered.json()["delivery_status"] == "delivered"

    # 已送达后重复投递不再计数
    dup = client.post(f"/api/food/notices/{notice_id}/attempts", json={"result": "delivered"})
    assert dup.status_code == 201 and dup.json()["attempt_count"] == 2

    progress = client.get(f"/api/food/recalls/{recall['id']}/progress").json()
    attempts = [a for a in progress["notice_attempts"] if a["notice_id"] == notice_id]
    assert len(attempts) == 2 and attempts[0]["result"] == "failed" and attempts[1]["result"] == "delivered"
    assert all(a["operator"] == "配送员" and a["attempted_at"] for a in attempts)


def test_recall_receipt_and_close_conditions(client):
    lot = _lot(client, "LOT-R02")
    _fail_lot(client, lot["id"], "S-R02")
    _deliver(client, lot["id"], "DLV-3", "merchant", "城西蔬菜店", 100)
    _deliver(client, lot["id"], "DLV-4", "canteen", "机关食堂", 50)
    recall = _recall(client, lot["id"], "RECALL-002")

    progress = client.get(f"/api/food/recalls/{recall['id']}/progress").json()
    # 未回执、未送达时不可关闭
    assert progress["closable"] is False
    early = client.post(f"/api/food/recalls/{recall['id']}/close", json={"operator": "监管员乙"})
    assert early.status_code == 409

    for node in progress["nodes"]:
        client.post(f"/api/food/notices/{node['notice_id']}/attempts", json={"result": "delivered"})

    # 第一个节点回执：部分销毁、部分退回、部分已售出
    first = progress["nodes"][0]
    receipt = client.post(f"/api/food/notices/{first['notice_id']}/receipt", json={"acknowledged_by": "店长", "on_hand_quantity_kg": 10, "disposed_quantity_kg": 60, "returned_quantity_kg": 20, "sold_quantity_kg": 10, "note": "现场封存"})
    assert receipt.status_code == 201, receipt.text
    # 回执幂等：重复提交不重复计数
    dup = client.post(f"/api/food/notices/{first['notice_id']}/receipt", json={"acknowledged_by": "店长", "disposed_quantity_kg": 60})
    assert dup.status_code == 201 and dup.json()["id"] == receipt.json()["id"]

    progress = client.get(f"/api/food/recalls/{recall['id']}/progress").json()
    assert len(progress["unacknowledged_nodes"]) == 1
    assert progress["quantities"]["disposed_kg"] == 60
    assert progress["quantities"]["gap_kg"] == 50  # 第二个节点尚未回执

    second = [n for n in progress["nodes"] if n["notice_id"] != first["notice_id"]][0]
    client.post(f"/api/food/notices/{second['notice_id']}/receipt", json={"acknowledged_by": "食堂管理员", "disposed_quantity_kg": 50})

    progress = client.get(f"/api/food/recalls/{recall['id']}/progress").json()
    assert progress["unacknowledged_nodes"] == []
    assert progress["quantities"]["gap_kg"] == 0
    assert all(c["satisfied"] for c in progress["close_conditions"] if c["code"] != "all_lots_confirmed")

    # 批次确认后满足全部关闭条件
    confirm = client.post(f"/api/food/recalls/{recall['id']}/lots/{lot['id']}/confirm", json={"operator": "监管员乙"})
    assert confirm.status_code == 200 and confirm.json()["lot_status"] == "confirmed"
    progress = client.get(f"/api/food/recalls/{recall['id']}/progress").json()
    assert progress["closable"] is True

    closed = client.post(f"/api/food/recalls/{recall['id']}/close", json={"operator": "监管员乙", "remark": "处置完毕"})
    assert closed.status_code == 200, closed.text
    assert closed.json()["status"] == "closed" and closed.json()["closed_by"] == "监管员乙" and closed.json()["closed_at"]

    # 时间线包含发起、投递、回执、确认、关闭，且都有操作者
    timeline = client.get(f"/api/food/recalls/{recall['id']}/progress").json()["timeline"]
    actions = {event["action"] for event in timeline}
    assert {"recall.initiate", "notice.attempt", "receipt.acknowledge", "recall_lot.confirm", "recall.close"} <= actions
    assert all(event["actor"] and event["created_at"] for event in timeline)


def test_recall_covers_split_sub_lots_with_independent_confirmation(client):
    lot = _lot(client, "LOT-R03", 500)
    _fail_lot(client, lot["id"], "S-R03")
    _deliver(client, lot["id"], "DLV-5", "merchant", "总店", 300)

    # 拆分出子批次并分别配送
    child = client.post(f"/api/food/lots/{lot['id']}/split", json={"lot_code": "LOT-R03-A", "trace_code": "LOT-R03-A-T", "quantity_kg": 200})
    assert child.status_code == 201, child.text
    child = child.json()
    assert child["parent_lot_id"] == lot["id"] and child["root_lot_id"] == lot["id"]
    _deliver(client, child["id"], "DLV-6", "canteen", "分店食堂", 150)

    recall = _recall(client, lot["id"], "RECALL-003")
    progress = client.get(f"/api/food/recalls/{recall['id']}/progress").json()
    assert len(progress["lots"]) == 2
    # 子批次继承召回原因
    child_lot = [item for item in progress["lots"] if item["lot_id"] == child["id"]][0]
    assert child_lot["inherited_reason"] == "毒死蜱残留超标"
    assert child_lot["inherited_from_lot_id"] == lot["id"]
    assert len(progress["nodes"]) == 2

    # 子批次与父批次分别确认：先处理子批次下游
    child_node = [n for n in progress["nodes"] if n["lot_id"] == child["id"]][0]
    client.post(f"/api/food/notices/{child_node['notice_id']}/attempts", json={"result": "delivered"})
    client.post(f"/api/food/notices/{child_node['notice_id']}/receipt", json={"acknowledged_by": "食堂管理员", "disposed_quantity_kg": 150})
    confirm = client.post(f"/api/food/recalls/{recall['id']}/lots/{child['id']}/confirm", json={"operator": "监管员丙"})
    assert confirm.status_code == 200 and confirm.json()["lot_status"] == "confirmed"

    # 父批次未确认时整体不可关闭
    progress = client.get(f"/api/food/recalls/{recall['id']}/progress").json()
    assert progress["closable"] is False
    lot_condition = [c for c in progress["close_conditions"] if c["code"] == "all_lots_confirmed"][0]
    assert lot_condition["satisfied"] is False

    # 父批次下游回执未完整时不能确认
    blocked = client.post(f"/api/food/recalls/{recall['id']}/lots/{lot['id']}/confirm", json={})
    assert blocked.status_code == 409

    parent_node = [n for n in progress["nodes"] if n["lot_id"] == lot["id"]][0]
    client.post(f"/api/food/notices/{parent_node['notice_id']}/attempts", json={"result": "delivered"})
    client.post(f"/api/food/notices/{parent_node['notice_id']}/receipt", json={"acknowledged_by": "店长", "disposed_quantity_kg": 200, "sold_quantity_kg": 100})
    confirm = client.post(f"/api/food/recalls/{recall['id']}/lots/{lot['id']}/confirm", json={"operator": "监管员丙"})
    assert confirm.status_code == 200

    progress = client.get(f"/api/food/recalls/{recall['id']}/progress").json()
    assert progress["closable"] is True
    closed = client.post(f"/api/food/recalls/{recall['id']}/close", json={"operator": "监管员丙"})
    assert closed.status_code == 200


def test_late_delivery_sync_does_not_duplicate_notices(client):
    lot = _lot(client, "LOT-R04")
    _fail_lot(client, lot["id"], "S-R04")
    _deliver(client, lot["id"], "DLV-7", "merchant", "早市摊位", 60)
    recall = _recall(client, lot["id"], "RECALL-004")

    # 召回后发现遗漏的送达节点，补登记并同步
    _deliver(client, lot["id"], "DLV-8", "canteen", "医院食堂", 40)
    synced = client.post(f"/api/food/recalls/{recall['id']}/sync-nodes")
    assert synced.status_code == 200 and synced.json() == {"snapshots": 1, "notices": 1}
    # 重复同步不再生成快照或通知
    again = client.post(f"/api/food/recalls/{recall['id']}/sync-nodes")
    assert again.json() == {"snapshots": 0, "notices": 0}

    progress = client.get(f"/api/food/recalls/{recall['id']}/progress").json()
    assert len(progress["nodes"]) == 2
    assert len(progress["unacknowledged_nodes"]) == 2
    assert progress["quantities"]["delivered_kg"] == 100


def test_split_after_recall_inherits_recall_scope(client):
    lot = _lot(client, "LOT-R06", 400)
    _fail_lot(client, lot["id"], "S-R06")
    _deliver(client, lot["id"], "DLV-9", "merchant", "北街菜行", 100)
    recall = _recall(client, lot["id"], "RECALL-006")

    # 召回发起后再拆分，子批次自动进入召回范围并继承召回原因
    child = client.post(f"/api/food/lots/{lot['id']}/split", json={"lot_code": "LOT-R06-A", "trace_code": "LOT-R06-A-T", "quantity_kg": 150})
    assert child.status_code == 201, child.text
    child = child.json()
    assert child["status"] == "recalled" and child["risk_level"] == "critical"

    progress = client.get(f"/api/food/recalls/{recall['id']}/progress").json()
    child_lot = [item for item in progress["lots"] if item["lot_id"] == child["id"]][0]
    assert child_lot["inherited_reason"] == "毒死蜱残留超标"
    assert child_lot["lot_status"] == "pending"


def test_split_quantity_cannot_exceed_parent(client):
    lot = _lot(client, "LOT-R05", 100)
    ok = client.post(f"/api/food/lots/{lot['id']}/split", json={"lot_code": "LOT-R05-A", "trace_code": "LOT-R05-A-T", "quantity_kg": 60})
    assert ok.status_code == 201
    too_much = client.post(f"/api/food/lots/{lot['id']}/split", json={"lot_code": "LOT-R05-B", "trace_code": "LOT-R05-B-T", "quantity_kg": 50})
    assert too_much.status_code == 409


def test_notice_retry_exhaustion_and_lot_exemption(client):
    lot = _lot(client, "LOT-R07")
    _fail_lot(client, lot["id"], "S-R07")
    _deliver(client, lot["id"], "DLV-10", "merchant", "失联商户", 30)
    recall = _recall(client, lot["id"], "RECALL-007")

    progress = client.get(f"/api/food/recalls/{recall['id']}/progress").json()
    notice_id = progress["nodes"][0]["notice_id"]
    # 连续失败直至达到最大重试次数
    for _ in range(5):
        response = client.post(f"/api/food/notices/{notice_id}/attempts", json={"result": "failed"})
        assert response.status_code == 201
    assert response.json()["delivery_status"] == "failed"
    # 耗尽后不允许继续投递
    blocked = client.post(f"/api/food/notices/{notice_id}/attempts", json={"result": "delivered"})
    assert blocked.status_code == 409

    progress = client.get(f"/api/food/recalls/{recall['id']}/progress").json()
    pending = progress["retry_pending"][0]
    assert pending["delivery_status"] == "failed" and pending["can_retry"] is False
    assert progress["closable"] is False

    # 监管员豁免该批次（节点失联，转线下处置），召回得以关闭
    exempt = client.post(f"/api/food/recalls/{recall['id']}/lots/{lot['id']}/confirm", json={"operator": "监管员丁", "exempt": True, "reason": "商户停业，现场封存"})
    assert exempt.status_code == 200 and exempt.json()["lot_status"] == "exempted"
    progress = client.get(f"/api/food/recalls/{recall['id']}/progress").json()
    assert progress["closable"] is True
    closed = client.post(f"/api/food/recalls/{recall['id']}/close", json={"operator": "监管员丁"})
    assert closed.status_code == 200

    # 关闭后所有变更被拒绝
    for response in (
        client.post(f"/api/food/notices/{notice_id}/attempts", json={"result": "delivered"}),
        client.post(f"/api/food/notices/{notice_id}/receipt", json={"acknowledged_by": "某人"}),
        client.post(f"/api/food/recalls/{recall['id']}/lots/{lot['id']}/confirm", json={}),
        client.post(f"/api/food/recalls/{recall['id']}/sync-nodes"),
        client.post(f"/api/food/recalls/{recall['id']}/close", json={}),
    ):
        assert response.status_code == 409, response.text


def test_recall_without_deliveries_closes_after_lot_confirm(client):
    lot = _lot(client, "LOT-R08")
    _fail_lot(client, lot["id"], "S-R08")
    recall = _recall(client, lot["id"], "RECALL-008")

    progress = client.get(f"/api/food/recalls/{recall['id']}/progress").json()
    assert progress["nodes"] == [] and progress["unacknowledged_nodes"] == []
    assert progress["closable"] is False  # 批次尚未确认

    confirm = client.post(f"/api/food/recalls/{recall['id']}/lots/{lot['id']}/confirm", json={"operator": "监管员戊"})
    assert confirm.status_code == 200
    progress = client.get(f"/api/food/recalls/{recall['id']}/progress").json()
    assert progress["closable"] is True
    closed = client.post(f"/api/food/recalls/{recall['id']}/close", json={"operator": "监管员戊"})
    assert closed.status_code == 200


def test_duplicate_recall_code_rejected(client):
    lot = _lot(client, "LOT-R09")
    _fail_lot(client, lot["id"], "S-R09")
    _recall(client, lot["id"], "RECALL-009")
    other = _lot(client, "LOT-R10")
    _fail_lot(client, other["id"], "S-R10")
    dup = client.post(f"/api/food/lots/{other['id']}/recalls", json={"recall_code": "RECALL-009", "reason": "重复编码"})
    assert dup.status_code == 409
