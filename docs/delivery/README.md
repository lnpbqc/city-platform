# 交付入口

24步功能已实现。用户于2026-10-27取消演示录屏，按功能交付收口。

- [启动与Max→FBX→modelTo3DTiles→ZIP流程](../../README.md)
- [一页接口说明](api.md)与[OpenAPI](openapi.json)
- [数据清单](data_manifest.json)：13个资产、13个版本及文件指纹
- [三组实际运行](run_examples/source.json)：正常、绕行、不可达的输入、记录、结果和日志
- [P0需求证据矩阵](acceptance-matrix.md)
- [前端验收](../verification/step24-frontend.md)、[后端验收](../verification/step24-backend.md)、[独立交接](../verification/step24-handoff.md)
- [1小时稳定性原始记录](rss-stability.json)：3600秒、7次采样、1800次请求、0错误；私有内存20–60分钟保持456310784字节

最终回归为前端247项、后端427项通过；生产首屏中位3.691秒，万对象查询p95最高44.68毫秒，十万边计算最高1.620秒。五并发和真实进程中断恢复通过。原库保持0007及原SHA；首次运行新代码前按README备份并升级迁移。

README与交付说明按`anti-defensive-writing`复查，保留数据来源、固定版本和测量口径。
