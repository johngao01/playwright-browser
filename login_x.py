# login_x.py
import traceback
import json
import os
import asyncio
import random
import aiofiles
from playwright.async_api import async_playwright, ProxySettings
from pydash import get

# X 的核心 Cookie 依然基于 twitter.com，但访问的是 x.com
site_keywords = ["x.com", "twitter.com"]
username = 'johngaogao'
password = 'belief1314*'
COOKIE_FILE = f'cookies/{username}.txt'
save_dir = 'data/x/json'


async def save_json(path, data):
    """
    通用异步保存 JSON 函数
    """
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        async with aiofiles.open(path, 'w', encoding='utf8') as f:
            await f.write(json.dumps(data, ensure_ascii=False, indent=4))
    except Exception as e:
        print(f"❌ 异步保存文件失败 {path}: {e}")


def extract_tweets_recursively(data):
    """
    从 X 的复杂 GraphQL 响应中递归提取 Tweet 对象
    """
    found_tweets = []

    def _search(obj):
        if isinstance(obj, dict):
            # 核心特征：类型是 Tweet，且包含核心数据 rest_id
            if obj.get('__typename') == 'Tweet':
                found_tweets.append(obj)

            for value in obj.values():
                _search(value)

        elif isinstance(obj, list):
            for item in obj:
                _search(item)

    _search(data)
    return found_tweets


async def process_and_save_tweet(tweet):
    """
    处理并保存单条推文
    """
    try:
        # 提取推文 ID
        tweet_id = get(tweet, 'rest_id')
        if not tweet_id:
            return

        # 尝试提取作者名 (路径较深，做容错处理)
        author_name = get(tweet, 'core.user_results.result.core.screen_name') or 'unknown'
        url = f"https://x.com/{author_name}/status/{tweet_id}"
        following = get(tweet, 'core.user_results.result.relationship_perspectives.following')
        if following:
            following = 'following'
        else:
            following = 'explore'
        json_path = os.path.join(save_dir, following, author_name, f'{tweet_id}.json')

        await save_json(json_path, tweet)

        # 简单的日志，提取推文内容前 30 个字
        text = get(tweet, 'legacy.full_text')
        print(f"💾 Saved Tweet: @{author_name} | {url} | {text}...")

    except Exception as e:
        print(f"保存单条推文失败: {e}")


async def handle_response(response):
    # 1. 过滤：只关心 GraphQL 请求
    if "/graphql/" not in response.url:
        return

    # 排除不需要的请求 (如 Log, Audio 等)
    if response.request.method != "GET" and response.request.method != "POST":
        return

    if not (200 <= response.status < 300):
        return

    # 2. 获取数据
    try:
        data = await response.json()
    except Exception:
        return

    # 3. 业务逻辑分流
    try:
        url = response.url
        # 提取推文
        tweets = extract_tweets_recursively(data)

        if not tweets:
            return

        # 并发保存
        tasks = [process_and_save_tweet(t) for t in tweets]
        if tasks:
            await asyncio.gather(*tasks)

    except Exception as e:
        traceback.print_exc()
        print(f"处理业务逻辑出错: {e}")


async def human_type(page, locator, text):
    """模拟人类打字"""
    await locator.click()
    for char in text:
        # 随机延迟
        await asyncio.sleep(random.uniform(0.05, 0.15))
        await locator.type(char)


async def login(context, page):
    context.on("response", handle_response)

    await page.goto("https://x.com/")
    print("正在检测登录状态...")
    await asyncio.sleep(5)
    if await page.get_by_role("link", name='个人资料').is_visible():
        print("已登录 X，无需重复登录")
    else:
        await page.get_by_test_id("loginButton").click()
        await page.get_by_role("button", name="重试").click()
        await page.get_by_role("textbox", name="手机号码、邮件地址或用户名").fill(username)
        await page.get_by_role("button", name="下一步").click()
        await page.get_by_role('input', name='password').click()
        await page.get_by_role('input', name='password').fill(password)
        await page.get_by_role('button', name='登录').click()


async def save_cookies(context):
    try:
        cookies_list = await context.cookies()
        # X 的认证 Cookie 混杂在 x.com 和 twitter.com
        filtered = [c for c in cookies_list if any(k in c["domain"] for k in site_keywords)]
        cookie_string = "; ".join(f"{c['name']}={c['value']}" for c in filtered)

        os.makedirs(os.path.dirname(COOKIE_FILE), exist_ok=True)

        async with aiofiles.open(COOKIE_FILE, "w", encoding="utf-8") as f:
            await f.write(cookie_string)

        print(f"🍪 X/Twitter cookies 保存完成")
    except Exception as e:
        print(f"保存失败: {e}")


# ================= 运行测试 =================

async def run():
    PROXY_SERVER = "http://127.0.0.1:10808"
    proxy = ProxySettings(server=PROXY_SERVER)
    # 使用独立的用户数据目录，避免和 Instagram 混用
    USER_DATA_DIR = './browser_data'

    async with async_playwright() as p:
        # === 关键：针对 X 的反爬虫配置 ===
        context = await p.chromium.launch_persistent_context(
            user_data_dir=USER_DATA_DIR,
            headless=False,
            channel="msedge",  # 建议使用实体浏览器核心
            proxy=proxy,
            # 1. 禁用自动化控制特征 (最重要)
            ignore_default_args=["--enable-automation"],
            args=[
                "--disable-blink-features=AutomationControlled",
                "--mute-audio",
                "--start-maximized",
                "--no-sandbox"
            ],
            no_viewport=True,
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        )

        # 增加隐身脚本，进一步移除 webdriver 特征
        await context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined
            });
        """)

        page = context.pages[0]

        # 设置较大的超时时间，因为代理访问 X 可能较慢

        await login(context, page)
        await save_cookies(context)

        print("\n>>> 程序挂起中，关闭窗口退出...")
        await context.wait_for_event("close", timeout=0)


if __name__ == "__main__":
    asyncio.run(run())
