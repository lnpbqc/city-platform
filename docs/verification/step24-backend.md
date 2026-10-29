# 步骤24：后端最终验收与交付

2026-10-27 在 Windows 10、Python 3.13.7 上完成。应用来源为提交 `62295c35156c33fb42ca018c7bd96257ad027d00`，验收工具和交付文件在本步骤新增。独立服务使用 `127.0.0.1:18001` 与 `.verification/step24-backend-*` 临时 SQLite；验收后服务、计算子进程和临时数据库已清理。

## 回归与性能

最终后端全量执行一次：**427 项通过，耗时 103.05 秒**。测试使用既有隔离 fixture；原始输出为 `.verification/step24-backend-pytest.txt`。唯一警告为 Starlette TestClient 对 httpx 的弃用提示。

| 检查 | 数据与口径 | 实测 | 阈值 |
| --- | --- | --- | --- |
| 万对象区域 bbox | 10,000 个点/线/面，真实 TCP、持久 HTTP 连接，100 次，每页 100；命中 100 个对象 | 中位 10.23 ms，p95 **11.64 ms** | p95 ≤200 ms |
| 万对象全范围 bbox | 同一数据集，100 次，每页 100；匹配总数 10,000 | 中位 31.62 ms，p95 **44.68 ms** | p95 ≤200 ms |
| 十万边寻路 | 100,000 节点和边；包含校验、构图、两次 Dijkstra、字典序路径重建、指标计算 | 1489.52 / 1619.95 / 1520.44 ms；最大 **1619.95 ms** | 每次 ≤2000 ms |

区域查询第一页有 13 个真实裁剪的线/面，逐一核对输出落在 bbox 内。列表总数、统计分组总数一致。p95 取 100 次升序样本第 95 个；计时覆盖 HTTP 请求、响应传输和 JSON 解析。十万边基准为内存模型计算时间，API 入队、持久化及进程启动单独由运行验收覆盖。

## 并发与恢复

用 barrier 同时发出五个不同输入的 `POST /api/runs`。五个运行 ID 和输入 SHA-256 均不同，逐项用实际 `/input` 快照独立重算摘要，再比对记录、结果 ID、状态日志及 trace；重复读取结果字节相同，各日志不含其他运行 ID。

| 输入 | 阻断后结果 |
| --- | --- |
| S→T，无阻断 | 660 m，66 s |
| S→T，阻断 B-T | 960 m，96 s |
| S→T，阻断 S-A | 不可达，距离/时间 null，运行成功 |
| S→S | 0 m，0 s，单节点路径 |
| A→T，无阻断 | 460 m，46 s |

故障恢复使用临时服务包装器延迟计算，生产模型源码保持。确认一个实际子进程运行、第二个任务 queued 后，强制终止自建服务 PID 55252。计算子进程 PID 56168 随父进程退出。使用原临时库重启后，原 running 变为 `failed/RUN_INTERRUPTED`，queued 继续为 succeeded、路线 960 m；两次输入快照与摘要均保持。

## 路径与凭据检查

真实 HTTP 完成 14 项路径检查。ZIP 成员中的 `../`、反斜杠、绝对路径和盘符路径均返回 422；下载地址中的 `..%2f`、反斜杠、绝对和盘符形式均返回 404，目录外 canary 内容与 SHA 保持。ZIP 内的 `..%2f` 作为字面文件名保存在生成资产目录内；multipart 原文件名也写入生成资产目录中的固定 `data.geojson`，未用作磁盘路径。

扫描 254 个 Git 跟踪的 UTF-8 源码、配置和文档，检查私钥、AWS/GitHub/OpenAI token 及直接赋值的凭据模式，命中 0 项。依赖、二进制和转换器分发包不在本次源码扫描范围。扫描结果只保留路径、类型和行号，输出中无凭据值。

## 数据与接口交付

- [OpenAPI](../delivery/openapi.json)：由最终应用的真实 `/openapi.json` 导出，OpenAPI 3.1.0、38 个路径；[一页接口说明](../delivery/api.md) 给出参数和重试规则。
- [现有数据清单](../delivery/data_manifest.json)：只读原库中的 13 个资产、13 个版本，版本容量合计 863,401 字节；16 条发布指纹均与实际文件匹配。清单包含 ID、版本、入口、坐标说明/范围、容量及逐文件 SHA。
- [三组运行样例](../delivery/run_examples/source.json)：normal、rerouted、unreachable 各包含原请求、完整固定输入、最终记录、结果和日志；另附实际路网快照。样例来自临时库的真实 API，路网及运行均标注合成演示。
- [机器可读验收结果](../delivery/backend_acceptance.json)：含查询测量、五并发记录、重启记录、14 项路径结果及数据保留核对。

原库通过 SQLite `mode=ro` 读取，schema 保持 `0007_object_index`，SHA-256 保持 `e76b99bb264270920b66c5563766522aae176b36c4c7a08c2024c95c74237eaf`。原 4 个发布文件、22 个样例文件的 SHA 全部保持。8000 用户服务和 18000 长时 RSS 服务保持运行，本工具只管理自己创建的 18001 服务。

## 复现命令

从仓库根目录运行，Python 使用 `map_back/.venv/Scripts/python.exe`：

```powershell
$env:PYTHONIOENCODING='utf-8'
& map_back/.venv/Scripts/python.exe scripts/acceptance/backend_checks.py
```

该工具占用 18001；占用时立即退出。它创建并迁移独立临时库，导出接口/数据/运行快照，验证后关闭自己创建的进程并删除临时库。

全量回归和十万边基准分别在 `map_back` 目录运行：

```powershell
& .venv/Scripts/python.exe -m pytest tests -q -p no:cacheprovider --basetemp D:/city/.verification/step24-backend-repeat
& .venv/Scripts/python.exe tools/verify_routing.py
```

本报告与接口交付说明按 `anti-defensive-writing` 复查，保留测量口径、数据来源和适用范围。
