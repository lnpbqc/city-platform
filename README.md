# 城市韧性 · Cesium 地图工作台

Windows 本机单用户地图工作台，支持图层与数据管理、空间查询、时间对比、路网阻断仿真及历史回放。Vue 3 + Cesium 前端位于 `map/`，FastAPI + SQLite 后端位于 `map_back/`。

## 快速启动

准备 Node.js 24、pnpm、Python 3.13 和 uv。以下以项目位于 `D:\city` 为例，首次安装依赖需要联网。在两个 PowerShell 终端分别启动后端和前端。

后端：

```powershell
Set-Location D:\city\map_back
uv sync --no-dev
uv run --no-dev alembic upgrade head
uv run --no-dev uvicorn app.main:app --host 127.0.0.1 --port 8000
```

前端：

```powershell
Set-Location D:\city\map
pnpm install --store-dir ..\.pnpm-store
if (-not (Test-Path -LiteralPath .env.local)) {
    Copy-Item -LiteralPath .env.example -Destination .env.local
}
# 编辑 .env.local，填写 VITE_CESIUM_ION_TOKEN；使用本地低分辨率底图时留空。
pnpm dev --port 5173 --strictPort
```

打开[地图工作台](http://127.0.0.1:5173/)，接口见[后端文档](http://127.0.0.1:8000/docs)。首次启动和升级后执行数据库迁移；升级已有环境前按部署说明备份完整存储目录。停止服务在对应终端按 `Ctrl+C`。

## 文档

| 说明 | 内容 |
| --- | --- |
| [文档导航](docs/README.md) | 按任务选择阅读入口 |
| [功能说明](docs/功能说明.md) | 地图、数据管理、查询、时间轴、仿真、回放与收藏 |
| [开发说明](docs/开发说明.md) | 结构、模块职责、测试和核心验证 |
| [部署说明](docs/部署说明.md) | Windows 安装启动、构建预览、升级、备份恢复和排障 |
| [接口说明](docs/api_contract.md) | API 速查、版本、并发、幂等和错误规则 |
| [数据与模型说明](docs/数据与模型说明.md) | 数据来源、坐标、上传规范、白模生成及 Max→3D Tiles 流程 |
