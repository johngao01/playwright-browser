# login_instagram.py
import datetime
import traceback
from playwright.sync_api import sync_playwright, ProxySettings
import json
import os


def extract_posts_recursively(data):
    """
    递归遍历字典或列表，查找所有同时包含 'code' 和 'user' 字段的字典。

    :param data: 响应体的 JSON 数据 (dict 或 list)
    :return: 符合条件的 post 字典列表
    """
    found_posts = []

    def _search(obj):
        if isinstance(obj, dict):
            # 核心判断逻辑：同时存在 code 和 user
            # 你也可以根据需要增加判断，例如: and obj['user'] is not None
            if (("code" in obj and type(obj['code']) is str) and
                    ("user" in obj and type(obj['user']) is dict and 'username' in obj['user'])):
                found_posts.append(obj)

            # 继续深入遍历字典的值
            for value in obj.values():
                _search(value)

        elif isinstance(obj, list):
            # 如果是列表，遍历列表中的每一项
            for item in obj:
                _search(item)

    _search(data)
    return found_posts


class InstagramLoginHandler:
    site = "instagram.com"
    username = 'neverblock11'
    password = 'swdawfadffg42158'
    COOKIE_FILE = f'cookies/{username}.txt'
    user_url = 'https://www.instagram.com/{}/'.format(username)
    posts = []

    def __init__(self, context):
        self.context = context

    def handle_response(self, response):
        # 1. 基础过滤：只处理我们关心的 URL 且必须是 POST
        if (("graphql/query" in response.url and response.request.method == "POST")
                or 'api/v1/discover/web/explore_grid' in response.url):
            # 2. 状态码过滤：如果是 302 跳转或 204 无内容，直接跳过，否则 .json() 必报错
            if not (200 <= response.status < 300):
                return
            # 3. 获取 POST 请求体数据
            # post_data 通常是 key=value&key2=value2 格式的字符串
            post_body_str = response.request.post_data or ''
            # 4. 【关键修改】获取响应体时的防御性处理
            try:
                # 尝试获取 JSON 数据
                # 这里是最容易报 "No resource with given identifier found" 的地方
                data = response.json()
            except Exception as e:
                # 捕获 Protocol error，不让它中断程序
                # 这种情况通常是偶发的，丢弃这条数据即可
                print(f"⚠️ 无法获取响应体 (可能是浏览器已清理资源): {e}")
                return
            try:
                if "PolarisProfilePageContentQuery" in post_body_str:
                    # 这是访问用户主页后，获取用户详细信息的请求
                    user = data['data']['user']
                    username = user['username']
                    save_path = os.path.join('data/instagram/profiles/json', username, f'{username}.json')
                    os.makedirs(os.path.dirname(save_path), exist_ok=True)
                    with open(save_path, 'w', encoding='utf8') as f:
                        json.dump(user, f, ensure_ascii=False, indent=4)
                    print(f"\n🔍 捕获到用户主页 {username} 请求")
                else:
                    if 'PolarisProfilePostsQuery' in post_body_str:
                        save_dir = f'data/instagram/profiles/json/'
                    elif 'PolarisProfilePostsTabContentQuery_connection' in post_body_str:
                        save_dir = f'data/instagram/profiles/json/'
                    else:
                        save_dir = f'data/instagram/explore/json/'
                    posts = extract_posts_recursively(data)
                    self.posts.extend(posts)
                    for post in posts:
                        try:
                            username = post['user']['username']
                            code = post['code']
                            json_path = os.path.join(save_dir, username, f'{code}.json')
                            os.makedirs(os.path.dirname(json_path), exist_ok=True)
                            with open(json_path, 'w', encoding='utf8') as f:
                                json.dump(post, f, ensure_ascii=False, indent=4)
                            print(f"💾 Saved Post: @{username} -> https://www.instagram.com/p/{code} -> {json_path}")
                        except Exception as e:
                            print(e)
            except Exception as e:
                traceback.print_exc()
                print(f"处理业务逻辑出错: {e}")

    def screenshot(self):
        for i, page in enumerate(self.context.pages, start=1):
            now = datetime.datetime.timestamp(datetime.datetime.now())
            page.screenshot(path=f'screenshot/fullpage-{now}.png', full_page=True)

    def login(self):
        page = self.context.pages[0]
        self.context.on("response", self.handle_response)
        page.on("load", self.screenshot)
        # page.on("framenavigated", lambda frame: print("URL:", frame.url))
        page.goto(f"https://www.{self.site}/")
        print("正在检测登录状态...")
        if page.get_by_role("link", name=self.username, exact=True).is_visible():
            print(">>> 已登录")
        else:
            print(">>> 未登录")
            page.get_by_role("textbox", name="电话号码、账号或邮箱").click()
            page.get_by_role("textbox", name="电话号码、账号或邮箱").fill("neverblock11")
            page.get_by_role("textbox", name="密码").click()
            page.get_by_role("textbox", name="密码").fill("swdawfadffg42158")
            page.get_by_role("button", name="登录").click()
            try:
                page.get_by_role("button", name="保存信息").click()
                print("保存信息")
            except TimeoutError:
                pass
            try:
                page.get_by_role("button", name="确定").click()
                print("点击确定")
            except TimeoutError:
                pass
            # page.get_by_role("link", name=self.username, exact=True).click()
            # page.get_by_role("link", name=f"{self.username}的头像 主页").click()
            # page.get_by_role("link", name="首页 首页").click()

    def save_cookies(self):
        try:
            cookies_list = self.context.cookies()
            filtered = [c for c in cookies_list if self.site in c["domain"]]
            cookie_string = "; ".join(f"{c['name']}={c['value']}" for c in filtered)

            os.makedirs(os.path.dirname(self.COOKIE_FILE), exist_ok=True)
            with open(self.COOKIE_FILE, "w", encoding="utf-8") as f:
                f.write(cookie_string)
            print(f"🍪 Instagram cookies 保存完成")
        except Exception as e:
            print(f"保存失败: {e}")


# ================= 运行测试 =================

def run():
    # 替换你的代理端口
    PROXY_SERVER = "http://127.0.0.1:10808"
    proxy = ProxySettings(server=PROXY_SERVER)
    USER_DATA_DIR = './browser_data/instagram'
    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=USER_DATA_DIR,
            headless=False,
            channel="chrome",
            # 这步操作直接去掉了“Chrome 正受到自动测试软件的控制”的横幅
            # ignore_default_args=["--enable-automation"],
            proxy=proxy,
            args=[
                "--autoplay-policy=no-user-gesture-required",
                "--mute-audio",
                "--start-maximized"  # 启动时最大化
            ],
            no_viewport=True,  # 必须开启，否则 maximize 不生效，页面会受限于默认窗口大小
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        )

        instagram = InstagramLoginHandler(context)
        instagram.login()
        # 登录成功后保存
        instagram.save_cookies()
        print("\n>>> 程序挂起中，关闭窗口退出...")
        context.wait_for_event("close", timeout=0)


if __name__ == "__main__":
    run()
