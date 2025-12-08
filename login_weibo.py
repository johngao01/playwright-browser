# login_weibo.py
import json
import os
import re
import asyncio
from datetime import datetime
from playwright.async_api import async_playwright

site = "weibo.com"
COOKIE_FILE = 'cookies/johnjohn01.txt'
weibo_list = []
username = ''
userid = ''
user_url = ''


def standardize_date(created_at):
    """
    将微博的创建时间标准格式化
    (纯逻辑函数，无需改为 async)
    """
    created_at = created_at.replace("+0800 ", "")
    ts = datetime.strptime(created_at, "%c")
    return ts


def parse_weibo(weibo, save_dir):
    """
    解析并保存微博数据
    (包含文件IO，在高性能场景下建议改为 aiofiles，但此处为保持逻辑一致仍保留同步 IO)
    """
    user = weibo.get('user', {})
    author_name = user.get('screen_name', '未知作者')
    idstr = str(weibo.get('id', ''))  # 确保是字符串
    json_path = os.path.join(save_dir, author_name, f'{idstr}.json')
    os.makedirs(os.path.dirname(json_path), exist_ok=True)

    with open(json_path, 'w', encoding='utf8') as f:
        json.dump(weibo, f, ensure_ascii=False, indent=4)

    content = weibo.get('text_raw', '')
    created_at = weibo.get('created_at', '')
    url = f"https://weibo.com/{user.get('id', '')}/{idstr}"
    print(f"{author_name} | {standardize_date(created_at)} | {url} | {content}")

    if 'retweeted_status' in weibo:
        retweet = weibo['retweeted_status']
        r_user = retweet.get('user', {}).get('screen_name', '未知')
        r_text = retweet.get('text_raw', '')
        print(f"   -> [转发] @{r_user}: {r_text[:50]}...")

    print("-" * 50)


# 2. 改为 async def，因为 playwright 的 response.json() 在异步模式下需要 await
async def handle_response(response):
    # 拦截并解析 主页时间流 微博
    if "unreadfriendstimeline" in response.url and response.status == 200:
        save_dir = f'data/weibo/explore/json/'
        try:
            # 3. await response.json()
            data = await response.json()
            print("=" * 20 + " 微博信息流数据 " + "=" * 20)
            statuses = data.get('statuses', [])
            if not statuses:
                print("未找到微博列表数据")
                return
            for i, weibo in enumerate(statuses):
                try:
                    weibo_list.append(weibo)
                    # parse_weibo 是同步函数，可以直接调用
                    parse_weibo(weibo, save_dir)
                except Exception as inner_e:
                    print(f"解析第 {i} 条微博时出错: {inner_e}")
        except Exception as e:
            print(f"响应内容解析失败: {e}")

    elif '/ajax/profile/info?uid=' in response.url and response.status == 200:
        try:
            data = await response.json()
            username = data['data']['user']['screen_name']
            save_dir = f'data/weibo/profiles/json/'
            json_path = os.path.join(save_dir, username, f'{username}.json')
            os.makedirs(os.path.dirname(json_path), exist_ok=True)
            with open(json_path, 'w', encoding='utf8') as f:
                json.dump(data, f, ensure_ascii=False, indent=4)
            print(f"已保存用户 {username} 的信息 -> {json_path}")
        except Exception as e:
            print(e)

    elif 'ajax/statuses/mymblog?uid=' in response.url and response.status == 200:
        save_dir = f'data/weibo/profiles/json/'
        try:
            data = await response.json()
            print("=" * 20 + " 微博信息流数据 " + "=" * 20)
            statuses = data['data']['list']
            if not statuses:
                print("未找到微博列表数据")
                return
            for i, weibo in enumerate(statuses):
                try:
                    weibo_list.append(weibo)
                    parse_weibo(weibo, save_dir)
                except Exception as inner_e:
                    print(f"解析第 {i} 条微博时出错: {inner_e}")
        except Exception as e:
            print(f"响应内容解析失败: {e}")


async def extract_user_info(page):
    print("正在提取用户信息...")
    try:
        # 4. Locator 操作改为 await
        profile_anchor = page.locator('div.woo-tab-nav a[href^="/u/"]').first
        await profile_anchor.wait_for(timeout=5000)

        href = await profile_anchor.get_attribute("href")
        userid = href.split("/")[-1]
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
    context.on("response", handle_response)

    print("正在访问微博首页...")
    await page.goto(f"https://{site}")

    # 6. 状态判断及操作全部 await
    # is_visible() 需要 await
    login_link = page.get_by_role("link", name="johnjohn01", exact=True)
    if await login_link.is_visible():
        print(">>> 状态：已登录")
        await extract_user_info(page)
    else:
        # 尝试登录功能
        print("1. 点击登录按钮...")
        # async 上下文管理器
        async with page.expect_popup() as page1_info:
            await page.get_by_role("button", name="登录/注册").click()

        # 获取弹出页面的句柄需要 await value
        page1 = await page1_info.value
        print("2. 扫码窗口已弹出，请扫码...")

        try:
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
    保存 Cookies
    """
    try:
        # cookies() 需要 await
        cookies_list = await context.cookies()
        filtered = [c for c in cookies_list if site in c["domain"]]
        cookie_string = "; ".join(f"{c['name']}={c['value']}" for c in filtered)
        with open(COOKIE_FILE, "w", encoding="utf-8") as f:
            f.write(cookie_string)
        print("🍪 cookies 保存完成")
        # os.system 是同步阻塞的，在严格异步编程中推荐 asyncio.create_subprocess_shell
        # 但为了简单起见，这里保留 os.system，它会短暂阻塞 event loop
        os.system("scp cookies/johnjohn01.txt root@rn:/root/pythonproject/weibo_tg_bot/cookies/")
        print("🚀 服务器上传 OK")
    except Exception as e:
        print(f"保存 Header 字符串失败: {e}")


# ================= 运行测试 =================

async def run():
    USER_DATA_DIR = './browser_data'

    # 使用 async_playwright
    async with async_playwright() as p:
        # launch_persistent_context 需要 await
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
        await login(context, context.pages[0])
        await save_cookies(context)

        print("\n>>> 程序挂起中，关闭窗口退出...")
        # 等待关闭事件
        await context.wait_for_event("close", timeout=0)


if __name__ == "__main__":
    # 使用 asyncio.run 运行主协程
    asyncio.run(run())
