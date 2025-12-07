# login_weibo.py
import json
import os
import re
from datetime import datetime

from playwright.sync_api import sync_playwright


def standardize_date(created_at):
    """
    将微博的创建时间标准格式化
    :param created_at: 微博的创建时间
    :return:
    """
    created_at = created_at.replace("+0800 ", "")
    ts = datetime.strptime(created_at, "%c")
    return ts


def parse_weibo(weibo, save_dir):
    user = weibo.get('user', {})
    author_name = user.get('screen_name', '未知作者')
    idstr = weibo.get('id', '')
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


class WeiboLoginHandler:
    site = "weibo.com"
    # 这个文件用来保存当前网站的cookies
    COOKIE_FILE = 'cookies/johnjohn01.txt'
    weibo_list = []
    username = ''
    userid = ''
    user_url = ''

    def __init__(self, context):
        self.context = context

    def handle_response(self, response):
        # 拦截并解析 主页时间流 微博
        if "unreadfriendstimeline" in response.url and response.status == 200:
            save_dir = f'data/weibo/explore/json/'
            try:
                data = response.json()
                print("=" * 20 + " 微博信息流数据 " + "=" * 20)
                statuses = data.get('statuses', [])
                if not statuses:
                    print("未找到微博列表数据")
                    return
                for i, weibo in enumerate(statuses):
                    try:
                        self.weibo_list.append(weibo)
                        parse_weibo(weibo, save_dir)
                    except Exception as inner_e:
                        print(f"解析第 {i} 条微博时出错: {inner_e}")
            except Exception as e:
                print(f"响应内容解析失败: {e}")
        elif '/ajax/profile/info?uid=' in response.url and response.status == 200:
            try:
                data = response.json()
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
                data = response.json()
                print("=" * 20 + " 微博信息流数据 " + "=" * 20)
                statuses = data['data']['list']
                if not statuses:
                    print("未找到微博列表数据")
                    return
                for i, weibo in enumerate(statuses):
                    try:
                        self.weibo_list.append(weibo)
                        parse_weibo(weibo, save_dir)
                    except Exception as inner_e:
                        print(f"解析第 {i} 条微博时出错: {inner_e}")
            except Exception as e:
                print(f"响应内容解析失败: {e}")

    def extract_user_info(self, page):
        print("正在提取用户信息...")
        try:
            profile_anchor = page.locator('div.woo-tab-nav a[href^="/u/"]').first
            profile_anchor.wait_for(timeout=5000)

            href = profile_anchor.get_attribute("href")
            self.userid = href.split("/")[-1]
            self.user_url = f"https://weibo.com{href}" if href.startswith("/") else href

            username_div = profile_anchor.locator('.woo-tab-item-main')
            self.username = username_div.get_attribute("aria-label")

            print("=" * 40)
            print(f"用户名: {self.username}")
            print(f"主页地址: {self.user_url}")
            print("=" * 40)

        except Exception as e:
            print(f"提取用户信息失败: {e}")

    def login(self):
        # 访问首页，检查是否已经登录，未登录使用perform_login完成登录
        page = self.context.pages[0]
        self.context.on("response", self.handle_response)

        print("正在访问微博首页...")
        page.goto(f"https://{self.site}")

        # 3. 状态判断
        if page.get_by_role("link", name="johnjohn01", exact=True).is_visible():
            print(">>> 状态：已登录")
            self.extract_user_info(page)
        else:
            # 尝试登录功能
            print("1. 点击登录按钮...")
            with page.expect_popup() as page1_info:
                page.get_by_role("button", name="登录/注册").click()
            page1 = page1_info.value
            print("2. 扫码窗口已弹出，请扫码...")

            try:
                page.wait_for_url(
                    re.compile(r"^https://weibo\.com/?$"),
                    timeout=0,
                    wait_until="domcontentloaded"
                )
                print("3. 登录成功，跳转完成！")
                self.extract_user_info(page)

            except Exception as e:
                print(f"登录过程出错: {e}")

    def save_cookies(self):
        """
        保存 Cookies
        """
        try:
            cookies_list = self.context.cookies()
            # 只保留 当前网站 的 cookies 到 self.COOKIE_FILE
            filtered = [c for c in cookies_list if self.site in c["domain"]]
            cookie_string = "; ".join(f"{c['name']}={c['value']}" for c in filtered)
            with open(self.COOKIE_FILE, "w", encoding="utf-8") as f:
                f.write(cookie_string)
            print("🍪 cookies 保存完成")
            os.system("scp cookies/johnjohn01.txt root@rn:/root/pythonproject/weibo_tg_bot/cookies/")
            print("🚀 服务器上传 OK")
        except Exception as e:
            print(f"保存 Header 字符串失败: {e}")


# ================= 运行测试 =================

def run():
    # 替换你的代理端口
    # COOKIE_JSON = 'cookies/playwright-browser-cookies.json'
    USER_DATA_DIR = './browser_data/weibo'
    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=USER_DATA_DIR,
            headless=False,
            channel="msedge",
            # 1. 核心步骤：告诉 Playwright 忽略默认的自动化参数
            # 这步操作直接去掉了“Chrome 正受到自动测试软件的控制”的横幅
            # ignore_default_args=["--enable-automation"],
            args=[
                "--autoplay-policy=no-user-gesture-required",
                "--mute-audio",
                "--start-maximized"  # 启动时最大化
            ],
            no_viewport=True,  # 必须开启，否则 maximize 不生效，页面会受限于默认窗口大小
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        )
        weibo = WeiboLoginHandler(context)
        weibo.login()
        weibo.save_cookies()

        print("\n>>> 程序挂起中，关闭窗口退出...")
        context.wait_for_event("close", timeout=0)


if __name__ == "__main__":
    run()
