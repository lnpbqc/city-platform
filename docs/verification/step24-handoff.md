# 步骤24：独立环境交接复现

从已提交源码`62295c3`导出至独立目录，使用独立SQLite和存储，后端18002、前端15175。用户8000服务、原库与原文件保持；此复现为独立源码与数据库环境验证。

前端使用Node 24.19、pnpm 11.9，从缓存重新安装97个包并完成生产构建。后端使用独立新虚拟环境安装生产依赖；`uv sync --frozen --no-dev`成功。完整开发依赖安装遇到本机Windows的httpx启动器PE资源写入错误，启动流程采用实际成功的生产依赖安装方式。

已执行数据库迁移、启动、健康读取、前端首屏、场景保存和net-001运行闭环。运行`04355c53-f71d-4464-af3f-f59f9c6af6f5`使用S→T、阻断B-T，结果为660/960米。截图：[地图](../../output/playwright/step24-handoff-map.png)、[运行](../../output/playwright/step24-handoff-run.png)。

README与后端说明的启动命令统一为`uv sync --no-dev`、`uv run --no-dev alembic upgrade head`及`uv run --no-dev uvicorn app.main:app …`，避免启动时引入开发依赖。独立端口的代理配置仅用于隔离验收；日常启动使用README默认8000/5173。
