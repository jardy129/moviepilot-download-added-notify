# MoviePilot 手动添加通知插件

这个插件用于监听 MoviePilot 的 `DownloadAdded` 事件，并调用 MoviePilot 自带的系统通知能力发送一条“已添加下载”的通知。

适用场景：

- 在 MoviePilot 页面手动添加种子后，希望强制走系统通知。
- 想把通知继续交给 MoviePilot 的通知渠道处理，例如企业微信、Telegram、微信、Slack 等。
- 不想在 qBittorrent 脚本里硬编码企业微信 webhook。

不适用场景：

- 直接在 qBittorrent 里添加种子。这种不会经过 MoviePilot 的 `DownloadAdded` 事件，需要用 qB 外部程序脚本。

## 安装

把插件目录复制到 MoviePilot 的插件目录：

```bash
cp -r plugins.v2/downloadaddednotify /path/to/MoviePilot/app/plugins/
```

Docker 部署时，一般需要复制到 MoviePilot 容器内的插件目录，或复制到你映射出来的插件目录。复制后重启 MoviePilot，进入插件页面启用“下载添加通知”。

## 配置

插件配置项：

- `启用插件`：开启后才会监听下载添加事件。
- `通知类型`：默认使用 `资源下载`，需要在 MoviePilot 通知渠道里勾选对应通知类型。
- `标题前缀`：通知标题前缀，默认 `[下载已添加]`。
- `只通知指定下载器`：可选，例如填 `qbittorrent`，为空则不限制。
- `附加原始事件摘要`：调试用，开启后会把事件里能识别到的字段追加到通知文本。
- `启用 qBittorrent 外部程序通知接口`：允许 qBittorrent 脚本主动调用插件接口。
- `qBittorrent 外部程序通知 Token`：脚本调用插件接口时使用，留空保存后会自动生成。
- `MoviePilot 地址`：qBittorrent 容器或主机访问 MoviePilot 的地址。
- `qBittorrent 下载器名称`：通知正文里显示的下载器名称。
- `推送头图 URL`：可选，填写图片直链后会作为通知头图推送；留空则不带头图。
- `自动给 qBittorrent 任务打标签`：开启后，插件收到 qB 通知会用 Info Hash 给任务添加标签。
- `qBittorrent Web 地址` / `用户名` / `密码`：用于调用 qB Web API 添加标签。
- `自动标签名称`：默认 `MOVIEPILOT`。
- `qBittorrent 添加种子时运行外部程序`：保存配置后自动生成，可直接复制到 qBittorrent。
- `qBittorrent 完成下载时运行外部程序`：保存配置后自动生成，可直接复制到 qBittorrent。

## 企业微信

在 MoviePilot 的通知设置里配置企业微信机器人，并勾选 `资源下载` 通知类型。插件会调用 MoviePilot 系统通知，不需要在插件里填写 webhook。

## qBittorrent 手动添加通知

如果种子是在 qBittorrent 里手动添加的，MoviePilot 不会触发 `DownloadAdded` 事件。可以改用 qBittorrent 的“运行外部程序”能力主动通知 MoviePilot。

1. 更新并启用插件后，保存一次插件配置，复制配置页里的 `qBittorrent 外部程序通知 Token`。
2. 填写 `MoviePilot 地址` 和 `qBittorrent 下载器名称` 后保存。
3. 复制插件配置页自动生成的 `qBittorrent 添加种子时运行外部程序`，填到 qBittorrent 对应设置里。
4. 如果也想在完成时通知，复制 `qBittorrent 完成下载时运行外部程序`，填到完成下载时运行外部程序里。

脚本会请求 MoviePilot 插件接口：

```text
/api/v1/plugin/DownloadAddedNotify/qbittorrent?token=插件配置页里的通知Token
```
