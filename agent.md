# MoviePilot 下载添加通知插件接手说明

## 当前任务

继续维护 `moviepilot-download-added-notify` 插件，重点处理 MoviePilot/qBittorrent 下载添加通知里的标题、名称、集数、电影识别和推送速度问题。

插件目标：

- qBittorrent 手动添加任务后，MoviePilot 能尽快发送下载添加通知。
- 通知标题和名称优先显示中文名，有中文时不显示英文。
- 电影和电视剧使用一致的精简通知格式。
- 剧集集数严格从可靠来源提取，避免目录、路径或无关文件污染出错误集数。
- qB 任务名不完整时，优先用 qB 文件列表或内容路径里的完整文件名解析。
- 尽量调用 MoviePilot 自身 `MetaInfo` / `MediaChain` 解析能力，不修改 MoviePilot 内部文件。

## 仓库信息

- 本地仓库：`/Users/jardy/Documents/Codex/2026-05-16/moviepilot-qb/moviepilot-download-added-notify`
- GitHub：`git@github.com:jardy129/moviepilot-download-added-notify.git`
- 主分支：`main`
- 当前最新版本：`0.3.8`
- 最新提交：以 `git log -1 --oneline` 为准

主要文件：

- `plugins.v2/downloadaddednotify/__init__.py`
- `plugins/downloadaddednotify/__init__.py`
- `package.json`
- `package.v2.json`

注意：`plugins.v2/...` 和 `plugins/...` 两份插件代码需要保持同步。

## 重要约束

- 不要修改 MoviePilot 容器内部源码，只能读取日志、查看接口、运行解析验证。
- 代码只改本插件仓库。
- 不要把 SSH、qB、MoviePilot 密码写进仓库文件。
- 每次推送前至少运行：

```bash
python3 -m py_compile plugins.v2/downloadaddednotify/__init__.py plugins/downloadaddednotify/__init__.py
python3 -m json.tool package.json
python3 -m json.tool package.v2.json
git diff --check
```

## 已确认的问题根因

MoviePilot 日志里看到，qB 传给插件的 `%N` 经常不是完整种子名，而是短任务名，例如：

- `2022 V2 坠落 3D`
- `封神2 Creation of the Gods 2_3D`

这些短名缺少年份、分辨率、音频、发布组等信息，导致 MoviePilot 的 `MetaInfo` 也只能按残缺标题解析。

因此插件不能只信任 qB payload 的 `name`，需要按优先级选择解析源：

1. qB 文件列表中的完整视频文件名。
2. qB 文件列表中原盘目录的上层完整目录名，例如 `.../BDMV/STREAM/00000.m2ts` 的上层发布名。
3. `content_path` 或 `save_path` 中的文件名/目录名。
4. qB 传入的短任务名。

## 当前 0.3.8 的关键逻辑

新增/调整的关键方法：

- `_qb_torrent_file_names_for_parse`
- `_needs_qb_file_parse_source`
- `_best_parse_title`
- `_path_parse_title`
- `_parse_title_score`
- `_moviepilot_parse`
- `_best_media_title`
- `_simple_cjk_title`
- `_compact_name_with_moviepilot`
- `_select_episode`

核心策略：

- qB 任务名不完整时，主动调用 qB Web API 获取文件列表。
- qB hash 取文件列表失败时，会按任务名反查 qB 当前任务 hash 再取文件列表。
- 短中文片名无法识别年份时，会尝试别名识别，例如 `封神2` -> `封神第二部`，但展示仍保留用户看到的短中文名。
- 标题只有季信息时，即使 `content_path` 里出现单集号，也优先查询 qB 文件列表合并多文件集数区间。
- 如果季包标题只有 `S01` 且 qB 文件列表不可用，不再用 `content_path` 的单集号兜底，避免误报 `S01E07`。
- 同一场景下也不能把 `content_path` 传给标题选择或 MoviePilot `MetaInfoPath`，否则仍会从路径解析出单集。
- 原始种子名如果已经包含完整发布信息，尤其是 `S01E07-E09` 这种集数范围，标题选择阶段必须保留原始种子名，不能被路径或单个文件覆盖。
- 季包原始种子名如果已经带年份和清晰度，也保留原始种子名，qB 文件列表只用于补 `S01E07-E09` 这类范围。
- 文件列表中如果是原盘结构，忽略 `00000.m2ts` 这种无意义文件名，取上层发布目录名。
- 解析标题优先用完整文件名，但展示标题继续优先中文短名。
- 标题里已经明确有 `S01E07-E09` 时，严格以标题为准，不能被其他文件里的 `E10` 污染。
- 标题只有 `S01` 时，才从 qB 文件列表补 `E01`、`E01-E03` 等集数。

## 现场验证过的样例

期望输出：

```text
原 qB 短名：2022 V2 坠落 3D
完整文件名：Free，Fall 2022 V2 1080p 3D Blu-ray AVC DTS-HD MA 5.1-DIY@HDSky
标题：坠落 (2022) 开始下载
名称：坠落 | 1080p | DTS-HD MA 5.1 | HDSky
```

```text
原 qB 短名：封神2 Creation of the Gods 2_3D
完整文件名：Creation of the Gods 2 Demon Force 2025 1080p 3D Blu-ray AVC Atmos TrueHD 7.1-DIY@HDSky
标题：封神2 (2025) 开始下载
名称：封神2 | 1080p | Atmos TrueHD 7.1 | HDSky
```

```text
原始标题：天龙八部.Eightfold Path of the Heavenly Dragon S01E07-E09 1997 2160p WEB-DL AAC H265 2Audio-Pure@HDSWEB
即使其他来源包含 E10，也必须输出：
标题：天龙八部 (1997) S01E07-E09 开始下载
```

```text
原始标题：主角.The.Lead.S01.2026.2160p.WEB-DL.DDP5.1.H265-Pure@HDSWEB
文件名：主角.The.Lead.S01E14.2026.2160p.WEB-DL.DDP5.1.H265-Pure@HDSWEB.mkv
标题：主角 (2026) S01E14 开始下载
名称：主角 | 2160p | DDP5.1 | H265-Pure | HDSWEB
```

## MoviePilot 现场排查

可读取 MoviePilot 日志确认插件版本和通知内容：

```bash
sudo docker logs --since 2h moviepilot-v2 2>&1 | grep -E "DownloadAddedNotify|下载添加通知|发送消息|qBittorrent|MetaInfo|MediaChain|解析|通知"
```

确认插件加载版本：

```bash
sudo docker logs --since 2h moviepilot-v2 2>&1 | grep "加载插件：DownloadAddedNotify"
```

使用 MoviePilot 环境验证 `MetaInfo`：

```bash
sudo docker exec moviepilot-v2 sh -lc '/opt/venv/bin/python - << "PY"
from app.core.metainfo import MetaInfo
sample = "Free，Fall 2022 V2 1080p 3D Blu-ray AVC DTS-HD MA 5.1-DIY@HDSky.mkv"
meta = MetaInfo(sample)
print(meta.name, meta.year, meta.resource_pix, meta.audio_term, meta.release_group)
PY'
```

查看插件运行时配置和 qB 文件列表时，使用 MoviePilot 虚拟环境里的 Python：

```bash
sudo docker exec moviepilot-v2 sh -lc '/opt/venv/bin/python - << "PY"
from app.plugins.downloadaddednotify import DownloadAddedNotify
p = DownloadAddedNotify()
p.init_plugin(p.get_config() or {})
print(p.plugin_version)
print(p._qb_web_url)
PY'
```

## 排查重点

如果用户反馈“标题/名称还是不对”，先看日志里的实际输入：

- 通知标题是什么。
- 通知文本里的 `📛 名称` 是什么。
- 插件日志是否出现：`qBittorrent 任务名不完整，改用文件名解析：原任务名 -> 实际解析名`。
- qB 文件列表是否能取到完整文件名。

如果 qB 文件列表取不到：

- 检查插件详情页里的 qB Web 地址、用户名、密码。
- 检查 MoviePilot 容器到 qB Web API 是否可达。
- 注意 qB API 文件列表接口是 `/api/v2/torrents/files?hash=...`。

## 版本发布习惯

每次功能修复：

1. 同步修改 `plugins.v2/downloadaddednotify/__init__.py` 和 `plugins/downloadaddednotify/__init__.py`。
2. 更新 `plugin_version`。
3. 更新 `package.json` 和 `package.v2.json` 里的 `version` 与 `history`。
4. 运行校验。
5. commit。
6. push 到 `main`。

推荐提交信息示例：

```bash
git commit -m "Use qB file names for short movie titles"
```
