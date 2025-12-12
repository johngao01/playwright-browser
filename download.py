import asyncio
from rich.console import Console

from platforms.manager import DownloadManager
from platforms.download.instagram import InstagramPlatform
from platforms.download.weibo import WeiboPlatform

console = Console()

if __name__ == "__main__":
    platforms = [
        InstagramPlatform(),
        WeiboPlatform(),
    ]

    manager = DownloadManager(platforms)
    try:
        asyncio.run(manager.run())
    except KeyboardInterrupt:
        console.print("[bold yellow]中断，正在保存进度...[/bold yellow]")
        manager.save_history()
        console.print("[green]已退出。[/green]")
