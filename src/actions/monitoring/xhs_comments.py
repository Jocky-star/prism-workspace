#!/usr/bin/env python3
"""
小红书评论收集 + 回复工具
用法:
  python3 xhs_comments.py collect          # 收集最新评论/提及
  python3 xhs_comments.py reply <note_url> <comment_id> <text>  # 回复指定评论

核心思路:
- Selenium + Firefox (Wayland) 打开小红书
- 在浏览器 context 内 fetch API（绕过反爬）
- 评论数据输出为 JSON，方便星星解析
"""
import os, sys, time, json

# Wayland 环境
os.environ["WAYLAND_DISPLAY"] = "wayland-0"
os.environ["XDG_RUNTIME_DIR"] = "/run/user/1000"
os.environ["MOZ_ENABLE_WAYLAND"] = "1"

from selenium import webdriver
from selenium.webdriver.firefox.service import Service
from selenium.webdriver.firefox.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# Firefox profile 目录（复用登录态）
PROFILE_DIR = os.path.expanduser("~/.mozilla/firefox/xhs-profile")
QR_SCREENSHOT = "/tmp/xhs_qr_comments.png"
STATUS_FILE = "/tmp/xhs_comments_status.json"
RESULT_FILE = "/tmp/xhs_comments_result.json"


def status(s, msg=""):
    data = {"status": s, "msg": msg, "time": time.time()}
    with open(STATUS_FILE, "w") as f:
        json.dump(data, f, ensure_ascii=False)
    print(f"[{s}] {msg}", flush=True)


def create_driver(headless=False):
    """创建 Firefox driver，尝试复用 profile"""
    service = Service(executable_path="/usr/local/bin/geckodriver")
    options = Options()
    if headless:
        options.add_argument("--headless")
    
    # 尝试复用 profile（保持登录态）
    if os.path.isdir(PROFILE_DIR):
        options.add_argument("-profile")
        options.add_argument(PROFILE_DIR)
    
    driver = webdriver.Firefox(service=service, options=options)
    driver.set_window_size(1280, 720)
    return driver


def load_cookies(driver):
    """从 cookies.json 加载已保存的 cookie"""
    cookie_file = os.path.join(PROFILE_DIR, "cookies.json")
    if not os.path.isfile(cookie_file):
        return False
    
    try:
        with open(cookie_file) as f:
            cookies = json.load(f)
        
        # 先访问小红书域名（Selenium 要求 cookie 域与当前页面匹配）
        driver.get("https://www.xiaohongshu.com/")
        time.sleep(2)
        
        for c in cookies:
            cookie = {
                "name": c["name"],
                "value": c["value"],
                "domain": c.get("domain", ""),
                "path": c.get("path", "/"),
            }
            if "expiry" in c:
                cookie["expiry"] = int(c["expiry"])
            if c.get("secure"):
                cookie["secure"] = True
            try:
                driver.add_cookie(cookie)
            except Exception:
                pass  # 跳过域名不匹配的 cookie
        
        status("cookies_loaded", f"{len(cookies)} cookies from {cookie_file}")
        return True
    except Exception as e:
        status("cookies_load_failed", str(e))
        return False


def ensure_login(driver, wait_for_scan=True):
    """确保已登录小红书，如需要则等扫码"""
    # 尝试先加载保存的 cookie
    has_cookies = load_cookies(driver)
    
    driver.get("https://creator.xiaohongshu.com/")
    time.sleep(5)
    
    # 检查是否已登录
    if "login" not in driver.current_url:
        status("logged_in", "session valid")
        return True
    
    # cookie 没生效，但如果有 cookie 文件，试试刷新
    if has_cookies:
        status("cookies_stale", "saved cookies did not work, need fresh login")
    
    if not wait_for_scan:
        status("need_login", "session expired, need QR scan")
        return False
    
    # 需要扫码
    driver.get("https://creator.xiaohongshu.com/login")
    time.sleep(3)
    
    # 尝试切到扫码 tab
    try:
        imgs = driver.find_elements(By.CSS_SELECTOR, ".login-box-container img")
        for img in imgs:
            if 20 < img.size.get("width", 0) < 100:
                img.click()
                break
        time.sleep(2)
    except Exception:
        pass
    
    driver.save_screenshot(QR_SCREENSHOT)
    status("qr_ready", f"screenshot: {QR_SCREENSHOT}")
    
    # 等扫码（最多 5 分钟）
    for _ in range(150):
        time.sleep(2)
        if "login" not in driver.current_url:
            status("logged_in", driver.current_url)
            
            # 保存 cookie
            save_profile(driver)
            return True
    
    status("login_timeout")
    return False


def save_profile(driver):
    """保存当前 cookie 到 profile 目录"""
    os.makedirs(PROFILE_DIR, exist_ok=True)
    
    # 保存当前域的 cookie
    cookies = driver.get_cookies()
    
    # 还要去小红书主站拿 cookie
    try:
        current = driver.current_url
        driver.get("https://www.xiaohongshu.com/")
        time.sleep(2)
        main_cookies = driver.get_cookies()
        # 合并，去重
        seen = set()
        all_cookies = []
        for c in cookies + main_cookies:
            key = (c["name"], c.get("domain", ""))
            if key not in seen:
                seen.add(key)
                all_cookies.append(c)
        cookies = all_cookies
        driver.get(current)
        time.sleep(1)
    except Exception:
        pass
    
    with open(os.path.join(PROFILE_DIR, "cookies.json"), "w") as f:
        json.dump(cookies, f, ensure_ascii=False)
    status("profile_saved", f"{len(cookies)} cookies -> {PROFILE_DIR}")


def collect_mentions(driver, num=20):
    """收集最新提及/评论通知"""
    # 必须在 creator 域下调用 API
    if "creator.xiaohongshu.com" not in driver.current_url:
        driver.get("https://creator.xiaohongshu.com/")
        time.sleep(5)
    
    # 先试 creator 后台的消息通知 API
    result = driver.execute_async_script(f"""
        var callback = arguments[arguments.length - 1];
        (async function() {{
            try {{
                // 先试 mentions
                var resp = await fetch(
                    'https://edith.xiaohongshu.com/api/sns/web/v1/you/mentions?num={num}&cursor=',
                    {{ credentials: 'include' }}
                );
                var data = await resp.json();
                if (data.code === 0 || data.success) {{
                    callback(JSON.stringify({{source: 'mentions', ...data}}));
                    return;
                }}
                
                // mentions 不行，试互动消息 API
                resp = await fetch(
                    'https://edith.xiaohongshu.com/api/sns/web/v1/you/interactions?num={num}&cursor=',
                    {{ credentials: 'include' }}
                );
                data = await resp.json();
                if (data.code === 0 || data.success) {{
                    callback(JSON.stringify({{source: 'interactions', ...data}}));
                    return;
                }}
                
                // 都不行，试评论列表 API（creator 后台）
                resp = await fetch(
                    'https://edith.xiaohongshu.com/api/galaxy/creator/comment/list?tab_type=0&page=1&page_size=20',
                    {{ credentials: 'include' }}
                );
                data = await resp.json();
                callback(JSON.stringify({{source: 'creator_comment', ...data}}));
            }} catch(e) {{
                callback(JSON.stringify({{error: e.toString()}}));
            }}
        }})();
    """)
    
    return json.loads(result) if result else {"error": "no response"}


def collect_comments_from_note(driver, note_url):
    """从笔记详情页收集评论"""
    driver.get(note_url)
    time.sleep(5)
    
    # 在页面 context 中提取评论
    result = driver.execute_script("""
        var comments = [];
        // 尝试从页面 DOM 提取评论
        var commentEls = document.querySelectorAll('.comment-item, .note-comment, [class*="comment"]');
        commentEls.forEach(function(el) {
            var author = el.querySelector('.author-name, .user-name, [class*="author"], [class*="nickname"]');
            var content = el.querySelector('.content, .comment-content, [class*="content"]');
            var timeEl = el.querySelector('.time, [class*="time"], [class*="date"]');
            if (content && content.textContent.trim()) {
                comments.push({
                    author: author ? author.textContent.trim() : 'unknown',
                    content: content.textContent.trim(),
                    time: timeEl ? timeEl.textContent.trim() : '',
                    // 尝试获取 comment id
                    id: el.getAttribute('data-id') || el.getAttribute('id') || ''
                });
            }
        });
        return comments;
    """)
    
    return result or []


def collect_notes_list(driver):
    """获取自己的笔记列表（从创作者中心）"""
    driver.get("https://creator.xiaohongshu.com/publish/note")
    time.sleep(3)
    
    # 尝试通过 API 获取笔记列表
    result = driver.execute_async_script("""
        var callback = arguments[arguments.length - 1];
        (async function() {
            try {
                const resp = await fetch(
                    'https://edith.xiaohongshu.com/api/galaxy/creator/datacenter/note/analyze/list?page=1&page_size=20&sort_field=time&sort_order=desc',
                    { credentials: 'include' }
                );
                const data = await resp.json();
                callback(JSON.stringify(data));
            } catch(e) {
                callback(JSON.stringify({error: e.toString()}));
            }
        })();
    """);
    
    return json.loads(result) if result else {"error": "no response"}


def reply_to_comment(driver, note_url, reply_text, target_comment_index=0):
    """
    在笔记详情页回复评论
    note_url: 笔记页面 URL
    reply_text: 回复内容
    target_comment_index: 要回复的评论索引（0=第一条）
    """
    driver.get(note_url)
    time.sleep(5)
    
    # 点击目标评论的"回复"按钮
    clicked = driver.execute_script(f"""
        var replyBtns = document.querySelectorAll('[class*="reply"], button');
        var targets = [];
        replyBtns.forEach(function(b) {{
            if (b.textContent.trim() === '回复' || b.textContent.trim().includes('回复')) {{
                targets.push(b);
            }}
        }});
        if (targets.length > {target_comment_index}) {{
            targets[{target_comment_index}].click();
            return 'clicked_reply_' + targets.length;
        }}
        return 'no_reply_btn_found_' + targets.length;
    """)
    
    status("reply_btn", clicked)
    time.sleep(1)
    
    # 找到输入框并填写
    typed = driver.execute_script(f"""
        // 找回复输入框
        var inputs = document.querySelectorAll(
            '.input-box [contenteditable=true], ' +
            '[class*="comment"] [contenteditable=true], ' +
            '[class*="reply"] [contenteditable=true], ' +
            'textarea[class*="comment"], textarea[class*="reply"]'
        );
        if (inputs.length > 0) {{
            var el = inputs[inputs.length - 1]; // 取最后一个（通常是回复框）
            el.focus();
            el.textContent = '{reply_text}';
            el.dispatchEvent(new Event('input', {{bubbles: true}}));
            return 'typed';
        }}
        return 'no_input_found';
    """)
    
    status("reply_typed", typed)
    time.sleep(1)
    
    # 点发送/提交按钮
    submitted = driver.execute_script("""
        var btns = document.querySelectorAll('button, [class*="submit"], [class*="send"]');
        for (var b of btns) {
            var t = b.textContent.trim();
            if ((t === '发送' || t === '提交' || t === '回复') && 
                b.getBoundingClientRect().width > 0) {
                b.click();
                return 'submitted: ' + t;
            }
        }
        return 'no_submit_btn';
    """)
    
    status("reply_submit", submitted)
    time.sleep(2)
    
    driver.save_screenshot("/tmp/xhs_reply_result.png")
    return submitted


def main():
    if len(sys.argv) < 2:
        print("用法:")
        print("  python3 xhs_comments.py collect              # 收集评论通知")
        print("  python3 xhs_comments.py notes                # 列出自己的笔记")
        print("  python3 xhs_comments.py note_comments <url>  # 收集笔记评论")
        print("  python3 xhs_comments.py reply <url> <text> [index]  # 回复评论")
        sys.exit(1)
    
    action = sys.argv[1]
    
    driver = create_driver(headless=False)
    try:
        if not ensure_login(driver):
            print("登录失败", file=sys.stderr)
            sys.exit(1)
        
        if action == "collect":
            status("collecting")
            mentions = collect_mentions(driver)
            with open(RESULT_FILE, "w") as f:
                json.dump(mentions, f, ensure_ascii=False, indent=2)
            status("done", f"saved to {RESULT_FILE}")
            
            # 打印摘要
            if isinstance(mentions, dict) and "data" in mentions:
                items = mentions["data"].get("mentions", mentions["data"].get("list", []))
                print(f"\n=== 收到 {len(items)} 条提及 ===")
                for i, item in enumerate(items[:10]):
                    user = item.get("user", {}).get("nickname", "?")
                    content = item.get("content", item.get("desc", ""))[:60]
                    print(f"  [{i}] {user}: {content}")
            else:
                print(json.dumps(mentions, ensure_ascii=False, indent=2)[:500])
        
        elif action == "notes":
            status("fetching_notes")
            notes = collect_notes_list(driver)
            with open(RESULT_FILE, "w") as f:
                json.dump(notes, f, ensure_ascii=False, indent=2)
            status("done", f"saved to {RESULT_FILE}")
            print(json.dumps(notes, ensure_ascii=False, indent=2)[:1000])
        
        elif action == "note_comments":
            if len(sys.argv) < 3:
                print("需要笔记 URL")
                sys.exit(1)
            url = sys.argv[2]
            status("collecting_comments", url)
            comments = collect_comments_from_note(driver, url)
            with open(RESULT_FILE, "w") as f:
                json.dump(comments, f, ensure_ascii=False, indent=2)
            status("done", f"{len(comments)} comments")
            for i, c in enumerate(comments[:10]):
                print(f"  [{i}] {c['author']}: {c['content'][:60]}")
        
        elif action == "reply":
            if len(sys.argv) < 4:
                print("需要: <note_url> <reply_text> [comment_index]")
                sys.exit(1)
            url = sys.argv[2]
            text = sys.argv[3]
            idx = int(sys.argv[4]) if len(sys.argv) > 4 else 0
            result = reply_to_comment(driver, url, text, idx)
            print(f"Reply result: {result}")
        
        else:
            print(f"未知操作: {action}")
            sys.exit(1)
    
    finally:
        driver.quit()


if __name__ == "__main__":
    main()
