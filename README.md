# MoviePilot 下载添加通知插件

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

## 企业微信

在 MoviePilot 的通知设置里配置企业微信机器人，并勾选 `资源下载` 通知类型。插件会调用 MoviePilot 系统通知，不需要在插件里填写 webhook。

