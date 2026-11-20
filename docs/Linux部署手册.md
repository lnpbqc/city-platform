# Linux 从零部署手册：统一准备

本手册适用于 Ubuntu 22.04、24.04，前六节统一完成源码、Conda、依赖、数据库、前端构建和前台检查。沿用当前登录用户与实际源码目录，不创建应用用户或搬迁源码。以 x86_64 为主，Miniforge 下载命令也适用于 aarch64。

先记录服务管理环境：

```bash
ps -p 1 -o pid,comm,args
systemd-detect-virt
```

PID 1 为 `systemd` 的服务器选择 systemd 路线；PID 1 为 Bash 或 init 的 Docker／非 systemd 环境选择 Supervisor 路线。先顺序完成下面六节，结束后只进入所选路线，后续操作都在对应文档内完成。

当前项目没有登录和用户权限。两条路线均按公开部署配置，访问者可以调用现有上传、删除等接口；入口认证留待用户模块实现。

## 1. 登录服务器，准备基础工具

**执行位置：本机终端。** 将用户名和 IP 替换为实际值；SSH 不是 22 端口时加 `-p 实际端口`。

```bash
ssh 你的用户名@服务器公网IP
```

**以下命令均在服务器 Bash 中执行，使用刚登录的用户。** 带 `sudo` 的命令用于配置系统，安装应用依赖不加 `sudo`。当前登录用户若为 root，也沿用该用户。

```bash
whoami
printf '用户目录：%s\n' "$HOME"
cat /etc/os-release
uname -m
sudo -v
sudo ss -lntp
df -h
free -h
```

确认系统为 Ubuntu 22.04 或 24.04，架构为 `x86_64` 或 `aarch64`。`sudo -v` 成功后继续；root 可直接使用以下命令中的 sudo，系统没有 sudo 时先用 `apt-get update` 和 `apt-get install -y sudo` 安装。

80、443 将供 Caddy 使用，8000 供后端使用，18744 供切片服务使用。若已有进程占用，先查清用途，再停止对应服务。磁盘同时承载上传文件、数据库、索引、切片暂存和构建产物，按实际数据量安排空间。

```bash
sudo apt-get update
sudo apt-get install -y sudo ca-certificates curl git build-essential \
  libsqlite3-dev zlib1g-dev ufw acl dnsutils gnupg nano \
  debian-keyring debian-archive-keyring apt-transport-https
```

## 2. 将源码放到自己选择的目录

**执行位置：服务器上你准备存放源码的父目录。** 已经拉取源码的，直接进入现有项目根目录，跳过克隆。

```bash
read -r -p '仓库地址：' CITY_GIT_URL
git clone "$CITY_GIT_URL" city
cd city
```

也可以把完整项目上传到服务器。保留同级的 `map/`、`map_back/` 和 `tile_service/`，包括 `map/public/samples/`、依赖锁文件和数据库迁移文件。不复制 Windows 的 `.venv/`、`node_modules/`。迁移已有数据时，先在原机器停止后端与切片服务，将完整 `storage/` 复制到当前源码的 `map_back/storage/`，再继续第 5 节。

**执行位置：项目根目录。** 记录实际路径，目录中有空格也可使用后面的命令。

```bash
export CITY_REPO="$(pwd -P)"
export CITY_USER="$(id -un)"
export CITY_USER_HOME="$HOME"
test -f "$CITY_REPO/map/package.json"
test -f "$CITY_REPO/map_back/uv.lock"
test -f "$CITY_REPO/tile_service/service.py"
printf '用户：%s\n项目：%s\n' "$CITY_USER" "$CITY_REPO"
```

三个 `test` 均无输出且退出码为 0，表示目录正确。后文所有路径由这里记录的值产生，不需要搬迁源码。

## 3. 安装或复用 Conda

### 3.1 首次安装 Miniforge

**执行位置：服务器，当前用户。** **已有可用 Conda 的跳至 3.2**。安装文件下载到临时目录，Conda 安装到当前用户的 `~/miniforge3`。

```bash
CITY_DOWNLOAD_DIR="$(mktemp -d)"
CITY_INSTALLER="Miniforge3-Linux-$(uname -m).sh"
curl -fL "https://github.com/conda-forge/miniforge/releases/latest/download/$CITY_INSTALLER" \
  -o "$CITY_DOWNLOAD_DIR/$CITY_INSTALLER"
curl -fL "https://github.com/conda-forge/miniforge/releases/latest/download/$CITY_INSTALLER.sha256" \
  -o "$CITY_DOWNLOAD_DIR/$CITY_INSTALLER.sha256"
(cd "$CITY_DOWNLOAD_DIR" && sha256sum -c "$CITY_INSTALLER.sha256")
```

校验输出 `OK` 后安装；下载或校验失败时重新下载这两个文件。

```bash
bash "$CITY_DOWNLOAD_DIR/$CITY_INSTALLER" -b -p "$HOME/miniforge3"
source "$HOME/miniforge3/etc/profile.d/conda.sh"
conda init bash
conda --version
```

安装步骤依据 [Miniforge 官方说明](https://github.com/conda-forge/miniforge)。不要在已存在的安装目录上重复运行安装器。

### 3.2 创建项目环境

已有 Conda 的用户先确保 `conda --version` 能执行。若提示需要初始化，在当前终端执行 `source "实际Conda安装目录/etc/profile.d/conda.sh"`，再运行 `conda init bash`。

```bash
conda create -y -n city --override-channels -c conda-forge \
  python=3.13 nodejs=24 pip uv
conda activate city
npm install --global pnpm@10
python --version
node --version
pnpm --version
python -c 'import sys; print(sys.executable)'
```

若 `city` 环境已经由本手册创建，直接激活。预期 Python 为 3.13、Node.js 为 24、pnpm 为 10，Python 路径位于该 Conda 环境。

若在安装`pnpm`时出现：

```bash
#$ npm install --global pnpm@10                                                                                                                          
npm error code EAI_AGAIN
npm error syscall getaddrinfo
npm error errno EAI_AGAIN
npm error request to https://registry.npmjs.org/pnpm failed, reason: getaddrinfo EAI_AGAIN registry.npmjs.org
npm error A complete log of this run can be found in: /root/.npm/_logs/2026-11-20T05_48_12_836Z-debug-0.log
```

需要添加国内镜像：

```bash
npm config set registry https://registry.npmmirror.com
```

以及在`/etc/resolv.conf`，添加或修改 `nameserver` 行，例如：

```bash
nameserver 223.5.5.5
nameserver 119.29.29.29
nameserver 8.8.8.8
nameserver 1.1.1.1
```

或者写IP映射:

```bash
 echo "222.217.94.75 registry.npmmirror.com" >> /etc/hosts
 echo "42.101.76.232 cdn.npmmirror.com" >> /etc/hosts
 getent hosts registry.npmmirror.com   # 能看到 IP 就说明 hosts 生效
```



### 3.3 保存部署位置

**执行位置：项目根目录，`city` 环境已激活。** 这些变量用于生成配置，不含业务令牌。

```bash
export CITY_CONDA_BASE="$(conda info --base)"
export CITY_ENV_PREFIX="$CONDA_PREFIX"
export CITY_TILE_DATA="$CITY_USER_HOME/.local/share/city-tile"
export CITY_DEPLOY_DIR="$CITY_USER_HOME/.config/city"
mkdir -p "$CITY_DEPLOY_DIR"
chmod 700 "$CITY_DEPLOY_DIR"
python - <<'PY'
import os
from pathlib import Path
import shlex

names = ('CITY_REPO', 'CITY_USER', 'CITY_USER_HOME', 'CITY_CONDA_BASE',
         'CITY_ENV_PREFIX', 'CITY_TILE_DATA', 'CITY_DEPLOY_DIR')
target = Path(os.environ['CITY_DEPLOY_DIR']) / 'deploy.env'
target.write_text(''.join(f'export {name}={shlex.quote(os.environ[name])}\n'
                          for name in names), encoding='utf-8')
target.chmod(0o600)
print(f'部署位置已保存：{target}')
PY
```

**以后重新登录服务器，先执行下面四行即可恢复操作环境：**

```bash
source "$HOME/.config/city/deploy.env"
source "$CITY_CONDA_BASE/etc/profile.d/conda.sh"
conda activate city
cd "$CITY_REPO"
```

**不要移动源码或 Conda 环境后继续使用旧服务配置；路径变化后重新记录位置，并重新生成所选部署路线中的服务和网站配置。**

## 4. 安装应用与切片依赖

### 4.1 后端与切片 Python 依赖

**执行位置：服务器，`city` 环境已激活。** 从现有锁文件导出依赖，直接安装进 Conda。`uv export` 使用 `--locked` 检查锁文件与项目声明一致，不创建 `.venv`。

```bash
cd "$CITY_REPO/map_back"
uv export --locked --no-dev --no-emit-project --no-hashes \
  --output-file "$CITY_DEPLOY_DIR/backend-requirements.txt"
python -m pip install -r "$CITY_DEPLOY_DIR/backend-requirements.txt" \
  -r "$CITY_REPO/tile_service/requirements.txt"
python -m pip check
```

预期最后输出 `No broken requirements found.`。锁文件不一致时，应获取包含匹配 `pyproject.toml` 与 `uv.lock` 的项目版本，不在服务器上临时重新解析版本。导出参数见 [uv 官方命令说明](https://docs.astral.sh/uv/reference/cli/#uv-export)。

### 4.2 编译固定版本 tippecanoe

**执行位置：服务器，当前用户，`city` 环境已激活。** 版本及提交与项目 `tile_service/install.sh` 保持一致，将两个工具放到 Conda 环境的 `bin/`。以下步骤将切片工具和 Python 依赖安装到 `city` Conda 环境，**无需运行原来的 `install.sh`**。

```bash
CITY_TIP_SOURCE="$CITY_USER_HOME/.local/src/city-tippecanoe-2.79.0"
mkdir -p "$(dirname "$CITY_TIP_SOURCE")"
if [ ! -d "$CITY_TIP_SOURCE/.git" ]; then
  git clone --depth 1 --branch 2.79.0 \
    https://github.com/felt/tippecanoe.git "$CITY_TIP_SOURCE"
fi
test "$(git -C "$CITY_TIP_SOURCE" rev-parse HEAD)" = \
  '68ab8dcc229f95b8b25877697d5e8d66783af503'
```

最后一个命令退出码为 0 后继续：

```bash
make -C "$CITY_TIP_SOURCE" -j2
install -m 755 "$CITY_TIP_SOURCE/tippecanoe" "$CITY_ENV_PREFIX/bin/tippecanoe"
install -m 755 "$CITY_TIP_SOURCE/tippecanoe-decode" "$CITY_ENV_PREFIX/bin/tippecanoe-decode"
"$CITY_ENV_PREFIX/bin/tippecanoe" --version
```

预期版本为 `2.79.0`。服务还需要同目录的 `tippecanoe-decode`，两个文件都要保留。

## 5. 配置存储、令牌与数据库

**执行位置：服务器，项目环境已恢复。** 后端使用项目内 `map_back/storage/`；切片队列、临时文件存放在当前用户的独立目录，两端不共用 SQLite。

```bash
export MAP_STORAGE_DIR="$CITY_REPO/map_back/storage"
export CITY_TILE_CONFIG="$MAP_STORAGE_DIR/tile-service.json"
export CITY_TILE_PYTHON="$CITY_ENV_PREFIX/bin/python"
export CITY_TILE_TIPPECANOE="$CITY_ENV_PREFIX/bin/tippecanoe"
unset MAP_DATABASE_URL CITY_TILE_SERVICE_URL CITY_TILE_TOKEN CITY_TILE_BACKEND_ORIGIN
mkdir -p "$MAP_STORAGE_DIR" "$CITY_TILE_DATA"
chmod 700 "$CITY_TILE_DATA"
python - <<'PY'
import json
import os
from pathlib import Path
import secrets

path = Path(os.environ['CITY_TILE_CONFIG'])
if not path.exists():
    config = {'url': 'http://127.0.0.1:18744',
              'backend': 'http://127.0.0.1:8000', 'token': secrets.token_hex(32)}
    with path.open('x', encoding='utf-8') as stream:
        json.dump(config, stream, indent=2)
config = json.loads(path.read_text(encoding='utf-8'))
assert config['url'] == 'http://127.0.0.1:18744', '请修正已有配置中的 url'
assert config['backend'] == 'http://127.0.0.1:8000', '请修正已有配置中的 backend'
assert len(config['token']) >= 24, '已有令牌长度不足'
path.chmod(0o600)
print('切片连接配置检查通过，未输出令牌')
PY
```

已有配置保留令牌。如检查发现原 Windows/WSL 地址，使用 `nano "$CITY_TILE_CONFIG"` 修改 `url`、`backend` 为上面的回环地址，再运行检查。两端读取同一份配置；不把令牌写进前端或命令参数。

本流程取消自定义数据库和切片地址的终端覆盖，确保手动验证与后续后台服务使用相同配置。迁移已有实例时，先确认完整存储目录已复制到 `map_back/storage/`，再执行迁移：

```bash
cd "$CITY_REPO/map_back"
python -m alembic upgrade head
```

命令成功退出后继续。后端不会自动加载 `.env`；后续后台服务将显式配置存储位置。

## 6. 构建前端，验证两个服务

### 6.1 配置底图并构建

**执行位置：服务器，`city` 环境。**

```bash
cd "$CITY_REPO/map"
pnpm install --frozen-lockfile
if [ ! -f .env.local ]; then
  cp .env.example .env.local
fi
nano .env.local
```

把示例 Key / Token 改成自己的值。初次只验证部署时可使用：

```dotenv
VITE_BASEMAP_PROVIDER=cesium
VITE_TIANDITU_KEY=ad49b32759d744369dbb6b0a1eaf6ac2
VITE_CESIUM_ION_TOKEN=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJub25jZSI6IjhLaEU5RkFEc3ljaXIyVVAiLCJqdGkiOiI0YmNkNGQ0OS0yYzNlLTRhODctYjJlMi1kYTZiZGEwZTJkNzciLCJpZCI6NTMyMjYwLCJzdWIiOiJsbnBicWMiLCJpc3MiOiJodHRwczovL2FwaS5jZXNpdW0uY29tIiwiYXVkIjoibGludXgtc2VydmVyIiwiaWF0IjoxNzk1MTU2OTgxfQ.WPOGf863SNDzxVuYpJHtkbscj936Gp7Rk_fvIAh9fYs
```

**以上token、key并不保证一定可用，需自行申请。**

此配置使用本地低分辨率底图和椭球地表。使用天地图则设置 `VITE_BASEMAP_PROVIDER=tianditu`，填写 `VITE_TIANDITU_KEY`，并在天地图控制台配置实际访问域名；使用 Cesium 在线资源则填写浏览器只读 Token。变量说明见 [现有部署说明](部署说明.md#首次启动)。这些值会进入浏览器构建产物，服务端内部令牌不放在这里。

```bash
pnpm build
test -s "$CITY_REPO/map/dist/index.html"
test -d "$CITY_REPO/map/dist/cesium/Workers"
test -d "$CITY_REPO/map/dist/cesium/Assets"
```

预期构建成功，三个文件检查通过。生产网页由 Caddy 直接提供，无需启动 Vite 开发或 preview 服务。修改 `.env.local` 后重新构建才生效。

### 6.2 首次前台检查

**第一个服务器终端：沿用第 5 节的环境，启动切片服务。**

```bash
cd "$CITY_REPO"
CITY_TILE_HOST=127.0.0.1 CITY_TILE_PORT=18744 bash tile_service/start.sh
```

**第二个服务器终端：先执行第 3.3 节的四行恢复命令，再启动后端。**

```bash
cd "$CITY_REPO/map_back"
unset MAP_DATABASE_URL CITY_TILE_SERVICE_URL CITY_TILE_TOKEN CITY_TILE_BACKEND_ORIGIN
MAP_STORAGE_DIR="$CITY_REPO/map_back/storage" \
  python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 1
```

**第三个服务器终端：检查结果。**

```bash
curl -fsS http://127.0.0.1:8000/api/health
curl -fsS http://127.0.0.1:18744/health
```

后端返回 `status: ok`；切片服务返回 `status: ok`、`worker_alive: true`、`tool_version: 2.79.0`。检查通过后，在前两个终端分别按 `Ctrl+C`，再配置后台服务，避免端口冲突。

## 完成准备后，选择一条部署路线

前六节的健康检查通过，并已停止两个前台服务后继续：

| 运行环境 | 后续文档 |
| --- | --- |
| PID 1 为 systemd 的服务器 | [systemd 部署路线，第 7～13 节](Linux-systemd部署.md) |
| Docker 或其他非 systemd 环境 | [Docker／非 systemd 部署路线，第 7～14 节](Linux非systemd部署.md) |

两份路线文档均包含各自完整的域名、HTTPS、网络配置、维护、备份恢复和验收命令。选择后无需返回本文查步骤。
