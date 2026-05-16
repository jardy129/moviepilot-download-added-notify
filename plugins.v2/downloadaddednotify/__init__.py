from typing import Any, Dict, List, Optional

from app.core.event import Event, eventmanager
from app.log import logger
from app.plugins import _PluginBase
from app.schemas.types import EventType, NotificationType


class DownloadAddedNotify(_PluginBase):
    plugin_name = "下载添加通知"
    plugin_desc = "监听下载添加事件，并通过 MoviePilot 系统通知发送消息"
    plugin_icon = "https://raw.githubusercontent.com/jxxghp/MoviePilot-Plugins/main/icons/notice.png"
    plugin_version = "0.0.1"
    plugin_author = "jardy"
    author_url = ""
    plugin_config_prefix = "downloadaddednotify_"
    plugin_order = 66
    auth_level = 1

    _enabled = False
    _notify_type = "Download"
    _title_prefix = "[下载已添加]"
    _only_downloader = ""
    _include_raw_summary = False

    def init_plugin(self, config: Optional[dict] = None):
        if not config:
            return

        self._enabled = bool(config.get("enabled"))
        self._notify_type = config.get("notify_type") or "Download"
        self._title_prefix = config.get("title_prefix") or "[下载已添加]"
        self._only_downloader = (config.get("only_downloader") or "").strip()
        self._include_raw_summary = bool(config.get("include_raw_summary"))

    def get_state(self) -> bool:
        return self._enabled

    @eventmanager.register(EventType.DownloadAdded)
    def download_added(self, event: Event):
        if not self._enabled:
            return

        event_data = event.event_data or {}
        data = self._to_dict(event_data)

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

        title = self._first_value(
            data,
            "title",
            "name",
            "torrent_name",
            "torrent",
            "resource_title",
            "torrent_title",
        ) or "未知任务"
        site = self._first_value(data, "site", "site_name", "sitename")
        save_path = self._first_value(data, "save_path", "savepath", "path", "download_path")
        category = self._first_value(data, "category", "cat")
        tags = self._first_value(data, "tags", "tag")
        size = self._first_value(data, "size", "total_size", "totalSize")
        media_title = self._first_value(data, "media_title", "media_name", "name_cn")
        year = self._first_value(data, "year")

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
            "title_prefix": "[下载已添加]",
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
