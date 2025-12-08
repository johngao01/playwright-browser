# login_instagram.py
import traceback
import json
import os
import asyncio
from playwright.async_api import async_playwright, ProxySettings

site = "instagram.com"
username = 'neverblock11'
password = 'swdawfadffg42158'
COOKIE_FILE = f'cookies/{username}.txt'
user_url = 'https://www.instagram.com/{}/'.format(username)
posts = []


def extract_posts_recursively(data):
    """
    递归遍历字典或列表 (纯 CPU 逻辑，无需改为 async)
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


# 2. 改为 async def
async def handle_response(response):
    # 1. 基础过滤
    if (("graphql/query" in response.url and response.request.method == "POST")
            or 'api/v1/discover/web/explore_grid' in response.url):

        if not (200 <= response.status < 300):
            return

        post_body_str = response.request.post_data or ''

        try:
            data = await response.json()
        except Exception as e:
            print(f"⚠️ 无法获取响应体: {e}")
            return

        try:
            if "PolarisProfilePageContentQuery" in post_body_str:
                user = data['data']['user']
                profile_name = user['username']
                save_path = os.path.join('data/instagram/profiles/json', profile_name, f'{profile_name}.json')
                os.makedirs(os.path.dirname(save_path), exist_ok=True)
                # 文件 IO 保持同步即可，除非数据量极大才需要 aiofiles
                with open(save_path, 'w', encoding='utf8') as f:
                    json.dump(user, f, ensure_ascii=False, indent=4)
                print(f"\n🔍 捕获到用户主页 {profile_name} 请求")
            else:
                if 'PolarisProfilePostsQuery' in post_body_str:
                    save_dir = f'data/instagram/profiles/json/'
                elif 'PolarisProfilePostsTabContentQuery_connection' in post_body_str:
                    save_dir = f'data/instagram/profiles/json/'
                else:
                    save_dir = f'data/instagram/explore/json/'

                profile_posts = extract_posts_recursively(data)
                posts.extend(profile_posts)
                for post in profile_posts:
                    try:
                        author_username = post['user']['username']
                        code = post['code']
                        json_path = os.path.join(save_dir, author_username, f'{code}.json')
                        os.makedirs(os.path.dirname(json_path), exist_ok=True)
                        with open(json_path, 'w', encoding='utf8') as f:
                            json.dump(post, f, ensure_ascii=False, indent=4)
                        print(f"💾 Saved Post: @{author_username} -> https://www.instagram.com/p/{code} -> {json_path}")
                    except Exception as e:
                        print(e)
        except Exception as e:
            traceback.print_exc()
            print(f"处理业务逻辑出错: {e}")


async def login(context, page):
    context.on("response", handle_response)

    await page.goto(f"https://www.{site}/")
    print("正在检测登录状态...")

    login_link = page.get_by_role("link", name=username, exact=True)
    if await login_link.is_visible():
        print(">>> 已登录")
    else:
        print(">>> 未登录")
        await page.get_by_role("textbox", name="电话号码、账号或邮箱").click()
        await page.get_by_role("textbox", name="电话号码、账号或邮箱").fill("neverblock11")
        await page.get_by_role("textbox", name="密码").click()
        await page.get_by_role("textbox", name="密码").fill("swdawfadffg42158")
        await page.get_by_role("button", name="登录").click()

        try:
            await page.get_by_role("button", name="保存信息").click()
            print("保存信息")
        except Exception:
            print("保存信息未点击")

        try:
            await page.get_by_role("button", name="确定").click()
            print("点击确定")
        except Exception:
            print("点击确定未点击")


async def save_cookies(context):
    try:
        cookies_list = await context.cookies()
        filtered = [c for c in cookies_list if site in c["domain"]]
        cookie_string = "; ".join(f"{c['name']}={c['value']}" for c in filtered)

        os.makedirs(os.path.dirname(COOKIE_FILE), exist_ok=True)
        with open(COOKIE_FILE, "w", encoding="utf-8") as f:
            f.write(cookie_string)
        print(f"🍪 Instagram cookies 保存完成")
    except Exception as e:
        print(f"保存失败: {e}")


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

        await  login(context, context.pages[0])
        await  save_cookies(context)

        print("\n>>> 程序挂起中，关闭窗口退出...")
        await context.wait_for_event("close", timeout=0)


if __name__ == "__main__":
    # 12. 使用 asyncio.run
    asyncio.run(run())
