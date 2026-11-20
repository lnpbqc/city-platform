# Linux 部署：systemd 路线

本路线承接统一准备的前六节，从第七节继续。适用于 PID 1 为 systemd 的服务器；后续安装、HTTPS、网络、维护和验收都在本文完成。继续沿用保存的当前用户、源码目录和 Conda 环境。

## 7. 配置 systemd 开机自启

**执行位置：服务器，当前登录用户。** 先恢复已保存的部署环境：

```bash
source "$HOME/.config/city/deploy.env"
source "$CITY_CONDA_BASE/etc/profile.d/conda.sh"
conda activate city
cd "$CITY_REPO"
```

 下面生成两份完整服务文件，用户名和路径自动填入。`WorkingDirectory` 按完整路径写入，空格原样保留，不在路径两侧加引号；`Environment` 与 `ExecStart` 的参数分别引用。服务通过 `conda run` 使用已创建的环境，不读取 `.bashrc`。

```bash
python - <<'PY'
import os
from pathlib import Path

repo = Path(os.environ['CITY_REPO'])
prefix = Path(os.environ['CITY_ENV_PREFIX'])
base = Path(os.environ['CITY_CONDA_BASE'])
out = Path(os.environ['CITY_DEPLOY_DIR'])

def quote(value):
    value = str(value).replace('\\', '\\\\').replace('"', '\\"').replace('%', '%%')
    return '"' + value + '"'

def command(args):
    return ' '.join(quote(str(arg).replace('$', '$$')) for arg in args)

common = {
    'HOME': os.environ['CITY_USER_HOME'],
    'PYTHONUNBUFFERED': '1',
    'MAP_STORAGE_DIR': str(repo / 'map_back/storage'),
    'CITY_TILE_CONFIG': str(repo / 'map_back/storage/tile-service.json'),
    'CITY_TILE_DATA': os.environ['CITY_TILE_DATA'],
    'CITY_TILE_TIPPECANOE': str(prefix / 'bin/tippecanoe'),
    'CITY_TILE_HOST': '127.0.0.1',
    'CITY_TILE_PORT': '18744',
    'PYTHONPATH': f'{repo / "map_back"}:{repo}',
}
launcher = [base / 'bin/conda', 'run', '--no-capture-output', '--prefix', prefix, 'python']
services = (
    ('city-tile', repo, ['-m', 'tile_service.launcher']),
    ('city-backend', repo / 'map_back', ['-m', 'uvicorn', 'app.main:app',
                                      '--host', '127.0.0.1', '--port', '8000', '--workers', '1']),
)
for name, workdir, args in services:
    after = 'network.target' + (' city-tile.service' if name == 'city-backend' else '')
    text = f'''[Unit]
Description={name}
After={after}

[Service]
Type=simple
User={os.environ['CITY_USER']}
WorkingDirectory={str(workdir).replace('%', '%%')}
'''
    text += ''.join(f'Environment={quote(f"{key}={value}")}\n' for key, value in common.items())
    text += f'''ExecStart={command(launcher + args)}
Restart=on-failure
RestartSec=5
TimeoutStopSec=120
KillMode=control-group
UMask=0077

[Install]
WantedBy=multi-user.target
'''
    target = out / f'{name}.service'
    target.write_text(text, encoding='utf-8')
    print(target)
PY
sudo install -m 644 "$CITY_DEPLOY_DIR/city-tile.service" /etc/systemd/system/city-tile.service
sudo install -m 644 "$CITY_DEPLOY_DIR/city-backend.service" /etc/systemd/system/city-backend.service
sudo systemd-analyze verify /etc/systemd/system/city-tile.service /etc/systemd/system/city-backend.service
sudo systemctl daemon-reload
sudo systemctl enable --now city-tile.service city-backend.service
sudo systemctl status city-tile.service city-backend.service --no-pager
```

预期两项均为 `active (running)`。服务始终以记录的当前用户运行，不创建新用户。后端排在切片服务之后启动，但仍需用健康接口确认服务已就绪。

```bash
curl -fsS http://127.0.0.1:18744/health
curl -fsS http://127.0.0.1:8000/api/health
sudo journalctl -u city-tile -u city-backend -n 80 --no-pager
```

首次启动初始化数据时，稍等后再检查。失败时先看日志，不要重复在终端启动另一个进程。两项都只运行一个 worker，不启用 `--reload`。

## 8. 配置域名、云安全组与 UFW

### 8.1 域名解析

在域名服务商的 DNS 控制台创建记录，例如 `map.example.com`：

| 项目 | 设置 |
| --- | --- |
| 记录类型 | A |
| 主机记录 | map |
| 记录值 | 服务器公网 IPv4 |
| AAAA | 仅在服务器 IPv6 确实可达时配置；已有错误记录应删除或修正 |

首次部署使用直接 DNS 解析，暂不套 CDN 代理，便于检查证书与大文件上传。服务器在路由器后时，需要将公网 TCP 80、443 转发到服务器。云服务器则在云控制台配置安全组。

**执行位置：服务器。** 输入实际域名，不加 `https://` 和路径。

```bash
read -r -p '网站域名，例如 map.example.com：' CITY_DOMAIN
export CITY_DOMAIN
printf 'export CITY_DOMAIN=%q\n' "$CITY_DOMAIN" >> "$CITY_DEPLOY_DIR/deploy.env"
dig +short A "$CITY_DOMAIN"
dig +short AAAA "$CITY_DOMAIN"
```

A 记录应返回服务器公网 IP；AAAA 存在时应指向可达的服务器 IPv6。可在自己的电脑上再次查询，确认外部解析结果。域名同时保存到部署位置文件，重新登录后用本路线第 7 节的四行命令恢复即可。

### 8.2 两层防火墙

云安全组与服务器 UFW 都需要放行，两者互不替代：

| 入站端口 | 来源 | 用途 |
| --- | --- | --- |
| 实际 SSH TCP 端口，常见为 22 | 自己当前公网 IP 或管理网段 | 登录维护 |
| TCP 80 | 所有访问者 | HTTP 跳转与证书验证 |
| TCP 443 | 所有访问者 | HTTPS 网站 |
| 8000、18744 | 不开放 | 服务器内部通信 |

启用 IPv6 时，云安全组也配置相应 IPv6 规则。UDP 443 可用于 HTTP/3，本手册只开放 TCP，HTTPS 仍可使用 HTTP/1.1、HTTP/2。服务器需能出站访问 DNS、软件源及证书服务。

**执行位置：当前 SSH 会话。先确认实际 SSH 端口，再启用 UFW。**

```bash
printf '当前 SSH 连接：%s\n' "$SSH_CONNECTION"
sudo sshd -T | sed -n '/^port /p'
read -r -p '实际 SSH 端口，常见为 22：' CITY_SSH_PORT
sudo ufw allow "$CITY_SSH_PORT/tcp"
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw show added
sudo ufw enable
sudo ufw status verbose
```

保持这个 SSH 会话，再从本机打开第二个连接。确认能重新登录后再关闭原会话。自定义 SSH 端口要以实际连接端口为准；UFW 配置方法见 [Ubuntu 官方说明](https://ubuntu.com/server/docs/firewalls/)。

## 9. 安装 Caddy，启用 HTTPS

### 9.1 安装官方软件包

**执行位置：服务器，当前用户。** 安装包会建立 Caddy 自带的服务账户，只供 Caddy 使用；后端与切片仍以你的登录用户运行。

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

### 9.2 允许读取前端构建产物

**执行位置：服务器，项目环境已恢复。** Caddy 只需穿过项目父目录并读取 `map/dist/`。下面给父目录增加 Caddy 专属的通行权限，给构建产物增加读取权限，不更改所有者，不递归开放源码。

```bash
python - <<'PY'
import os
from pathlib import Path
import subprocess

dist = (Path(os.environ['CITY_REPO']) / 'map/dist').resolve()
assert (dist / 'index.html').is_file(), '请先构建前端'
for parent in reversed(dist.parents):
    subprocess.run(['sudo', 'setfacl', '-m', 'u:caddy:--x', str(parent)], check=True)
subprocess.run(['sudo', 'setfacl', '-R', '-m', 'u:caddy:r-X', str(dist)], check=True)
PY
sudo install -d /etc/systemd/system/caddy.service.d
printf '[Service]\nProtectHome=read-only\n' | \
  sudo tee /etc/systemd/system/caddy.service.d/city-static.conf >/dev/null
sudo systemctl daemon-reload
sudo -u caddy test -r "$CITY_REPO/map/dist/index.html"
```

最后一条命令成功退出表示文件权限通过。`ProtectHome=read-only` 允许 Caddy 在服务内读取已获授权的用户目录，支持源码放在 `/home/用户名/` 或 `/root/` 的情况。每次前端重新构建后重做本小节，构建过程可能替换整个 `dist/`。

### 9.3 生成完整网站配置

**执行位置：服务器，`city` 环境。** 若终端已重开，先执行本路线第 7 节的四行环境恢复命令，已保存的域名会一并恢复。

```bash
python - <<'PY'
import json
import os
from pathlib import Path

domain = os.environ['CITY_DOMAIN']
root = json.dumps(str(Path(os.environ['CITY_REPO']) / 'map/dist'), ensure_ascii=False)
text = '''DOMAIN {
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
'''.replace('DOMAIN', domain).replace('ROOT', root)
target = Path(os.environ['CITY_DEPLOY_DIR']) / 'Caddyfile'
target.write_text(text, encoding='utf-8')
print(target)
PY
caddy fmt --overwrite "$CITY_DEPLOY_DIR/Caddyfile"
caddy adapt --config "$CITY_DEPLOY_DIR/Caddyfile" --adapter caddyfile >/dev/null
```

配置中的 `11GiB` 为请求体上限，给项目允许的最大 10 GiB ZIP 及 multipart 边界留出空间；GeoJSON 的应用上限仍为 1 GiB。大文件传输采用流式代理，不配置请求体缓冲，不对 PMTiles 增加 gzip 编码，保留 `Range`、`Content-Range`、`Accept-Ranges`、`ETag`。

代理超时设为 3600 秒，用于等待大文件上传、处理及响应；前置 CDN、网关也须允许相同体积和耗时。代理路径使用 `handle`，保留原始 `/api/` 等前缀。`/cesium/` 和 `/assets/` 下缺失的静态文件直接返回 404，便于定位构建缺失。

**首次替换 Caddy 默认配置前保留副本。** 已经运行其他网站的服务器，应将生成的站点块合并进现有配置，保留其他站点。

```bash
sudo cp -a /etc/caddy/Caddyfile "/etc/caddy/Caddyfile.before-city-$(date +%Y%m%d-%H%M%S)"
sudo install -m 644 "$CITY_DEPLOY_DIR/Caddyfile" /etc/caddy/Caddyfile
sudo -u caddy caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile
sudo systemctl enable caddy
sudo systemctl restart caddy
sudo systemctl status caddy --no-pager
sudo journalctl -u caddy -n 80 --no-pager
```

预期验证输出 `Valid configuration`，服务为 `active (running)`。Caddy 随后申请可信证书、自动续期，并将 HTTP 跳转到 HTTPS。域名须已解析，公网 TCP 80、443 须到达 Caddy；此流程不需要购买证书或另装 Certbot。参见 [自动 HTTPS](https://caddyserver.com/docs/automatic-https) 和 [Let’s Encrypt 免费证书说明](https://letsencrypt.org/docs/faq/)。

## 10. 完成服务器验收

### 10.1 服务与公网入口

**执行位置：服务器；域名检查也在自己电脑上执行一次。**

```bash
sudo systemctl is-enabled city-tile city-backend caddy
sudo systemctl is-active city-tile city-backend caddy
sudo ss -lntp
curl -fsS http://127.0.0.1:8000/api/health
curl -fsS http://127.0.0.1:18744/health
curl -I "http://$CITY_DOMAIN"
curl -fsS "https://$CITY_DOMAIN/api/health"
curl -I "https://$CITY_DOMAIN/cesium/Assets/approximateTerrainHeights.json"
curl -I "https://$CITY_DOMAIN/internal/render-source/test/1.0.0"
```

预期三项服务均已启用且活动；8000、18744 仅绑定 `127.0.0.1`；HTTP 返回 HTTPS 跳转；HTTPS 健康接口返回 `ok`；Cesium 静态资源返回 200；内部接口返回 404。不要使用 `curl -k` 跳过证书验证。

### 10.2 页面、上传与 Range 请求

在浏览器打开 `https://你的域名`：

1. 确认页面可打开，浏览器没有证书错误，开发者工具中无静态文件 404、接口 502 或脚本错误。
2. 上传一个自己的小型 GeoJSON，确认登记、查询和地图加载成功，切片完成后出现正式显示产物。
3. 在浏览器网络面板找到 `/api/render-files/{key}/map.pmtiles`，复制 URL，在终端验证：

```bash
read -r -p '已发布 PMTiles 的完整 HTTPS URL：' CITY_PMTILES_URL
curl -sS -D - -o /dev/null -H 'Range: bytes=0-16383' "$CITY_PMTILES_URL"
```

预期状态为 `206 Partial Content`，包含 `Content-Range`、`Accept-Ranges` 和 `ETag`，没有整体 gzip 编码。若切片失败，先查切片日志；视野接口仍能显示数据不代表切片成功。

### 10.3 开机启动与恢复

安排一次服务器重启，重新登录后运行 10.1 的服务与健康检查，确认不用手动激活 Conda 或开启终端即可访问。重启命令为 `sudo reboot`，它会断开当前 SSH。

按第 12 节完成一次停服备份，并在可停机的时段恢复该备份，确认原有资产、场景、历史运行和切片产物可读。恢复前仍保留当前数据目录。

视觉检查由使用者完成：复核地图显示、移动端布局、长文本折行和大数据量下的交互表现。

## 11. 日常管理与升级

### 11.1 常用命令

重新登录后先恢复操作环境：

```bash
source "$HOME/.config/city/deploy.env"
source "$CITY_CONDA_BASE/etc/profile.d/conda.sh"
conda activate city
cd "$CITY_REPO"
```

查看、停止或启动 systemd 服务本身不要求激活 Conda。

| 操作 | 命令 |
| --- | --- |
| 查看状态 | `sudo systemctl status city-backend city-tile caddy --no-pager` |
| 跟踪应用日志 | `sudo journalctl -u city-backend -u city-tile -f` |
| 跟踪网页入口日志 | `sudo journalctl -u caddy -f` |
| 重启应用 | `sudo systemctl restart city-tile city-backend` |
| 停止应用 | `sudo systemctl stop city-backend city-tile` |
| 启动应用 | `sudo systemctl start city-tile city-backend` |
| 检查磁盘 | `df -h` |

修改切片地址或令牌后重启两个应用服务；修改 systemd 文件后先 `sudo systemctl daemon-reload` 再重启；修改 Caddyfile 后先验证，再 `sudo systemctl reload caddy`。首次设置的 `ProtectHome` 属于 systemd 配置，需要 restart 才生效。

不要同时使用手动启动命令和 systemd 启动同一服务。手动排障前先停止对应 systemd 服务，结束后按 `Ctrl+C` 退出，再交回 systemd。

### 11.2 升级顺序

**执行位置：服务器，恢复项目环境后。**

1. 按第 12 节停服并备份，记录 `git rev-parse HEAD`，保留 `.env.local` 和匹配版本的源码。
2. 在原目录更新源码：`git -C "$CITY_REPO" pull --ff-only`。有本地改动或分支分歧时先处理，不强制覆盖。
3. 安装新版本锁定的依赖：

```bash
cd "$CITY_REPO/map_back"
uv export --locked --no-dev --no-emit-project --no-hashes \
  --output-file "$CITY_DEPLOY_DIR/backend-requirements.txt"
python -m pip install -r "$CITY_DEPLOY_DIR/backend-requirements.txt" \
  -r "$CITY_REPO/tile_service/requirements.txt"
python -m pip check
```

切片工具版本变化时，使用匹配该版本的 `tippecanoe` 与 `tippecanoe-decode` 替换 Conda 环境内的两个二进制，并核对版本。
4. 在 `map_back/` 执行 `MAP_STORAGE_DIR="$CITY_REPO/map_back/storage" python -m alembic upgrade head`。先执行 `unset MAP_DATABASE_URL`，使用与服务相同的数据库。
5. 重新构建前端，再按本路线第 9.2 节补齐 Caddy 读取权限：

```bash
cd "$CITY_REPO/map"
pnpm install --frozen-lockfile
pnpm build
```
6. 执行 `sudo systemctl start city-tile city-backend`，检查健康接口、旧资产、场景与历史运行，刷新网页。

升级前后都保留实际部署路径。后端依赖同级 `map/public/samples/`，只留下前端 `dist/` 会影响内置资源初始化。

## 12. 备份、迁移与恢复

### 12.1 停服备份

**执行位置：服务器，恢复项目环境后。** 先停止后端与切片，等待命令结束再复制 SQLite，连同 WAL 和资源目录整体备份。

```bash
sudo systemctl stop city-backend city-tile
CITY_BACKUP_ROOT="$CITY_USER_HOME/city-backups"
mkdir -p "$CITY_BACKUP_ROOT"
chmod 700 "$CITY_BACKUP_ROOT"
CITY_BACKUP="$CITY_BACKUP_ROOT/$(date +%Y%m%d-%H%M%S)"
mkdir -m 700 "$CITY_BACKUP"
cp -a "$CITY_REPO/map_back/storage" "$CITY_BACKUP/storage"
cp -a "$CITY_TILE_DATA" "$CITY_BACKUP/tile-data"
cp -a "$CITY_DEPLOY_DIR" "$CITY_BACKUP/deploy-config"
cp -a "$CITY_REPO/map/.env.local" "$CITY_BACKUP/frontend.env.local"
cp /etc/caddy/Caddyfile "$CITY_BACKUP/Caddyfile"
git -C "$CITY_REPO" rev-parse HEAD > "$CITY_BACKUP/source-commit.txt"
git -C "$CITY_REPO" status --short > "$CITY_BACKUP/source-status.txt"
conda list --explicit > "$CITY_BACKUP/conda-explicit.txt"
python -m pip freeze > "$CITY_BACKUP/python-packages.txt"
test -s "$CITY_BACKUP/storage/catalog.db"
du -sh "$CITY_BACKUP"
```

若仓库有未提交改动，额外保留实际源码副本；提交号不包含这些改动。将备份复制到服务器以外的位置。备份包含令牌和前端配置，保持目录权限为 700。

SQLite、`files/`、`renders/`、运行镜像及其他存储内容需要来自同一次停服备份。不要单独清空 `expired-sources/`，它参与原文件到期清理的事务恢复。

只做备份、不继续升级时，执行：

```bash
sudo systemctl start city-tile city-backend
```

### 12.2 恢复到当前目录

**执行位置：服务器，恢复项目环境后。** 输入一次完整备份目录。下面将当前存储改名留存，再复制备份，路径不会改变。

```bash
read -r -p '完整备份目录：' CITY_RESTORE
test -s "$CITY_RESTORE/storage/catalog.db"
test -d "$CITY_RESTORE/tile-data"
```

两个检查均成功后继续：

```bash
sudo systemctl stop city-backend city-tile
CITY_RESTORE_STAMP="$(date +%Y%m%d-%H%M%S)"
mv "$CITY_REPO/map_back/storage" "$CITY_REPO/map_back/storage.before-$CITY_RESTORE_STAMP"
mv "$CITY_TILE_DATA" "$CITY_TILE_DATA.before-$CITY_RESTORE_STAMP"
cp -a "$CITY_RESTORE/storage" "$CITY_REPO/map_back/storage"
cp -a "$CITY_RESTORE/tile-data" "$CITY_TILE_DATA"
```

恢复与备份匹配的源码版本后，复制前端配置、安装依赖并重新构建：

```bash
cp -a "$CITY_RESTORE/frontend.env.local" "$CITY_REPO/map/.env.local"
cd "$CITY_REPO/map_back"
uv export --locked --no-dev --no-emit-project --no-hashes \
  --output-file "$CITY_DEPLOY_DIR/backend-requirements.txt"
python -m pip install -r "$CITY_DEPLOY_DIR/backend-requirements.txt" \
  -r "$CITY_REPO/tile_service/requirements.txt"
python -m pip check
cd "$CITY_REPO/map"
pnpm install --frozen-lockfile
pnpm build
```

按本路线第 9.2 节补齐 Caddy 读取权限。用较新代码读取旧备份时先执行迁移；回退代码时恢复与旧代码匹配的完整数据备份，不以数据库降级代替恢复。

```bash
unset MAP_DATABASE_URL
cd "$CITY_REPO/map_back"
MAP_STORAGE_DIR="$CITY_REPO/map_back/storage" python -m alembic upgrade head
sudo systemctl start city-tile city-backend
curl -fsS http://127.0.0.1:8000/api/health
```

随后检查旧资产、场景、历史运行和切片显示。确认恢复成功后，再安排清理 `.before-时间戳` 目录。

### 12.3 从 Windows 或另一台服务器迁移

在原机器停止服务，复制完整 `storage/` 和匹配版本源码。Linux 切片队列可从空目录启动，后端会按正式数据重新排队。将完整 `storage/` 放到新源码的 `map_back/storage/`，保留 `tile-service.json` 中的令牌，将 `url`、`backend` 分别设为 `http://127.0.0.1:18744`、`http://127.0.0.1:8000`，再执行本节的数据库迁移。

新服务器重新记录自己的用户、源码目录和 Conda 路径，重新生成 systemd 与 Caddy 配置，不直接安装旧机器的绝对路径配置。保持原来的切片令牌，修正其中的地址；域名变更时同步修改 DNS 和底图平台的访问域名。

## 13. 按现象排障

| 现象 | 检查与处理 |
| --- | --- |
| 激活环境后命令找不到 | `conda info --envs` 查看环境；`command -v python node pnpm uv` 确认来自项目环境；按本路线第 7 节恢复终端 |
| 服务报 `CHDIR`、`EXEC` 或找不到 Conda | `sudo systemctl cat city-backend`，核对实际路径、用户和目录是否仍存在；重新生成第 7 节配置 |
| 服务启动频繁失败 | `sudo journalctl -u city-backend -u city-tile -n 100 --no-pager`；修复日志中的原因后执行 `sudo systemctl reset-failed city-backend city-tile`，再启动 |
| 端口被占用 | `sudo ss -lntp` 找到旧进程所属服务；关闭手动前台实例或旧服务，再启动 systemd 服务 |
| 后端提示缺表 | 确认在实际 `map_back/` 执行迁移，`MAP_STORAGE_DIR` 与服务一致，未被旧 `MAP_DATABASE_URL` 覆盖 |
| 证书申请失败 | `dig +short A "$CITY_DOMAIN"`、`dig +short AAAA "$CITY_DOMAIN"`；检查云安全组、UFW、路由转发、80/443 占用及 `sudo journalctl -u caddy -n 100 --no-pager`；CAA 限制也会影响签发 |
| HTTPS 502 | 先请求服务器本机 `/api/health`，再看后端日志；确认 Caddy 代理到 `127.0.0.1:8000` |
| 网页 403 或日志 `permission denied` | 重做第 9.2 节，检查 `sudo -u caddy test -r "$CITY_REPO/map/dist/index.html"` 和 `sudo systemctl cat caddy` 中的 `ProtectHome`；不使用递归 `chmod 777` |
| `/cesium/` 返回 404 | 检查完整构建产物，重新 `pnpm build`；Workers、ThirdParty、Assets、Widgets 都应存在 |
| 上传返回 413 | 核对 Caddy 11GiB 请求体上限、项目自身文件限额，以及前置 CDN/网关限额 |
| 上传中断、超时或磁盘不足 | 查看 Caddy 与后端日志、`df -h`；计入数据库索引、原文件、ZIP、解包及切片暂存，不只看上传文件大小 |
| 切片不启动或版本不符 | 请求 `http://127.0.0.1:18744/health`；检查共享配置、工具版本、两个工具的绝对路径及切片日志 |
| 切片 401 或来源校验失败 | 检查两端读取同一 `map_back/storage/tile-service.json`，`url` 为 `http://127.0.0.1:18744`，`backend` 为 `http://127.0.0.1:8000`；修改后重启两端 |
| 地图能显示但没有 PMTiles | 检查切片任务和日志，确认正式产物发布；视野接口可在切片不可用时继续显示 |
| 在线底图、地形或行政边界失败 | 浏览器网络面板检查 Key/Token、域名授权及外部网络；网页和健康接口成功与在线底图连通是两项检查 |

更多数据限制见 [数据与模型说明](数据与模型说明.md)，切片处理规则见 [切片服务技术说明](../tile_service/技术说明.md)，Windows 部署见 [部署说明](部署说明.md)。
