import os
import json
from datetime import datetime
from typing import List, Optional
from rich.console import Console

from .base import BasePlatform
from ..models import PostItem, MediaItem

console = Console()


class WeiboPlatform(BasePlatform):
    def __init__(self):
        super().__init__('weibo')
        self.video_url_keys = [
            "mp4_720p_mp4", "stream_url", "mp4_hd_url", "hevc_mp4_hd",
            "mp4_sd_url", "mp4_ld_mp4", "h265_mp4_hd", "h265_mp4_ld",
            "inch_4_mp4_hd", "inch_5_5_mp4_hd", "inch_5_mp4_hd",
            "stream_url_hd", "stream_url"
        ]

    @property
    def use_proxy(self) -> bool:
        return False

    def get_headers(self):
        return {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/139.0.0.0 Safari/537.36",
            "Referer": "https://weibo.com/",
        }

    def scan_files(self) -> List[str]:
        if not os.path.exists(self.base_dir):
            console.print(f"[red]目录不存在: {self.base_dir}[/red]")
            return []

        json_dir = os.path.join(self.base_dir, 'json')
        if not os.path.exists(json_dir):
            return []

        files_to_process = []
        for root, dirs, files in os.walk(json_dir):
            for file in files:
                if file.endswith('.json'):
                    files_to_process.append(os.path.join(root, file))
        return files_to_process

    def _parse_created_at(self, created_at_str):
        try:
            clean_str = created_at_str.replace("+0800 ", "")
            dt = datetime.strptime(clean_str, "%c")
            return dt
        except Exception:
            return datetime.now()

    def _get_video_url(self, media_info):
        if not media_info: return None
        for key in self.video_url_keys:
            if media_info.get(key):
                return media_info[key]
        return None

    def parse_file(self, file_path: str) -> Optional[PostItem]:
        try:
            with open(file_path, mode='r', encoding='utf8') as f:
                data = json.load(f)
        except:
            return None

        if not data or 'idstr' not in data: return None
        if data.get('mblog_vip_type') == 1: return None
        if isinstance(data.get('retweeted_status'), dict): return None

        user = data['user']['screen_name'] if 'user' in data else 'unknown'
        post_id = data['idstr']
        desc = data.get('text_raw', '')
        created_dt = self._parse_created_at(data.get('created_at', ''))
        create_time_str = created_dt.strftime('%Y-%m-%d %H:%M:%S')
        date_prefix = created_dt.strftime("%Y%m%d")
        source_url = f"https://weibo.com/{data.get('user', {}).get('idstr', '')}/{post_id}"

        post = PostItem(self.name, post_id, user, desc, create_time_str, source_url, source_file_path=file_path)

        mix_media_info = data.get('mix_media_info', {})
        pic_ids = data.get('pic_ids', [])
        pic_infos = data.get('pic_infos', {})
        page_info = data.get('page_info', {})

        if mix_media_info and mix_media_info.get('items'):
            items = mix_media_info['items']
            index = 1
            for item in items:
                if item['type'] == 'pic':
                    pic_data = item.get('data', {})
                    if not pic_data: continue
                    largest = pic_data.get('largest', {})
                    url = largest.get('url')
                    if url:
                        ext = url.split('.')[-1]
                        filename = f"{date_prefix}_{post_id}_{index}.{ext}"
                        post.media_list.append(
                            MediaItem(url=url, filename=filename, file_type='image', width=largest.get('width', 0),
                                      height=largest.get('height', 0)))
                        index += 1
                elif item['type'] == 'video':
                    video_data = item.get('data', {})
                    media_info = video_data.get('media_info', {})
                    video_url = self._get_video_url(media_info)
                    if video_url:
                        filename = f"{date_prefix}_{post_id}_{index}.mp4"
                        post.media_list.append(MediaItem(url=video_url, filename=filename, file_type='video'))
                        index += 1
        elif pic_ids:
            index = 1
            for pic_id in pic_ids:
                if pic_id not in pic_infos: continue
                info = pic_infos[pic_id]
                largest = info.get('largest', {})
                url = largest.get('url') or f"https://wx4.sinaimg.cn/large/{pic_id}.jpg"
                ext = url.split('.')[-1]
                filename = f"{date_prefix}_{post_id}_{index}.{ext}"
                post.media_list.append(
                    MediaItem(url=url, filename=filename, file_type='image', width=largest.get('width', 0),
                              height=largest.get('height', 0)))

                if info.get('type') == 'livephoto' and info.get('video'):
                    video_url = info['video']
                    video_filename = f"{date_prefix}_{post_id}_{index}.mov"
                    post.media_list.append(MediaItem(url=video_url, filename=video_filename, file_type='video'))
                index += 1
        elif page_info and page_info.get('type') == 'video':
            media_info = page_info.get('media_info')
            video_url = self._get_video_url(media_info)
            if video_url:
                filename = f"{date_prefix}_{post_id}.mp4"
                post.media_list.append(MediaItem(url=video_url, filename=filename, file_type='video'))

        if not post.media_list: return None
        return post
