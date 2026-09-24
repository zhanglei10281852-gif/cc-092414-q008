# 餐桌安全食品追溯服务

这是一个面向农产品监管部门、检测实验室和蔬菜配送企业的模块化后端，集中管理供应商、蔬菜批次、抽样检测、农残限值、运输链、风险处置、用户权限、会话、审计和可恢复后台任务。项目使用 FastAPI 与 SQLite，所有运行数据保存在单个本地数据库文件中，不依赖另行部署的数据库、缓存或消息队列。

## 主要模块

- 农产品档案：登记供应商、种植地、蔬菜批次和追溯标识。
- 检测业务：登记抽样、实验室结果、农残限值和风险判定。
- 运输追踪：记录装车、转运、到货、温度与异常处置。
- 风险协同：支持批次隔离、召回、监管公告和跨部门办理。
- 召回闭环：农残超标确认后发起召回事件，自动冻结下游商户/食堂送达快照，生成通知并支持重试，下游回执上报已处置/退回/售出/存量数量，拆分子批次继承召回原因但分别确认，满足全部关闭条件后方可关闭召回。
- 身份与权限：用户、角色、细粒度权限、会话令牌、账号停用和会话撤销。
- 审计记录：关键身份操作留痕，并对口令和令牌等敏感字段做过滤。
- 后台任务：使用 SQLite 保存待执行任务，支持去重、租约、重试和完成回执。

## 运行环境

- Python 3.11
- SQLite 3，由 Python 标准库提供
- Linux、macOS 或 Windows

## 安装

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
```

配置项均以 `TOWNSHIP_` 开头。可以复制 `.env.example` 后按需设置，默认数据库位于 `./data/township.db`。

## 初始化与检查

```bash
python -m app.cli init-db
python -m app.cli check-db
```

## 启动服务

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8432
```

健康检查：

```bash
curl -sS http://127.0.0.1:8432/api/system/health
```

首次部署可创建唯一的初始管理员：

```bash
curl -sS -X POST http://127.0.0.1:8432/api/auth/bootstrap   -H 'Content-Type: application/json'   -d '{"username":"admin","password":"Admin!23456","client_label":"initial-setup"}'
```

之后通过 `/api/auth/login` 获取会话令牌，并在管理接口请求头中使用 `Authorization: Bearer <token>`。

## 测试

```bash
python -m pytest
```

测试覆盖身份初始化、登录、用户与角色维护、权限计算、账号停用后的会话撤销、审计脱敏、农产品批次、抽样检测、运输追踪、风险任务和数据库时间格式。

## 召回闭环接口

农残超标确认后，对批次发起召回事件，形成"快照 → 通知 → 回执 → 确认 → 关闭"的闭环：

```text
POST /api/food/lots/{lot_id}/recalls            发起召回（覆盖整个批次族，冻结下游送达快照并生成通知）
POST /api/food/lots/{lot_id}/split              拆分子批次（召回中的批次拆分后，子批次自动继承召回原因）
POST /api/food/lots/{lot_id}/deliveries         登记下游送达（商户/食堂、数量、时间、操作人）
POST /api/food/recalls/{recall_id}/sync-nodes   召回后补录遗漏送达节点（重复调用不重复计数）
GET  /api/food/recalls/{recall_id}/progress     查询未确认节点、数量差额、重试清单与最终关闭条件
POST /api/food/notices/{notice_id}/attempts     记录通知投递（失败可重试；已送达/已回执后重复提交不计数）
POST /api/food/notices/{notice_id}/receipt      下游回执（尚存/已销毁/已退回/已售出数量，重复提交幂等）
POST /api/food/recalls/{recall_id}/lots/{lot_id}/confirm  分别确认召回范围内的（子）批次，可豁免
POST /api/food/recalls/{recall_id}/close        全部条件满足后关闭召回
```

关闭条件：全部下游通知已送达、全部节点已回执、召回范围内批次（含子批次）均已分别确认或豁免、送达数量与处置/退回/售出/存量核对无差额。通知、回执、确认、关闭均记录操作者与时间，并写入审计时间线。

## 编译检查

```bash
python -m compileall -q app tests
```

## API 冒烟

```bash
python -m app.cli smoke
```

该命令在进程内启动应用并检查服务根路径与健康接口，适合部署前快速确认路由和数据库初始化是否正常。

## 目录结构

```text
app/
  api/             用户、角色、审计、认证和系统接口
  core/            时钟、安全、异常和分页能力
  repositories/    SQLite 查询与持久化读取
  routers/         灾情、事件、公告、部门和信访业务接口
  food/             农产品、检测、运输和风险处置服务
  schemas/         管理接口输入模型
  services/        身份、审计和后台任务领域服务
  cli.py           初始化、检查和冒烟入口
  database.py      SQLite 连接、事务、表结构与基础权限
tests/             核心、管理接口和原有业务回归测试
tools/             本地维护脚本
```

## 数据一致性

SQLite 连接默认启用外键、WAL、busy timeout 与同步写入策略。需要跨多张表更新的管理操作在即时事务中执行，失败会整体回滚。会话令牌只保存摘要；用户停用会撤销仍有效的会话。审计事件保存操作者、动作、资源、结果和前后状态，但不会保存明文密码或令牌。
