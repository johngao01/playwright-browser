import os
import json
import asyncio
import aiohttp
import aiofiles
import time
from datetime import datetime
from typing import List

from rich.console import Console
from rich.table import Table
from rich.progress import (
    Progress, BarColumn, DownloadColumn, TransferSpeedColumn,
    TimeRemainingColumn, TextColumn
)
from rich.panel import Panel

from .config import PROXY_URL, MAX_CONCURRENT_DOWNLOADS, GLOBAL_HISTORY_FILE
from .models import PostItem, MediaItem, get_human_readable_size
from .download.base import BasePlatform

console = Console()


class DownloadManager:
    def __init__(self, platforms: List[BasePlatform]):
        self.platforms = platforms
        self.history = self.load_history()
        self.semaphore = asyncio.Semaphore(MAX_CONCURRENT_DOWNLOADS)
        self.start_time = 0
        self.failed_json_files = []
        self.stats = {
            "total": {"success_post": 0, "skip_post": 0, "fail_post": 0, "files": 0, "size": 0},
        }
        for p in platforms:
            self.stats[p.name] = {"success_post": 0, "skip_post": 0, "fail_post": 0, "files": 0, "size": 0}

    def load_history(self):
        if os.path.exists(GLOBAL_HISTORY_FILE):
            try:
                with open(GLOBAL_HISTORY_FILE, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except:
                return {}
        return {}

    def save_history(self):
        os.makedirs(os.path.dirname(GLOBAL_HISTORY_FILE), exist_ok=True)
        try:
            with open(GLOBAL_HISTORY_FILE, 'w', encoding='utf-8') as f:
                json.dump(self.history, f, ensure_ascii=False, indent=2)
        except Exception as e:
            console.print(f"[red]保存历史记录失败: {e}[/red]")

    def _update_stats(self, platform_name, key, value=1):
        self.stats["total"][key] += value
        self.stats[platform_name][key] += value

    async def download_file(self, session, progress, media: MediaItem, save_dir: str, headers: dict, use_proxy: bool,
                            user_context: str):
        filepath = os.path.join(save_dir, media.filename)
        media.filepath = filepath
        relative_display_path = f"{user_context}/{media.filename}"
        icon = "🎥" if media.file_type == "video" else "📷"

        if os.path.exists(filepath):
            try:
                media.size = os.path.getsize(filepath)
                media.human_readable_size = get_human_readable_size(media.size)
                media.save_time = datetime.fromtimestamp(os.path.getmtime(filepath)).strftime('%Y-%m-%d %H:%M:%S')
                return True, False
            except:
                pass

        proxy = PROXY_URL if use_proxy else None
        task_id = None

        async with self.semaphore:
            try:
                task_id = progress.add_task(f"[cyan]{relative_display_path}", total=None, start=False)
                start_time = time.time()

                async with session.get(media.url, headers=headers, proxy=proxy, timeout=120) as response:
                    if response.status != 200:
                        if task_id is not None: progress.remove_task(task_id)
                        task_id = None
                        console.print(f"[red]✘[/] {icon} {relative_display_path} [dim](HTTP {response.status})[/dim]")
                        return False, False

                    total_len = int(response.headers.get('Content-Length', 0))
                    progress.update(task_id, total=total_len)
                    progress.start_task(task_id)

                    os.makedirs(os.path.dirname(filepath), exist_ok=True)

                    async with aiofiles.open(filepath, mode='wb') as f:
                        async for chunk in response.content.iter_chunked(8192):
                            await f.write(chunk)
                            progress.update(task_id, advance=len(chunk))

                    end_time = time.time()
                    duration = end_time - start_time
                    avg_speed = (total_len / 1024 / 1024) / duration if duration > 0 else 0

                    media.size = total_len
                    media.human_readable_size = get_human_readable_size(total_len)
                    media.save_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

                    if task_id is not None: progress.remove_task(task_id)
                    task_id = None
                    console.print(
                        f"[green]✔[/] {icon} {relative_display_path} "
                        f"[dim]({media.human_readable_size} | {avg_speed:.2f} MB/s | {duration:.1f}s)[/dim]"
                    )
                    return True, True

            except Exception as e:
                if task_id is not None: progress.remove_task(task_id)
                task_id = None
                console.print(f"[red]✘[/] {icon} {relative_display_path} [dim]({str(e)})[/dim]")
                if os.path.exists(filepath):
                    try:
                        os.remove(filepath)
                    except:
                        pass
                return False, False
            finally:
                if task_id is not None:
                    try:
                        progress.remove_task(task_id)
                    except:
                        pass

    async def process_post(self, session, progress, platform: BasePlatform, post: PostItem):
        unique_id = post.get_unique_id()
        if unique_id in self.history:
            self._update_stats(platform.name, 'skip_post')
            return

        save_dir = os.path.join(platform.download_dir, post.user)
        headers = platform.get_headers()
        if platform.name == 'instagram':
            headers['Referer'] = post.source_url

        tasks = []
        for media in post.media_list:
            tasks.append(
                self.download_file(
                    session, progress, media, save_dir, headers, platform.use_proxy, post.user
                )
            )

        results = await asyncio.gather(*tasks, return_exceptions=True)
        valid_results = []
        for r in results:
            if isinstance(r, Exception):
                console.print(f"[red]系统错误[/]: {r}")
                valid_results.append((False, False))
            else:
                valid_results.append(r)

        all_success = all(r[0] for r in valid_results)

        if all_success:
            download_size = 0
            new_file_count = 0
            for i, (success, is_new) in enumerate(valid_results):
                if is_new:
                    new_file_count += 1
                    download_size += post.media_list[i].size

            self._update_stats(platform.name, 'files', new_file_count)
            self._update_stats(platform.name, 'size', download_size)
            self._update_stats(platform.name, 'success_post')

            history_entry = {
                "platform": post.platform,
                "username": post.user,
                "desc": post.desc,
                "create_time": post.create_time,
                "url": post.source_url,
                "file_num": len(post.media_list),
                "files": [m.to_dict() for m in post.media_list]
            }
            self.history[unique_id] = history_entry
        else:
            self._update_stats(platform.name, 'fail_post')
            if post.source_file_path:
                self.failed_json_files.append(post.source_file_path)

    def cleanup_failed_tasks(self):
        if not self.failed_json_files: return
        console.print(
            f"\n[yellow]开始清理 {len(self.failed_json_files)} 个因下载失败而失效的 Post JSON 文件...[/yellow]")
        deleted_count = 0
        for path in self.failed_json_files:
            if path and os.path.exists(path):
                try:
                    os.remove(path)
                    console.print(f"  [dim red]已删除:[/dim red] {path}")
                    deleted_count += 1
                except OSError as e:
                    console.print(f"  [bold red]删除失败:[/bold red] {path} ({e})")
        console.print(f"[green]清理完成，共删除 {deleted_count} 个文件。[/green]\n")

    async def run(self):
        all_posts = []
        self.start_time = time.time()
        console.print("[yellow]正在扫描所有平台目录...[/yellow]")
        for platform in self.platforms:
            files = platform.scan_files()
            console.print(f"  - [{platform.name}]: 发现 {len(files)} 个文件")
            for f in files:
                post = platform.parse_file(f)
                if post:
                    all_posts.append((platform, post))
        console.print(f"[green]扫描完成，共 {len(all_posts)} 个有效 Post 待处理。[/green]")

        async with aiohttp.ClientSession() as session:
            with Progress(
                    TextColumn("[bold blue]{task.description}", justify="left"),
                    BarColumn(bar_width=None),
                    "[progress.percentage]{task.percentage:>3.0f}%",
                    "•",
                    DownloadColumn(),
                    "•",
                    TransferSpeedColumn(),
                    "•",
                    TimeRemainingColumn(),
                    console=console,
                    expand=True,
                    transient=True
            ) as progress:
                tasks = []
                for platform, post in all_posts:
                    tasks.append(self.process_post(session, progress, platform, post))
                if tasks:
                    await asyncio.gather(*tasks, return_exceptions=True)

        self.cleanup_failed_tasks()
        self.save_history()
        self.print_summary()

    def print_summary(self):
        end_time = time.time()
        total_duration = end_time - self.start_time
        table = Table(box=None, show_header=True, header_style="bold cyan")
        table.add_column("平台", justify="center", no_wrap=True)
        table.add_column("成功Post", justify="right", style="green")
        table.add_column("跳过Post", justify="right", style="dim")
        table.add_column("失败Post", justify="right", style="red")
        table.add_column("文件数", justify="right", style="magenta")
        table.add_column("流量", justify="right", style="blue")

        for platform in self.platforms:
            s = self.stats[platform.name]
            table.add_row(platform.name, str(s['success_post']), str(s['skip_post']), str(s['fail_post']),
                          str(s['files']), get_human_readable_size(s['size']))

        t = self.stats['total']
        table.add_section()
        table.add_row("总计 (Total)", str(t['success_post']), str(t['skip_post']), str(t['fail_post']), str(t['files']),
                      get_human_readable_size(t['size']), style="bold white")

        summary_panel = Panel(table, title=f"🚀 任务完成 (耗时: {total_duration:.1f}s)", expand=False,
                              border_style="green", padding=(1, 2))
        console.print(summary_panel)
