# login_instagram.py
import traceback
import json
import os
import asyncio
import aiofiles
from playwright.async_api import async_playwright, ProxySettings
from pydash import get

site = "instagram.com"
username = 'neverblock11'
password = 'swdawfadffg42158'
COOKIE_FILE = f'cookies/{username}.txt'
user_url = 'https://www.instagram.com/{}/'.format(username)
save_dir = 'data/instagram/json/'


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
            if (("code" in obj and type(obj['code']) is str) and
                    ("user" in obj and type(obj['user']) is dict and 'username' in obj['user'])):
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
        author_username = get(post, 'user.username')
        code = get(post, 'code')
        following = get(post, 'user.friendship_status.following')
        if following:
            following = 'following'
        else:
            following = 'explore'
        json_path = os.path.join(save_dir, following, author_username, f'{code}.json')

        await save_json(json_path, post)

        # 仅打印日志，不阻塞
        print(f"💾 Saved Post: @{author_username} -> https://www.instagram.com/p/{code}")
    except Exception as e:
        print(f"保存单条帖子失败: {e}")


async def handle_response(response):
    # 1. 基础过滤：URL 和 状态码
    target_urls = ["graphql/query", "api/v1/discover/web/explore_grid"]
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
        # 3. 业务逻辑分流
        if "PolarisProfilePageContentQuery" in post_body_str:
            # === 处理用户主页信息 ===
            try:
                user = data['data']['user']
                profile_name = user['username']
                save_path = os.path.join('data/instagram/json/profiles', f'{profile_name}.json')

                # 异步保存
                await save_json(save_path, user)
                print(f"\n🔍 捕获到用户主页 {profile_name} 请求")
            except KeyError:
                pass

        else:

            # 提取数据 (CPU)
            profile_posts = extract_posts_recursively(data)
            if not profile_posts:
                return

            # === 并发保存 (IO) ===
            # 创建所有保存任务
            tasks = [process_and_save_post(post) for post in profile_posts]

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

    login_link = page.get_by_role("link", name=username, exact=True)

    if await login_link.is_visible():
        print(">>> Instagram 已登录")
    else:
        print(">>> Instagram 未登录，开始尝试自动登录...")
        await page.get_by_role("textbox", name="电话号码、账号或邮箱").click()
        await page.get_by_role("textbox", name="电话号码、账号或邮箱").fill(username)  # 使用变量
        await page.get_by_role("textbox", name="密码").click()
        await page.get_by_role("textbox", name="密码").fill(password)  # 使用变量
        await page.get_by_role("button", name="登录").click()

        # 处理弹窗
        try:
            await page.get_by_role("button", name="保存信息").click()
            print("保存信息")
        except Exception:
            print("保存信息: 未出现或点击失败")

        try:
            await page.get_by_role("button", name="确定").click()
            print("点击确定")
        except Exception:
            pass

        try:
            not_now_btn = page.get_by_role("button", name="以后再说")
            await not_now_btn.click(timeout=3000)
            print("通知弹窗: 点击以后再说")
        except Exception:
            pass


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
        cmd = "scp cookies/neverblock11.txt root@rn:/root/pythonproject/weibo_tg_bot/cookies/"

        process = await asyncio.create_subprocess_shell(
            cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )

        # 等待命令结束
        stdout, stderr = await process.communicate()

        if process.returncode == 0:
            print("🚀 🍪 Instagram Cookies 服务器上传 OK")
        else:
            print(f"❌ 🍪 Instagram Cookies 服务器上传失败: {stderr.decode().strip()}")

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
