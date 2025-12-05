import os
import json
import asyncio
import aiohttp
import aiofiles
from urllib.parse import urlparse
from datetime import datetime
from rich.console import Console
from rich.progress import (
    Progress,
    BarColumn,
    DownloadColumn,
    TransferSpeedColumn,
    TimeRemainingColumn,
    TextColumn,
    FileSizeColumn,
)
from rich.panel import Panel

# --- 配置区域 ---
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0',
}

# 代理设置 (如果不需要请设为 None)
PROXY_URL = 'http://127.0.0.1:10808'

BASE_DIR = 'data/instagram'
DOWNLOAD_DIR = 'data/instagram/download'
HISTORY_FILE = 'data/instagram/download_history.json'
MAX_CONCURRENT_DOWNLOADS = 5

console = Console()


def get_human_readable_size(size_in_bytes):
    """将字节转换为人类可读格式"""
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size_in_bytes < 1024.0:
            return f"{size_in_bytes:.2f} {unit}"
        size_in_bytes /= 1024.0
    return f"{size_in_bytes:.2f} TB"


class DownloadManager:
    def __init__(self):
        self.history = self.load_history()
        self.semaphore = asyncio.Semaphore(MAX_CONCURRENT_DOWNLOADS)
        self.success_post_count = 0
        self.skip_post_count = 0
        self.fail_post_count = 0
        self.total_files_downloaded = 0
        self.total_images_downloaded = 0
        self.total_videos_downloaded = 0

    def load_history(self):
        """加载已下载的历史记录 (字典格式)"""
        if os.path.exists(HISTORY_FILE):
            try:
                with open(HISTORY_FILE, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    # 确保是字典格式
                    if isinstance(data, dict):
                        return data
                    # 兼容旧版本 set/list 格式，如果是旧格式则清空或迁移（这里选择清空重建以保证结构正确）
                    return {}
            except (json.JSONDecodeError, OSError):
                return {}
        return {}

    def save_history(self):
        """保存历史记录到本地"""
        os.makedirs(os.path.dirname(HISTORY_FILE), exist_ok=True)
        try:
            with open(HISTORY_FILE, 'w', encoding='utf-8') as f:
                json.dump(self.history, f, ensure_ascii=False, indent=2)
        except Exception as e:
            console.print(f"[red]保存历史记录失败: {e}[/red]")

    async def download_single_file(self, session, progress, url, filepath, short_code):
        """
        下载单个文件。
        返回: (success: bool, file_info: dict)
        """
        file_exists = os.path.exists(filepath)

        # 如果文件已存在，直接获取信息
        if file_exists:
            try:
                file_size = os.path.getsize(filepath)
                return True, {
                    'size': file_size,
                    'save_time': datetime.fromtimestamp(os.path.getmtime(filepath)).strftime('%Y-%m-%d %H:%M:%S'),
                    'is_new_download': False
                }
            except OSError:
                # 如果读取文件失败，视为不存在，重新下载
                pass

        async with self.semaphore:
            filename = os.path.basename(filepath)
            task_id = progress.add_task(
                f"[cyan]下载中... {filename[:15]}..",
                total=None,
                start=False
            )

            try:
                headers = HEADERS.copy()
                headers['referer'] = f'https://www.instagram.com/p/{short_code}'

                async with session.get(url, headers=headers, proxy=PROXY_URL, timeout=30) as response:
                    if response.status != 200:
                        console.print(f"[bold red]下载失败 ({response.status})[/]: {filename}")
                        progress.remove_task(task_id)
                        return False, {}

                    total_length = int(response.headers.get('Content-Length', 0))
                    progress.update(task_id, total=total_length)
                    progress.start_task(task_id)

                    os.makedirs(os.path.dirname(filepath), exist_ok=True)

                    async with aiofiles.open(filepath, mode='wb') as f:
                        async for chunk in response.content.iter_chunked(8192):
                            await f.write(chunk)
                            progress.update(task_id, advance=len(chunk))

                    self.total_files_downloaded += 1

                    # 统计文件类型
                    if filename.lower().endswith('.mp4'):
                        self.total_videos_downloaded += 1
                    else:
                        self.total_images_downloaded += 1

                    progress.remove_task(task_id)

                    return True, {
                        'size': total_length,
                        'save_time': datetime.fromtimestamp(os.path.getmtime(filepath)).strftime('%Y-%m-%d %H:%M:%S'),
                        'is_new_download': True
                    }

            except Exception as e:
                console.print(f"[bold red]错误[/] {filename}: {e}")
                progress.remove_task(task_id)
                return False, {}

    async def process_post(self, session, progress, post_data):
        """
        处理单个 Post：解析元数据，下载所有包含的文件（图片或视频）。
        只有所有文件都成功，才返回 Post 记录信息。
        """
        item = post_data['item']
        user = post_data['user']
        short_code = item['code']

        # 如果历史记录里已经有这个 Post，且我们认为它完整，则跳过
        if short_code in self.history:
            self.skip_post_count += 1
            return

        # 提取 Post 元数据
        caption_node = item.get('caption')
        desc = caption_node.get('text', '') if caption_node else ''
        timestamp = item.get('taken_at')
        create_time = datetime.fromtimestamp(timestamp).strftime('%Y-%m-%d %H:%M:%S') if timestamp else ''

        # --- 核心修改：媒体资源提取逻辑 ---

        def get_best_candidate(candidates):
            """从列表中根据分辨率选出最佳资源"""
            if not candidates:
                return None
            return max(candidates, key=lambda x: x.get('width', 0) * x.get('height', 0))

        candidates_to_process = []

        # 确定需要处理的媒体节点列表
        media_nodes = []
        if 'carousel_media' in item and item['carousel_media']:
            # 多图/视频 (Carousel)
            media_nodes = item['carousel_media']
        else:
            # 单图/视频/Reel
            media_nodes = [item]

        # 遍历所有节点提取下载链接
        for node in media_nodes:
            # 1. 尝试提取图片 (封面或纯图片)
            image_candidate = None
            if 'image_versions2' in node:
                image_candidate = get_best_candidate(node['image_versions2'].get('candidates', []))

            # 2. 尝试提取视频
            video_candidate = None
            if 'video_versions' in node and node['video_versions']:
                video_candidate = get_best_candidate(node['video_versions'])

            # --- 生成下载目标 ---

            # 用于保持同名 (basename) 的基础名称
            base_filename = ""

            # A. 处理图片/封面
            if image_candidate:
                # 从图片 URL 提取基础文件名，例如: 123456_789.jpg -> 123456_789
                parsed_path = urlparse(image_candidate['url']).path
                base_filename = os.path.splitext(os.path.basename(parsed_path))[0]

                candidates_to_process.append({
                    'url': image_candidate['url'],
                    'width': image_candidate.get('width', 0),
                    'height': image_candidate.get('height', 0),
                    'is_video': False,
                    'duration': None,
                    'final_filename': f"{base_filename}.jpg"
                })

            # B. 处理视频 (如果存在)
            if video_candidate:
                # 如果没有图片来提供 base_filename (极少见), 则直接使用视频 URL 的名字
                if not base_filename:
                    parsed_path = urlparse(video_candidate['url']).path
                    base_filename = os.path.splitext(os.path.basename(parsed_path))[0]

                candidates_to_process.append({
                    'url': video_candidate['url'],
                    'width': video_candidate.get('width', 0),
                    'height': video_candidate.get('height', 0),
                    'is_video': True,
                    'duration': node.get('video_duration'),
                    'final_filename': f"{base_filename}.mp4"
                })

        if not candidates_to_process:
            return

        # 准备下载任务
        download_futures = []
        file_metadata_list = []

        for index, cand in enumerate(candidates_to_process):
            filename = cand['final_filename']
            filepath = os.path.join(DOWNLOAD_DIR, user, filename)

            # 记录预定元数据
            file_meta = {
                "filename": filename,
                "filepath": filepath,
                "url": cand['url'],
                "resolution": f"{cand['width']}x{cand['height']}",
                "file_type": "video" if cand['is_video'] else "image",
                "duration": cand['duration'],
                # size, human_readable_size, save_time 在下载后补充
            }
            file_metadata_list.append(file_meta)

            # 创建下载协程
            download_futures.append(
                self.download_single_file(session, progress, cand['url'], filepath, short_code)
            )

        # 并发执行该 Post 下的所有文件下载
        results = await asyncio.gather(*download_futures)

        # 检查是否所有文件都成功 (success 字段)
        all_success = all(r[0] for r in results)

        if all_success:
            final_files_list = []
            for i, (success, info) in enumerate(results):
                meta = file_metadata_list[i]
                meta['size'] = info['size']
                meta['human_readable_size'] = get_human_readable_size(info['size'])
                meta['save_time'] = info['save_time']
                final_files_list.append(meta)

                # 打印日志 (仅对新下载的文件或需要提示的)
                if info.get('is_new_download'):
                    file_icon = "🎥" if meta['file_type'] == "video" else "📷"
                    console.print(f"[green]✔[/] {file_icon} {user}/{meta['filename']} ({meta['human_readable_size']})")

            # 构建 Post 历史记录 Entry
            post_entry = {
                "username": user,
                "desc": desc,
                "create_time": create_time,
                "url": f"https://www.instagram.com/p/{short_code}",
                "file_num": len(final_files_list),
                "files": final_files_list
            }

            # 更新内存中的历史记录
            self.history[short_code] = post_entry
            self.success_post_count += 1
        else:
            self.fail_post_count += 1
            # console.print(f"[red]Post {short_code} 部分文件下载失败，不记录历史。[/red]")

    async def scan_and_download(self):
        if not os.path.exists(BASE_DIR):
            console.print(f"[red]目录不存在: {BASE_DIR}[/red]")
            return

        # 1. 扫描所有 Post JSON
        console.print(f"[yellow]正在扫描 JSON 文件 (目录: {BASE_DIR})...[/yellow]")

        posts_to_process = []

        for root, dirs, files in os.walk(BASE_DIR):
            for file in files:
                # 简单的过滤：排除非 json 文件
                if not file.endswith('.json'):
                    continue

                path = os.path.join(root, file)

                try:
                    user_folder = path.split(os.sep)[-2]
                except IndexError:
                    continue

                # 排除用户信息的 json (通常是 username.json)
                if file.startswith(user_folder):
                    continue

                try:
                    with open(path, mode='r', encoding='utf8') as f:
                        item = json.load(f)
                except (json.JSONDecodeError, UnicodeDecodeError):
                    # 仅删除完全损坏的文件
                    # os.remove(path)
                    continue

                if not item or 'code' not in item:
                    continue

                posts_to_process.append({
                    'user': user_folder,
                    'item': item
                })

        console.print(f"[green]扫描完成，共找到 {len(posts_to_process)} 个 Post。[/green]")

        # 2. 开始处理
        async with aiohttp.ClientSession() as session:
            with Progress(
                    TextColumn("[bold blue]{task.description}", justify="right"),
                    BarColumn(bar_width=None),
                    "[progress.percentage]{task.percentage:>3.1f}%",
                    "•",
                    FileSizeColumn(),
                    "•",
                    TransferSpeedColumn(),
                    "•",
                    TimeRemainingColumn(),
                    console=console
            ) as progress:

                # 创建所有 Post 任务
                # 注意：虽然这里创建了所有协程，但在 download_single_file 内部有 semaphore 限制并发下载数
                post_tasks = []
                for post_data in posts_to_process:
                    post_tasks.append(self.process_post(session, progress, post_data))

                if post_tasks:
                    await asyncio.gather(*post_tasks)

        # 3. 结束
        self.save_history()
        self.print_summary()

    def print_summary(self):
        summary_text = (
            f"[bold green]任务完成![/bold green]\n"
            f"Post 成功/已存: {self.success_post_count}\n"
            f"Post 跳过(历史存在): {self.skip_post_count}\n"
            f"Post 失败/不完整: {self.fail_post_count}\n"
            f"本次下载文件数: {self.total_files_downloaded}\n"
            f"  - 图片: {self.total_images_downloaded}\n"
            f"  - 视频: {self.total_videos_downloaded}"
        )
        console.print(Panel(summary_text, title="下载统计", expand=False))


if __name__ == "__main__":
    manager = DownloadManager()
    try:
        asyncio.run(manager.scan_and_download())
    except KeyboardInterrupt:
        console.print("[bold yellow]用户中断操作，正在保存进度...[/bold yellow]")
        manager.save_history()
        console.print("[bold green]进度已保存，程序退出。[/bold green]")
