# 步骤15：持久运行队列验收

2026-10-26，后端329项测试通过，包含运行、真实子进程、服务异常退出与迁移回退用例。前端沿用步骤11的157项及构建结果，本步后端接口供步骤17、18页面接入。

| 检查 | 结果 |
| --- | --- |
| 快照和幂等 | 原子固定场景版本、资产/路网版本和输入；同key同输入201后重放200，5个并发提交只生成1条运行；同key变化409，新key不同ID、相同哈希 |
| 输入校验 | 非法节点、正式边ID、缺失场景及路网版本在创建运行前拒绝，数据库和目录无新增 |
| 状态与只读约束 | 排队直接取消；运行中取消先终止实际计算，再保存终态及finished_at；终态取消409，数据库拒绝终态或输入覆盖 |
| 真实计算 | 660m/66s与960m/96s、不可达、同起终点、不同阻断5条运行逐条核对，结果ID及输入保持对应 |
| 隔离进程 | Windows虚拟环境启动时绕过Python重定向器，Popen.pid与子进程实际PID一致；取消及超时后该PID退出 |
| 超时和异常 | 测试将生产超时常量缩短为0.8s，实际终止慢进程并保存RUN_TIMEOUT；异常细节留服务日志，接口和状态日志返回可追踪错误 |
| 异常重启 | 隔离目录、真实TCP服务和两次独立uvicorn启动；杀死首次服务，子进程随之退出；重启后旧running为failed/RUN_INTERRUPTED、queued继续成功，快照字节和哈希一致 |
| 文件一致性 | 数据库提交后发布镜像；注入提交异常时不生成成功结果文件。缺文件按数据库恢复，已改文件409并保留，孤立结果/目录明确报告 |
| 查询与下载 | 状态/场景/时间范围筛选、稳定分页、超大页码、输入及日志、运行统计通过；JSON下载与result.json字节一致，GeoJSON含两条路线及实际阻断边 |
| 历史引用 | 场景可关联有效run；删除场景、移除全局登记后，运行仍保留快照并阻止删除其资产版本 |
| 迁移回退 | 带非空Scene.run_id的0010→0009→0010，清除被删运行关联，其余场景字段、版本及时间逐项相等；重新提交返回201 |

文件安全覆盖真实Windows目录联接，以及文件重解析点的访问拒绝。当前账户缺少创建文件符号链接的权限，文件用例注入FILE_ATTRIBUTE_REPARSE_POINT元数据，确认读取前拒绝；目录联接使用实际文件系统创建与校验，外部标记文件字节保持一致。

服务退出时，计算进程监视创建它的父进程。Windows通过[OpenProcess](https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-openprocess)取得同步句柄，并通过[WaitForSingleObject](https://learn.microsoft.com/en-us/windows/win32/api/synchapi/nf-synchapi-waitforsingleobject)等待父进程退出；测试强制终止服务后确认实际子进程退出。正常停止保存SERVICE_STOPPED，异常停止由下次启动保存RUN_INTERRUPTED。

真实数据库仅复制后验收：0007→0010→0007→0010，原有13资产、1图层登记、1收藏、164对象保留，4个发布文件及22个样例文件SHA-256一致；外键检查通过，原数据库SHA-256保持，临时副本已清理。黄埔建筑既有自交索引问题保留原记录和文件。

复现：在map_back执行`uv run pytest -q`；进程与重启用例位于tests/test_run_processes.py、tests/test_run_restart.py，提交故障及镜像校验位于tests/test_runs.py，降级关联位于tests/test_run_migration.py。队列使用单个uvicorn服务进程，默认计算时限60秒。备份和回退以完整storage为单位，运行文件镜像通过专用API读取。

README、后端说明、API契约及本报告已按anti-defensive-writing复查，保留单进程、计时方式、真实/模拟文件系统证据和回退影响，移除已过期的接口接入说明。
