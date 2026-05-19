import json
import os
import re
import secrets
from datetime import datetime
from typing import Any, Dict, List, Optional
from urllib.parse import urlencode, urlparse
from urllib.request import Request as UrlRequest, urlopen

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
    plugin_version = "0.3.3"
    plugin_author = "jardy"
    author_url = "https://github.com/jardy129/"
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
    _qb_poll_interval = 15
    _qb_seen_hashes_key = "qb_seen_hashes"
    _external_notify_enabled = True
    _external_notify_token = ""
    _moviepilot_base_url = "http://moviepilot:3001"
    _qb_downloader_name = "Qbittorrent"
    _downloader_label_name = ""
    _header_image_url = ""
    _qb_auto_tag_enabled = True
    _qb_web_url = ""
    _qb_username = ""
    _qb_password = ""
    _qb_tag_name = "MOVIEPILOT"
    _release_name_template = "{title} | {resolution}{fps_part} | {audio} | {release_tag} | {group}"
    _video_extensions = {
        ".mkv",
        ".mp4",
        ".avi",
        ".mov",
        ".ts",
        ".m2ts",
        ".wmv",
        ".flv",
        ".rmvb",
    }
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
    _episode_text_keys = (
        "season_episode",
        "season_episode_text",
        "episode_text",
        "download_episodes",
        "episodes",
        "name",
        "title",
        "org_string",
        "original_name",
        "subtitle",
    )

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
        if str(config.get("qb_poll_interval", "")).strip() == "60":
            config["qb_poll_interval"] = 15
        self._qb_poll_interval = self._safe_int(config.get("qb_poll_interval"), 15, 5)
        self._external_notify_enabled = bool(config.get("external_notify_enabled", True))
        self._external_notify_token = (config.get("external_notify_token") or "").strip()
        self._moviepilot_base_url = (config.get("moviepilot_base_url") or "http://moviepilot:3001").strip()
        self._qb_downloader_name = (config.get("qb_downloader_name") or "Qbittorrent").strip()
        self._downloader_label_name = (config.get("downloader_label_name") or "").strip()
        self._header_image_url = (config.get("header_image_url") or "").strip()
        self._qb_auto_tag_enabled = bool(config.get("qb_auto_tag_enabled", True))
        self._qb_web_url = (config.get("qb_web_url") or "").strip()
        self._qb_username = (config.get("qb_username") or "").strip()
        self._qb_password = (config.get("qb_password") or "").strip()
        self._qb_tag_name = (config.get("qb_tag_name") or "MOVIEPILOT").strip()
        release_name_template = config.get("release_name_template")
        if release_name_template == "{title} | {resolution}{fps_part} | {audio} | {group}":
            release_name_template = "{title} | {resolution}{fps_part} | {audio} | {release_tag} | {group}"
            config["release_name_template"] = release_name_template
        self._release_name_template = (
            release_name_template
            or "{title} | {resolution}{fps_part} | {audio} | {release_tag} | {group}"
        ).strip()
        self.__class__._release_name_template = self._release_name_template
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
            or config.get("downloader_label_name") != saved_config.get("downloader_label_name")
            or config.get("qb_added_command") != saved_config.get("qb_added_command")
            or config.get("qb_completed_command") != saved_config.get("qb_completed_command")
            or "qb_auto_tag_enabled" not in saved_config
            or "qb_tag_name" not in saved_config
            or "release_name_template" not in saved_config
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
            or self._media_title(media_info, meta_info)
            or self._preferred_title(meta_data)
            or "未知任务"
        )
        site = self._first_value(torrent_data, "site_name", "site")
        save_path = self._first_value(data, "save_path", "savepath", "path", "download_path")
        category = self._format_category(
            self._first_value(torrent_data, "category")
            or self._first_value(media_data, "category", "type"),
            title,
        )
        tags = self._first_value(data, "tags", "tag")
        size = self._format_size_gb(self._first_raw_value(torrent_data, "size"))
        quality = self._first_value(torrent_data, "quality", "resolution") or self._extract_quality(title)
        seeders = self._format_seed_count(self._first_raw_value(torrent_data, "seeders", "seeds", "num_seeds"))
        media_title = self._media_title(media_info, meta_info)
        year = self._first_value(media_data, "year") or self._first_value(meta_data, "year")
        torrent_hash = self._first_value(torrent_data, "hash", "info_hash") or self._first_value(data, "hash", "info_hash")
        file_names = self._qb_torrent_file_names_if_needed(torrent_hash, title, save_path)
        mp_info = self._moviepilot_parse(title, file_names=file_names, path=save_path)
        episode = self._resolve_episode(
            title,
            file_names,
            self._extract_episode_from_download_path(save_path),
            torrent_data,
            meta_data,
            media_data,
            data,
        )
        episode = self._select_episode(title, episode, mp_info.get("episode"))

        media_title = self._best_media_title(title, media_title, mp_info.get("title")) or media_title
        year = year or mp_info.get("year")
        quality = quality or mp_info.get("quality")
        category = category or mp_info.get("category")
        media_text = media_title
        if media_text and year:
            media_text = f"{media_text} ({year})"
        display_title = self._display_title(title, media_text, year, "开始下载", episode)
        compact_name = self._compact_name_with_moviepilot(title, mp_info, episode=episode)
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
            ("下载器", self._format_downloader_label(downloader)),
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
            self._media_title(media_info, meta_info)
            or self._preferred_title(self._to_dict(meta_info))
            or self._first_value(self._to_dict(fileitem), "name", "path")
            or "未知任务"
        )
        source_path = self._first_value(self._to_dict(fileitem), "path", "name")
        transfer_data = self._to_dict(transferinfo)
        target_path = (
            self._first_value(self._to_dict(transfer_data.get("target_item")), "path", "name")
            or self._first_value(transfer_data, "target_path", "target_dir", "file_path")
        )
        episode = self._resolve_episode(
            title,
            None,
            self._extract_episode_from_download_path(source_path),
            self._extract_episode_from_download_path(target_path),
            data,
        )

        lines = self._message_lines(
            ("时间", self._now_text()),
            (
                "名称",
                self._compact_name(
                    title,
                    episode=episode,
                ),
            ),
            ("下载器", self._format_downloader_label(downloader)),
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
                title=self._display_title(title, event_text="下载完成", episode=episode),
                text="\n".join(lines),
            )
            logger.info(f"{self.plugin_name}: 已发送下载完成通知 - {title}")
        except TypeError:
            self._post_notification(
                title=self._display_title(title, event_text="下载完成", episode=episode),
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
        content_path = self._first_value(torrent_data, "content_path", "contentPath", "file_path", "path")
        save_path = self._first_value(torrent_data, "save_path", "content_path")
        torrent_hash = self._first_value(torrent_data, "hash", "info_hash")
        category = self._format_category(self._first_value(torrent_data, "category"), title)
        tags = self._first_value(torrent_data, "tags")
        state = self._first_value(torrent_data, "state")
        site = self._format_site(self._first_value(torrent_data, "tracker", "tracker_host", "site", "site_name"))
        size = self._format_size_gb(self._first_raw_value(torrent_data, "total_size", "size"))
        quality = self._first_value(torrent_data, "quality", "resolution") or self._extract_quality(title)
        seeders = self._format_seed_count(self._first_raw_value(torrent_data, "num_seeds", "seeders", "seeds"))
        file_names = self._qb_torrent_file_names_if_needed(torrent_hash, title, content_path, save_path)
        mp_info = self._moviepilot_parse(title, file_names=file_names, path=content_path or save_path)
        episode = self._resolve_episode(
            title,
            file_names,
            self._extract_episode_from_download_path(content_path),
            torrent_data,
        )
        episode = self._select_episode(title, episode, mp_info.get("episode"))
        quality = quality or mp_info.get("quality")
        category = category or mp_info.get("category")
        display_title = self._display_title(
            title,
            media_title=self._best_media_title(title, mp_info.get("title")),
            year=mp_info.get("year"),
            event_text="开始下载",
            episode=episode,
        )
        compact_name = self._compact_name_with_moviepilot(title, mp_info, episode=episode)

        lines = self._message_lines(
            ("时间", self._now_text()),
            ("站点", site),
            ("状态", self._format_qb_state(state)),
            ("质量", quality),
            ("大小", size),
            ("做种", seeders),
            ("类别", category),
            ("标签", tags),
            ("名称", compact_name),
            ("下载器", self._format_downloader_label(downloader)),
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
            self._add_qb_tag(torrent_hash)
            logger.info(f"{self.plugin_name}: 已发送 Qbittorrent 新任务通知 - {title}")
        except TypeError:
            self._post_notification(
                title=display_title,
                text="\n".join(lines),
            )
            self._add_qb_tag(torrent_hash)
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
        content_path = self._first_value(payload, "content_path", "contentPath", "file_path")
        save_path = self._first_value(payload, "save_path", "path", "content_path")
        category = self._format_category(self._first_value(payload, "category"), title)
        tags = self._first_value(payload, "tags")
        state = self._first_value(payload, "state")
        site = self._format_site(self._first_value(payload, "tracker", "site", "site_name"))
        size = self._format_size_gb(self._first_raw_value(payload, "size", "total_size"))
        quality = self._first_value(payload, "quality", "resolution") or self._extract_quality(title)
        seeders = self._format_seed_count(self._first_raw_value(payload, "num_seeds", "seeders", "seeds"))
        torrent_hash = self._first_value(payload, "hash", "info_hash")
        file_names = self._qb_torrent_file_names_if_needed(torrent_hash, title, content_path, save_path)
        mp_info = self._moviepilot_parse(title, file_names=file_names, path=content_path or save_path)
        episode = self._resolve_episode(
            title,
            file_names,
            self._extract_episode_from_download_path(content_path),
            payload,
        )
        episode = self._select_episode(title, episode, mp_info.get("episode"))
        quality = quality or mp_info.get("quality")
        category = category or mp_info.get("category")

        event_name = "下载完成" if event in ("completed", "finished", "done") else "下载已添加"
        display_title = self._display_title(
            title,
            media_title=self._best_media_title(title, mp_info.get("title")),
            year=mp_info.get("year"),
            event_text="下载完成" if event in ("completed", "finished", "done") else "开始下载",
            episode=episode,
        )
        compact_name = self._compact_name_with_moviepilot(title, mp_info, episode=episode)
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
            ("名称", compact_name),
            ("下载器", self._format_downloader_label(downloader)),
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
        if event not in ("completed", "finished", "done"):
            self._add_qb_tag(torrent_hash)
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
                                "props": {"cols": 12, "md": 4},
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
                                "props": {"cols": 12, "md": 4},
                                "content": [
                                    {
                                        "component": "VTextField",
                                        "props": {
                                            "model": "downloader_label_name",
                                            "label": "下载器标签名称",
                                            "placeholder": "例如 QB-电影，留空显示原下载器名",
                                        },
                                    }
                                ],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 4},
                                "content": [
                                    {
                                        "component": "VSwitch",
                                        "props": {
                                            "model": "qb_auto_tag_enabled",
                                            "label": "自动给 qBittorrent 任务打标签",
                                        },
                                    }
                                ],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 4},
                                "content": [
                                    {
                                        "component": "VTextField",
                                        "props": {
                                            "model": "qb_tag_name",
                                            "label": "自动标签名称",
                                            "placeholder": "MOVIEPILOT",
                                        },
                                    }
                                ],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 4},
                                "content": [
                                    {
                                        "component": "VTextField",
                                        "props": {
                                            "model": "qb_web_url",
                                            "label": "qBittorrent Web 地址",
                                            "placeholder": "http://127.0.0.1:8080",
                                        },
                                    }
                                ],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 4},
                                "content": [
                                    {
                                        "component": "VTextField",
                                        "props": {
                                            "model": "qb_username",
                                            "label": "qBittorrent 用户名",
                                            "placeholder": "admin",
                                        },
                                    }
                                ],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 4},
                                "content": [
                                    {
                                        "component": "VTextField",
                                        "props": {
                                            "model": "qb_password",
                                            "label": "qBittorrent 密码",
                                            "type": "password",
                                        },
                                    }
                                ],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 4},
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
                                "props": {"cols": 12, "md": 4},
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
                                "props": {"cols": 12, "md": 4},
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
                                "props": {"cols": 12, "md": 4},
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
                                "props": {"cols": 12, "md": 4},
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
                                "props": {"cols": 12, "md": 4},
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
                                "props": {"cols": 12, "md": 4},
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
                                "props": {"cols": 12, "md": 4},
                                "content": [
                                    {
                                        "component": "VTextField",
                                        "props": {
                                            "model": "release_name_template",
                                            "label": "名称标签模板",
                                            "placeholder": "{title} | {resolution}{fps_part} | {audio} | {release_tag} | {group}",
                                        },
                                    }
                                ],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 4},
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
                                "props": {"cols": 12, "md": 4},
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
                                "props": {"cols": 12, "md": 4},
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
                                "props": {"cols": 12, "md": 4},
                                "content": [
                                    {
                                        "component": "VTextField",
                                        "props": {
                                            "model": "qb_poll_interval",
                                            "label": "Qbittorrent 轮询间隔（秒）",
                                            "type": "number",
                                            "min": 5,
                                            "placeholder": "15",
                                        },
                                    }
                                ],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 4},
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
                                "props": {"cols": 12, "md": 4},
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
                                            "auto-grow": False,
                                            "no-resize": True,
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
                                            "auto-grow": False,
                                            "no-resize": True,
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
            "qb_poll_interval": 15,
            "external_notify_enabled": True,
            "external_notify_token": "",
            "moviepilot_base_url": "http://moviepilot:3001",
            "qb_downloader_name": "Qbittorrent",
            "downloader_label_name": "",
            "header_image_url": "",
            "qb_auto_tag_enabled": True,
            "qb_web_url": "",
            "qb_username": "",
            "qb_password": "",
            "qb_tag_name": "MOVIEPILOT",
            "release_name_template": "{title} | {resolution}{fps_part} | {audio} | {release_tag} | {group}",
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
        return [
            {
                "component": "VForm",
                "content": [
                    {
                        "component": "VRow",
                        "content": [
                            self._page_switch("enabled", "启用插件", self._enabled, 4),
                            self._page_switch(
                                "qb_poll_enabled",
                                "轮询 Qbittorrent 手动添加任务",
                                self._qb_poll_enabled,
                                4,
                            ),
                            self._page_switch(
                                "qb_auto_tag_enabled",
                                "自动给任务打标签",
                                self._qb_auto_tag_enabled,
                                4,
                            ),
                            self._page_text("qb_web_url", "qBittorrent Web 地址", self._qb_web_url, 4),
                            self._page_text("qb_username", "qBittorrent 用户名", self._qb_username, 4),
                            self._page_text("qb_password", "qBittorrent 密码", self._qb_password, 4, "password"),
                            self._page_text("qb_tag_name", "自动标签名称", self._qb_tag_name, 4),
                            self._page_text("moviepilot_base_url", "MoviePilot 地址", self._moviepilot_base_url, 4),
                            self._page_text("qb_downloader_name", "下载器名称", self._qb_downloader_name, 4),
                            self._page_text("downloader_label_name", "下载器标签名称", self._downloader_label_name, 4),
                            self._page_text("qb_poll_interval", "轮询间隔（秒）", self._qb_poll_interval, 4),
                            self._page_text("notify_stage", "通知时机", self._format_notify_stage(), 4),
                            self._page_text("notify_type", "通知类型", self._notify_type, 4),
                            self._page_text("only_downloader", "只通知下载器", self._only_downloader or "全部", 4),
                            self._page_text("release_name_template", "名称标签模板", self._release_name_template, 4),
                            self._page_text("header_image_url", "推送头图 URL", self._header_image_url or "未设置", 4),
                            self._page_switch(
                                "external_notify_enabled",
                                "外部程序通知接口",
                                self._external_notify_enabled,
                                4,
                            ),
                            self._page_text("external_notify_token", "外部通知 Token", self._external_notify_token, 4),
                            self._page_textarea(
                                "qb_added_command",
                                "qBittorrent 添加种子时运行外部程序",
                                self._build_qb_command("added"),
                                True,
                            ),
                            self._page_textarea(
                                "qb_completed_command",
                                "qBittorrent 完成下载时运行外部程序",
                                self._build_qb_command("completed"),
                                True,
                            ),
                        ],
                    }
                ],
            }
        ]

    @staticmethod
    def _page_col(content: dict, md: int = 6) -> dict:
        return {
            "component": "VCol",
            "props": {"cols": 12, "md": md},
            "content": [content],
        }

    @classmethod
    def _page_switch(cls, model: str, label: str, value: bool, md: int = 4) -> dict:
        return cls._page_col(
            {
                "component": "VSwitch",
                "props": {
                    "model": model,
                    "label": label,
                    "model-value": bool(value),
                    "readonly": True,
                },
            },
            md,
        )

    @classmethod
    def _page_text(cls, model: str, label: str, value: Any, md: int = 6, field_type: Optional[str] = None) -> dict:
        props = {
            "model": model,
            "label": label,
            "model-value": cls._display_page_value(value),
            "density": "compact",
            "readonly": True,
        }
        if field_type:
            props["type"] = field_type
        return cls._page_col(
            {
                "component": "VTextField",
                "props": props,
            },
            md,
        )

    @classmethod
    def _page_textarea(cls, model: str, label: str, value: Any, readonly: bool = False) -> dict:
        props = {
            "model": model,
            "label": label,
            "model-value": cls._display_page_value(value),
            "rows": 2,
            "auto-grow": False,
            "density": "compact",
            "no-resize": True,
        }
        if readonly:
            props["readonly"] = True
        return cls._page_col(
            {
                "component": "VTextarea",
                "props": props,
            },
            12,
        )

    @staticmethod
    def _display_page_value(value: Any) -> str:
        if value in (None, ""):
            return ""
        return str(value)

    def _mask_token(self) -> str:
        if not self._external_notify_token:
            return "未生成"
        token = self._external_notify_token
        if len(token) <= 8:
            return "已生成"
        return f"{token[:4]}...{token[-4:]}"

    def _format_notify_stage(self) -> str:
        return {
            "download_added": "添加下载任务时",
            "transfer_complete": "文件整理完成时",
            "both": "两者都通知",
        }.get(self._notify_stage, self._notify_stage or "")

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

    @classmethod
    def _moviepilot_parse(cls, title: Any, file_names: Any = None, path: Any = None) -> Dict[str, str]:
        try:
            from app.core.metainfo import MetaInfo, MetaInfoPath
        except Exception:
            return {}

        result: Dict[str, str] = {}
        meta = None
        title_text = cls._clean_message_value(title)
        try:
            if title_text:
                meta = MetaInfo(title_text)
        except Exception as err:
            logger.warn(f"{cls.plugin_name}: MoviePilot MetaInfo 解析标题失败 - {err}")

        file_metas = []
        for file_name in cls._trusted_episode_values(file_names):
            file_text = cls._clean_message_value(file_name)
            if not file_text:
                continue
            try:
                file_metas.append(MetaInfo(file_text))
            except Exception as err:
                logger.warn(f"{cls.plugin_name}: MoviePilot MetaInfo 解析文件名失败 - {err}")

        path_text = cls._clean_message_value(path)
        if path_text:
            try:
                from pathlib import Path

                path_meta = MetaInfoPath(Path(path_text))
                if path_meta and cls._meta_title(path_meta):
                    meta = path_meta if not meta else meta
                if path_meta:
                    file_metas.append(path_meta)
            except Exception:
                pass

        if meta:
            result.update(cls._moviepilot_meta_to_dict(meta))
            if not result.get("title") or not result.get("year"):
                recognized = cls._moviepilot_recognize(meta)
                if recognized:
                    result.update({key: value for key, value in recognized.items() if value})

        local_release = cls._parse_release_name(title_text)
        local_title = cls._strip_title_brackets(local_release.get("title_zh") or "") if local_release else ""
        if local_title and cls._has_cjk(local_title):
            result["title"] = local_title

        title_episode = cls._extract_explicit_episode_text(title_text)
        episode = title_episode or cls._moviepilot_episode_from_metas(file_metas) or cls._moviepilot_episode_from_meta(meta)
        if episode:
            result["episode"] = episode
        if file_metas:
            for key in ("quality", "audio", "group"):
                if not result.get(key):
                    for item in file_metas:
                        value = cls._moviepilot_meta_to_dict(item).get(key)
                        if value:
                            result[key] = value
                            break
        return {key: value for key, value in result.items() if value}

    @classmethod
    def _select_episode(cls, title: Any, local_episode: Any = None, moviepilot_episode: Any = None) -> Optional[str]:
        title_episode = cls._extract_explicit_episode_text(title)
        if title_episode:
            return title_episode
        mp_episode = cls._format_episode_text(moviepilot_episode)
        if mp_episode:
            return mp_episode
        local_text = cls._format_episode_text(local_episode)
        if local_text:
            return local_text
        return cls._clean_message_value(local_episode) or cls._clean_message_value(moviepilot_episode)

    @classmethod
    def _best_media_title(cls, title: Any, *candidates: Any) -> Optional[str]:
        release_info = cls._parse_release_name(title) or {}
        values = [
            cls._strip_title_brackets(release_info.get("title_zh") or ""),
            *candidates,
            release_info.get("title_en"),
        ]
        cleaned = [cls._clean_message_value(value) for value in values]
        cleaned = [value for value in cleaned if value]
        for value in cleaned:
            if cls._has_cjk(value):
                return value
        return cleaned[0] if cleaned else None

    @classmethod
    def _compact_name_with_moviepilot(cls, title: Any, mp_info: Dict[str, str], episode: Any = None) -> Optional[str]:
        release_info = cls._parse_release_name(title)
        if release_info:
            merged = dict(release_info)
            mp_title = cls._clean_message_value((mp_info or {}).get("title"))
            if mp_title:
                if cls._has_cjk(mp_title):
                    merged["title_zh"] = mp_title
                elif not merged.get("title_zh"):
                    merged["title_en"] = mp_title
            if (mp_info or {}).get("year"):
                merged["year"] = mp_info["year"]
            if (mp_info or {}).get("quality") and not merged.get("resolution"):
                merged["resolution"] = mp_info["quality"]
            if (mp_info or {}).get("audio") and (
                not merged.get("audio")
                or re.match(r"^\d+\s*Audio$", str(merged.get("audio")), re.IGNORECASE)
            ):
                merged["audio"] = mp_info["audio"]
            if (mp_info or {}).get("group") and not merged.get("group"):
                merged["group"] = mp_info["group"]
            formatted = cls._format_release_name_by_template(merged)
            if formatted:
                return formatted
        return cls._compact_name(title, episode=episode) or cls._moviepilot_compact_name(mp_info)

    @classmethod
    def _moviepilot_meta_to_dict(cls, meta: Any) -> Dict[str, str]:
        if not meta:
            return {}
        return {
            "title": cls._meta_title(meta),
            "year": cls._clean_message_value(getattr(meta, "year", None)),
            "episode": cls._moviepilot_episode_from_meta(meta),
            "quality": cls._clean_message_value(getattr(meta, "resource_pix", None)),
            "audio": cls._clean_message_value(getattr(meta, "audio_term", None) or getattr(meta, "audio_encode", None)),
            "group": cls._clean_message_value(getattr(meta, "release_group", None) or getattr(meta, "resource_team", None)),
            "category": cls._moviepilot_category(getattr(meta, "type", None)),
        }

    @classmethod
    def _moviepilot_recognize(cls, meta: Any) -> Dict[str, str]:
        try:
            from app.chain.media import MediaChain
        except Exception:
            return {}
        try:
            mediainfo = MediaChain().recognize_by_meta(meta, obtain_images=False)
        except Exception as err:
            logger.warn(f"{cls.plugin_name}: MoviePilot MediaChain 识别失败 - {err}")
            return {}
        if not mediainfo:
            return {}
        media_data = cls._to_dict(mediainfo)
        return {
            "title": cls._first_value(media_data, "title", "title_year") or cls._clean_message_value(getattr(mediainfo, "title", None)),
            "year": cls._first_value(media_data, "year") or cls._clean_message_value(getattr(mediainfo, "year", None)),
            "category": cls._format_category(cls._first_value(media_data, "type")),
        }

    @classmethod
    def _moviepilot_episode_from_metas(cls, metas: List[Any]) -> Optional[str]:
        pairs = []
        season = None
        for meta in metas or []:
            item_season = cls._to_positive_int(getattr(meta, "begin_season", None))
            begin_episode = cls._to_positive_int(getattr(meta, "begin_episode", None))
            end_episode = cls._to_positive_int(getattr(meta, "end_episode", None))
            season = season or item_season
            if begin_episode and end_episode and end_episode >= begin_episode:
                pairs.extend((item_season, episode) for episode in range(begin_episode, end_episode + 1))
            elif begin_episode:
                pairs.append((item_season, begin_episode))
        if pairs:
            return cls._format_episode_pairs(pairs, season)
        return None

    @classmethod
    def _moviepilot_episode_from_meta(cls, meta: Any) -> Optional[str]:
        if not meta:
            return None
        season = cls._to_positive_int(getattr(meta, "begin_season", None))
        begin_episode = cls._to_positive_int(getattr(meta, "begin_episode", None))
        end_episode = cls._to_positive_int(getattr(meta, "end_episode", None))
        if begin_episode and end_episode and end_episode >= begin_episode:
            if season:
                return f"S{season:02d}E{begin_episode:02d}-E{end_episode:02d}"
            return f"E{begin_episode:02d}-E{end_episode:02d}"
        if begin_episode:
            if season:
                return f"S{season:02d}E{begin_episode:02d}"
            return f"E{begin_episode:02d}"
        season_episode = cls._clean_message_value(getattr(meta, "season_episode", None))
        if season_episode:
            return season_episode.replace(" ", "").upper()
        return None

    @classmethod
    def _moviepilot_compact_name(cls, info: Dict[str, str]) -> Optional[str]:
        if not info or not info.get("title"):
            return None
        parts = [
            info.get("title"),
            info.get("quality"),
            info.get("audio"),
            info.get("group"),
        ]
        return " | ".join(str(part).strip() for part in parts if part)

    @classmethod
    def _meta_title(cls, meta: Any) -> Optional[str]:
        if not meta:
            return None
        for attr in ("name", "cn_name", "en_name", "original_name"):
            try:
                value = getattr(meta, attr, None)
            except Exception:
                value = None
            text = cls._clean_message_value(value)
            if text:
                return text
        return None

    @classmethod
    def _moviepilot_category(cls, media_type: Any) -> Optional[str]:
        text = cls._clean_message_value(getattr(media_type, "value", media_type))
        if not text:
            return None
        if text.lower() in ("unknown", "mediatype.unknown", "未知"):
            return None
        if text.lower() in ("movie", "movies"):
            return "电影"
        if text.lower() in ("tv", "series", "电视剧"):
            return "剧集"
        return text

    def _add_qb_tag(self, torrent_hash: Optional[str]):
        if not self._qb_auto_tag_enabled:
            return
        if not torrent_hash:
            logger.warn(f"{self.plugin_name}: 未获取到 Info Hash，跳过自动打标签")
            return
        if not self._qb_web_url or not self._qb_username or not self._qb_password:
            logger.warn(f"{self.plugin_name}: qBittorrent Web API 配置不完整，跳过自动打标签")
            return

        base_url = self._qb_web_url.rstrip("/")
        tag_name = self._qb_tag_name or "MOVIEPILOT"
        try:
            login_data = urlencode({
                "username": self._qb_username,
                "password": self._qb_password,
            }).encode()
            login_request = UrlRequest(
                f"{base_url}/api/v2/auth/login",
                data=login_data,
                method="POST",
            )
            with urlopen(login_request, timeout=3) as response:
                cookie = response.headers.get("Set-Cookie", "").split(";", 1)[0]
                login_body = response.read().decode(errors="ignore").strip()

            if not cookie or login_body.lower().startswith("fails"):
                logger.error(f"{self.plugin_name}: qBittorrent 登录失败，无法自动打标签")
                return

            tag_data = urlencode({
                "hashes": torrent_hash,
                "tags": tag_name,
            }).encode()
            tag_request = UrlRequest(
                f"{base_url}/api/v2/torrents/addTags",
                data=tag_data,
                headers={"Cookie": cookie},
                method="POST",
            )
            with urlopen(tag_request, timeout=3) as response:
                response.read()

            logger.info(f"{self.plugin_name}: 已尝试为 {torrent_hash} 添加 qBittorrent 标签 {tag_name}")
        except Exception as err:
            logger.error(f"{self.plugin_name}: 自动添加 qBittorrent 标签失败 - {err}", exc_info=True)

    def _qb_torrent_file_names_if_needed(self, torrent_hash: Optional[str], title: Any, *known_values: Any) -> List[str]:
        release_info = self._parse_release_name(title)
        if not release_info or not release_info.get("season") or release_info.get("episode"):
            return []
        if self._extract_episode(title, *known_values):
            return []
        return self._qb_torrent_file_names(torrent_hash)

    def _qb_torrent_file_names(self, torrent_hash: Optional[str]) -> List[str]:
        if not torrent_hash or not self._qb_web_url or not self._qb_username or not self._qb_password:
            return []

        base_url = self._qb_web_url.rstrip("/")
        try:
            login_data = urlencode({
                "username": self._qb_username,
                "password": self._qb_password,
            }).encode()
            login_request = UrlRequest(
                f"{base_url}/api/v2/auth/login",
                data=login_data,
                method="POST",
            )
            with urlopen(login_request, timeout=2) as response:
                cookie = response.headers.get("Set-Cookie", "").split(";", 1)[0]
                login_body = response.read().decode(errors="ignore").strip()
            if not cookie or login_body.lower().startswith("fails"):
                return []

            files_url = f"{base_url}/api/v2/torrents/files?{urlencode({'hash': torrent_hash})}"
            files_request = UrlRequest(files_url, headers={"Cookie": cookie}, method="GET")
            with urlopen(files_request, timeout=2) as response:
                files = json.loads(response.read().decode(errors="ignore") or "[]")
            if not isinstance(files, list):
                return []
            names = []
            for item in files:
                if isinstance(item, dict):
                    name = item.get("name")
                else:
                    name = str(item)
                if name:
                    path_text = str(name)
                    base_name = os.path.basename(path_text)
                    ext = os.path.splitext(base_name)[1].lower()
                    if ext in self._video_extensions:
                        names.append(base_name)
            return names
        except Exception as err:
            logger.warn(f"{self.plugin_name}: 获取 qBittorrent 文件列表失败 - {err}")
            return []

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
            "--data-urlencode \"tracker=%T\" "
            "--data-urlencode \"content_path=%F\""
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
                    lines.append(cls._format_name_line(label_text, value))
                else:
                    lines.append(f"{label_text}： {text}")
        return lines

    @classmethod
    def _format_name_line(cls, label: str, value: Any) -> str:
        text = cls._clean_multiline_message_value(value)
        if not text:
            return ""
        return f"{label}：{text}"

    @classmethod
    def _clean_multiline_message_value(cls, value: Any) -> Optional[str]:
        if value in (None, ""):
            return None
        text = cls._stringify(value).strip()
        if not text:
            return None
        lines = [" ".join(line.strip().split()) for line in text.splitlines()]
        return "\n".join(line for line in lines if line)

    @staticmethod
    def _format_wrapped_line(label: str, text: str, max_width: int = 36) -> str:
        prefix = f"{label}： "
        if DownloadAddedNotify._display_width(text) <= max_width:
            return f"{prefix}{text}"
        indent = " " * len(prefix)
        chunks = DownloadAddedNotify._wrap_text_by_width(text, max_width)
        return prefix + ("\n" + indent).join(chunks)

    @staticmethod
    def _wrap_text_by_width(text: str, max_width: int) -> List[str]:
        chunks = []
        current = text.strip()
        while current:
            if DownloadAddedNotify._display_width(current) <= max_width:
                chunks.append(current)
                break
            split_at = DownloadAddedNotify._best_wrap_index(current, max_width)
            chunks.append(current[:split_at].rstrip(" ._-|"))
            current = current[split_at:].lstrip(" ._-|")
        return [chunk for chunk in chunks if chunk]

    @staticmethod
    def _best_wrap_index(text: str, max_width: int) -> int:
        width = 0
        hard_limit = 0
        best = 0
        for index, char in enumerate(text):
            char_width = DownloadAddedNotify._char_display_width(char)
            if width + char_width > max_width:
                break
            width += char_width
            hard_limit = index + 1
            if char in (" ", ".", "-", "_", "·", "、"):
                best = index + 1
        if best >= max(8, hard_limit * 2 // 3):
            return best
        return max(hard_limit, 1)

    @staticmethod
    def _display_width(text: str) -> int:
        return sum(DownloadAddedNotify._char_display_width(char) for char in text)

    @staticmethod
    def _char_display_width(char: str) -> int:
        return 2 if re.match(r"[\u4e00-\u9fff\uff00-\uffef]", char) else 1

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
        release_info = cls._parse_release_name(title)
        media_text = cls._clean_message_value(media_title)
        episode_text = cls._format_episode_text(episode) or cls._extract_episode(title)
        if release_info:
            base_title = media_text or release_info.get("title_zh") or release_info.get("title_en")
            release_year = year or release_info.get("year") or cls._extract_year(title)
            base = cls._ensure_title_year(base_title, release_year)
            release_episode = cls._release_episode_text(release_info, episode_text)
            return cls._join_title_parts(base, release_episode, event_text)
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
        text = cls._strip_title_brackets(text)
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

    @classmethod
    def _release_episode_text(cls, info: Dict[str, str], fallback_episode: Optional[str] = None) -> Optional[str]:
        season = info.get("season")
        episode = info.get("episode")
        episode_end = info.get("episode_end")
        if season and episode and episode_end:
            return f"{season.upper()}E{int(episode):02d}-E{int(episode_end):02d}"
        if season and episode:
            return cls._format_season_episode(season.lstrip("S"), episode)
        if season and fallback_episode:
            if re.match(r"^S\d{2}E\d{2,3}$", fallback_episode, re.IGNORECASE):
                return fallback_episode.upper()
            if re.match(r"^E\d{2,3}$", fallback_episode, re.IGNORECASE):
                return f"{season.upper()}{fallback_episode.upper()}"
            return fallback_episode
        if season:
            return season.upper()
        return None

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
    def _trusted_episode_values(cls, value: Any) -> List[Any]:
        if value in (None, ""):
            return []
        if isinstance(value, dict):
            values = []
            for key in cls._episode_text_keys:
                item = value.get(key)
                if item not in (None, ""):
                    values.append(item)
            return values
        if isinstance(value, (list, tuple, set)):
            return list(value)
        return [value]

    @classmethod
    def _extract_explicit_episode_text(cls, value: Any) -> Optional[str]:
        if value in (None, ""):
            return None
        if isinstance(value, dict):
            for item in cls._trusted_episode_values(value):
                explicit = cls._extract_explicit_episode_text(item)
                if explicit:
                    return explicit
            return None
        if isinstance(value, (list, tuple, set)):
            for item in value:
                explicit = cls._extract_explicit_episode_text(item)
                if explicit:
                    return explicit
            return None

        text = cls._clean_message_value(value)
        if not text:
            return None

        range_match = re.search(
            r"\bS(?:eason)?\s*0?(\d{1,2})\s*[-_. ]*\s*(?:E|EP|Episode)\s*0?(\d{1,3})"
            r"\s*(?:-|~|–|—|至|到)\s*(?:E|EP|Episode)?\s*0?(\d{1,3})\b",
            text,
            re.IGNORECASE,
        )
        if range_match:
            season = int(range_match.group(1))
            start = int(range_match.group(2))
            end = int(range_match.group(3))
            if end >= start:
                return f"S{season:02d}E{start:02d}-E{end:02d}"

        list_match = re.search(
            r"\bS(?:eason)?\s*0?(\d{1,2})\s*[-_. ]*\s*(?:E|EP|Episode)\s*0?(\d{1,3})"
            r"(?P<tail>(?:\s*[,，]\s*(?:E|EP|Episode)?\s*0?\d{1,3})+)",
            text,
            re.IGNORECASE,
        )
        if list_match:
            season = int(list_match.group(1))
            episodes = [int(list_match.group(2))]
            episodes.extend(int(item) for item in re.findall(r"(?:E|EP|Episode)?\s*0?(\d{1,3})", list_match.group("tail"), re.IGNORECASE))
            episodes = sorted(dict.fromkeys(episodes))
            if episodes == list(range(min(episodes), max(episodes) + 1)):
                return f"S{season:02d}E{min(episodes):02d}-E{max(episodes):02d}"
            return f"S{season:02d}" + ",".join(f"E{episode:02d}" for episode in episodes)

        season_match = re.search(r"\bS(?:eason)?\s*0?(\d{1,2})\b", text, re.IGNORECASE)
        total_match = re.search(r"(?:全|共)\s*(\d{1,3})\s*[集话]|全集|全季|Complete", text, re.IGNORECASE)
        if season_match and total_match:
            season = int(season_match.group(1))
            if total_match.group(1):
                return f"S{season:02d}E01-E{int(total_match.group(1)):02d}"
            return f"S{season:02d} 全集"

        return None

    @classmethod
    def _extract_episode_summary(cls, *values: Any) -> Optional[str]:
        for value in values:
            explicit_episode = cls._extract_explicit_episode_text(value)
            if explicit_episode:
                return explicit_episode
        season_hint = None
        episode_pairs = []
        for value in values:
            season_hint = season_hint or cls._extract_season_number(value)
        for value in values:
            episode_pairs.extend(cls._collect_episode_pairs(value, season_hint))
        if not episode_pairs:
            return cls._extract_episode(*values)
        return cls._format_episode_pairs(episode_pairs, season_hint)

    @classmethod
    def _extract_episode_candidate(cls, value: Any) -> Optional[str]:
        if value in (None, ""):
            return None
        if isinstance(value, (list, tuple, set)):
            pairs = cls._collect_episode_pairs(value)
            if pairs:
                return cls._format_episode_pairs(pairs)
            return None
        if isinstance(value, dict):
            for item in cls._trusted_episode_values(value):
                candidate = cls._extract_episode_candidate(item)
                if candidate:
                    return candidate
            return None
        return cls._extract_episode_from_value(value)

    @classmethod
    def _resolve_episode(cls, title: Any, file_names: Any = None, *other_sources: Any) -> Optional[str]:
        explicit_title = cls._extract_explicit_episode_text(title)
        if explicit_title:
            return explicit_title

        file_candidate = cls._extract_episode_candidate(file_names)
        if file_candidate:
            return file_candidate

        for source in other_sources:
            if isinstance(source, str):
                source_text = source.replace("\\", "/").rstrip("/")
                ext = os.path.splitext(os.path.basename(source_text))[1].lower()
                if ext in cls._video_extensions:
                    candidate = cls._extract_episode_candidate(source)
                    if candidate:
                        return candidate

        for source in other_sources:
            explicit = cls._extract_explicit_episode_text(source)
            if explicit:
                return explicit

        for source in other_sources:
            candidate = cls._extract_episode_candidate(source)
            if candidate:
                return candidate
        return None

    @classmethod
    def _format_episode_pairs(cls, episode_pairs: List[tuple], season_hint: Optional[int] = None) -> Optional[str]:
        if not episode_pairs:
            return None

        unique = []
        seen = set()
        for season, episode in episode_pairs:
            key = (season or 0, episode)
            if key not in seen:
                seen.add(key)
                unique.append(key)
        unique.sort()
        seasons = {season for season, _ in unique if season}
        episodes = [episode for _, episode in unique]
        season = next(iter(seasons)) if len(seasons) == 1 else (season_hint if season_hint else None)
        if len(unique) == 1:
            only_season, only_episode = unique[0]
            return cls._format_season_episode(only_season, only_episode) if only_season else f"E{only_episode:02d}"
        if season:
            if episodes == list(range(min(episodes), max(episodes) + 1)):
                return f"S{season:02d}E{min(episodes):02d}-E{max(episodes):02d}"
            dominant_run = cls._dominant_episode_run(episodes)
            if dominant_run:
                return f"S{season:02d}E{dominant_run[0]:02d}-E{dominant_run[-1]:02d}"
            return f"S{season:02d}" + ",".join(f"E{episode:02d}" for episode in episodes)
        if episodes == list(range(min(episodes), max(episodes) + 1)):
            return f"E{min(episodes):02d}-E{max(episodes):02d}"
        dominant_run = cls._dominant_episode_run(episodes)
        if dominant_run:
            return f"E{dominant_run[0]:02d}-E{dominant_run[-1]:02d}"
        return ",".join(f"E{episode:02d}" for episode in episodes)

    @staticmethod
    def _dominant_episode_run(episodes: List[int]) -> Optional[List[int]]:
        if len(episodes) < 5:
            return None

        runs = []
        current = [episodes[0]]
        for episode in episodes[1:]:
            if episode == current[-1] + 1:
                current.append(episode)
            else:
                runs.append(current)
                current = [episode]
        runs.append(current)

        longest = max(runs, key=len)
        outliers = [episode for episode in episodes if episode not in set(longest)]
        if len(longest) < 4 or len(outliers) != 1:
            return None

        outlier = outliers[0]
        nearest_gap = min(abs(outlier - longest[0]), abs(outlier - longest[-1]))
        if nearest_gap >= 3:
            return longest
        return None

    @classmethod
    def _collect_episode_pairs(cls, value: Any, season_hint: Optional[int] = None) -> List[tuple]:
        if value in (None, ""):
            return []
        if isinstance(value, dict):
            pairs = []
            season = cls._extract_season_number(value) or season_hint
            for item in cls._trusted_episode_values(value):
                pairs.extend(cls._collect_episode_pairs(item, season))
            return pairs
        if isinstance(value, (list, tuple, set)):
            pairs = []
            for item in value:
                pairs.extend(cls._collect_episode_pairs(item, season_hint))
            return pairs

        text = cls._stringify(value)
        if "/" in text or "\\" in text:
            text = text.replace("\\", "/").rstrip("/")
            base_name = os.path.basename(text)
            ext = os.path.splitext(base_name)[1].lower()
            if ext and ext in cls._video_extensions:
                text = base_name
            else:
                return []
        pairs = []
        for match in re.finditer(
            r"\bS(?:eason)?\s*0?(\d{1,2})\s*[-_. ]*\s*(?:E|EP|Episode)\s*0?(\d{1,3})\b",
            text,
            re.IGNORECASE,
        ):
            pairs.append((int(match.group(1)), int(match.group(2))))
        for match in re.finditer(r"\b0?(\d{1,2})\s*x\s*0?(\d{1,3})\b", text, re.IGNORECASE):
            pairs.append((int(match.group(1)), int(match.group(2))))
        if pairs:
            return pairs

        local_season = cls._extract_season_number(text) or season_hint
        for match in re.finditer(r"\b(?:E|EP|Episode)\s*0?(\d{1,3})\b", text, re.IGNORECASE):
            pairs.append((local_season, int(match.group(1))))
        for match in re.finditer(r"第\s*(\d+)\s*[集话]", text):
            pairs.append((local_season, int(match.group(1))))
        return pairs

    @classmethod
    def _extract_episode_from_value(cls, value: Any) -> Optional[str]:
        if value in (None, ""):
            return None
        if isinstance(value, (list, tuple, set)):
            pairs = cls._collect_episode_pairs(value)
            if not pairs:
                return None
            return cls._format_episode_pairs(pairs)
        if isinstance(value, dict):
            for item in cls._trusted_episode_values(value):
                extracted = cls._extract_episode_from_value(item)
                if extracted:
                    return extracted
            return None

        text = cls._stringify(value)
        if "/" in text or "\\" in text:
            text = text.replace("\\", "/").rstrip("/")
            base_name = os.path.basename(text)
            ext = os.path.splitext(base_name)[1].lower()
            if ext and ext in cls._video_extensions:
                text = base_name
            else:
                return None
        explicit = cls._extract_explicit_episode_text(text)
        if explicit:
            return explicit
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
            for item in cls._trusted_episode_values(value):
                found = cls._extract_season_number(item)
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
            for item in cls._trusted_episode_values(value):
                raw = cls._extract_episode_number(item)
                if raw:
                    return raw
            return None
        match = re.search(r"\b(?:E|EP|Episode)\s*0?(\d{1,3})\b", str(value), re.IGNORECASE)
        if match:
            return int(match.group(1))
        match = re.search(r"第\s*(\d+)\s*[集话]", str(value))
        return int(match.group(1)) if match else None

    @classmethod
    def _extract_episode_from_download_path(cls, value: Any) -> Optional[str]:
        path = cls._clean_message_value(value)
        if not path:
            return None
        normalized_path = path.replace("\\", "/").rstrip("/")
        base_name = os.path.basename(normalized_path)
        ext = os.path.splitext(base_name)[1].lower()
        if ext in cls._video_extensions:
            episode = cls._extract_episode_from_value(base_name)
            if episode:
                return episode
        if not os.path.exists(path):
            return None
        if os.path.isfile(path):
            return cls._extract_episode_from_value(base_name)
        if not os.path.isdir(path):
            return None

        candidates = cls._download_path_candidates(path)
        for name in candidates:
            episode = cls._extract_episode_from_value(name)
            if episode:
                return episode
        return None

    @classmethod
    def _download_path_candidates(cls, root: str, max_depth: int = 2, max_items: int = 300) -> List[str]:
        candidates = []
        stack = [(root, 0)]
        scanned = 0
        while stack and scanned < max_items:
            current, depth = stack.pop(0)
            try:
                entries = sorted(os.scandir(current), key=lambda item: item.name.lower())
            except (OSError, PermissionError):
                continue
            for entry in entries:
                scanned += 1
                if scanned > max_items:
                    break
                name = entry.name
                try:
                    if entry.is_file():
                        ext = os.path.splitext(name)[1].lower()
                        if ext in cls._video_extensions:
                            candidates.insert(0, name)
                        else:
                            candidates.append(name)
                    elif entry.is_dir() and depth < max_depth:
                        candidates.append(name)
                        stack.append((entry.path, depth + 1))
                except (OSError, PermissionError):
                    continue
        return candidates

    @staticmethod
    def _format_episode_text(value: Any) -> Optional[str]:
        if value in (None, ""):
            return None
        text = str(value)
        if re.match(r"^S\d{2}E\d{2,3}$", text, re.IGNORECASE):
            return text.upper()
        if re.match(r"^S\d{2}E\d{2,3}-E\d{2,3}$", text, re.IGNORECASE):
            return text.upper()
        if re.match(r"^S\d{2}(?:E\d{2,3},)+E\d{2,3}$", text, re.IGNORECASE):
            return text.upper()
        if re.match(r"^E\d{2,3}$", text, re.IGNORECASE):
            return text.upper()
        if re.match(r"^E\d{2,3}-E\d{2,3}$", text, re.IGNORECASE):
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
    def _compact_name(cls, value: Any, max_len: int = 96, episode: Any = None) -> Optional[str]:
        pretty_name = cls._format_release_name(value, episode=episode)
        if pretty_name:
            return pretty_name
        text = cls._clean_message_value(value)
        if not text:
            return None
        text = re.sub(r"\s+", " ", text).strip()
        if len(text) <= max_len:
            return text
        return f"{text[:max_len - 3].rstrip()}..."

    @classmethod
    def _format_release_name(cls, value: Any, episode: Any = None) -> Optional[str]:
        info = cls._parse_release_name(value)
        if not info:
            return None
        return cls._format_release_name_by_template(info)

    @classmethod
    def _format_release_name_by_template(cls, info: Dict[str, str]) -> Optional[str]:
        variables = cls._release_name_variables(info)
        template = cls._release_name_template or "{title} | {resolution}{fps_part} | {audio} | {release_tag} | {group}"

        def replace_var(match: re.Match) -> str:
            return variables.get(match.group(1), "") or ""

        text = re.sub(r"\{([a-zA-Z0-9_]+)\}", replace_var, template)
        parts = [re.sub(r"\s+", " ", part).strip(" -_/") for part in text.split("|")]
        return " | ".join(part for part in parts if part) or None

    @classmethod
    def _release_name_variables(cls, info: Dict[str, str]) -> Dict[str, str]:
        title = cls._strip_title_brackets(info.get("title_zh") or info.get("title_en") or "")
        audio = cls._format_release_audio(info.get("audio")) or ""
        group = cls._format_release_group(info.get("group")) or ""
        release_tag = cls._format_release_tag(info) or ""
        fps = info.get("fps") or ""
        return {
            "title": title,
            "title_zh": cls._strip_title_brackets(info.get("title_zh") or ""),
            "title_en": info.get("title_en") or "",
            "year": info.get("year") or "",
            "season": info.get("season") or "",
            "episode": f"E{int(info['episode']):02d}" if info.get("episode") else "",
            "resolution": info.get("resolution") or "",
            "source": info.get("source") or "",
            "codec": info.get("codec") or "",
            "quality": info.get("quality") or "",
            "fps": fps,
            "fps_part": f" {fps}" if fps else "",
            "audio": audio,
            "group": group,
            "release_tag": release_tag,
        }

    @staticmethod
    def _format_release_audio(value: Any) -> Optional[str]:
        if not value:
            return None
        text = str(value).strip()
        text = re.sub(r"(\d)\.(\d)", r"\1__DOT__\2", text)
        text = text.replace(".", " ").replace("__DOT__", ".")
        text = re.sub(r"^(DTS-HD)\.MA\.(\d(?:\.\d)?)$", r"\1 MA \2", text, flags=re.IGNORECASE)
        match = re.search(
            r"((?:Atmos\s+)?DTS-HD(?:\s+MA)?(?:\s+\d(?:\.\d)?)?|"
            r"(?:Atmos\s+)?TrueHD(?:\s+\d(?:\.\d)?)?|"
            r"DTS\d(?:\.\d)?|DDP?\d(?:\.\d)?|AAC|AC3)",
            text,
            re.IGNORECASE,
        )
        return match.group(1) if match else text

    @staticmethod
    def _format_release_group(value: Any) -> Optional[str]:
        if not value:
            return None
        text = str(value).strip()
        if "@" in text:
            text = text.rsplit("@", 1)[-1]
        return text or None

    @classmethod
    def _format_release_tag(cls, info: Dict[str, str]) -> Optional[str]:
        release_tag = info.get("release_tag")
        if release_tag:
            return release_tag
        audio = info.get("audio")
        codec = info.get("codec")
        group = info.get("group")
        if codec and group and "@" in str(group):
            group_prefix = str(group).split("@", 1)[0]
            if (
                re.match(r"^(H\.?26[45]|x26[45])$", str(codec), re.IGNORECASE)
                and re.match(r"^[A-Za-z0-9]+$", group_prefix)
            ):
                return f"{codec}-{group_prefix}"
        if (
            audio
            and group
            and "@" in str(group)
            and re.match(r"^(H\.?26[45]|HEVC|AVC|x26[45])$", str(audio), re.IGNORECASE)
        ):
            return f"{audio}-{str(group).split('@', 1)[0]}"
        return None

    @classmethod
    def _format_category(cls, category: Any, title: Any = None) -> Optional[str]:
        text = cls._clean_message_value(category)
        release_info = cls._parse_release_name(title)
        if release_info and release_info.get("year") and not release_info.get("season"):
            return "电影"
        return text

    @classmethod
    def _parse_release_name(cls, value: Any) -> Optional[Dict[str, str]]:
        text = cls._clean_message_value(value)
        if not text:
            return None
        basename = os.path.basename(text)
        root, ext = os.path.splitext(basename)
        if ext.lower() in cls._video_extensions:
            basename = root
        basename = re.sub(
            r"^[\[\【]\s*(?P<title_zh>[\u4e00-\u9fff][^\]\】]+?)\s*[\]\】]\s*(?P<title_en>[A-Za-z][^.]+)\.",
            r"\g<title_zh>.\g<title_en>.",
            basename,
        )
        base_pattern = (
            r"(?P<year>\d{4})\."
            r"(?P<resolution>\d{3,4}p)\."
            r"(?P<source>[^.]+)\."
            r"(?P<codec>[^.]+)"
            r"(?:\.(?P<quality>[^.]+))?"
            r"(?:\.(?P<fps>\d+fps))?"
            r"(?:\.(?P<audio>.+?))?"
            r"(?:-(?P<group>[^.-]+))?$"
        )
        patterns = (
            rf"^(?P<title_zh>[\u4e00-\u9fff][^.]+)\.(?P<title_en>.+?)\."
            rf"(?P<year>\d{{4}})\.(?P<source>.+?)\.(?P<resolution>\d{{3,4}}p)\."
            rf"(?P<codec>H\.?26[45]|HEVC|AVC|x26[45])\.(?P<audio>.+?)-(?P<group>[^.-]+)$",
            rf"^(?P<title_en>.+?)\."
            rf"(?P<year>\d{{4}})\.(?P<edition>V\d+)\.(?P<source>.+?)\.(?P<resolution>\d{{3,4}}p)\."
            rf"(?P<codec>H\.?26[45]|HEVC|AVC|x26[45])\.(?P<audio>.+?)-(?P<group>[^.-]+)$",
            rf"^(?P<title_en>.+?)\."
            rf"(?P<year>\d{{4}})\.(?P<source>.+?)\.(?P<resolution>\d{{3,4}}p)\."
            rf"(?P<codec>H\.?26[45]|HEVC|AVC|x26[45])\.(?P<audio>.+?)-(?P<group>[^.-]+)$",
            rf"^(?P<title_zh>[\u4e00-\u9fff][^.]+)\."
            rf"(?P<title_en>.+?)\."
            rf"(?P<season>S\d{{1,2}})(?:E(?P<episode>\d{{1,3}})(?:[-_.]?E?(?P<episode_end>\d{{1,3}}))?)?\.{base_pattern}",
            rf"^(?P<title_zh>[\u4e00-\u9fff][^.]+)\.(?P<title_en>.+?)\.{base_pattern}",
            rf"^(?P<title_en>.+?)\.{base_pattern}",
        )
        match = None
        for pattern in patterns:
            match = re.match(pattern, basename, re.IGNORECASE)
            if match:
                break
        if not match:
            title_prefix = (
                r"^(?:(?P<title_zh>[\u4e00-\u9fff][^.\s]+)(?:\.|\s+))?"
                r"(?P<title_en>.+?)\s+"
                r"(?:(?P<season>S\d{1,2})(?:E(?P<episode>\d{1,3})(?:[-~–—]E?(?P<episode_end>\d{1,3}))?)?\s+)?"
                r"(?P<year>\d{4})(?:\s+(?P<edition>V\d+))?\s+"
                r"(?P<resolution>\d{3,4}p)\s+"
            )
            space_patterns = (
                title_prefix
                + r"(?P<source>.+?)\s+"
                + r"(?P<codec>H\.?26[45]|HEVC|AVC|x26[45])\s+"
                + r"(?P<audio>DTS-HD(?:\s+MA)?(?:\s+\d(?:\.\d)?)?|TrueHD(?:\s+\d(?:\.\d)?)?|DDP?\d(?:\.\d)?|AAC|AC3)"
                + r"-(?P<group>.+)$",
                title_prefix
                + r"(?P<source>.+?)\s+"
                + r"(?P<codec>H\.?26[45]|HEVC|AVC|x26[45])\s+"
                + r"(?P<audio>.+?)-(?P<group>.+)$",
                title_prefix
                + r"(?P<source>.+?)\s+"
                + r"(?P<audio>DTS\d(?:\.\d)?|TrueHD(?:\s+\d(?:\.\d)?)?|DDP?\d(?:\.\d)?|AAC|AC3)\s+"
                + r"(?P<quality>(?:H\.?26[45]|HEVC|AVC|x26[45])(?:-[^@]+)?@.+)$",
                title_prefix
                + r"(?P<source>\S+)\s+"
                + r"(?P<codec>\S+)"
                + r"(?:\s+(?P<audio>.+?))?"
                + r"(?:-(?P<group>[^-]+))?$",
            )
            for pattern in space_patterns:
                match = re.match(pattern, basename, re.IGNORECASE)
                if match:
                    break
        if not match:
            return None
        info = {key: value for key, value in match.groupdict().items() if value}
        if "title_zh" in info:
            info["title_zh"] = cls._strip_title_brackets(info["title_zh"])
        if "title_en" in info:
            info["title_en"] = re.sub(r"[，,._]+", " ", info["title_en"]).strip()
            info["title_en"] = re.sub(r"\s+", " ", info["title_en"])
        if "season" in info:
            info["season"] = info["season"].upper()
        if "resolution" in info:
            info["resolution"] = info["resolution"].lower()
        cls._normalize_release_info(info)
        return info

    @classmethod
    def _normalize_release_info(cls, info: Dict[str, str]):
        codec = info.get("codec")
        if codec and not info.get("audio"):
            packed_match = re.match(
                r"^(?P<codec>H\.?26[45]|HEVC|AVC|x26[45])(?:\.(?P<quality>[^.]+))?\.(?P<audio>.+?)-(?P<group>[^-]+)$",
                str(codec),
                re.IGNORECASE,
            )
            if packed_match:
                info["codec"] = packed_match.group("codec")
                if packed_match.group("quality"):
                    info["quality"] = packed_match.group("quality")
                info["audio"] = packed_match.group("audio")
                info["group"] = packed_match.group("group")

        codec = info.get("codec")
        quality = info.get("quality")
        audio = info.get("audio")
        group = info.get("group")
        if quality and audio and group and re.match(r"^DTS-HD$", quality, re.IGNORECASE):
            audio_head = str(audio)
            if "-" in audio_head:
                audio_head, group_prefix = audio_head.rsplit("-", 1)
                info["group"] = f"{group_prefix}-{group}"
            info["audio"] = f"{quality}.{audio_head}"
            info.pop("quality", None)

        codec = info.get("codec")
        quality = info.get("quality")
        audio = info.get("audio")
        group = info.get("group")
        if (
            codec
            and quality
            and audio
            and group
            and cls._looks_like_audio(f"{codec}.{quality}")
            and re.match(r"^(H\.?26[45]|HEVC|AVC|x26[45])$", audio, re.IGNORECASE)
        ):
            info["audio"] = f"{codec}.{quality}"
            info["codec"] = audio
            info.pop("quality", None)
            if "@" in group:
                info["release_tag"] = f"{audio}-{group.split('@', 1)[0]}"

        quality = info.get("quality")
        if quality and "@" in quality:
            release_match = re.match(
                r"^(?P<codec>H\.?26[45]|HEVC|AVC|x26[45])(?:-(?P<tag>[^@]+))?@(?P<group>.+)$",
                quality,
                re.IGNORECASE,
            )
            if release_match:
                current_codec = info.get("codec")
                if current_codec and cls._looks_like_audio(current_codec) and not info.get("audio"):
                    info["audio"] = current_codec
                info["codec"] = release_match.group("codec")
                tag = release_match.group("tag")
                if tag:
                    info["release_tag"] = f"{release_match.group('codec')}-{tag}"
                info["group"] = release_match.group("group")
                info.pop("quality", None)

        audio = info.get("audio")
        group = info.get("group")
        if not audio or not group or "@" not in group:
            return
        if re.match(r"^(H\.?26[45]|HEVC|AVC|x26[45])$", audio, re.IGNORECASE):
            info["release_tag"] = f"{audio}-{group.split('@', 1)[0]}"
            if info.get("codec") and cls._looks_like_audio(info["codec"]):
                info["audio"] = info["codec"]
            info["codec"] = audio

    @staticmethod
    def _looks_like_audio(value: Any) -> bool:
        if not value:
            return False
        return bool(re.match(r"^(DTS|TrueHD|DDP?|AAC|AC3)", str(value), re.IGNORECASE))

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

    def _format_downloader_label(self, downloader: Any) -> Optional[str]:
        return self._downloader_label_name or self._clean_message_value(downloader)

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
    def _media_title(cls, media_info: Any, meta_info: Any = None) -> Optional[str]:
        title = cls._preferred_title(cls._to_dict(media_info))
        if title:
            return title
        return cls._preferred_title(cls._to_dict(meta_info))

    @classmethod
    def _preferred_title(cls, data: Dict[str, Any]) -> Optional[str]:
        if not data:
            return None

        for key in ("cn_name", "chinese_name", "zh_name"):
            title = cls._clean_title_candidate(cls._first_value(data, key))
            if title:
                return title

        title_candidates = [
            cls._first_value(data, "title"),
            cls._first_value(data, "name"),
            cls._first_value(data, "org_string"),
        ]
        for candidate in title_candidates:
            title = cls._clean_title_candidate(candidate, prefer_chinese=True)
            if title:
                return title

        for key in ("en_name", "original_name", "original_title"):
            title = cls._clean_title_candidate(cls._first_value(data, key))
            if title:
                return title

        for candidate in title_candidates:
            title = cls._clean_title_candidate(candidate)
            if title:
                return title
        return None

    @classmethod
    def _clean_title_candidate(cls, value: Any, prefer_chinese: bool = False) -> Optional[str]:
        text = cls._clean_message_value(value)
        if not text:
            return None
        text = cls._strip_title_brackets(text)
        text = re.sub(r"[._]+", " ", text).strip()
        if prefer_chinese:
            chinese_match = re.match(r"^([\u4e00-\u9fff][\u4e00-\u9fff\s·、，,：:《》「」『』!！?？-]*)\s+[A-Za-z]", text)
            if chinese_match:
                text = chinese_match.group(1).strip()
            elif not cls._has_cjk(text):
                return None
        text = re.sub(r"\b(19\d{2}|20\d{2})\b", "", text)
        text = re.sub(r"\bS\d{1,2}(?:\s*[-_. ]*\s*(?:E|EP)\s*\d{1,3})?\b", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\b(2160p|1080p|720p|480p|WEB-?DL|WEBRip|BluRay|BDRip|HDTV|DVDRip|H\.?265|H\.?264|HEVC|AVC|x265|x264).*$", "", text, flags=re.IGNORECASE)
        text = re.sub(r"[-_\s.]+$", "", text).strip()
        text = re.sub(r"\s+", " ", text)
        return text or None

    @staticmethod
    def _strip_title_brackets(value: Any) -> str:
        text = str(value or "").strip()
        for pattern in (
            r"^[\[\【\(\（]\s*([\u4e00-\u9fff][^\]\】\)\）]*)\s*[\]\】\)\）](?:\s+[A-Za-z].*)?$",
            r"^[\[\【]\s*(.*?)\s*[\]\】]$",
        ):
            match = re.match(pattern, text)
            if match:
                return match.group(1).strip()
        return text

    @staticmethod
    def _has_cjk(value: str) -> bool:
        return bool(re.search(r"[\u4e00-\u9fff]", value))
