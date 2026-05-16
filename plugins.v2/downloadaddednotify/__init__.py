from typing import Any, Dict, List, Optional

from app.core.event import Event, eventmanager
from app.log import logger
from app.plugins import _PluginBase
from app.schemas.types import EventType, NotificationType


class DownloadAddedNotify(_PluginBase):
    plugin_name = "下载添加通知"
    plugin_desc = "监听下载添加事件，并通过 MoviePilot 系统通知发送消息"
    plugin_icon = "https://raw.githubusercontent.com/jxxghp/MoviePilot-Plugins/main/icons/notice.png"
    plugin_version = "0.0.2"
    plugin_author = "jardy"
    author_url = ""
    plugin_config_prefix = "downloadaddednotify_"
    plugin_order = 66
    auth_level = 1

    _enabled = False
    _notify_type = "Download"
    _notify_stage = "download_added"
    _title_prefix = "[下载已添加]"
    _complete_title_prefix = "[下载已完成]"
    _only_downloader = ""
    _include_raw_summary = False

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

    def get_state(self) -> bool:
        return self._enabled

    @eventmanager.register(EventType.DownloadAdded)
    def download_added(self, event: Event):
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

    @eventmanager.register(EventType.TransferComplete)
    def transfer_complete(self, event: Event):
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
        }

    def get_command(self) -> List[Dict[str, Any]]:
        return []

    def get_api(self) -> List[Dict[str, Any]]:
        return []

    def get_service(self) -> List[Dict[str, Any]]:
        return []

    def stop_service(self):
        pass

    def _notification_type(self):
        if self._notify_type == "Manual":
            return NotificationType.Manual
        return NotificationType.Download

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
