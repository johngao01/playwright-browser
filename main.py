# main.py
import asyncio

from playwright.async_api import ProxySettings, async_playwright
from platforms.login import login_weibo
from platforms.login import login_instagram
from platforms.login import login_x


async def main():
    # 替换你的代理端口
    PROXY_SERVER = "http://127.0.0.1:10808"
    proxy = ProxySettings(server=PROXY_SERVER)
    USER_DATA_DIR = './browser_data'
    async with async_playwright() as p:
        context = await p.chromium.launch_persistent_context(
            user_data_dir=USER_DATA_DIR,
            headless=False,
            channel="msedge",
            # 这步操作直接去掉了“msedge 正受到自动测试软件的控制”的横幅
            ignore_default_args=["--enable-automation"],
            proxy=proxy,
            args=[
                "--disable-blink-features=AutomationControlled",  # 最关键：禁用自动化控制特征
                "--autoplay-policy=no-user-gesture-required",
                "--mute-audio",
                "--start-maximized"  # 启动时最大化
            ],
            no_viewport=True,  # 必须开启，否则 maximize 不生效，页面会受限于默认窗口大小
        )
        context.set_default_timeout(0)
        weibo_page = context.pages[0]
        await login_weibo.login(context, weibo_page)
        instagram_page = await context.new_page()
        await login_instagram.login(context, instagram_page)
        x_page = await context.new_page()
        await login_x.login(context, x_page)
        await login_instagram.save_cookies(context)
        await login_weibo.save_cookies(context)

        await context.wait_for_event("close", timeout=0)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("程序已停止")
