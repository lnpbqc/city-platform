# 城市韧性 · Cesium 地图原型

本机单用户地图工作台。Vue 3 前端位于 `map/`；FastAPI + SQLAlchemy + Alembic + SQLite 后端位于同级 `map_back/`。

## Windows 启动

准备 Node.js 24、pnpm、Python 3.13 和 uv。以下命令按项目位于 `D:\city` 编写；放在其他位置时替换路径。首次安装依赖及使用在线底图需要联网。

分别打开两个 PowerShell 终端，先启动后端，再启动前端。

### 后端 map_back

```powershell
Set-Location D:\city\map_back
uv sync --no-dev
uv run --no-dev alembic upgrade head
uv run --no-dev uvicorn app.main:app --host 127.0.0.1 --port 8000
```

首次启动和代码升级后需执行上述数据库迁移。启动成功后，打开 [API 文档](http://127.0.0.1:8000/docs)，或在另一个终端检查健康状态，预期返回 `status: ok`：

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/health
```

### 前端 map

```powershell
Set-Location D:\city\map
pnpm install --store-dir ..\.pnpm-store
if (-not (Test-Path -LiteralPath .env.local)) {
    Copy-Item -LiteralPath .env.example -Destination .env.local
}
# 编辑 .env.local，填写 VITE_CESIUM_ION_TOKEN；保留已有配置。
pnpm dev --port 5173 --strictPort
```

浏览器打开 [地图工作台](http://127.0.0.1:5173/)。Cesium ion Token 使用具备所需影像和地形权限的浏览器读取 Token；修改 `.env.local` 后重启前端。使用离线低分辨率底图时，可将 `VITE_CESIUM_ION_TOKEN` 留空。

停止服务：在对应终端按 `Ctrl+C`。SQLite 和已上传文件位于 `map_back/storage/`，重启后保留。前端的上传和登记功能需要后端运行；5173 或 8000 端口被占用时，先停止占用该端口的旧服务。开发和预览的后端代理均指向 `127.0.0.1:8000`。

## 从 .max 制作可上传的 3D Tiles ZIP

流程：**3ds Max 打开 `.max` → 调整整个模型的局部原点 → 导出 FBX → modelTo3DTiles 转换并地理配准 → 检查、打包 ZIP → 网页上传并加入地图**。本项目上传已转换的瓦片；本地 `modelTo3DTiles.exe` 2.1.1 支持 FBX、OBJ、glTF、GLB 输入，`.max` 先在 3ds Max 中导出。

以下以静态建筑场景为例，使用 `D:\city\exports\cbd-origin.fbx` 作为中间文件，`D:\city\cbd-tiles` 作为新转换目录，最终生成 `D:\city\cbd-tiles.zip`。操作原文件前，在 3ds Max 中另存为 `cbd-origin.max`。

### 1. 在 3ds Max 中调整原点

这里的原点是模型中与目标经纬高对应的参考点。选取可识别的地面角点或场地中心地面点，并取得该点的 **WGS84 经度、纬度和高度**。几何坐标在 Max 中保持局部长度单位，经纬高在转换阶段填写。

1. 打开 `.max`，补齐缺失贴图。在 `Customize（自定义）→ Units Setup（单位设置）→ System Unit Setup（系统单位设置）` 核对源模型的系统单位，并用已知建筑尺寸检查比例。显示单位可设为米；已有场景保持原系统单位，导出时换算为米。若源模型尺寸本身有误，先修正整体比例。
2. 选中本次导出的建筑、道路、地面等全部相关模型，通过 `Group（组）→ Group` 建立一个整体组，例如 `CBD_EXPORT`。后续操作选中关闭状态的整个组，保持各建筑的相对位置；相机、灯光及无关模型留在导出选择之外。
3. 选择组，进入右侧 `Hierarchy（层次）→ Pivot（轴）→ Affect Pivot Only（仅影响轴）`。用移动工具和顶点捕捉，将组轴放到选定的地面参考点；已知参考点的场景坐标时，可按 `W` 后按 `F12`，在 `Absolute: World（绝对：世界）` 中输入其 X、Y、Z。`Center to Object（居中到对象）` 得到包围盒中心，选择地面中心作锚点时还需把轴的 Z 调到地面高度。
4. **关闭 Affect Pivot Only**，参考坐标系选 `World（世界）`，保持整个组被选中。按 `W`、`F12`，在 `Absolute: World` 中把 X、Y、Z 设为 `0, 0, 0`。这一步将整个组连同几何体移动到世界原点；只移动轴会保留几何体原来的远距离坐标。
5. 核对参考点位于 `(0,0,0)`，建筑间距和高度符合真实尺寸。将场景方向整理为 X 向东、Y 向北、Z 向上，并记录选定参考点的经纬高。保存 `cbd-origin.max`。

轴操作依据 [Autodesk 轴调整说明](https://help.autodesk.com/cloudhelp/2021/ENU/3DSMax-Animation/files/GUID-6872F014-4785-43D9-A83B-C774507907B3.htm)；单位设置依据 [Autodesk 系统单位说明](https://help.autodesk.com/cloudhelp/2026/ENU/3DSMax-Customizing/files/GUID-22D2D2B9-9A82-47FA-88DD-67B1A91E2337.htm)。

### 2. 导出 FBX

1. 新建 `D:\city\exports` 文件夹，选中整个 `CBD_EXPORT` 组，使用 `File（文件）→ Export（导出）→ Export Selected（导出选定对象）`，保存为 `D:\city\exports\cbd-origin.fbx`。
2. 在 FBX 导出窗口的 `Advanced Options → Units` 中关闭 `Automatic`，将 `Scene Units Converted To` 设为 `Meters（米）`；在 `Axis Conversion` 中明确选择 **Z-up**，与下文 `--inputUpAxis Z` 配套。FBX 预设可能使用 Y-up，导出时核对实际选项。
3. 启用 `Embed Media（嵌入媒体）` 携带贴图。使用 FBX 可转换的材质；V-Ray、Corona 等专用材质先转换或烘焙为标准贴图，并检查导出警告和贴图路径。
4. 在新场景中重新导入 FBX，检查尺寸、原点、朝向与贴图。确认后进入瓦片转换。

FBX 选项见 [Autodesk 单位与轴转换](https://help.autodesk.com/cloudhelp/2022/ENU/3DSMax-Data-Exchange/files/GUID-94C10F56-EE1D-45E1-9858-7AA9E99CE25D.htm)和 [嵌入媒体](https://help.autodesk.com/cloudhelp/2022/ENU/3DSMax-Data-Exchange/files/GUID-FB993022-FD65-4ABD-8AF3-7F2CF613D71D.htm)。

### 3. 使用 modelTo3DTiles 转换并配准

在 PowerShell 中运行。经纬高填写第 1 步所选参考点的数据，经纬度顺序为 **经度、纬度、高度（米）**；高度按 WGS84 椭球高准备，来源为正高时先转换高程基准。高德、百度的偏移坐标先转换为 WGS84。

```powershell
Set-Location D:\city
.\modelTo3DTiles.exe --help

$modelLon = Read-Host '参考点 WGS84 经度（东经为正）'
$modelLat = Read-Host '参考点 WGS84 纬度（北纬为正）'
$modelAltitude = Read-Host '参考点 WGS84 椭球高（米）'
if (Test-Path -LiteralPath 'D:\city\cbd-tiles') {
    throw 'cbd-tiles 已存在，请为本次转换选择新的输出目录，并同步修改后续打包路径。'
}
.\modelTo3DTiles.exe `
    -i 'D:\city\exports\cbd-origin.fbx' `
    -o 'D:\city\cbd-tiles' `
    --inputUpAxis Z `
    --lla "$modelLon,$modelLat,$modelAltitude" `
    --correctCenter false `
    --clampToGround false `
    --noneTransform false `
    --split material `
    --draco true `
    --b3dm true `
    --tileSize 10
if ($LASTEXITCODE -ne 0) { throw '模型转换失败，请检查转换日志。' }
if (-not (Test-Path -LiteralPath 'D:\city\cbd-tiles\tileset.json')) {
    throw '未生成 tileset.json，请检查转换输出。'
}
```

关键参数按本地可执行文件 `--help` 核对：

| 参数 | 本流程的作用 |
| --- | --- |
| `--inputUpAxis Z` | 对应上一步导出的 Z-up FBX；导出为 Y-up 时改用 `Y`。 |
| `--lla` | 将模型局部原点放到输入的经度、纬度和高度。省略时使用转换器的北京默认坐标。 |
| `--correctCenter false` | 保留在 Max 中选定的原点。默认 `true` 会将锚点改到包围盒中心。 |
| `--clampToGround false` | 使用输入高度。默认 `true` 会使 `--lla` 中的高度失效。 |
| `--noneTransform false` | 写入模型变换矩阵，使地理定位生效。 |
| `--split material`、`--draco true` | 按材质拆分并压缩几何。`spatial` 模式生成层级瓦片，可能增加总量。 |
| `--b3dm true` | 输出 B3DM 瓦片。`false` 输出 3D Tiles 1.1 的 GLB 瓦片，本项目也可加载。 |
| `--tileSize 10` | 期望单瓦片容量；总包体积仍需单独检查。 |

方向已在 Max 中对齐时省略 `--rotation`；仍有偏航时，根据参考地物校准旋转后重新转换。输出目录应包含 `tileset.json` 及其引用的全部瓦片、子清单和外置贴图。米制距离、局部 Z 向上及椭球高约定参见 [OGC 3D Tiles 标准](https://docs.ogc.org/cs/22-025r4/22-025r4.html)。

### 4. 检查上传标准并生成 ZIP

当前后端上传规则见 [uploads.py](map_back/app/uploads.py)：

| 项目 | 要求 |
| --- | --- |
| 文件类型与大小 | `.zip`，压缩后 ≤512 MiB（536,870,912 字节）。 |
| 解压总量 | ≤2 GiB（2,147,483,648 字节）。 |
| 归档条目数 | ≤10,000，含显式目录条目。 |
| 入口位置 | ZIP 根目录为 `tileset.json`，或 ZIP 只有一个顶层文件夹、其中直接包含 `tileset.json`。 |
| 入口内容 | UTF-8 JSON，`asset.version` 为字符串 `"1.0"` 或 `"1.1"`，包含 `root.boundingVolume`。 |
| 资源完整性 | 包含入口引用的全部资源，保留相对目录和文件名；使用包内相对 URI，目录分隔符为 `/`。 |
| 归档路径 | 无绝对路径、盘符、`..`、反斜线、大小写冲突的重复路径、符号链接或加密文件。 |

推荐把转换目录的**内容**打包到 ZIP 根目录，例如：

```text
cbd-tiles.zip
├── tileset.json
├── Tile-0.b3dm
├── Tile-1.b3dm
└── textures/          # 仅在转换结果有外置贴图时出现
    └── facade.jpg
```

保留转换结果中的实际目录结构。将 `.max`、FBX、备份和旧 ZIP 放在发布目录之外。资源引用检查包括子清单及 GLTF 的外置 buffer、贴图；后端只校验归档安全及入口结构，完整性和地理位置还需在地图中验收。

以下命令使用后端虚拟环境的 Python 按相对路径打包，先检查解压量、文件数及入口，再检查 ZIP 大小。`'x'` 模式要求目标 ZIP 尚不存在；重新打包时换用新文件名。

```powershell
Set-Location D:\city
@'
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED

source = Path(r"D:\city\cbd-tiles")
target = Path(r"D:\city\cbd-tiles.zip")
files = sorted(p for p in source.rglob("*") if p.is_file())
if not (source / "tileset.json").is_file():
    raise SystemExit("缺少根入口 tileset.json")
expanded = sum(p.stat().st_size for p in files)
print(f"文件数: {len(files)}，解压总量: {expanded / 1024**2:.2f} MiB")
if len(files) > 10_000 or expanded > 2 * 1024**3:
    raise SystemExit("超过上传上限，请先精简模型或贴图，再重新转换")
with ZipFile(target, "x", compression=ZIP_DEFLATED, allowZip64=True) as bundle:
    for path in files:
        bundle.write(path, path.relative_to(source).as_posix())
size = target.stat().st_size
print(f"ZIP: {target}，大小: {size / 1024**2:.2f} MiB")
if size > 512 * 1024**2:
    raise SystemExit("ZIP 超过 512 MiB，请精简模型或贴图后重新生成")
print("体积和文件数检查通过，继续执行后端结构校验")
'@ | & 'D:\city\map_back\.venv\Scripts\python.exe' -
if ($LASTEXITCODE -ne 0) { throw '打包或体积检查失败，请先处理输出提示。' }
```

用后端实际上传校验函数检查 ZIP 路径、入口和清单结构。命令解压到临时目录并自动清理，不建立登记：

```powershell
Set-Location D:\city\map_back
@'
from pathlib import Path
from tempfile import TemporaryDirectory
from app.uploads import ZIP_LIMIT, extract_tiles

archive = Path(r"D:\city\cbd-tiles.zip")
if archive.stat().st_size > ZIP_LIMIT:
    raise SystemExit("ZIP 超过 512 MiB")
with TemporaryDirectory() as temporary:
    entry = extract_tiles(archive, Path(temporary))
    print(f"后端上传结构校验通过，入口: {entry.name}")
'@ | & '.\.venv\Scripts\python.exe' -
if ($LASTEXITCODE -ne 0) { throw '上传结构校验失败，请先修正 ZIP。' }
```

超限时，回到 Max 精简无用几何、降低模型面数或贴图分辨率，再输出到新目录。减小 `--tileSize` 不能保证降低解压总量；提高 ZIP 压缩率只影响压缩后体积。保留 `.zip` 格式及所有被引用资源。大型场景可按区域导出独立模型，每个区域分别生成完整 tileset 和 ZIP、单独登记。

### 5. 上传与地图验收

1. 保持前后端运行，打开 [我的数据](http://127.0.0.1:5173/#/data)，通过页面上传入口选择 **3D Tiles**，填写名称、分类和来源，选择 `cbd-tiles.zip`。
2. 页面显示上传进度；达到100%后进入校验与发布，收到成功提示后，登记出现在“图层登记”，完整解压目录出现在“资产目录”。传输与校验期间可取消。点击登记的 **加入地图**，检查模型加载与相机定位。
3. 对照参考地物检查位置、朝向、比例和底部高度，近距离检查贴图，并试用显隐、不透明度及图层下载。资源请求应无 404；下载 ZIP 应保留全部目录与资源。
4. 整体偏移时检查参考点与 WGS84 经纬度；倒伏时检查 FBX 导出轴与 `--inputUpAxis`；悬空或埋地时检查参考点高度、高程基准、地形高程及 `--correctCenter`、`--clampToGround`。修正后重新转换、打包并上传。

HTTP 413 表示上传包或解压总量超限；HTTP 422 表示元信息、ZIP 路径或入口结构无效。上传成功表示文件已保存并登记，点击“加入地图”完成实际渲染验收。

## 操作闭环

1. 首屏自动加载校园建筑白模与三个合成点线面图层；定位、显隐和不透明度控制位于每个图层行。
2. 点击“对象查询”选择已加入的图层，按关键词和类型筛选并翻页。点击列表对象定位和高亮，点击地图对象会跳到对应分页并滚动到该行；详情显示稳定ID、原始属性和资产版本，未知高度、等级和置信度显示“未提供”。
3. 点击“添加数据图层”，上传 GeoJSON 或 3D Tiles ZIP，也可登记 HTTP(S) 数据地址。
4. 顶部“我的数据”进入独立管理页（`#/data`），分为“图层登记”和“资产目录”。上传或登记后留在管理页，点击“加入地图”才加载；刷新后登记与文件仍在。
5. 地图左侧只显示当前加入的图层，× 仅从地图移除；通过“添加图层”可重新加入示例或已有登记。登记编辑、删除及实体文件管理统一位于“我的数据”。
6. 在左侧对应地图图层卡片点击下载按钮：GeoJSON 下载单文件，内置三维小样及上传三维资产下载完整 ZIP；右上角帮助保留操作说明。
7. 默认展示广州大学大学城校区白模；地区面板提供“大学城校区（默认）”“黄埔校区”快捷切换。白模采用 OSM 公开建筑轮廓，高度含估计，点击建筑查看依据。全国省、市、区县定位和边界高亮仍可使用；用户登记数据保持原位置。
8. “资产目录”支持分页、类型/状态/时间/关键词筛选和体积排序，详情显示版本、SHA-256、WGS84范围及逐文件清单；顶部汇总资产数量、本地容量和最近7天新增。“扫描已有文件”更新目录快照并补录历史文件。点击引用数量可查看图层、场景及历史运行的ID、固定版本与处理方式；历史运行持续保护源文件，仅有场景/运行引用时仍可重新登记。默认文件受保护，外部地址只移除登记。
9. 地区旁的“收藏位置”可保存多个地区或地图选取点位。自定义图层的加入状态、显隐和不透明度保存在服务器，刷新或重启后自动恢复；旧登记升级后首次手动加入一次。
10. 对象查询中的“框选”按住左键拖动，“多边形”逐点点击后按“完成”；范围按真实地面坐标查询，完整选择集高亮，列表在同一集合内分页。“清除范围”恢复全层查询，Esc或关闭面板取消草稿。移除图层、切换校区或资产版本会取消当前绘制。普通3D Tiles按一个模型资源查询，缺少空间几何的模型不参与范围选择；无语义属性时显示“该瓦片未携带语义属性，来源：几何模型”。
11. 顶部“仿真推演”打开`#/simulation`，选择固定路网版本、起终点和随机种子，点击地图道路或勾选正式边ID设置阻断。“固定图层与状态”保存加入、显隐、不透明度及资产版本；创建/保存场景同时保存当前相机，刷新后恢复上次场景。保存冲突保留本地草稿，点击“读取最新场景”读取服务器版本。
12. “提交运行”显示run_id、状态、输入SHA-256及trace_id，排队和运行中可取消。提交响应丢失时，配置锁定，“重试同一次提交”复用原幂等键和请求体。成功后显示蓝色基准路径、橙色阻断后路径、红叉阻断边；net-001阻断B-T为660→960m、66→96秒、+45.5%。不可达保留空路径和未知指标，同起终点为0米、0秒。点击“编辑配置”开始新草稿，已保存的运行结果保留在后端。

## 验证命令

```powershell
Set-Location D:\city\map_back
uv run pytest -q

Set-Location D:\city\map
pnpm test
pnpm build
pnpm preview --port 4173 --strictPort
```

构建预览：<http://127.0.0.1:4173/>，同样需要后端运行。前端开发和预览都将 `/api`、`/data-files` 代理到本机 8000 端口。

## 首版边界

广州大学大学城、黄埔校区白模分别包含135和27条OSM建筑记录，支持独立轮廓、组合多边形及庭院内洞。记录数按组合建筑归并，不等于建筑部件数，也不代表完整校园模型；没有真实立面。高度优先采用OSM标注，其次楼层×3米估计，缺测时统一9米。数据依ODbL使用并署名。积水、道路和可选的六栋瓦片建筑仍为合成演示，不代表真实风险。校区参考点不作为测量依据。底图与地形来自Cesium ion，取决于Token权限及网络；不可用时显示提示，其他本地图层仍可操作。

仿真页提供场景配置、阻断、持久运行、路径对比及运行历史。点击“运行历史”按场景ID、状态和北京时间筛选，选择记录恢复固定输入、相机、图层及结果。“从历史编辑”复制为新场景草稿；“从历史重跑”保留原输入哈希和版本、生成新run_id，场景后来修改或删除仍可重跑。结果区支持JSON/GeoJSON下载与预计时间回放：蓝/橙标记按逐边时间移动，可播放、暂停、拖动、节点步进、调速和复位。运行保存快照、版本、哈希和日志，重启处理见[后端说明](map_back/README.md)。后续功能见[完整功能清单](待办/待办-前后端完整功能.md)。通用坐标转换、模型转换、多人权限及公网部署保留在项目外部流程；上文给出模型转换操作。

地图下方“专题时间轴”控制现有点线面合成数据，提供2026-10-25、26日08:00/09:00四个北京时间时次。可逐小时/逐日、拖动/步进、播放/暂停和1×/2×/5×调速；列表与选中对象详情同步当前值及单位。小时空档和整日缺测显示“缺测/未覆盖”，真实0保留；日值为北京时间当天已有小时值均值。时间切换更新专题实体，静态底图和建筑保持原资源。点击“双视图时间对比”，左右分别选时次并联动视角；退出对比释放第二侧地图资源。

顶部“收藏与链接”保存完整画面，可命名、打开、改名和删除。收藏包含独立场景快照、固定资产版本、图层显隐/透明度/顺序、相机、时次和仿真运行；双视图同时记录右侧时间。地图快照中的图层操作编辑当前草稿，点击“返回普通地图”恢复原目录状态。删除收藏保留场景和运行，资产引用仍由场景/运行管理。

地址栏自动记录当前画面；“复制复现链接”可立即生成分享地址。链接使用`scene`、`v`、`run`、`t`、`resolution`、`camera`及`compare_t`/`compare_resolution`，例如`?scene=<场景ID>&v=1&run=<运行ID>&t=2026-10-25T12:00#/simulation`。无时区时间按北京时间解释，生成链接统一使用UTC。接收者须能访问同一前后端与资产服务；场景版本变化或引用失效时显示错误代码和trace_id。复制当前画面会保存独立场景快照，既有分享链接继续引用其原场景。

普通地图相机同时保存在浏览器；图层目录状态、收藏和场景保存在服务器。普通GeoJSON贴地显示，白模多边形按显式高度属性拉伸，三维瓦片使用自身配准坐标。

服务中断时，顶部显示“连接中断，正在重试”，按1/2/5/10/30秒退避检查；“立即重连”可马上检查。连接恢复后自动刷新目录、当前列表/详情、时序和已知运行，保留筛选、分页、相机和草稿。提交结果未知时保留同一次幂等请求，点击“重试同一次提交”确认结果。顶部“请求诊断”可查看并复制最近错误的code、message和trace_id；读取无权限、加载失败与空数据分别显示。

“我的数据”顶部展示资产数、对象数、运行数、本地容量、各类型数量和近7天新增。进入数据页、连接恢复和运行状态变化后更新统计，统计读取失败时显示独立错误与重试入口。

详细说明见 [前端与小样](map/README.md)、[后端接口与上传](map_back/README.md)、[验收记录](待办/待办-Cesium地图原型.md)、[数据管理验收](待办/待办-数据管理与实体文件.md)。
