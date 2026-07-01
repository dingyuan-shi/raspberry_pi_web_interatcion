# raspberry_pi_web_interaction

在局域网里用浏览器监控和操作树莓派。作为raspberry connect / teamviewer / vnc的平替。一个轻量 **FastAPI** 服务，无需公网、无需手机 App。

## 它能做什么

### 1. 局域网监控

打开首页即可看到实时仪表盘，Chart.js 折线图 + SSE 推送，适合电脑和现代浏览器。

- **默认面板**：CPU、内存、温度、网络、磁盘、Top 进程
- **可自定义**：登录后点击「管理面板」，可添加 / 编辑 / 删除 / 复制 / 拖动排序
- **统一模型**：每个面板 = **提炼方式** + **后台命令** + **展示方式**
  - **内置**：`cpu`、`memory`、`temp`、`network`、`disks`、`procs`（由服务端采集）
  - **Shell**：任意 shell 命令，服务端定期后台执行，再用「提取首个数字 / 正则 / 全文」提炼结果
  - **展示**：折线图、纯文本、磁盘条、进程表

配置保存在 `{DATA_DIR}/monitor_panels.json`（默认 `/opt/pi-remote/data/`，安装时不会被覆盖）。

```
http://<树莓派IP>:8080/
```

![监控仪表盘](docs/screenshots/watch.png)

### 2. 快捷命令与 Shell（可扩展）

点击右上角 **Deploy** 输入密码后解锁：

- **命令**：文本协议（`status`、`gpio:17:toggle`、`shell:vcgencmd measure_temp` 等），方便脚本和二次开发
- **交互终端**：xterm.js + WebSocket PTY，体验接近 SSH
- **自定义按钮**：命令页「管理」可添加固定命令或带 `${参数}` 的模板，支持拖动排序、复制、最近使用记录

协议集中在 `pi_remote_core/commands.py`，新增命令只需改一处。按钮配置保存在 `{DATA_DIR}/command_buttons.json`。

![快捷命令](docs/screenshots/cmd.png)

![交互式终端](docs/screenshots/shell.png)

💡 **上面两个功能实现了web端的输入和输出，配合其他硬件拓展模块，可以自行搭建更多的监控和命令。**

### 3. Lite / Cheap — 廉价设备也能看

| 路由 | 适合 | 说明 |
|------|------|------|
| `/lite` | 电脑 / 老浏览器 | HTML + SVG 矢量图，折线清晰 |
| `/cheap` | Kindle、极老设备 | 自动刷新的 PNG（默认 Paperwhite 5：1236×1648） |

两者共用 `web_pi_control/kindle_html.py` 一套模板；改这个文件，`/lite` 和 `/cheap` 同步更新。

```
http://<树莓派IP>:8080/lite     # 廉价监控（SVG）
http://<树莓派IP>:8080/cheap    # Kindle 上用（PNG）
```

![Lite 廉价监控](docs/screenshots/lite.png)

`/cheap` 需要 `chromium`（Bookworm 上包名为 `chromium`；`install.sh` 会尝试安装）。诊断：

```bash
curl http://<pi>:8080/api/kindle/status
```

---

## 快速开始

**系统要求：** Raspberry Pi OS **Bookworm**（或更新版本），Python **3.11+**。

```bash
git clone https://github.com/dingyuan-shi/raspberry_pi_web_interaction.git
cd raspberry_pi_web_interaction
sudo ./install.sh

# 安装后务必修改默认密码
sudoedit /etc/default/web-pi-control
sudo systemctl restart web-pi-control
```

浏览器访问 `http://<树莓派IP>:8080`。

安装时 pip 默认走清华镜像，并**禁用**树莓派系统自带的 `piwheels.org`（国内访问很慢）。若你在英国/欧洲且想用 piwheels 预编译包：

```bash
sudo USE_PIWHEELS=1 ./install.sh
```

自定义镜像：`sudo PIP_INDEX_URL=https://pypi.org/simple ./install.sh`

卸载：`sudo ./uninstall.sh`

---

## 路由一览

```
/                       监控仪表盘（公开）
/lite                   SVG 精简监控页
/cheap                  PNG 监控页（Kindle）
/api/cheap.png          cheap 图源
/api/status             状态 JSON
/api/status/stream      状态 SSE
/api/monitor            详细监控（?history=N，含 panels 自定义面板数据）
/api/monitor/stream     监控 SSE
GET  /api/monitor-panels   监控面板配置（公开）
PUT  /api/monitor-panels   保存面板配置（需登录）
GET  /api/command-buttons  命令按钮配置（需登录）
PUT  /api/command-buttons  保存命令按钮（需登录）
POST /login             Deploy 登录
POST /api/command       执行命令（需登录）
WS   /api/shell         交互终端（需登录）
```

---

## 自定义监控面板

登录后，监控页右上角 **管理面板**：

| 字段 | 说明 |
|------|------|
| 提炼方式 | `builtin`（内置指标）或 `shell`（后台 shell） |
| 命令 | 内置键名，或 shell 命令（如 `vcgencmd measure_temp`） |
| 结果提炼 | Shell 专用：`float`（首个数字）、`regex`（正则捕获组 1）、`text`（全文） |
| 展示方式 | `chart` 折线图、`text` 文本、`disks` 磁盘条、`table` 进程表 |

**Shell 面板示例**（GPU 温度）：

| 标题 | 提炼方式 | 命令 | 结果提炼 | 正则 | 展示 |
|------|----------|------|----------|------|------|
| GPU 温度 | shell | `vcgencmd measure_temp` | regex | `temp=([\d.]+)` | chart（单位 °C） |

**内置面板示例**：

| 命令键 | 展示 | 说明 |
|--------|------|------|
| `cpu` | chart | CPU 占用 %，附 load / 各核占用 |
| `memory` | chart | 内存占用 %，附 swap |
| `temp` | chart | CPU 温度（sysfs / vcgencmd） |
| `network` | chart | 网络吞吐 KB/s |
| `disks` | disks | 各分区使用率条 |
| `procs` | table | Top 进程表 |

拖动左侧 `≡` 可调整面板顺序；「复制」可快速基于现有面板新建。

---

## 自定义命令按钮

登录后，命令页 **管理**：

- **命令**：固定内容，点击即执行
- **命令模板**：命令中含 `${参数名}`，每次执行前弹窗填参；最近 10 次可「存为命令」
- 支持拖动排序、复制、危险操作确认

---

## 命令示例

| 命令 | 说明 |
|------|------|
| `help` | 列出命令 |
| `status` | 系统快照 |
| `gpio:<pin>:on\|off\|toggle\|read` | GPIO（白名单引脚） |
| `shell:<cmd>` | 执行 shell |
| `reboot` / `shutdown` | 重启 / 关机 |

```bash
curl -c jar.txt -d 'password=你的密码' http://<pi>:8080/login
curl -b jar.txt -H 'Content-Type: application/json' \
     -d '{"command":"shell:uptime"}' http://<pi>:8080/api/command
```

---

## 配置

文件：`/etc/default/web-pi-control`

| 变量 | 默认 | 说明 |
|------|------|------|
| `WEB_PASSWORD` | `changeme` | **部署后必改** |
| `WEB_SESSION_SECRET` | 安装时随机 | Cookie 签名密钥 |
| `WEB_HOST` | `0.0.0.0` | 监听地址 |
| `WEB_PORT` | `8080` | 端口 |
| `WEB_SESSION_HOURS` | `12` | 会话有效期 |
| `PI_REMOTE_GPIO_PINS` | `17,18,22,...` | GPIO 白名单 |
| `STATUS_INTERVAL` | `5` | SSE 间隔（秒） |
| `PI_REMOTE_DATA_DIR` | `/opt/pi-remote/data` | 持久化数据目录（面板、按钮 JSON） |

持久化文件（安装升级时 `install.sh` 会保留 `data/` 目录）：

| 文件 | 内容 |
|------|------|
| `command_buttons.json` | 快捷命令 / 模板 / 最近使用 |
| `monitor_panels.json` | 监控面板布局与提炼配置 |

---

## Cheap 分辨率

```
/cheap                              # 默认 1236×1648（Paperwhite 5）
/cheap?w=1072&h=1448               # Paperwhite 4
/cheap?refresh=120                  # 刷新间隔（秒）
```

---

## 项目结构

```
raspberry_pi_web_interaction/
├── docs/screenshots/        # README 截图（watch / lite / cmd / shell）
├── pi_remote_core/          # 命令协议、系统信息采集、配置
│   ├── command_buttons.py   # 命令按钮持久化
│   ├── monitor_panels.py    # 监控面板持久化
│   └── panel_extractors.py  # 面板数据提炼（builtin + shell）
├── web_pi_control/          # FastAPI + 前端静态文件
│   ├── kindle_html.py       # lite / cheap 共用仪表盘模板
│   └── static/              # 主页 index.html / app.js / style.css
├── systemd/                 # systemd 单元与默认环境变量
├── install.sh
└── requirements.txt
```

---

## 安全说明

- 仓库内**不包含**任何真实密码或 API Key；默认值仅为 `changeme` 占位符
- `install.sh` 首次安装会生成随机 `WEB_SESSION_SECRET`
- 服务设计为**局域网使用**；若暴露到公网，请改强密码并加反向代理 + TLS
- 监控页公开，命令与终端需 Deploy 登录

---

## License

MIT — 见 [LICENSE](LICENSE)。
