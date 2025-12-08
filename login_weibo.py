# login_weibo.py
import json
import os
import re
import asyncio
from datetime import datetime
import aiofiles
from playwright.async_api import async_playwright

site = "weibo.com"
COOKIE_FILE = 'cookies/johnjohn01.txt'


def standardize_date(created_at):
    """
    纯 CPU 逻辑，保持同步即可
    """
    created_at = created_at.replace("+0800 ", "")
    ts = datetime.strptime(created_at, "%c")
    return ts


async def save_json(path, data):
    """
    异步保存 JSON 文件，避免阻塞事件循环
    """
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        async with aiofiles.open(path, 'w', encoding='utf8') as f:
            # json.dumps 是 CPU 操作，速度很快；write 是 I/O 操作，需要 await
            await f.write(json.dumps(data, ensure_ascii=False, indent=4))
    except Exception as e:
        print(f"异步保存文件失败 {path}: {e}")


async def parse_weibo(weibo, save_dir):
    """
    异步解析并保存单条微博
    """
    user = weibo.get('user', {})
    author_name = user.get('screen_name', '未知作者')
    idstr = str(weibo.get('id', ''))

    # 构造路径
    json_path = os.path.join(save_dir, author_name, f'{idstr}.json')

    # 异步写入文件
    await save_json(json_path, weibo)

    content = weibo.get('text_raw', '')
    created_at = weibo.get('created_at', '')
    url = f"https://weibo.com/{user.get('id', '')}/{idstr}"

    # Print 也是 I/O，但在终端输出通常很快，暂时保留同步 print
    # 如果追求极致性能，可以使用 logging 模块的异步 handler，或者减少 print
    print(f"{author_name} | {standardize_date(created_at)} | {url} | {content[:30]}...")

    if 'retweeted_status' in weibo:
        retweet = weibo['retweeted_status']
        r_user = retweet.get('user', {}).get('screen_name', '未知')
        r_text = retweet.get('text_raw', '')
        print(f"   -> [转发] @{r_user}: {r_text[:30]}...")

    print("-" * 50)


async def parse_weibo_list(weibo_list, save_dir):
    """
    并发处理微博列表
    """
    print("=" * 20 + " 微博信息流数据 " + "=" * 20)
    if not weibo_list:
        print("未找到微博列表数据")
        return

    # 创建任务列表
    tasks = []
    for i, weibo in enumerate(weibo_list):
        # 将每个微博的处理封装为一个 Task
        tasks.append(parse_weibo(weibo, save_dir))

    # 使用 gather 并发执行所有保存任务，大大加快速度
    if tasks:
        try:
            await asyncio.gather(*tasks)
        except Exception as e:
            print(f"并发处理微博列表出错: {e}")


async def handle_response(response):
    # 快速检查 URL，避免不必要的 await response.json()
    target_urls = [
        '/ajax/profile/info?uid=',
        "unreadfriendstimeline",
        'ajax/statuses/mymblog?uid=',
        'ajax/feed/friendstimeline',
        'ajax/feed/groupstimeline'
    ]

    if not any(sub in response.url for sub in target_urls) or response.status != 200:
        return

    try:
        data = await response.json()
    except Exception:
        return

    if '/ajax/profile/info?uid=' in response.url:
        try:
            profile_username = data['data']['user']['screen_name']
            save_dir = f'data/weibo/profiles/json/'
            json_path = os.path.join(save_dir, profile_username, f'{profile_username}.json')
            await save_json(json_path, data)
            print(f"已保存用户 {profile_username} 的信息 -> {json_path}")
        except Exception as e:
            print(f"保存用户信息出错: {e}")

    elif "unreadfriendstimeline" in response.url:
        save_dir = f'data/weibo/explore/json/'
        await parse_weibo_list(data.get('statuses', []), save_dir)

    elif 'ajax/statuses/mymblog?uid=' in response.url:
        save_dir = f'data/weibo/profiles/json/'
        await parse_weibo_list(data.get('data', {}).get('list', []), save_dir)

    elif 'friendstimeline' in response.url or 'groupstimeline' in response.url:
        save_dir = f'data/weibo/profiles/json/'
        await parse_weibo_list(data.get('statuses', []), save_dir)


async def extract_user_info(page):
    print("正在提取用户信息...")
    try:
        profile_anchor = page.locator('div.woo-tab-nav a[href^="/u/"]').first
        await profile_anchor.wait_for(timeout=5000)

        href = await profile_anchor.get_attribute("href")
        user_url = f"https://weibo.com{href}" if href.startswith("/") else href

        username_div = profile_anchor.locator('.woo-tab-item-main')
        username = await username_div.get_attribute("aria-label")

        print("=" * 40)
        print(f"用户名: {username}")
        print(f"主页地址: {user_url}")
        print("=" * 40)

    except Exception as e:
        print(f"提取用户信息失败: {e}")


async def login(context, page):
    # 监听 response 事件
    context.on("response", handle_response)

    print("正在访问微博首页...")
    await page.goto(f"https://{site}")

    login_link = page.get_by_role("link", name="johnjohn01", exact=True)
    if await login_link.is_visible():
        print(">>> 状态：已登录")
        await extract_user_info(page)
    else:
        print("1. 点击登录按钮...")
        async with page.expect_popup() as page1_info:
            await page.get_by_role("button", name="登录/注册").click()

        page1 = await page1_info.value
        print("2. 扫码窗口已弹出，请扫码...")

        try:
            # 增加超时时间，防止用户扫码过慢直接抛出 timeout error
            await page.wait_for_url(
                re.compile(r"^https://weibo\.com/?$"),
                timeout=0,
                wait_until="domcontentloaded"
            )
            print("3. 登录成功，跳转完成！")
            await extract_user_info(page)

        except Exception as e:
            print(f"登录过程出错: {e}")


async def save_cookies(context):
    """
    完全异步保存 Cookies 和上传
    """
    try:
        cookies_list = await context.cookies()
        filtered = [c for c in cookies_list if site in c["domain"]]
        cookie_string = "; ".join(f"{c['name']}={c['value']}" for c in filtered)

        # 1. 异步写文件
        async with aiofiles.open(COOKIE_FILE, "w", encoding="utf-8") as f:
            await f.write(cookie_string)
        print("🍪 cookies 保存完成")

        # 2. 异步执行 SCP 命令
        # 使用 create_subprocess_shell 替代 os.system
        print("🚀 开始上传服务器...")
        cmd = "scp cookies/johnjohn01.txt root@rn:/root/pythonproject/weibo_tg_bot/cookies/"

        process = await asyncio.create_subprocess_shell(
            cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )

        # 等待命令结束
        stdout, stderr = await process.communicate()

        if process.returncode == 0:
            print("🚀 服务器上传 OK")
        else:
            print(f"❌ 上传失败: {stderr.decode().strip()}")

    except Exception as e:
        print(f"保存/上传失败: {e}")


# ================= 运行测试 =================

async def run():
    USER_DATA_DIR = './browser_data'

    async with async_playwright() as p:
        context = await p.chromium.launch_persistent_context(
            user_data_dir=USER_DATA_DIR,
            headless=False,
            channel="msedge",
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
