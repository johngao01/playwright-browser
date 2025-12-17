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
from rich.text import Text
from rich.progress import (
    Progress, BarColumn, DownloadColumn,
    TimeRemainingColumn, TextColumn, ProgressColumn, Task
)
from rich.panel import Panel

from .config import PROXY_URL, MAX_CONCURRENT_DOWNLOADS, GLOBAL_HISTORY_FILE
from .models import PostItem, MediaItem, get_human_readable_size
from .download.base import BasePlatform

console = Console()


class SmartTransferSpeedColumn(ProgressColumn):
    """
    智能速度显示列：
    - 对于普通文件任务：显示单个文件的下载速度
    - 对于整体进度任务：计算并显示所有活跃下载任务的总速度
    """

    def __init__(self):
        super().__init__()
        self.progress_ref = None

    def render(self, task: Task) -> Text:
        # 如果没有关联 progress 对象，或者速度未知，返回空
        if self.progress_ref is None:
            if task.speed is None: return Text("")
            return Text(f"{get_human_readable_size(task.speed)}/s", style="progress.data.speed")

        # 判定是否为"整体进度"任务 (通过描述文本包含关键词)
        if "整体进度" in task.description:
            # 计算所有其他任务（即文件下载任务）的速度之和
            total_speed = sum(t.speed or 0 for t in self.progress_ref.tasks if t.id != task.id)
            # 使用 bold green 醒目显示总速度
            return Text(f"{get_human_readable_size(total_speed)}/s", style="bold green")
        else:
            # 普通文件任务：显示自身速度
            if task.speed is None: return Text("?", style="progress.data.speed")
            return Text(f"{get_human_readable_size(task.speed)}/s", style="progress.data.speed")


class SmartDownloadColumn(DownloadColumn):
    """
    智能下载数据列：
    - 整体任务：显示 5/10 (计数)
    - 文件任务：显示 1.5 MB / 5.0 MB (流量，自动转换单位)
    """

    def __init__(self):
        # 强制开启 binary_units 以显示 MB/GB
        super().__init__(binary_units=True)

    def render(self, task: Task) -> Text:
        # 对整体进度任务特殊处理，显示 计数
        if "整体进度" in task.description:
            if task.total is None: return Text("")
            # 显示格式：已完成/总数
            return Text(f"{int(task.completed)}/{int(task.total)}", style="bold magenta")

        # 对普通文件任务，使用父类逻辑 (显示 MB)
        return super().render(task)


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
                    # 如果 Content-Length 为 0 或不存在，保持 total=None 以显示不确定进度，避免显示 0/0
                    progress.update(task_id, total=total_len if total_len > 0 else None)
                    progress.start_task(task_id)

                    os.makedirs(os.path.dirname(filepath), exist_ok=True)

                    async with aiofiles.open(filepath, mode='wb') as f:
                        async for chunk in response.content.iter_chunked(8192):
                            await f.write(chunk)
                            progress.update(task_id, advance=len(chunk))

                    end_time = time.time()
                    duration = end_time - start_time
                    avg_speed = (total_len / duration) if duration > 0 else 0

                    media.size = total_len
                    media.human_readable_size = get_human_readable_size(os.path.getsize(filepath))
                    media.save_time = datetime.fromtimestamp(os.path.getmtime(filepath)).strftime('%Y-%m-%d %H:%M:%S')

                    if task_id is not None: progress.remove_task(task_id)
                    task_id = None
                    console.print(
                        f"[green]✔[/] {icon} {relative_display_path} "
                        f"| {media.human_readable_size} | {get_human_readable_size(avg_speed)}/s | {duration:.2f} s"
                    )
                    return True, True

            except Exception as e:
                if task_id is not None: progress.remove_task(task_id)
                task_id = None

                # 优化错误信息显示：确保显示异常类型
                error_name = type(e).__name__
                error_msg = str(e)
                full_error_msg = f"{error_name}: {error_msg}" if error_msg else error_name

                console.print(f"[red]✘[/] {icon} {relative_display_path} | [bright_red]{full_error_msg}[/bright_red]")

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
            return True

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
            return True
        else:
            self._update_stats(platform.name, 'fail_post')
            if post.source_file_path:
                self.failed_json_files.append(post.source_file_path)
            return False

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

    async def _process_post_wrapper(self, session, progress, platform, post, overall_task_id):
        """包装处理函数，用于更新总进度条"""
        await self.process_post(session, progress, platform, post)
        progress.advance(overall_task_id)

    async def run(self):
        all_posts = []
        pending_posts = []
        skipped_count = 0
        self.start_time = time.time()
        console.print("[yellow]正在扫描所有平台目录...[/yellow]")

        for platform in self.platforms:
            files = platform.scan_files()
            console.print(f"  - {platform.name}: 发现 {len(files)} 个文件")
            for f in files:
                post_id = os.path.splitext(os.path.basename(f))[0]
                unique_id = f"{platform.name}_{post_id}"
                all_posts.append(unique_id)
                if unique_id in self.history:
                    skipped_count += 1
                    self._update_stats(platform.name, 'skip_post')
                else:
                    post = platform.parse_file(f)
                    if post:
                        pending_posts.append((platform, post))

        console.print(Panel(
            f"共扫描到 [bold cyan]{len(all_posts)}[/bold cyan] 个 Post\n"
            f"✅ [green]已完成: {skipped_count}[/green]\n"
            f"📥 [bold yellow]需下载: {len(pending_posts)}[/bold yellow]",
            title="扫描报告",
            expand=False,
            border_style="cyan"
        ))

        if not pending_posts:
            self.print_summary()
            return

        async with aiohttp.ClientSession() as session:
            # 初始化我们自定义的速度列和下载列
            speed_col = SmartTransferSpeedColumn()
            download_col = SmartDownloadColumn()

            with Progress(
                    TextColumn("[bold blue]{task.description}", justify="left"),
                    BarColumn(bar_width=None),
                    "[progress.percentage]{task.percentage:>3.0f}%",
                    "•",
                    # 移除了会导致乱码的 TextColumn("{task.completed}/{task.total}")
                    # 使用智能下载列代替
                    download_col,
                    "•",
                    speed_col,  # 替换原有的 TransferSpeedColumn
                    "•",
                    TimeRemainingColumn(),
                    console=console,
                    expand=True,
                    transient=False
            ) as progress:

                # 关键：绑定 progress 引用
                speed_col.progress_ref = progress

                overall_task_id = progress.add_task(
                    f"[bold yellow]🚀 整体进度 (共 {len(pending_posts)} 个任务)",
                    total=len(pending_posts)
                )

                tasks = []
                for platform, post in pending_posts:
                    tasks.append(
                        self._process_post_wrapper(session, progress, platform, post, overall_task_id)
                    )

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
