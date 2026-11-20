# 项目文档

| 说明 | 查阅内容 |
| --- | --- |
| [功能说明](功能说明.md) | 地图操作、数据管理、对象查询、时间对比、仿真与历史回放 |
| [开发说明](开发说明.md) | 技术栈、模块职责、开发约定、测试及核心验证步骤 |
| [部署说明](部署说明.md) | Windows 本机安装、启动、构建预览、升级、备份恢复与排障 |
| [Linux 统一准备](Linux部署手册.md) | 前六节：源码、Conda、依赖、数据库、前端构建与前台检查 |
| [Linux systemd 路线](Linux-systemd部署.md) | 第七节起：systemd 服务、域名与 HTTPS、防火墙、维护及验收 |
| [Linux Docker／非 systemd 路线](Linux非systemd部署.md) | 第七节起：Supervisor、IP／域名 HTTP 访问与 65001→80 映射、维护及验收 |
| [切片服务使用说明](../tile_service/README.md) | WSL 服务启停、地址和令牌配置、Windows 与 Linux 的存储分工 |
| [接口说明](api_contract.md) | API 速查、字段约定、错误、版本、幂等及并发规则 |
| [数据与模型说明](数据与模型说明.md) | 数据来源、坐标、上传格式、白模生成和 Max→3D Tiles 转换 |
| [天地图功能适用性与用量评估](天地图功能适用性与用量评估.md) | 已接入能力、候选功能、个人额度、团队调用量估算与底图优化边界 |

首次启动见[项目 README](../README.md)。运行中的后端提供[交互文档](http://127.0.0.1:8000/docs)和 [OpenAPI JSON](http://127.0.0.1:8000/openapi.json)。

实施记录见[待办目录](../待办/)，白模原始快照见 [map/docs/research](../map/docs/research/)。
