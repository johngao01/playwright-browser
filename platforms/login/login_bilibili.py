# login_bilibili.py
import traceback
import json
import os
import asyncio
import aiofiles
from playwright.async_api import async_playwright, ProxySettings
from pydash import get

site = "bilibili.com"
username = '17601319702'
password = '1314wan*'
COOKIE_FILE = f'cookies/bilibili.txt'
user_url = 'https://www.bilibili.com/{}/'.format(username)
save_dir = 'data/bilibili/json/'


async def save_json(path, data):
    """
    通用异步保存 JSON 函数
    """
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        async with aiofiles.open(path, 'w', encoding='utf8') as f:
            # json.dumps 是 CPU 操作，write 是 IO 操作
            await f.write(json.dumps(data, ensure_ascii=False, indent=4))
    except Exception as e:
        print(f"❌ 异步保存文件失败 {path}: {e}")


def extract_posts_recursively(data):
    """
    递归遍历字典或列表 (CPU 密集型逻辑，保持同步)
    """
    found_posts = []

    def _search(obj):
        if isinstance(obj, dict):
            if ("type" in obj and 'id_str' in obj) or ('bvid' in obj and 'author' in obj) \
                    or ('opus_id' in obj and 'cover' in obj):
                found_posts.append(obj)

            for value in obj.values():
                _search(value)

        elif isinstance(obj, list):
            for item in obj:
                _search(item)

    _search(data)
    return found_posts


async def process_and_save_post(post):
    """
    处理并保存单个帖子（作为并发任务单元）
    """
    try:
        if "type" in post and 'id_str' in post:
            author_username = get(post, 'modules.module_author.name')
            code = get(post, 'id_str')
            following = get(post, 'modules.module_author.following')
            if following:
                following = 'following'
            else:
                following = 'explore'
            json_path = os.path.join(save_dir, following, author_username, 'dynamic', f'{code}.json')
            await save_json(json_path, post)
            print(f"💾 Saved Dynamic: @{author_username} -> https://t.bilibili.com/{code}")
        elif 'bvid' in post and 'author' in post:
            author_username = get(post, 'author')
            code = get(post, 'bvid')
            following = 'explore'
            json_path = os.path.join(save_dir, following, author_username, 'post', f'{code}.json')
            await save_json(json_path, post)
            print(f"💾 Saved Video: @{author_username} -> https://www.bilibili.com/video/{code}")
        elif 'opus_id' in post and 'cover' in post:
            code = get(post, 'opus_id')
            content = get(post, 'content') or ''
            json_path = os.path.join(save_dir, 'opus', f'{code}.json')

            await save_json(json_path, post)
            print(f"💾 Saved opus: {content} -> www.bilibili.com/opus/{code}")
        else:
            print(f"未知类型帖子，无法保存")
    except Exception as e:
        print(f"保存单条帖子失败: {e}, post: {post}")


async def handle_response(response):
    # 1. 基础过滤：URL 和 状态码
    target_urls = ["x/polymer/web-dynamic/v1/feed/space", "x/space/wbi/arc/search",
                   "x/polymer/web-dynamic/v1/opus/feed/space"]
    if not any(sub in response.url for sub in target_urls):
        return

    if not (200 <= response.status < 300):
        return

    # 2. 获取数据
    try:
        # 预先获取 post_data，不需要 await
        post_body_str = response.request.post_data or ''
        # 获取 JSON 需要 await
        data = await response.json()
    except Exception:
        # 忽略无法解析 JSON 的响应（如图片资源误入等）
        return

    try:
        dynamics = extract_posts_recursively(data)
        if not dynamics:
            return

        # === 并发保存 (IO) ===
        # 创建所有保存任务
        tasks = [process_and_save_post(dynamic) for dynamic in dynamics]

        # 并发执行
        if tasks:
            await asyncio.gather(*tasks)

    except Exception as e:
        traceback.print_exc()
        print(f"处理业务逻辑出错: {e}")


async def login(context, page):
    context.on("response", handle_response)

    await page.goto(f"https://www.{site}/")
    print("正在检测登录状态...")

    login_link = page.get_by_text("登录", exact=True)

    if await login_link.is_visible():
        print(">>> bilibili 未登录，开始尝试自动登录...")
        await page.get_by_text("登录", exact=True).click()
        await page.get_by_role("textbox", name="请输入账号").click()
        await page.get_by_role("textbox", name="请输入账号").fill(username)
        await page.get_by_role("textbox", name="请输入账号").press("Tab")
        await page.get_by_role("textbox", name="请输入密码").fill(password)
        await page.get_by_text("登录", exact=True).nth(1).click()

        print("请手动登录")
    else:
        print(">>> bilibili 已登录")


async def save_cookies(context):
    try:
        cookies_list = await context.cookies()
        filtered = [c for c in cookies_list if site in c["domain"]]
        cookie_string = "; ".join(f"{c['name']}={c['value']}" for c in filtered)

        os.makedirs(os.path.dirname(COOKIE_FILE), exist_ok=True)

        # 异步写入 Cookie
        async with aiofiles.open(COOKIE_FILE, "w", encoding="utf-8") as f:
            await f.write(cookie_string)

        # 2. 异步执行 SCP 命令
        # 使用 create_subprocess_shell 替代 os.system
        cmd = "scp cookies/bilibili.txt root@rn:/root/pythonproject/weibo_tg_bot/cookies/"

        process = await asyncio.create_subprocess_shell(
            cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )

        # 等待命令结束
        stdout, stderr = await process.communicate()

        if process.returncode == 0:
            print("🚀 🍪 Bilibili Cookies 服务器上传 OK")
        else:
            print(f"❌ 🍪 Bilibili Cookies 服务器上传失败: {stderr.decode().strip()}")

    except Exception as e:
        print(f"保存/上传失败: {e}")


# ================= 运行测试 =================

async def run():
    PROXY_SERVER = "http://127.0.0.1:10808"
    proxy = ProxySettings(server=PROXY_SERVER)
    USER_DATA_DIR = './browser_data'

    async with async_playwright() as p:
        context = await p.chromium.launch_persistent_context(
            user_data_dir=USER_DATA_DIR,
            headless=False,
            channel="msedge",
            proxy=proxy,
            args=[
                "--autoplay-policy=no-user-gesture-required",
                "--mute-audio",
                "--start-maximized"
            ],
            no_viewport=True,
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        )

        page = context.pages[0]
        await login(context, page)
        await save_cookies(context)

        print("\n>>> 程序挂起中，关闭窗口退出...")
        await context.wait_for_event("close", timeout=0)


if __name__ == "__main__":
    asyncio.run(run())
