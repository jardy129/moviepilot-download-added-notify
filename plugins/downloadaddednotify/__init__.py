import re
import secrets
from datetime import datetime
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from app.plugins import _PluginBase

try:
    from fastapi import HTTPException, Request
except Exception:
    HTTPException = None
    Request = Any

try:
    from app.core.event import eventmanager
    from app.schemas.types import EventType
except Exception:
    eventmanager = None
    EventType = None

try:
    from app.log import logger
except Exception:
    class _FallbackLogger:
        @staticmethod
        def info(*args, **kwargs):
            pass

        @staticmethod
        def warn(*args, **kwargs):
            pass

        @staticmethod
        def error(*args, **kwargs):
            pass

    logger = _FallbackLogger()


def _register_event(event_type: Any):
    if eventmanager is None or event_type is None:
        return lambda func: func
    return eventmanager.register(event_type)


class DownloadAddedNotify(_PluginBase):
    plugin_name = "下载添加通知"
    plugin_desc = "监听下载添加事件，并通过 MoviePilot 系统通知发送消息"
    plugin_icon = "https://raw.githubusercontent.com/jardy129/moviepilot-download-added-notify/main/icons/qbittorrent.png"
    plugin_version = "0.1.1"
    plugin_author = "jardy"
    author_url = ""
    plugin_config_prefix = "downloadaddednotify_"
    plugin_order = 66
    auth_level = 0

    _enabled = False
    _notify_type = "Download"
    _notify_stage = "download_added"
    _title_prefix = "[下载已添加]"
    _complete_title_prefix = "[下载已完成]"
    _only_downloader = ""
    _include_raw_summary = False
    _qb_poll_enabled = True
    _qb_poll_interval = 60
    _qb_seen_hashes_key = "qb_seen_hashes"
    _external_notify_enabled = True
    _external_notify_token = ""
    _moviepilot_base_url = "http://moviepilot:3001"
    _qb_downloader_name = "Qbittorrent"
    _header_image_url = ""
    _label_icons = {
        "时间": "🕒",
        "媒体": "🎬",
        "类别": "🎭",
        "分类": "🎭",
        "站点": "🌐",
        "质量": "🌟",
        "大小": "💾",
        "做种": "🌱",
        "标签": "🏷",
        "名称": "📛",
        "下载器": "⬇️",
        "目录": "📁",
        "状态": "📌",
        "事件": "🔔",
    }

    def init_plugin(self, config: Optional[dict] = None):
        if not config:
            return

        self._enabled = bool(config.get("enabled"))
        self._notify_type = config.get("notify_type") or "Download"
        self._notify_stage = config.get("notify_stage") or "download_added"
        self._title_prefix = config.get("title_prefix") or "[下载已添加]"
        self._complete_title_prefix = config.get("complete_title_prefix") or "[下载已完成]"
        self._only_downloader = (config.get("only_downloader") or "").strip()
        self._include_raw_summary = bool(config.get("include_raw_summary"))
        self._qb_poll_enabled = bool(config.get("qb_poll_enabled", True))
        self._qb_poll_interval = self._safe_int(config.get("qb_poll_interval"), 60, 15)
        self._external_notify_enabled = bool(config.get("external_notify_enabled", True))
        self._external_notify_token = (config.get("external_notify_token") or "").strip()
        self._moviepilot_base_url = (config.get("moviepilot_base_url") or "http://moviepilot:3001").strip()
        self._qb_downloader_name = (config.get("qb_downloader_name") or "Qbittorrent").strip()
        self._header_image_url = (config.get("header_image_url") or "").strip()
        if not self._external_notify_token:
            self._external_notify_token = secrets.token_urlsafe(24)
            config["external_notify_token"] = self._external_notify_token
        config["qb_added_command"] = self._build_qb_command("added")
        config["qb_completed_command"] = self._build_qb_command("completed")
        if not config.get("moviepilot_base_url"):
            config["moviepilot_base_url"] = self._moviepilot_base_url
        if not config.get("qb_downloader_name"):
            config["qb_downloader_name"] = self._qb_downloader_name
        if config.get("external_notify_token") != self._external_notify_token:
            config["external_notify_token"] = self._external_notify_token
        saved_config = self.get_config() or {}
        if (
            not saved_config
            or config.get("external_notify_token") != saved_config.get("external_notify_token")
            or config.get("moviepilot_base_url") != saved_config.get("moviepilot_base_url")
            or config.get("qb_downloader_name") != saved_config.get("qb_downloader_name")
            or config.get("qb_added_command") != saved_config.get("qb_added_command")
            or config.get("qb_completed_command") != saved_config.get("qb_completed_command")
        ):
            self.update_config(config)

    def get_state(self) -> bool:
        return self._enabled

    @_register_event(getattr(EventType, "DownloadAdded", None) if EventType else None)
    def download_added(self, event):
        if not self._enabled or self._notify_stage not in ("download_added", "both"):
            return

        event_data = event.event_data or {}
        data = self._to_dict(event_data)
        context = data.get("context")

        downloader = self._first_value(
            data,
            "downloader",
            "download_client",
            "downloadclient",
            "client",
        )
        if self._only_downloader and downloader:
            if self._only_downloader.lower() not in str(downloader).lower():
                return

        media_info = self._get_context_value(context, "media_info")
        torrent_info = self._get_context_value(context, "torrent_info")
        meta_info = self._get_context_value(context, "meta_info")
        media_data = self._to_dict(media_info)
        torrent_data = self._to_dict(torrent_info)
        meta_data = self._to_dict(meta_info)

        title = (
            self._first_value(torrent_data, "title")
            or self._media_title(media_info)
            or self._first_value(meta_data, "org_string", "title", "cn_name", "en_name")
            or "未知任务"
        )
        site = self._first_value(torrent_data, "site_name", "site")
        save_path = self._first_value(data, "save_path", "savepath", "path", "download_path")
        category = (
            self._first_value(torrent_data, "category")
            or self._first_value(media_data, "category", "type")
        )
        tags = self._first_value(data, "tags", "tag")
        size = self._format_size_gb(self._first_raw_value(torrent_data, "size"))
        quality = self._first_value(torrent_data, "quality", "resolution") or self._extract_quality(title)
        seeders = self._format_seed_count(self._first_raw_value(torrent_data, "seeders", "seeds", "num_seeds"))
        media_title = self._media_title(media_info)
        year = self._first_value(media_data, "year") or self._first_value(meta_data, "year")
        episode = self._extract_episode(title, torrent_data, meta_data, media_data, data)

        media_text = media_title
        if media_text and year:
            media_text = f"{media_text} ({year})"
        display_title = self._display_title(title, media_text, year, "开始下载", episode)
        compact_name = self._compact_name(title)
        lines = self._message_lines(
            ("时间", self._now_text()),
            ("媒体", media_text),
            ("站点", site),
            ("质量", quality),
            ("大小", size),
            ("做种", seeders),
            ("类别", category),
            ("标签", tags),
            ("名称", compact_name),
            ("下载器", downloader),
            ("目录", save_path),
        )
        if self._include_raw_summary:
            lines.append("")
            lines.append("事件字段：")
            for key, value in sorted(data.items()):
                if value is None or isinstance(value, (dict, list, tuple, set)):
                    continue
                lines.append(f"- {key}: {value}")

        try:
            self._post_notification(
                title=display_title,
                text="\n".join(lines),
            )
            logger.info(f"{self.plugin_name}: 已发送下载添加通知 - {title}")
        except TypeError:
            self._post_notification(
                title=display_title,
                text="\n".join(lines),
            )
            logger.info(f"{self.plugin_name}: 已发送下载添加通知 - {title}")
        except Exception as err:
            logger.error(f"{self.plugin_name}: 发送下载添加通知失败 - {err}", exc_info=True)

    @_register_event(getattr(EventType, "TransferComplete", None) if EventType else None)
    def transfer_complete(self, event):
        if not self._enabled or self._notify_stage not in ("transfer_complete", "both"):
            return

        event_data = event.event_data or {}
        data = self._to_dict(event_data)
        downloader = self._first_value(data, "downloader")
        if self._only_downloader and downloader:
            if self._only_downloader.lower() not in str(downloader).lower():
                return

        fileitem = data.get("fileitem")
        meta_info = data.get("meta")
        media_info = data.get("mediainfo")
        transferinfo = data.get("transferinfo")

        title = (
            self._media_title(media_info)
            or self._first_value(self._to_dict(meta_info), "org_string", "title", "cn_name", "en_name")
            or self._first_value(self._to_dict(fileitem), "name", "path")
            or "未知任务"
        )
        source_path = self._first_value(self._to_dict(fileitem), "path", "name")
        transfer_data = self._to_dict(transferinfo)
        target_path = (
            self._first_value(self._to_dict(transfer_data.get("target_item")), "path", "name")
            or self._first_value(transfer_data, "target_path", "target_dir", "file_path")
        )

        lines = self._message_lines(
            ("时间", self._now_text()),
            ("名称", self._compact_name(title)),
            ("下载器", downloader),
            ("源文件", source_path),
            ("入库位置", target_path),
        )
        if self._include_raw_summary:
            lines.append("")
            lines.append("事件字段：")
            for key, value in sorted(data.items()):
                if value is None or isinstance(value, (dict, list, tuple, set)):
                    continue
                lines.append(f"- {key}: {value}")

        try:
            self._post_notification(
                title=self._display_title(title, event_text="下载完成"),
                text="\n".join(lines),
            )
            logger.info(f"{self.plugin_name}: 已发送下载完成通知 - {title}")
        except TypeError:
            self._post_notification(
                title=self._display_title(title, event_text="下载完成"),
                text="\n".join(lines),
            )
            logger.info(f"{self.plugin_name}: 已发送下载完成通知 - {title}")
        except Exception as err:
            logger.error(f"{self.plugin_name}: 发送下载完成通知失败 - {err}", exc_info=True)

    def poll_qb_torrents(self):
        if not self._enabled or not self._qb_poll_enabled:
            return

        try:
            from app.modules.qbittorrent import QbittorrentModule

            qb_module = QbittorrentModule()
            qb_module.init_module()
            instances = qb_module.get_instances()
        except Exception as err:
            logger.error(f"{self.plugin_name}: 初始化 Qbittorrent 下载器失败 - {err}", exc_info=True)
            return

        if not instances:
            logger.warn(f"{self.plugin_name}: 未找到已启用的 Qbittorrent 下载器配置")
            return

        previous_hashes = set(self.get_data(self._qb_seen_hashes_key) or [])
        current_hashes = set()
        new_torrents = []

        for downloader, server in instances.items():
            if self._only_downloader and self._only_downloader.lower() not in str(downloader).lower():
                continue
            try:
                if server.is_inactive():
                    server.reconnect()
                torrents, error = server.get_torrents()
            except Exception as err:
                logger.error(f"{self.plugin_name}: 查询 Qbittorrent 任务失败 - {downloader}: {err}", exc_info=True)
                continue
            if error:
                logger.error(f"{self.plugin_name}: 查询 Qbittorrent 任务失败 - {downloader}")
                continue

            for torrent in torrents or []:
                torrent_data = self._to_dict(torrent)
                torrent_hash = self._first_value(torrent_data, "hash")
                if not torrent_hash:
                    continue
                torrent_key = f"{downloader}:{torrent_hash}"
                current_hashes.add(torrent_key)
                if previous_hashes and torrent_key not in previous_hashes:
                    new_torrents.append((downloader, torrent_data))

        if not previous_hashes:
            self.save_data(self._qb_seen_hashes_key, sorted(current_hashes))
            logger.info(f"{self.plugin_name}: 已建立 Qbittorrent 任务基线，共 {len(current_hashes)} 个任务")
            return

        for downloader, torrent_data in new_torrents:
            self._notify_qb_torrent_added(downloader, torrent_data)

        if current_hashes != previous_hashes:
            self.save_data(self._qb_seen_hashes_key, sorted(current_hashes))

    def _notify_qb_torrent_added(self, downloader: str, torrent_data: Dict[str, Any]):
        title = self._first_value(torrent_data, "name", "title") or "未知任务"
        save_path = self._first_value(torrent_data, "save_path", "content_path")
        category = self._first_value(torrent_data, "category")
        tags = self._first_value(torrent_data, "tags")
        state = self._first_value(torrent_data, "state")
        site = self._format_site(self._first_value(torrent_data, "tracker", "tracker_host", "site", "site_name"))
        size = self._format_size_gb(self._first_raw_value(torrent_data, "total_size", "size"))
        quality = self._first_value(torrent_data, "quality", "resolution") or self._extract_quality(title)
        seeders = self._format_seed_count(self._first_raw_value(torrent_data, "num_seeds", "seeders", "seeds"))
        display_title = self._display_title(
            title,
            event_text="开始下载",
            episode=self._extract_episode(title, torrent_data),
        )

        lines = self._message_lines(
            ("时间", self._now_text()),
            ("站点", site),
            ("状态", self._format_qb_state(state)),
            ("质量", quality),
            ("大小", size),
            ("做种", seeders),
            ("类别", category),
            ("标签", tags),
            ("名称", self._compact_name(title)),
            ("下载器", downloader),
            ("目录", save_path),
        )
        if self._include_raw_summary:
            lines.append("")
            lines.append("事件字段：")
            for key, value in sorted(torrent_data.items()):
                if value is None or isinstance(value, (dict, list, tuple, set)):
                    continue
                lines.append(f"- {key}: {value}")

        try:
            self._post_notification(
                title=display_title,
                text="\n".join(lines),
            )
            logger.info(f"{self.plugin_name}: 已发送 Qbittorrent 新任务通知 - {title}")
        except TypeError:
            self._post_notification(
                title=display_title,
                text="\n".join(lines),
            )
            logger.info(f"{self.plugin_name}: 已发送 Qbittorrent 新任务通知 - {title}")
        except Exception as err:
            logger.error(f"{self.plugin_name}: 发送 Qbittorrent 新任务通知失败 - {err}", exc_info=True)

    async def qbittorrent_notify(self, request: Request) -> Dict[str, Any]:
        payload = await self._request_payload(request)
        if not self._external_notify_enabled:
            self._raise_http_error(403, "external notify is disabled")
        notify_token = self._first_value(payload, "token", "notify_token")
        if not self._external_notify_token or not notify_token:
            self._raise_http_error(401, "missing notify token")
        if not secrets.compare_digest(str(notify_token), self._external_notify_token):
            self._raise_http_error(401, "invalid notify token")

        event = self._first_value(payload, "event", "action") or "added"
        title = self._first_value(payload, "name", "title") or "未知任务"
        downloader = self._first_value(payload, "downloader") or "Qbittorrent"
        save_path = self._first_value(payload, "save_path", "path", "content_path")
        category = self._first_value(payload, "category")
        tags = self._first_value(payload, "tags")
        state = self._first_value(payload, "state")
        site = self._format_site(self._first_value(payload, "tracker", "site", "site_name"))
        size = self._format_size_gb(self._first_raw_value(payload, "size", "total_size"))
        quality = self._first_value(payload, "quality", "resolution") or self._extract_quality(title)
        seeders = self._format_seed_count(self._first_raw_value(payload, "num_seeds", "seeders", "seeds"))

        event_name = "下载完成" if event in ("completed", "finished", "done") else "下载已添加"
        display_title = self._display_title(
            title,
            event_text="下载完成" if event in ("completed", "finished", "done") else "开始下载",
            episode=self._extract_episode(title, payload),
        )
        lines = self._message_lines(
            ("时间", self._now_text()),
            ("事件", event_name),
            ("站点", site),
            ("状态", self._format_qb_state(state)),
            ("质量", quality),
            ("大小", size),
            ("做种", seeders),
            ("类别", category),
            ("标签", tags),
            ("名称", self._compact_name(title)),
            ("下载器", downloader),
            ("目录", save_path),
        )
        if self._include_raw_summary:
            lines.append("")
            lines.append("事件字段：")
            for key, value in sorted(payload.items()):
                if value is None or isinstance(value, (dict, list, tuple, set)):
                    continue
                lines.append(f"- {key}: {value}")

        self._post_notification(
            title=display_title,
            text="\n".join(lines),
        )
        logger.info(f"{self.plugin_name}: 已接收 Qbittorrent 外部程序通知 - {event}: {title}")
        return {"success": True, "message": "ok"}

    def get_form(self):
        return [
            {
                "component": "VForm",
                "content": [
                    {
                        "component": "VRow",
                        "content": [
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 6},
                                "content": [
                                    {
                                        "component": "VSwitch",
                                        "props": {
                                            "model": "enabled",
                                            "label": "启用插件",
                                        },
                                    }
                                ],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 6},
                                "content": [
                                    {
                                        "component": "VTextField",
                                        "props": {
                                            "model": "moviepilot_base_url",
                                            "label": "MoviePilot 地址",
                                            "placeholder": "http://moviepilot:3001",
                                        },
                                    }
                                ],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 6},
                                "content": [
                                    {
                                        "component": "VTextField",
                                        "props": {
                                            "model": "qb_downloader_name",
                                            "label": "qBittorrent 下载器名称",
                                            "placeholder": "Qbittorrent",
                                        },
                                    }
                                ],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 6},
                                "content": [
                                    {
                                        "component": "VSelect",
                                        "props": {
                                            "model": "notify_stage",
                                            "label": "通知时机",
                                            "items": [
                                                {"title": "添加下载任务时", "value": "download_added"},
                                                {"title": "文件整理完成时", "value": "transfer_complete"},
                                                {"title": "两者都通知", "value": "both"},
                                            ],
                                        },
                                    }
                                ],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 6},
                                "content": [
                                    {
                                        "component": "VSelect",
                                        "props": {
                                            "model": "notify_type",
                                            "label": "通知类型",
                                            "items": [
                                                {"title": "资源下载", "value": "Download"},
                                                {"title": "手动处理通知", "value": "Manual"},
                                            ],
                                        },
                                    }
                                ],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 6},
                                "content": [
                                    {
                                        "component": "VTextField",
                                        "props": {
                                            "model": "title_prefix",
                                            "label": "标题前缀",
                                            "placeholder": "[下载已添加]",
                                        },
                                    }
                                ],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 6},
                                "content": [
                                    {
                                        "component": "VTextField",
                                        "props": {
                                            "model": "complete_title_prefix",
                                            "label": "完成通知标题前缀",
                                            "placeholder": "[下载已完成]",
                                        },
                                    }
                                ],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 6},
                                "content": [
                                    {
                                        "component": "VTextField",
                                        "props": {
                                            "model": "only_downloader",
                                            "label": "只通知指定下载器",
                                            "placeholder": "例如 qbittorrent，留空表示全部",
                                        },
                                    }
                                ],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12},
                                "content": [
                                    {
                                        "component": "VTextField",
                                        "props": {
                                            "model": "header_image_url",
                                            "label": "推送头图 URL",
                                            "placeholder": "填写图片直链，留空则不推送头图",
                                        },
                                    }
                                ],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12},
                                "content": [
                                    {
                                        "component": "VSwitch",
                                        "props": {
                                            "model": "include_raw_summary",
                                            "label": "附加原始事件摘要",
                                        },
                                    }
                                ],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 6},
                                "content": [
                                    {
                                        "component": "VSwitch",
                                        "props": {
                                            "model": "qb_poll_enabled",
                                            "label": "轮询 Qbittorrent 手动添加任务",
                                        },
                                    }
                                ],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 6},
                                "content": [
                                    {
                                        "component": "VTextField",
                                        "props": {
                                            "model": "qb_poll_interval",
                                            "label": "Qbittorrent 轮询间隔（秒）",
                                            "type": "number",
                                            "min": 15,
                                            "placeholder": "60",
                                        },
                                    }
                                ],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 6},
                                "content": [
                                    {
                                        "component": "VSwitch",
                                        "props": {
                                            "model": "external_notify_enabled",
                                            "label": "启用 qBittorrent 外部程序通知接口",
                                        },
                                    }
                                ],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 6},
                                "content": [
                                    {
                                        "component": "VTextField",
                                        "props": {
                                            "model": "external_notify_token",
                                            "label": "qBittorrent 外部程序通知 Token",
                                            "placeholder": "留空保存后自动生成",
                                        },
                                    }
                                ],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12},
                                "content": [
                                    {
                                        "component": "VTextarea",
                                        "props": {
                                            "model": "qb_added_command",
                                            "label": "qBittorrent 添加种子时运行外部程序",
                                            "rows": 2,
                                            "auto-grow": True,
                                            "readonly": True,
                                        },
                                    }
                                ],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12},
                                "content": [
                                    {
                                        "component": "VTextarea",
                                        "props": {
                                            "model": "qb_completed_command",
                                            "label": "qBittorrent 完成下载时运行外部程序",
                                            "rows": 2,
                                            "auto-grow": True,
                                            "readonly": True,
                                        },
                                    }
                                ],
                            },
                        ],
                    }
                ],
            }
        ], {
            "enabled": False,
            "notify_type": "Download",
            "notify_stage": "download_added",
            "title_prefix": "[下载已添加]",
            "complete_title_prefix": "[下载已完成]",
            "only_downloader": "",
            "include_raw_summary": False,
            "qb_poll_enabled": True,
            "qb_poll_interval": 60,
            "external_notify_enabled": True,
            "external_notify_token": "",
            "moviepilot_base_url": "http://moviepilot:3001",
            "qb_downloader_name": "Qbittorrent",
            "header_image_url": "",
            "qb_added_command": "",
            "qb_completed_command": "",
        }

    def get_command(self) -> List[Dict[str, Any]]:
        return []

    def get_api(self) -> List[Dict[str, Any]]:
        return [
            {
                "path": "/qbittorrent",
                "endpoint": self.qbittorrent_notify,
                "methods": ["POST"],
                "allow_anonymous": True,
                "summary": "接收 Qbittorrent 外部程序通知",
                "description": "由 Qbittorrent 外部程序脚本调用，用于通知手动添加或完成的种子任务",
            }
        ]

    def get_page(self) -> Optional[List[dict]]:
        return None

    def get_service(self) -> List[Dict[str, Any]]:
        if not self._enabled or not self._qb_poll_enabled:
            return []
        return [
            {
                "id": "qb_poll_torrents",
                "name": "轮询 Qbittorrent 手动添加任务",
                "trigger": "interval",
                "func": self.poll_qb_torrents,
                "kwargs": {"seconds": self._qb_poll_interval},
            }
        ]

    def stop_service(self):
        pass

    def _notification_type(self):
        if self._notify_type == "Manual":
            return self._notification_type_value("Manual")
        return self._notification_type_value("Download")

    @staticmethod
    def _notification_type_value(name: str):
        try:
            from app.schemas.types import NotificationType

            return getattr(NotificationType, name)
        except Exception:
            return None

    @staticmethod
    def _now_text() -> str:
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def _post_notification(self, title: str, text: str):
        kwargs = {
            "mtype": self._notification_type(),
            "title": title,
            "text": text,
        }
        if self._header_image_url:
            kwargs["image"] = self._header_image_url
        try:
            self.post_message(**kwargs)
        except TypeError:
            kwargs.pop("image", None)
            try:
                self.post_message(**kwargs)
            except TypeError:
                kwargs.pop("mtype", None)
                self.post_message(**kwargs)

    @staticmethod
    def _raise_http_error(status_code: int, detail: str):
        if HTTPException:
            raise HTTPException(status_code=status_code, detail=detail)
        raise Exception(detail)

    def _build_qb_command(self, event: str) -> str:
        base_url = (self._moviepilot_base_url or "http://moviepilot:3001").rstrip("/")
        token = self._external_notify_token or "插件配置页里的通知Token"
        downloader = self._qb_downloader_name or "Qbittorrent"
        return (
            f"curl -fsS -X POST \"{base_url}/api/v1/plugin/DownloadAddedNotify/qbittorrent?token={token}\" "
            f"--data-urlencode \"event={event}\" "
            f"--data-urlencode \"downloader={downloader}\" "
            "--data-urlencode \"name=%N\" "
            "--data-urlencode \"hash=%I\" "
            "--data-urlencode \"save_path=%D\" "
            "--data-urlencode \"category=%L\" "
            "--data-urlencode \"tags=%G\" "
            "--data-urlencode \"size=%Z\" "
            "--data-urlencode \"tracker=%T\""
        )

    @staticmethod
    def _to_dict(value: Any) -> Dict[str, Any]:
        if isinstance(value, dict):
            return value
        if hasattr(value, "dict"):
            try:
                return value.dict()
            except Exception:
                pass
        if hasattr(value, "to_dict"):
            try:
                return value.to_dict()
            except Exception:
                pass
        if hasattr(value, "model_dump"):
            try:
                return value.model_dump()
            except Exception:
                pass
        if hasattr(value, "__dict__"):
            return {
                key: val
                for key, val in vars(value).items()
                if not key.startswith("_")
            }
        return {}

    @classmethod
    def _first_value(cls, data: Dict[str, Any], *keys: str) -> Optional[Any]:
        value = cls._first_raw_value(data, *keys)
        if value not in (None, ""):
            return cls._stringify(value)
        return None

    @staticmethod
    def _first_raw_value(data: Dict[str, Any], *keys: str) -> Optional[Any]:
        for key in keys:
            value = data.get(key)
            if value not in (None, ""):
                return value
        return None

    @staticmethod
    def _stringify(value: Any) -> str:
        if isinstance(value, (list, tuple, set)):
            return ", ".join(str(item) for item in value)
        return str(value)

    @classmethod
    def _message_lines(cls, *items: tuple) -> List[str]:
        lines = []
        for label, value in items:
            text = cls._clean_message_value(value)
            if text:
                icon = cls._label_icons.get(label)
                label_text = f"{icon} {label}" if icon else label
                if label == "名称":
                    lines.append(f"{label_text}：\n{text}")
                else:
                    lines.append(f"{label_text}： {text}")
        return lines

    @classmethod
    def _clean_message_value(cls, value: Any) -> Optional[str]:
        if value in (None, ""):
            return None
        text = cls._stringify(value).strip()
        if not text:
            return None
        return " ".join(text.splitlines())

    @classmethod
    def _display_title(
        cls,
        title: Any,
        media_title: Any = None,
        year: Any = None,
        event_text: Optional[str] = None,
        episode: Any = None,
    ) -> str:
        media_text = cls._clean_message_value(media_title)
        episode_text = cls._format_episode_text(episode) or cls._extract_episode(title)
        if media_text:
            base = cls._ensure_title_year(media_text, year or cls._extract_year(title))
            return cls._join_title_parts(base, episode_text, event_text)

        text = cls._clean_message_value(title) or "未知任务"
        text = re.sub(
            r"\b(2160p|1080p|720p|480p|WEB-?DL|WEBRip|BluRay|BDRip|HDTV|DVDRip|"
            r"DDP?\d(?:\.\d)?|DTS|AAC|AC3|H\.?265|H\.?264|HEVC|AVC|x265|x264|"
            r"HDR10\+?|DoVi|DV|SDR).*$",
            "",
            text,
            flags=re.IGNORECASE,
        )
        text = re.sub(r"[-._]+$", "", text).strip()
        text = re.sub(r"[._]+", " ", text)
        title_year = year or cls._extract_year(text)
        if episode_text:
            text = re.sub(r"\bS\d{1,2}\s*[-_. ]*\s*(?:E|EP)\s*\d{1,3}\b", "", text, flags=re.IGNORECASE).strip()
            text = re.sub(r"\b\d{1,2}\s*x\s*\d{1,3}\b", "", text, flags=re.IGNORECASE).strip()
            text = re.sub(r"\b第\s*\d+\s*[集话话]\b", "", text).strip()
        if title_year:
            text = re.sub(rf"\b{re.escape(str(title_year))}\b", "", text).strip()
        text = re.sub(r"[-._]+$", "", text).strip()
        text = re.sub(r"\s+", " ", text)
        base = cls._ensure_title_year(text or "未知任务", title_year)
        return cls._join_title_parts(base, episode_text, event_text)

    @classmethod
    def _ensure_title_year(cls, title: Any, year: Any = None) -> str:
        text = cls._clean_message_value(title) or "未知任务"
        if re.search(r"\(\d{4}\)", text):
            return text
        title_year = year or cls._extract_year(text)
        if title_year:
            text = re.sub(rf"\b{re.escape(str(title_year))}\b", "", text).strip()
            text = re.sub(r"[-._]+$", "", text).strip()
            return f"{text} ({title_year})"
        return text

    @classmethod
    def _join_title_parts(cls, title: str, episode: Optional[str], event_text: Optional[str]) -> str:
        parts = [title]
        if episode:
            parts.append(episode)
        if event_text:
            parts.append(event_text)
        return cls._compact_name(" ".join(parts), 64) or "未知任务"

    @staticmethod
    def _extract_year(value: Any) -> Optional[str]:
        if value in (None, ""):
            return None
        match = re.search(r"\b(19\d{2}|20\d{2})\b", str(value))
        return match.group(1) if match else None

    @classmethod
    def _extract_episode(cls, *values: Any) -> Optional[str]:
        season = None
        episode = None
        for value in values:
            extracted = cls._extract_episode_from_value(value)
            if extracted:
                return extracted
            current_season = cls._extract_season_number(value)
            current_episode = cls._extract_episode_number(value)
            season = season or current_season
            episode = episode or current_episode
        if season and episode:
            return cls._format_season_episode(season, episode)
        if episode:
            return f"E{int(episode):02d}"
        return None

    @classmethod
    def _extract_episode_from_value(cls, value: Any) -> Optional[str]:
        if value in (None, ""):
            return None
        if isinstance(value, dict):
            direct = cls._first_raw_value(
                value,
                "season_episode",
                "season_episode_text",
                "episode_text",
                "download_episodes",
                "episodes",
                "episode",
                "ep",
                "episode_number",
                "episode_num",
                "begin_episode",
            )
            extracted = cls._extract_episode_from_value(direct)
            if extracted:
                return extracted
            season = cls._extract_season_number(value)
            episode = cls._extract_episode_number(value)
            if season and episode:
                return cls._format_season_episode(season, episode)
            return None

        text = cls._stringify(value)
        match = re.search(r"\bS(?:eason)?\s*0?(\d{1,2})\s*[-_. ]*\s*(?:E|EP|Episode)\s*0?(\d{1,3})\b", text, re.IGNORECASE)
        if match:
            return cls._format_season_episode(match.group(1), match.group(2))
        match = re.search(r"\b0?(\d{1,2})\s*x\s*0?(\d{1,3})\b", text, re.IGNORECASE)
        if match:
            return cls._format_season_episode(match.group(1), match.group(2))
        match = re.search(r"第\s*(\d+)\s*[集话]", text)
        if match:
            return f"第{int(match.group(1))}集"
        match = re.search(r"\b(?:E|EP|Episode)\s*0?(\d{1,3})\b", text, re.IGNORECASE)
        if match:
            return f"E{int(match.group(1)):02d}"
        return None

    @classmethod
    def _extract_season_number(cls, value: Any) -> Optional[int]:
        if value in (None, ""):
            return None
        if isinstance(value, dict):
            raw = cls._first_raw_value(value, "season", "season_number", "season_num", "season_no")
            if raw not in (None, ""):
                return cls._to_positive_int(raw)
            for key in ("title", "name", "org_string"):
                found = cls._extract_season_number(value.get(key))
                if found:
                    return found
            return None
        match = re.search(r"\bS(?:eason)?\s*0?(\d{1,2})\b", str(value), re.IGNORECASE)
        return int(match.group(1)) if match else None

    @classmethod
    def _extract_episode_number(cls, value: Any) -> Optional[int]:
        if value in (None, ""):
            return None
        if isinstance(value, dict):
            raw = cls._first_raw_value(
                value,
                "episode",
                "ep",
                "episode_number",
                "episode_num",
                "episode_no",
                "begin_episode",
                "current_episode",
            )
            if raw not in (None, ""):
                return cls._to_positive_int(raw)
            return None
        match = re.search(r"\b(?:E|EP|Episode)\s*0?(\d{1,3})\b", str(value), re.IGNORECASE)
        if match:
            return int(match.group(1))
        match = re.search(r"第\s*(\d+)\s*[集话]", str(value))
        return int(match.group(1)) if match else None

    @staticmethod
    def _format_episode_text(value: Any) -> Optional[str]:
        if value in (None, ""):
            return None
        text = str(value)
        if re.match(r"^S\d{2}E\d{2,3}$", text, re.IGNORECASE):
            return text.upper()
        if re.match(r"^E\d{2,3}$", text, re.IGNORECASE):
            return text.upper()
        if re.match(r"^第\d+集$", text):
            return text
        return None

    @staticmethod
    def _format_season_episode(season: Any, episode: Any) -> Optional[str]:
        season_number = DownloadAddedNotify._to_positive_int(season)
        episode_number = DownloadAddedNotify._to_positive_int(episode)
        if not season_number or not episode_number:
            return None
        return f"S{season_number:02d}E{episode_number:02d}"

    @staticmethod
    def _to_positive_int(value: Any) -> Optional[int]:
        try:
            number = int(float(str(value).strip()))
        except (TypeError, ValueError):
            return None
        return number if number > 0 else None

    @classmethod
    def _compact_name(cls, value: Any, max_len: int = 96) -> Optional[str]:
        text = cls._clean_message_value(value)
        if not text:
            return None
        text = re.sub(r"\s+", " ", text).strip()
        if len(text) <= max_len:
            return text
        return f"{text[:max_len - 3].rstrip()}..."

    @staticmethod
    def _format_qb_state(state: Any) -> Optional[str]:
        if state in (None, ""):
            return None
        text = str(state)
        state_map = {
            "allocating": "分配空间",
            "checkingdl": "校验中",
            "checkingup": "校验中",
            "checkingresumedata": "校验恢复数据",
            "downloading": "下载中",
            "error": "错误",
            "forceddl": "强制下载",
            "forcedup": "强制做种",
            "metadl": "获取元数据",
            "missingfiles": "文件缺失",
            "moved": "已移动",
            "pauseddl": "已暂停",
            "pausedup": "已暂停做种",
            "queueddl": "排队下载",
            "queuedup": "排队做种",
            "stalleddl": "等待下载",
            "stalledup": "等待做种",
            "uploading": "做种中",
        }
        return state_map.get(text.lower(), text)

    @staticmethod
    def _extract_quality(title: Any) -> Optional[str]:
        if title in (None, ""):
            return None
        text = str(title)
        parts = []
        quality_patterns = (
            r"\b(2160p|1080p|720p|480p)\b",
            r"\b(WEB-?DL|WEBRip|BluRay|BDRip|HDTV|DVDRip)\b",
            r"\b(H\.?265|H\.?264|HEVC|AVC|x265|x264)\b",
            r"\b(HDR10\+?|DV|DoVi|SDR)\b",
        )
        for pattern in quality_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                value = match.group(1).replace(".", "").upper()
                if value == "WEB-DL":
                    value = "WEB-DL"
                elif value == "WEBDL":
                    value = "WEB-DL"
                parts.append(value)
        return " ".join(dict.fromkeys(parts)) or None

    @staticmethod
    def _format_site(value: Any) -> Optional[str]:
        if value in (None, ""):
            return None
        text = str(value).strip()
        if not text:
            return None
        parsed = urlparse(text)
        host = parsed.netloc or parsed.path
        if "@" in host:
            host = host.rsplit("@", 1)[-1]
        if ":" in host:
            host = host.split(":", 1)[0]
        if "/" in host:
            host = host.split("/", 1)[0]
        host = re.sub(r"^(tracker|announce|tr)[-_.]?\d*[-_.]+", "", host, flags=re.IGNORECASE)
        return DownloadAddedNotify._main_domain(host) or host or text

    @staticmethod
    def _main_domain(host: str) -> Optional[str]:
        labels = [part for part in host.lower().strip(".").split(".") if part]
        if len(labels) <= 2:
            return ".".join(labels) if labels else None
        if labels[0] == "www":
            labels = labels[1:]
        if len(labels) <= 2:
            return ".".join(labels) if labels else None
        second_level_suffixes = {
            "com.cn",
            "net.cn",
            "org.cn",
            "gov.cn",
            "edu.cn",
            "co.uk",
            "org.uk",
            "com.au",
            "net.au",
        }
        suffix = ".".join(labels[-2:])
        if suffix in second_level_suffixes and len(labels) >= 3:
            return ".".join(labels[-3:])
        return ".".join(labels[-2:])

    @staticmethod
    def _format_seed_count(value: Any) -> Optional[str]:
        if value in (None, ""):
            return None
        try:
            number = int(float(value))
        except (TypeError, ValueError):
            return str(value)
        if number < 0:
            return None
        return str(number)

    @staticmethod
    def _format_size_gb(value: Any) -> Optional[str]:
        if value in (None, ""):
            return None
        if isinstance(value, str):
            formatted = DownloadAddedNotify._parse_size_string_to_gb(value)
            if formatted:
                return formatted
        try:
            size = float(value)
        except (TypeError, ValueError):
            return str(value)
        if size <= 0:
            return None
        return DownloadAddedNotify._format_gb_number(size / 1024 / 1024 / 1024)

    @classmethod
    def _parse_size_string_to_gb(cls, value: str) -> Optional[str]:
        text = value.strip()
        match = re.search(r"([\d.]+)\s*([KMGT]?I?B?|[KMGT])", text, re.IGNORECASE)
        if not match:
            return None
        try:
            number = float(match.group(1))
        except (TypeError, ValueError):
            return None
        unit = match.group(2).upper()
        if unit in ("", "B"):
            gb = number / 1024 / 1024 / 1024
        elif unit in ("K", "KB", "KIB"):
            gb = number / 1024 / 1024
        elif unit in ("M", "MB", "MIB"):
            gb = number / 1024
        elif unit in ("G", "GB", "GIB"):
            gb = number
        elif unit in ("T", "TB", "TIB"):
            gb = number * 1024
        else:
            return None
        return cls._format_gb_number(gb)

    @staticmethod
    def _format_gb_number(gb: float) -> Optional[str]:
        if gb <= 0:
            return None
        if gb >= 100:
            return f"{gb:.0f} GB"
        if gb >= 10:
            return f"{gb:.1f} GB"
        return f"{max(gb, 0.01):.2f} GB"

    @staticmethod
    def _safe_int(value: Any, default: int, minimum: int) -> int:
        try:
            number = int(value)
        except (TypeError, ValueError):
            return default
        return max(number, minimum)

    @staticmethod
    async def _request_payload(request: Request) -> Dict[str, Any]:
        payload = dict(request.query_params)
        content_type = request.headers.get("content-type", "")
        if "application/json" in content_type:
            try:
                data = await request.json()
                if isinstance(data, dict):
                    payload.update(data)
                return payload
            except Exception:
                return payload
        try:
            form = await request.form()
            payload.update(dict(form))
            return payload
        except Exception:
            return payload

    @staticmethod
    def _get_context_value(context: Any, key: str) -> Any:
        if isinstance(context, dict):
            return context.get(key)
        return getattr(context, key, None)

    @classmethod
    def _media_title(cls, media_info: Any) -> Optional[str]:
        data = cls._to_dict(media_info)
        title = cls._first_value(data, "title", "name", "cn_name", "en_name")
        year = cls._first_value(data, "year")
        if title and year:
            return f"{title} ({year})"
        return title
