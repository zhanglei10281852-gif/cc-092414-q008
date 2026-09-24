# 餐桌安全食品追溯服务

这是一个面向农产品监管部门、检测实验室和蔬菜配送企业的模块化后端，集中管理供应商、蔬菜批次、抽样检测、农残限值、运输链、风险处置、用户权限、会话、审计和可恢复后台任务。项目使用 FastAPI 与 SQLite，所有运行数据保存在单个本地数据库文件中，不依赖另行部署的数据库、缓存或消息队列。

## 主要模块

- 农产品档案：登记供应商、种植地、蔬菜批次和追溯标识。
- 检测业务：登记抽样、实验室结果、农残限值和风险判定。
- 运输追踪：记录装车、转运、到货、温度与异常处置。
- 风险协同：支持批次隔离、召回、监管公告和跨部门办理。
- 召回闭环：农残超标确认后创建召回事件，快照下游商户/食堂节点，通知可重试且全程留痕，节点回执与已处置数量闭环核对，满足条件才允许关闭。
- 身份与权限：用户、角色、细粒度权限、会话令牌、账号停用和会话撤销。
- 审计记录：关键身份操作留痕，并对口令和令牌等敏感字段做过滤。
- 后台任务：使用 SQLite 保存待执行任务，支持去重、租约、重试和完成回执。

## 召回闭环

农残超标确认后，通过 `POST /api/food/lots/{lot_id}/recalls` 创建召回事件：批次随即冻结为 `recalled`，并按运输单目的地自动快照下游节点（也可在请求中显式给出商户/食堂及数量），同一批次同一时间只允许一个进行中的召回。

- `POST /api/food/recalls/{id}/notifications` 为未通知节点生成通知，重复调用不会重复计数；`POST .../nodes/{node_id}/notification/retry` 追加投递尝试，每次尝试的操作者、结果与时间均留痕。
- `POST .../nodes/{node_id}/receipt` 登记节点回执（需先存在通知，重复登记返回现状）；`POST .../nodes/{node_id}/disposals` 累计已处置数量（须先回执，累计不得超过节点应收数量）。
- `GET /api/food/recalls/{id}` 返回仍未确认的节点、数量差额（应收/已处置/剩余）与最终关闭条件；全部节点回执且数量处置到位后，`POST /api/food/recalls/{id}/close` 才允许关闭。
- `POST /api/food/lots/{lot_id}/splits` 拆分子批次：子批次继承原批次状态；存在未关闭召回时，每个子批次生成继承同一召回原因的子召回事件，各自独立回执、处置与关闭。拆分数量累计不得超过原批次数量。

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
