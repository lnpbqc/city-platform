# Linux 部署：Docker／非 systemd 路线

完成统一准备的前六节后，按本文继续配置。适用于 Ubuntu 22.04／24.04 的 Docker 或其他非 systemd 环境，使用当前用户和 `city` Conda 环境运行 Supervisor、后端、切片服务与 Caddy。

## 7. 恢复环境，安装 Supervisor

**执行位置：服务器，当前登录用户。**

```bash
source "$HOME/.config/city/deploy.env"
source "$CITY_CONDA_BASE/etc/profile.d/conda.sh"
conda activate city
cd "$CITY_REPO"
python -m pip install supervisor==4.3.0
supervisord --version
```

预期版本为 `4.3.0`。Supervisor 安装到现有 Conda 环境；安装方式见 [官方说明](https://supervisord.org/installing.html)。

确认 8000、18744 端口空闲：

```bash
ss -lntp
```

## 8. 生成后台服务配置

**执行位置：服务器，`city` 环境。** 以下命令覆盖生成 Supervisor 配置，使用已保存的项目与 Conda 路径。日志和管理 socket 放在 `~/.config/city/`。

```bash
python - <<'PY'
import json
import os
from pathlib import Path
import shlex

repo = Path(os.environ['CITY_REPO'])
prefix = Path(os.environ['CITY_ENV_PREFIX'])
deploy = Path(os.environ['CITY_DEPLOY_DIR'])
logs = deploy / 'logs'
logs.mkdir(parents=True, exist_ok=True)
socket = deploy / 'supervisor.sock'

def literal(value):
    return str(value).replace('%', '%%')

environment = {
    'HOME': os.environ['CITY_USER_HOME'],
    'PATH': f'{prefix / "bin"}:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin',
    'PYTHONUNBUFFERED': '1',
    'MAP_STORAGE_DIR': str(repo / 'map_back/storage'),
    'CITY_TILE_CONFIG': str(repo / 'map_back/storage/tile-service.json'),
    'CITY_TILE_DATA': os.environ['CITY_TILE_DATA'],
    'CITY_TILE_TIPPECANOE': str(prefix / 'bin/tippecanoe'),
    'CITY_TILE_HOST': '127.0.0.1',
    'CITY_TILE_PORT': '18744',
    'PYTHONPATH': f'{repo / "map_back"}:{repo}',
}
text = f'''[unix_http_server]
file={literal(socket)}
chmod=0600

[supervisord]
logfile={literal(logs / 'supervisord.log')}
logfile_maxbytes=10MB
logfile_backups=3
pidfile={literal(deploy / 'supervisord.pid')}
childlogdir={literal(logs)}
umask=0077
environment=''' + ','.join(f'{key}={literal(json.dumps(value, ensure_ascii=False))}'
                           for key, value in environment.items()) + f'''

[rpcinterface:supervisor]
supervisor.rpcinterface_factory=supervisor.rpcinterface:make_main_rpcinterface

[supervisorctl]
serverurl=unix://{literal(socket)}
'''
programs = (
    ('city-tile', repo, [prefix / 'bin/python', '-m', 'tile_service.launcher'], 10, 'true'),
    ('city-backend', repo / 'map_back', [prefix / 'bin/python', '-m', 'uvicorn',
        'app.main:app', '--host', '127.0.0.1', '--port', '8000', '--workers', '1'], 20, 'true'),
    ('city-web', repo, ['/usr/bin/caddy', 'run', '--config', '/etc/caddy/Caddyfile',
        '--adapter', 'caddyfile'], 30, 'false'),
)
for name, directory, args, priority, autostart in programs:
    text += f'''
[program:{name}]
command={literal(shlex.join([str(arg) for arg in args]))}
directory={literal(directory)}
priority={priority}
autostart={autostart}
autorestart=true
startsecs=3
startretries=3
stopasgroup=true
killasgroup=true
stopwaitsecs=120
redirect_stderr=true
stdout_logfile={literal(logs / f'{name}.log')}
stdout_logfile_maxbytes=10MB
stdout_logfile_backups=3
'''
target = deploy / 'supervisord.conf'
target.write_text(text, encoding='utf-8')
target.chmod(0o600)
print(f'配置已生成：{target}')
PY
```

后端和切片自动启动，网站入口在第 10 节配置完成后启动。配置字段见 [Supervisor 官方说明](https://supervisord.org/configuration.html)。

## 9. 启动后端和切片

**执行位置：同一服务器终端。** 清除终端中的配置覆盖，按生成的配置启动 Supervisor：

```bash
unset MAP_DATABASE_URL CITY_TILE_SERVICE_URL CITY_TILE_TOKEN CITY_TILE_BACKEND_ORIGIN
supervisord -c "$CITY_DEPLOY_DIR/supervisord.conf"
```

Supervisor 转入后台运行。约五秒后查询状态：

```bash
supervisorctl -c "$CITY_DEPLOY_DIR/supervisord.conf" status
curl -fsS http://127.0.0.1:18744/health
curl -fsS http://127.0.0.1:8000/api/health
```

预期 `city-tile`、`city-backend` 为 `RUNNING`，`city-web` 为 `STOPPED`；健康接口均返回 `status: ok`，切片服务还应有 `worker_alive: true`。

若显示 `STARTING`，稍等后再查；`BACKOFF`、`FATAL` 则查对应日志：

```bash
tail -n 80 "$CITY_DEPLOY_DIR/logs/city-tile.log"
tail -n 80 "$CITY_DEPLOY_DIR/logs/city-backend.log"
```


## 10. 配置 IP 访问、端口映射和 HTTP

### 10.1 确认访问地址

从平台的端口映射记录中获取节点 IP 和节点端口。

| 访问位置 | 地址 |
| --- | --- |
| 你的电脑 | `http://节点IP:节点端口/` |
| 容器内部 | `http://127.0.0.1/` |

可选域名：将域名的 A 记录指向同一入口 IP，使用 `http://域名:节点端口/` 访问，Caddy 配置保持不变。

### 10.2 检查容器网络与防火墙

以下以节点端口 65001 映射容器端口 80 为例，在平台或宿主机配置：

| 配置项 | 值 |
| --- | --- |
| 协议 | TCP |
| 节点端口 | 65001 |
| 容器端口 | 80 |

节点和网络防火墙放行 TCP 65001，保留现有 SSH 入口。后端 8000、切片 18744 仅监听容器内的 `127.0.0.1`。

平台或宿主机管理员负责端口映射与外层防火墙，容器内不启用 UFW。使用内网节点 IP 时，访问电脑需要能到达该网络；互联网访问需配置公网入口。

### 10.3 安装 Caddy

**执行位置：服务器，当前用户。**

```bash
curl -fsSL https://dl.cloudsmith.io/public/caddy/stable/gpg.key \
  -o "$CITY_DEPLOY_DIR/caddy-signing-key.asc"
sudo gpg --dearmor --yes -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg \
  "$CITY_DEPLOY_DIR/caddy-signing-key.asc"
curl -fsSL https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt \
  -o "$CITY_DEPLOY_DIR/caddy-stable.list"
sudo install -m 644 "$CITY_DEPLOY_DIR/caddy-stable.list" /etc/apt/sources.list.d/caddy-stable.list
sudo chmod a+r /usr/share/keyrings/caddy-stable-archive-keyring.gpg
sudo apt-get update
sudo apt-get install -y caddy
caddy version
```

软件源来自 [Caddy 官方安装说明](https://caddyserver.com/docs/install#debian-ubuntu-raspbian)。

Caddy 由 Supervisor 以当前用户运行，读取 `map/dist/`。监听 80 需要 root 或管理员授予的低端口绑定权限。

### 10.4 生成完整 HTTP 网站配置

**执行位置：服务器，`city` 环境。** 以下命令覆盖生成 `$CITY_DEPLOY_DIR/Caddyfile`：

```bash
python - <<'PY'
import json
import os
from pathlib import Path

root = json.dumps(str(Path(os.environ['CITY_REPO']) / 'map/dist'), ensure_ascii=False)
text = ''':80 {
    request_body {
        max_size 11GiB
    }

    @backend path /api /api/* /data-files /data-files/* /samples /samples/*
    handle @backend {
        reverse_proxy 127.0.0.1:8000 {
            transport http {
                dial_timeout 10s
                response_header_timeout 3600s
                read_timeout 3600s
                write_timeout 3600s
            }
        }
    }

    @private path /internal /internal/* /docs /docs/* /redoc /openapi.json
    handle @private {
        respond 404
    }

    @static path /cesium /cesium/* /assets /assets/*
    handle @static {
        root * ROOT
        file_server
    }

    handle {
        root * ROOT
        try_files {path} /index.html
        file_server
    }

    log
}
'''.replace('ROOT', root)
target = Path(os.environ['CITY_DEPLOY_DIR']) / 'Caddyfile'
target.write_text(text, encoding='utf-8')
print(target)
PY
caddy fmt --overwrite "$CITY_DEPLOY_DIR/Caddyfile"
caddy adapt --config "$CITY_DEPLOY_DIR/Caddyfile" --adapter caddyfile >/dev/null
```

`:80` 表示监听容器内的 HTTP 80。参数说明见 [Caddy 官方文档](https://caddyserver.com/docs/caddyfile/concepts#addresses)。

配置中的 `11GiB` 为请求体上限，给项目允许的最大 10 GiB ZIP 及 multipart 边界留出空间；GeoJSON 的应用上限仍为 1 GiB。大文件传输采用流式代理，不配置请求体缓冲，不对 PMTiles 增加 gzip 编码，保留 `Range`、`Content-Range`、`Accept-Ranges`、`ETag`。

代理超时设为 3600 秒，用于等待大文件上传、处理及响应；前置 CDN、网关也须允许相同体积和耗时。代理路径使用 `handle`，保留原始 `/api/` 等前缀。`/cesium/` 和 `/assets/` 下缺失的静态文件直接返回 404，便于定位构建缺失。

### 10.5 安装配置并启动网站

覆盖写入 Caddy 配置并验证：

```bash
sudo install -m 644 "$CITY_DEPLOY_DIR/Caddyfile" /etc/caddy/Caddyfile
caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile
caddy reload --config /etc/caddy/Caddyfile --adapter caddyfile
```

看到 `Valid configuration` 后，编辑 Supervisor 配置：

```bash
nano "$CITY_DEPLOY_DIR/supervisord.conf"
```

在 `[program:city-web]` 段内将 `autostart=false` 改为 `autostart=true`，保存退出，然后加载变更：

```bash
supervisorctl -c "$CITY_DEPLOY_DIR/supervisord.conf" reread
supervisorctl -c "$CITY_DEPLOY_DIR/supervisord.conf" update
caddy reload --config /etc/caddy/Caddyfile --adapter caddyfile
supervisorctl -c "$CITY_DEPLOY_DIR/supervisord.conf" status
tail -n 80 "$CITY_DEPLOY_DIR/logs/city-web.log"
ss -lntp
```

预期三项服务为 `RUNNING`，Caddy 监听容器内的 80。在容器内部直接用 IP 检查：

```bash
curl -I http://127.0.0.1/
curl -fsS http://127.0.0.1/api/health
```

网页应返回 200，健康接口应返回 `status: ok`。

在自己的 Windows PowerShell 中输入平台访问地址，例如 `http://节点IP:65001`：

```powershell
$cityAccessUrl = (Read-Host '平台访问地址，不带结尾斜杠').TrimEnd('/')
curl.exe -I "$cityAccessUrl/"
curl.exe -fsS "$cityAccessUrl/api/health"
```

预期首页返回 200，健康接口返回 `status: ok`。浏览器打开同一地址。


## 11. 日常管理、升级与实例重启

### 11.1 常用命令

重新登录后先恢复操作环境：

```bash
source "$HOME/.config/city/deploy.env"
source "$CITY_CONDA_BASE/etc/profile.d/conda.sh"
conda activate city
cd "$CITY_REPO"
```

| 操作 | 命令 |
| --- | --- |
| 状态 | `supervisorctl -c "$CITY_DEPLOY_DIR/supervisord.conf" status` |
| 重启应用 | `supervisorctl -c "$CITY_DEPLOY_DIR/supervisord.conf" restart city-tile city-backend` |
| 停止应用 | `supervisorctl -c "$CITY_DEPLOY_DIR/supervisord.conf" stop city-backend city-tile` |
| 启动应用 | `supervisorctl -c "$CITY_DEPLOY_DIR/supervisord.conf" start city-tile city-backend` |
| 后端日志 | `tail -f "$CITY_DEPLOY_DIR/logs/city-backend.log"` |
| 切片日志 | `tail -f "$CITY_DEPLOY_DIR/logs/city-tile.log"` |
| 网站日志 | `tail -f "$CITY_DEPLOY_DIR/logs/city-web.log"` |
| 磁盘 | `df -h` |

修改切片地址或令牌后重启两个应用；更新 Supervisor 配置后执行 `reread` 和 `update`。

修改 Caddyfile 后先验证，再平滑加载：

```bash
caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile
caddy reload --config /etc/caddy/Caddyfile --adapter caddyfile
```

### 11.2 升级

先按本路线第 12.1 节停服备份，保留当前源码版本及配置，然后在原目录更新：

```bash
git -C "$CITY_REPO" pull --ff-only
cd "$CITY_REPO/map_back"
uv export --locked --no-dev --no-emit-project --no-hashes \
  --output-file "$CITY_DEPLOY_DIR/backend-requirements.txt"
python -m pip install -r "$CITY_DEPLOY_DIR/backend-requirements.txt" \
  -r "$CITY_REPO/tile_service/requirements.txt"
python -m pip check
unset MAP_DATABASE_URL
MAP_STORAGE_DIR="$CITY_REPO/map_back/storage" python -m alembic upgrade head
cd "$CITY_REPO/map"
pnpm install --frozen-lockfile
pnpm build
supervisorctl -c "$CITY_DEPLOY_DIR/supervisord.conf" start city-tile city-backend
curl -fsS http://127.0.0.1:8000/api/health
curl -fsS http://127.0.0.1:18744/health
```

确认依赖安装、迁移、前端构建均成功后再启动应用。有本地改动或分支分歧时先处理，不强制覆盖。切片工具版本变化时，将匹配版本的 `tippecanoe` 与 `tippecanoe-decode` 安装到 Conda 环境的 `bin/`，检查版本后重启切片服务。

刷新页面，检查资产、场景、历史运行和地图加载。保留同级 `map/public/samples/`，后端初始化依赖这些资源。

### 11.3 实例整体重启后恢复

实例停止或重启后，先执行本节 11.1 的四行环境恢复命令，再启动 Supervisor：

```bash
unset MAP_DATABASE_URL CITY_TILE_SERVICE_URL CITY_TILE_TOKEN CITY_TILE_BACKEND_ORIGIN
supervisord -c "$CITY_DEPLOY_DIR/supervisord.conf"
```

随后查询状态和两个健康接口。

需要随实例自动启动时，将 Conda 环境内的 `supervisord -n -c 配置绝对路径` 配置为平台启动命令，并使用相同的环境设置。

## 12. 备份、迁移与恢复

### 12.1 停服备份

执行位置为服务器，操作环境已恢复。先停止两个应用，等待停止命令成功返回后再复制数据库和资源：

```bash
supervisorctl -c "$CITY_DEPLOY_DIR/supervisord.conf" stop city-backend city-tile
CITY_BACKUP_ROOT="$CITY_USER_HOME/city-backups"
mkdir -p "$CITY_BACKUP_ROOT"
chmod 700 "$CITY_BACKUP_ROOT"
CITY_BACKUP="$CITY_BACKUP_ROOT/$(date +%Y%m%d-%H%M%S)"
mkdir -m 700 "$CITY_BACKUP"
cp -a "$CITY_REPO/map_back/storage" "$CITY_BACKUP/storage"
cp -a "$CITY_TILE_DATA" "$CITY_BACKUP/tile-data"
mkdir -m 700 "$CITY_BACKUP/deploy-config"
cp -a "$CITY_DEPLOY_DIR/deploy.env" "$CITY_DEPLOY_DIR/supervisord.conf" "$CITY_BACKUP/deploy-config/"
cp -a "$CITY_REPO/map/.env.local" "$CITY_BACKUP/frontend.env.local"
cp /etc/caddy/Caddyfile "$CITY_BACKUP/Caddyfile"
git -C "$CITY_REPO" rev-parse HEAD > "$CITY_BACKUP/source-commit.txt"
git -C "$CITY_REPO" status --short > "$CITY_BACKUP/source-status.txt"
conda list --explicit > "$CITY_BACKUP/conda-explicit.txt"
python -m pip freeze > "$CITY_BACKUP/python-packages.txt"
test -s "$CITY_BACKUP/storage/catalog.db"
du -sh "$CITY_BACKUP"
```

配置只复制 `deploy.env` 与 `supervisord.conf`，运行中的 socket、PID 和日志不作为恢复配置。SQLite、`files/`、`renders/`、运行镜像及其他存储内容来自同一次停服备份。备份中保留完整存储目录，包括可能存在的 WAL，不单独清空 `expired-sources/`。

仓库有未提交改动时额外保留实际源码副本；提交号不包含这些改动。备份包含令牌，保持目录权限 700，并复制一份到实例以外。

只做备份、不继续升级时重新启动：

```bash
supervisorctl -c "$CITY_DEPLOY_DIR/supervisord.conf" start city-tile city-backend
```

### 12.2 恢复到当前目录

先选择一次完整备份：

```bash
read -r -p '完整备份目录：' CITY_RESTORE
test -s "$CITY_RESTORE/storage/catalog.db"
test -d "$CITY_RESTORE/tile-data"
```

两个检查均成功后继续。当前数据改名留存，再复制备份：

```bash
supervisorctl -c "$CITY_DEPLOY_DIR/supervisord.conf" stop city-backend city-tile
CITY_RESTORE_STAMP="$(date +%Y%m%d-%H%M%S)"
mv "$CITY_REPO/map_back/storage" "$CITY_REPO/map_back/storage.before-$CITY_RESTORE_STAMP"
mv "$CITY_TILE_DATA" "$CITY_TILE_DATA.before-$CITY_RESTORE_STAMP"
cp -a "$CITY_RESTORE/storage" "$CITY_REPO/map_back/storage"
cp -a "$CITY_RESTORE/tile-data" "$CITY_TILE_DATA"
cp -a "$CITY_RESTORE/frontend.env.local" "$CITY_REPO/map/.env.local"
```

恢复与备份匹配的源码版本后，安装依赖、执行迁移并构建前端：

```bash
cd "$CITY_REPO/map_back"
uv export --locked --no-dev --no-emit-project --no-hashes \
  --output-file "$CITY_DEPLOY_DIR/backend-requirements.txt"
python -m pip install -r "$CITY_DEPLOY_DIR/backend-requirements.txt" \
  -r "$CITY_REPO/tile_service/requirements.txt"
python -m pip check
unset MAP_DATABASE_URL
MAP_STORAGE_DIR="$CITY_REPO/map_back/storage" python -m alembic upgrade head
cd "$CITY_REPO/map"
pnpm install --frozen-lockfile
pnpm build
supervisorctl -c "$CITY_DEPLOY_DIR/supervisord.conf" start city-tile city-backend
curl -fsS http://127.0.0.1:8000/api/health
```

用新代码读取旧备份时先迁移；回退代码时恢复与旧代码匹配的完整数据备份。检查资产、场景、历史运行和切片显示，确认恢复成功后再清理 `.before-时间戳` 目录。

### 12.3 迁移到另一实例

在原实例停服，复制完整 `storage/` 与匹配源码。新实例的切片工作目录可以从空目录启动，后端根据正式数据重新排队。保留切片令牌，`tile-service.json` 中的 `url`、`backend` 分别使用 `http://127.0.0.1:18744`、`http://127.0.0.1:8000`。

按新实例实际的用户、源码和 Conda 路径重新生成 Supervisor 与 Caddy 配置，不直接使用旧绝对路径配置。访问地址变化时，同步核对在线底图平台允许的访问来源。

## 13. 验收

### 13.1 服务和 HTTP

在服务器执行：

```bash
supervisorctl -c "$CITY_DEPLOY_DIR/supervisord.conf" status
ss -lntp
curl -fsS http://127.0.0.1:8000/api/health
curl -fsS http://127.0.0.1:18744/health
curl -I http://127.0.0.1/
curl -fsS http://127.0.0.1/api/health
curl -I http://127.0.0.1/cesium/Assets/approximateTerrainHeights.json
curl -I http://127.0.0.1/internal/render-source/test/1.0.0
```

三项服务应为 `RUNNING`；Caddy 监听容器内的 80，8000、18744 只监听 `127.0.0.1`；网页和 Cesium 静态文件返回 200，健康接口返回 `ok`，内部接口返回 404。退出并重新登录 SSH 后，再次确认状态与健康接口。

在自己的电脑上使用平台访问地址重复第 10.5 节的两个请求，验证节点端口映射。

### 13.2 页面、上传与 PMTiles

浏览器打开平台访问地址，确认页面加载，开发者工具无脚本错误、静态资源 404 或接口 502。上传自己的小型 GeoJSON，检查登记、查询、地图显示和切片发布。

在网络面板找到 `/api/render-files/{key}/map.pmtiles`，复制完整 URL，在终端执行：

```bash
read -r -p '已发布 PMTiles 的完整 HTTP URL：' CITY_PMTILES_URL
curl -sS -D - -o /dev/null -H 'Range: bytes=0-16383' "$CITY_PMTILES_URL"
```

预期 `206 Partial Content`，包含 `Content-Range`、`Accept-Ranges`、`ETag`，没有归档整体 gzip 编码。视野接口能显示数据与切片发布成功分别检查。

### 13.3 数据恢复与实例恢复

按第 12 节完成一次停服备份和恢复，检查资产、场景、历史运行与显示产物。实例重启后，按 11.3 恢复并检查服务；配置了平台启动命令的，确认其自动启动结果。

视觉检查由使用者完成，复核地图显示、移动端布局、长文本折行和大数据量下的交互表现。

## 14. 按现象排障

| 现象 | 检查与处理 |
| --- | --- |
| 找不到 Supervisor 命令 | 恢复本路线第 7 节的环境，检查 `command -v supervisord supervisorctl python` |
| 管理连接不存在 | 先启动 `supervisord -c "$CITY_DEPLOY_DIR/supervisord.conf"`，再查询；查看 `logs/supervisord.log` |
| 提示已有 Supervisor | 使用同一配置的 `supervisorctl` 管理进程 |
| 应用 BACKOFF 或 FATAL | 查看 `logs/city-tile.log`、`logs/city-backend.log`；修复原因后用 `supervisorctl` 启动对应程序 |
| 后端缺表或读到空库 | 检查 `MAP_STORAGE_DIR`，清除旧 `MAP_DATABASE_URL`，在 `map_back/` 对同一数据库执行迁移 |
| 端口占用 | `ss -lntp` 确定旧进程，停止其原启动入口，再由 Supervisor 启动 |
| Caddy 不能监听容器内的 80 | 检查端口占用和低端口绑定权限；当前普通用户需管理员授权 |
| 容器内正常，电脑访问超时 | 检查电脑到节点的网络、平台 65001→80 映射及网络防火墙 |
| HTTP 意外跳转到 HTTPS | 检查生效的 Caddyfile 站点行是 `:80 {`，验证并重新加载；再检查浏览器或前置代理的 HTTPS 强制设置 |
| HTTP 502 | 先请求本机 8000 健康接口，再看后端日志和网站代理配置 |
| 静态资源 404 | 检查 `map/dist/` 完整性和 Caddy 静态根目录，重新构建前端 |
| 上传 413 或中断 | 核对代理 11GiB 上限、应用文件限额、前置网关限制、超时和 `df -h` |
| 切片失败或没有产物 | 检查切片健康接口、固定工具版本、同一份连接配置及切片日志 |
| 在线底图失败 | 浏览器网络面板检查 Key/Token、域名授权和外部网络 |
