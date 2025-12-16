import os
import json
from datetime import datetime
from urllib.parse import urlparse
from typing import List, Optional
from rich.console import Console

from .base import BasePlatform
from ..models import PostItem, MediaItem

console = Console()


class InstagramPlatform(BasePlatform):
    def __init__(self):
        super().__init__('instagram')

    @property
    def use_proxy(self) -> bool:
        return True

    def get_headers(self):
        return {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0',
            'Referer': 'https://www.instagram.com/'
        }

    def scan_files(self) -> List[str]:
        if not os.path.exists(self.json_dir):
            console.print(f"[red]目录不存在: {self.json_dir}[/red]")
            return []

        files_to_process = []
        for root, dirs, files in os.walk(self.json_dir):
            for file in files:
                if not file.endswith('.json'): continue
                path = os.path.join(root, file)
                files_to_process.append(path)
        return files_to_process

    def parse_file(self, file_path: str) -> Optional[PostItem]:
        try:
            with open(file_path, mode='r', encoding='utf8') as f:
                item = json.load(f)
        except (json.JSONDecodeError, UnicodeDecodeError):
            return None

        if not item or 'code' not in item: return None

        try:
            user = file_path.split(os.sep)[-2]
        except:
            user = "unknown"

        short_code = item['code']
        caption_node = item.get('caption')
        desc = caption_node.get('text', '') if caption_node else ''
        timestamp = item.get('taken_at')
        create_time = datetime.fromtimestamp(timestamp).strftime('%Y-%m-%d %H:%M:%S') if timestamp else ''
        source_url = f"https://www.instagram.com/p/{short_code}"

        post = PostItem(self.name, short_code, user, desc, create_time, source_url, source_file_path=file_path)

        def get_best_candidate(candidates):
            if not candidates: return None
            return max(candidates, key=lambda x: x.get('width', 0) * x.get('height', 0))

        media_nodes = item['carousel_media'] if 'carousel_media' in item and item['carousel_media'] else [item]

        for node in media_nodes:
            image_candidate = get_best_candidate(
                node['image_versions2'].get('candidates', [])) if 'image_versions2' in node else None
            video_candidate = get_best_candidate(node['video_versions']) if 'video_versions' in node else None

            base_filename = ""
            if image_candidate:
                base_filename = os.path.splitext(os.path.basename(urlparse(image_candidate['url']).path))[0]
            elif video_candidate:
                base_filename = os.path.splitext(os.path.basename(urlparse(video_candidate['url']).path))[0]

            if image_candidate:
                post.media_list.append(MediaItem(
                    url=image_candidate['url'],
                    filename=f"{base_filename}.jpg",
                    file_type='image',
                    width=image_candidate.get('width', 0),
                    height=image_candidate.get('height', 0)
                ))
            if video_candidate:
                post.media_list.append(MediaItem(
                    url=video_candidate['url'],
                    filename=f"{base_filename}.mp4",
                    file_type='video',
                    width=video_candidate.get('width', 0),
                    height=video_candidate.get('height', 0),
                    duration=node.get('video_duration')
                ))

        if not post.media_list: return None
        return post
