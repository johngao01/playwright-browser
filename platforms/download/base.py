from abc import ABC, abstractmethod
from typing import List, Optional
from ..models import PostItem


class BasePlatform(ABC):
    def __init__(self, name):
        self.name = name
        self.base_dir = f'data/{name}'
        self.json_dir = f'data/{name}/json'
        self.download_dir = f'data/{name}/download'

    @property
    def use_proxy(self) -> bool:
        """是否使用代理"""
        return True

    @abstractmethod
    def get_headers(self) -> dict:
        pass

    @abstractmethod
    def scan_files(self) -> List[str]:
        pass

    @abstractmethod
    def parse_file(self, file_path: str) -> Optional[PostItem]:
        pass
