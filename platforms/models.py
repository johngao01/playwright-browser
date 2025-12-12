from typing import List
from datetime import datetime


# --- 工具函数 ---
def get_human_readable_size(size_in_bytes):
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size_in_bytes < 1024.0:
            return f"{size_in_bytes:.2f} {unit}"
        size_in_bytes /= 1024.0
    return f"{size_in_bytes:.2f} TB"


# --- 数据模型 ---
class MediaItem:
    def __init__(self, url: str, filename: str, file_type: str,
                 width: int = 0, height: int = 0, duration: float = None):
        self.url = url
        self.filename = filename
        self.file_type = file_type
        self.width = width
        self.height = height
        self.duration = duration
        self.size = 0
        self.human_readable_size = ""
        self.save_time = ""
        self.filepath = ""

    def to_dict(self):
        return {
            "filename": self.filename,
            "filepath": self.filepath,
            "url": self.url,
            "resolution": f"{self.width}x{self.height}",
            "file_type": self.file_type,
            "duration": self.duration,
            "size": self.size,
            "human_readable_size": self.human_readable_size,
            "save_time": self.save_time
        }


class PostItem:
    def __init__(self, platform: str, post_id: str, user: str,
                 desc: str, create_time: str, source_url: str, source_file_path: str = None):
        self.platform = platform
        self.post_id = post_id
        self.user = user
        self.desc = desc
        self.create_time = create_time
        self.source_url = source_url
        self.source_file_path = source_file_path
        self.media_list: List[MediaItem] = []

    def get_unique_id(self):
        return f"{self.platform}_{self.post_id}"
