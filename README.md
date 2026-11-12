# 城市韧性 · Cesium 地图工作台

Windows 本机单用户地图工作台，支持图层与数据管理、空间查询、时间对比、路网阻断仿真及历史回放。Vue 3 + Cesium 前端位于 `map/`，FastAPI + SQLite 后端位于 `map_back/`；GeoJSON 自动切片服务位于 `tile_service/`，运行在 WSL Ubuntu 中。

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
# 编辑 .env.local：天地图设置 VITE_BASEMAP_PROVIDER=tianditu 并填写 VITE_TIANDITU_KEY。
# 默认使用 Cesium，填写 VITE_CESIUM_ION_TOKEN；使用本地低分辨率底图时留空。
pnpm dev --port 5173 --strictPort
```

打开[地图工作台](http://127.0.0.1:5173/)，接口见[后端文档](http://127.0.0.1:8000/docs)。首次启动和升级后执行数据库迁移；升级已有环境前按部署说明备份完整存储目录。停止服务在对应终端按 `Ctrl+C`。

## GeoJSON 自动切片

启用自动切片需再启动一个 **WSL Linux 服务**。Windows 的 `start.ps1` 负责调用 WSL，与 Linux 的 `start.sh` 是同一个服务的两种启动入口。

首次使用需安装 WSL Ubuntu，并在 Ubuntu 终端安装一次切片依赖：

```bash
cd /mnt/d/city
bash tile_service/install.sh
```

日常在 Windows PowerShell 中启动切片服务，再照常启动上述前后端：

```powershell
Set-Location D:\city
.\tile_service\start.ps1
```

停止切片服务时运行 `.\tile_service\start.ps1 -Stop`。

首次启动自动生成 `map_back/storage/tile-service.json`，包含切片地址、后端地址和随机令牌，已有配置不覆盖。默认切片地址为 `http://127.0.0.1:18744`，后端为 `http://127.0.0.1:8000`。直接在 Linux 启动、手动生成令牌或修改地址，见[切片服务使用说明](tile_service/README.md#连接配置与直接在-linux-启动)。

道路通过等级筛选控制密度，保留原有弯曲走向，默认显示到第 2 级。新版 `geojson-v2` 禁止道路主动简化和超预算降到粗瓦片，必要时改用保真视野接口。升级后重启切片服务、后端并刷新网页，旧产物自动重建，无需重新上传，原文件七天计时不重置。

## 文档

| 说明 | 内容 |
| --- | --- |
| [文档导航](docs/README.md) | 按任务选择阅读入口 |
| [功能说明](docs/功能说明.md) | 地图、数据管理、查询、时间轴、仿真、回放与收藏 |
| [开发说明](docs/开发说明.md) | 结构、模块职责、测试和核心验证 |
| [部署说明](docs/部署说明.md) | Windows 安装启动、构建预览、升级、备份恢复和排障 |
| [切片服务使用说明](tile_service/README.md) | WSL 切片服务启停、地址、令牌及存储位置 |
| [接口说明](docs/api_contract.md) | API 速查、版本、并发、幂等和错误规则 |
| [数据与模型说明](docs/数据与模型说明.md) | 数据来源、坐标、上传规范、白模生成及 Max→3D Tiles 流程 |
