import secrets
from typing import Any, Dict, List, Optional

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
    plugin_icon = "https://raw.githubusercontent.com/jxxghp/MoviePilot-Plugins/main/icons/notice.png"
    plugin_version = "0.0.11"
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

        title = (
            self._first_value(self._to_dict(torrent_info), "title")
            or self._media_title(media_info)
            or self._first_value(self._to_dict(meta_info), "org_string", "title", "cn_name", "en_name")
            or "未知任务"
        )
        site = self._first_value(self._to_dict(torrent_info), "site_name", "site")
        save_path = self._first_value(data, "save_path", "savepath", "path", "download_path")
        category = (
            self._first_value(self._to_dict(torrent_info), "category")
            or self._first_value(self._to_dict(media_info), "category", "type")
        )
        tags = self._first_value(data, "tags", "tag")
        size = self._first_value(self._to_dict(torrent_info), "size")
        media_title = self._media_title(media_info)
        year = self._first_value(self._to_dict(media_info), "year") or self._first_value(self._to_dict(meta_info), "year")

        lines = [f"名称：{title}"]
        if media_title:
            media_text = str(media_title)
            if year:
                media_text = f"{media_text} ({year})"
            lines.append(f"媒体：{media_text}")
        if site:
            lines.append(f"站点：{site}")
        if downloader:
            lines.append(f"下载器：{downloader}")
        if category:
            lines.append(f"分类：{category}")
        if tags:
            lines.append(f"标签：{tags}")
        if size:
            lines.append(f"大小：{size}")
        if save_path:
            lines.append(f"目录：{save_path}")
        if self._include_raw_summary:
            lines.append("")
            lines.append("事件字段：")
            for key, value in sorted(data.items()):
                if value is None or isinstance(value, (dict, list, tuple, set)):
                    continue
                lines.append(f"- {key}: {value}")

        try:
            self.post_message(
                mtype=self._notification_type(),
                title=f"{self._title_prefix} {title}",
                text="\n".join(lines),
            )
            logger.info(f"{self.plugin_name}: 已发送下载添加通知 - {title}")
        except TypeError:
            self.post_message(
                title=f"{self._title_prefix} {title}",
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
        download_hash = self._first_value(data, "download_hash")

        lines = [f"名称：{title}"]
        if source_path:
            lines.append(f"源文件：{source_path}")
        if target_path:
            lines.append(f"入库位置：{target_path}")
        if downloader:
            lines.append(f"下载器：{downloader}")
        if download_hash:
            lines.append(f"HASH：{download_hash}")
        if self._include_raw_summary:
            lines.append("")
            lines.append("事件字段：")
            for key, value in sorted(data.items()):
                if value is None or isinstance(value, (dict, list, tuple, set)):
                    continue
                lines.append(f"- {key}: {value}")

        try:
            self.post_message(
                mtype=self._notification_type(),
                title=f"{self._complete_title_prefix} {title}",
                text="\n".join(lines),
            )
            logger.info(f"{self.plugin_name}: 已发送下载完成通知 - {title}")
        except TypeError:
            self.post_message(
                title=f"{self._complete_title_prefix} {title}",
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
        size = self._first_value(torrent_data, "total_size", "size")
        torrent_hash = self._first_value(torrent_data, "hash")
        state = self._first_value(torrent_data, "state")

        lines = [f"名称：{title}", f"下载器：{downloader}"]
        if state:
            lines.append(f"状态：{state}")
        if category:
            lines.append(f"分类：{category}")
        if tags:
            lines.append(f"标签：{tags}")
        if size:
            lines.append(f"大小：{size}")
        if save_path:
            lines.append(f"目录：{save_path}")
        if torrent_hash:
            lines.append(f"HASH：{torrent_hash}")
        if self._include_raw_summary:
            lines.append("")
            lines.append("事件字段：")
            for key, value in sorted(torrent_data.items()):
                if value is None or isinstance(value, (dict, list, tuple, set)):
                    continue
                lines.append(f"- {key}: {value}")

        try:
            self.post_message(
                mtype=self._notification_type(),
                title=f"{self._title_prefix} {title}",
                text="\n".join(lines),
            )
            logger.info(f"{self.plugin_name}: 已发送 Qbittorrent 新任务通知 - {title}")
        except TypeError:
            self.post_message(
                title=f"{self._title_prefix} {title}",
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
        size = self._first_value(payload, "size", "total_size")
        torrent_hash = self._first_value(payload, "hash", "info_hash")
        state = self._first_value(payload, "state")

        event_name = "下载完成" if event in ("completed", "finished", "done") else "下载已添加"
        prefix = self._complete_title_prefix if event in ("completed", "finished", "done") else self._title_prefix
        lines = [f"名称：{title}", f"来源：qBittorrent 外部程序", f"事件：{event_name}", f"下载器：{downloader}"]
        if state:
            lines.append(f"状态：{state}")
        if category:
            lines.append(f"分类：{category}")
        if tags:
            lines.append(f"标签：{tags}")
        if size:
            lines.append(f"大小：{size}")
        if save_path:
            lines.append(f"目录：{save_path}")
        if torrent_hash:
            lines.append(f"HASH：{torrent_hash}")
        if self._include_raw_summary:
            lines.append("")
            lines.append("事件字段：")
            for key, value in sorted(payload.items()):
                if value is None or isinstance(value, (dict, list, tuple, set)):
                    continue
                lines.append(f"- {key}: {value}")

        self.post_message(
            mtype=self._notification_type(),
            title=f"{prefix} {title}",
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
            "--data-urlencode \"state=%T\""
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
        for key in keys:
            value = data.get(key)
            if value not in (None, ""):
                return cls._stringify(value)
        return None

    @staticmethod
    def _stringify(value: Any) -> str:
        if isinstance(value, (list, tuple, set)):
            return ", ".join(str(item) for item in value)
        return str(value)

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
