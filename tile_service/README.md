# GeoJSON 自动切片服务

**切片服务运行在 WSL Ubuntu 中。日常在 Windows PowerShell 中启动，脚本会自动调用 WSL。** Windows 后端和网页仍按原来的方式启动。

## 怎么用

在 Windows PowerShell 中执行：

```powershell
cd D:\city
.\tile_service\start.ps1
```

然后正常启动项目的 Windows 后端和前端。首次启动脚本会自动生成连接配置；后端默认端口为 `8000`。如果后端已经运行，首次生成配置后重启后端。

以后上传 GeoJSON，系统会自动处理；已有符合条件的数据也会自动补处理。无需进入 Ubuntu 手动切片，也无需在地图上切换加载方式。服务未启动或处理失败时，地图继续使用原有视野接口。

道路按等级减少显示数量，保留原有转折。新版 `geojson-v2` 关闭道路主动简化及自动降精度；超预算时使用保真视野接口。升级后重启切片服务和后端、刷新网页，旧产物会自动重建，原文件保留期不延长。

停止切片服务也在 Windows 执行：

```powershell
.\tile_service\start.ps1 -Stop
```

首次在新电脑使用时，需先安装 WSL Ubuntu，并在 **Ubuntu 终端**安装一次依赖：

```bash
cd /mnt/d/city
bash tile_service/install.sh
```

装好后，日常只用上面的 Windows 启停命令。

## 连接配置与直接在 Linux 启动

Windows 后端读取 `D:\city\map_back\storage\tile-service.json`；WSL 启动时指定同一文件。在同机 WSL 环境中，配置如下：

```json
{
  "url": "http://127.0.0.1:18744",
  "backend": "http://127.0.0.1:8000",
  "token": "替换为下面命令生成的令牌"
}
```

| 字段 | 含义 |
| --- | --- |
| `url` | Windows 后端访问切片服务的地址 |
| `backend` | 项目后端地址；当前推送模式用于来源校验，拉取模式才由切片服务实际访问 |
| `token` | 两端使用的同一串连接凭据，无需注册或申请 |

使用 `start.ps1` 时，脚本自动生成 32 字节随机令牌，并以 64 个十六进制字符写入配置。**仅使用 `.sh` 时，需自行创建上述配置文件**；在 Linux 终端生成令牌：

```bash
python3 -c "import secrets; print(secrets.token_hex(32))"
```

将输出完整粘贴到 `token`，然后在 Ubuntu 终端运行：

```bash
cd /mnt/d/city
export CITY_TILE_CONFIG=/mnt/d/city/map_back/storage/tile-service.json
bash tile_service/start.sh
```

此方式在当前终端前台运行，按 `Ctrl+C` 停止。两种入口任选一种，无需重复启动。修改地址或令牌后重启两端；环境变量配置优先于文件。配置含凭据，已被 Git 忽略。

如果部署在另一台 Linux 电脑，Windows 的 `url` 填 Windows 能访问的 Linux 地址；Linux 端可使用自己的配置文件，但 `token` 和 `backend` 要与 Windows 一致，并设置监听地址允许 Windows 连接。详细配置见[技术说明](技术说明.md)。

## 数据存在哪里

以下是默认位置：

| 内容 | 存放位置 | 保留方式 |
| --- | --- | --- |
| 上传的 GeoJSON 原文件 | Windows：`D:\city\map_back\storage\files\` | 完整快照验证且首次切片发布成功后，保留七天 |
| 完整几何、属性、资产版本及对象索引 | Windows：`D:\city\map_back\storage\catalog.db` | 正式数据，到期清理原文件后仍保留 |
| 最终 PMTiles、清单及道路来源映射 | Windows：`D:\city\map_back\storage\renders\` | 正式产物，随资产正常管理和删除 |
| 切片输入、中间文件和待交付产物 | WSL：`~/.local/share/city-tile/` | 处理后清理中间文件，Windows 确认接收后清理产物副本 |
| 切片队列和进程记录 | WSL：`~/.local/share/city-tile/` | 保留少量任务记录，用于重启恢复 |

处理时的数据流是：

```text
Windows 完整数据 → HTTP 发送给 WSL → WSL 去冗余并切片
                                      ↓
浏览器按需读取 ← Windows 保存最终瓦片 ← HTTP 取回产物
```

**`/mnt/d/city` 就是 WSL 中访问 Windows `D:\city` 的路径，指向同一份文件。** Ubuntu 从这里读取项目代码和连接配置。

“工作目录不要放在 `/mnt/d`”仅指 **WSL 切片队列和临时工作文件**。这些文件放在 Linux 自己的目录中；项目源码和 Windows 正式数据仍可以放在 D 盘。Linux 工作文件会占用 WSL 所在磁盘的空间。

无需手工复制数据。Windows 与 WSL 各自管理自己的数据库，最终长期保留的完整数据和瓦片都在 Windows。备份时应覆盖 Windows 的整个 `map_back\storage` 目录。

自定义端口、存储路径、接口和排障见 [技术说明](技术说明.md)。
