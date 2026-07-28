"""Browser automation tools — headless browser control via Playwright.

Provides tools for navigating web pages, extracting content, taking screenshots,
and interacting with page elements. All operations use a shared browser context
for session persistence (cookies, etc.).
"""
import asyncio
import base64
import re

# Lazy-initialized browser state
_browser = None
_context = None
_lock = asyncio.Lock()


async def _get_browser():
    """Lazy-init Playwright browser (singleton)."""
    global _browser, _context
    if _browser is None:
        from playwright.async_api import async_playwright
        pw = await async_playwright().start()
        _browser = await pw.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-gpu", "--disable-dev-shm-usage"],
        )
        _context = await _browser.new_context(
            viewport={"width": 1280, "height": 720},
            user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        )
    return _browser, _context


async def _cleanup():
    """Close browser on shutdown."""
    global _browser, _context
    if _context:
        await _context.close()
        _context = None
    if _browser:
        await _browser.close()
        _browser = None


def register(registry):
    """Register browser tools."""
    registry.register(
        name="browser_navigate",
        description="用无头浏览器导航到指定URL，返回页面标题和主要内容文本。支持等待页面加载完成。",
        parameters={
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "要访问的URL地址",
                },
                "wait_until": {
                    "type": "string",
                    "enum": ["load", "domcontentloaded", "networkidle"],
                    "description": "等待条件: load(默认), domcontentloaded, networkidle(等待网络空闲)",
                },
            },
            "required": ["url"],
        },
        handler=navigate,
        toolset="browser",
        is_async=True,
        emoji="🌐",
    )
    registry.register(
        name="browser_extract_content",
        description="导航到URL并提取页面的主要内容（正文文本），自动去除导航栏、侧边栏、广告等干扰元素。适合阅读文章、获取页面信息。",
        parameters={
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "要提取内容的URL",
                },
                "selector": {
                    "type": "string",
                    "description": "可选的CSS选择器，只提取匹配元素的内容。不指定则自动提取主体内容。",
                },
                "max_length": {
                    "type": "integer",
                    "description": "返回文本的最大字符数，默认5000",
                },
            },
            "required": [],
        },
        handler=extract_content,
        toolset="browser",
        is_async=True,
        emoji="📄",
    )
    # 注意：url 设为可选（不传则提取当前已打开页面），故 required 为空
    registry.register(
        name="browser_screenshot",
        description="对指定URL或当前页面截图，返回base64编码的PNG图片。可用于查看页面布局、验证操作结果。",
        parameters={
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "要截图的URL。不指定则对当前页面截图。",
                },
                "full_page": {
                    "type": "boolean",
                    "description": "是否截取完整页面（包括滚动区域），默认false只截取可视区域",
                },
            },
            "required": [],
        },
        handler=screenshot,
        toolset="browser",
        is_async=True,
        emoji="📸",
    )
    registry.register(
        name="browser_click",
        description="在页面上点击匹配CSS选择器的元素。需要先导航到页面。",
        parameters={
            "type": "object",
            "properties": {
                "selector": {
                    "type": "string",
                    "description": "要点击的元素的CSS选择器",
                },
                "url": {
                    "type": "string",
                    "description": "可选，先导航到此URL再点击",
                },
            },
            "required": ["selector"],
        },
        handler=click,
        toolset="browser",
        is_async=True,
        emoji="👆",
    )
    registry.register(
        name="browser_type",
        description="在页面的输入框中填写文本。可配合browser_click使用来填写表单。",
        parameters={
            "type": "object",
            "properties": {
                "selector": {
                    "type": "string",
                    "description": "输入框的CSS选择器",
                },
                "text": {
                    "type": "string",
                    "description": "要输入的文本",
                },
                "clear_first": {
                    "type": "boolean",
                    "description": "是否先清空输入框，默认true",
                },
            },
            "required": ["selector", "text"],
        },
        handler=type_text,
        toolset="browser",
        is_async=True,
        emoji="⌨️",
    )
    registry.register(
        name="browser_evaluate",
        description="在页面中执行JavaScript代码并返回结果。可用于提取数据、操作DOM、调用页面JS函数。",
        parameters={
            "type": "object",
            "properties": {
                "script": {
                    "type": "string",
                    "description": "要执行的JavaScript代码",
                },
                "url": {
                    "type": "string",
                    "description": "可选，先导航到此URL再执行",
                },
            },
            "required": ["script"],
        },
        handler=evaluate,
        toolset="browser",
        is_async=True,
        emoji="🔧",
    )
    registry.register(
        name="browser_close",
        description="关闭浏览器，释放资源。在不需要的时侯调用以节省内存。",
        parameters={
            "type": "object",
            "properties": {},
        },
        handler=close_browser,
        toolset="browser",
        is_async=True,
        emoji="🔒",
    )


async def navigate(url: str, wait_until: str = "load") -> str:
    """Navigate to URL and return page title + main text."""
    try:
        _, ctx = await _get_browser()
        page = await ctx.new_page()
        await page.goto(url, wait_until=wait_until, timeout=30000)

        title = await page.title()

        # Extract main content — try common content selectors first
        main_text = ""
        for sel in ["article", "main", "[role='main']", ".content", ".post", "#content", "body"]:
            el = page.locator(sel).first
            if await el.count() > 0:
                main_text = await el.inner_text()
                if main_text.strip():
                    break

        # 注意：不关闭 page，保留会话供后续 extract/click/screenshot 复用

        # Clean up whitespace
        main_text = re.sub(r'\n{3,}', '\n\n', main_text)
        main_text = re.sub(r' {2,}', ' ', main_text)

        # Truncate if too long
        if len(main_text) > 5000:
            main_text = main_text[:5000] + "\n...[truncated]"

        return f"标题: {title}\n\n{main_text.strip()}"

    except Exception as e:
        return f"浏览器导航失败: {e}"


async def extract_content(url: str = "", selector: str = "", max_length: int = 5000) -> str:
    """Extract main content from a URL. If url is empty, extract from the
    currently open page (e.g. after browser_navigate) instead of reloading."""
    try:
        _, ctx = await _get_browser()
        if url:
            page = await ctx.new_page()
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        else:
            pages = ctx.pages
            if not pages:
                return "请先提供 url 参数，或用 browser_navigate 打开一个页面后再提取。"
            page = pages[-1]

        if selector:
            el = page.locator(selector).first
            text = await el.inner_text() if await el.count() > 0 else ""
        else:
            # Remove common noise elements
            await page.evaluate("""
                document.querySelectorAll('nav, footer, aside, .sidebar, .ad, .ads, .advertisement, .cookie-banner, .popup, script, style').forEach(el => el.remove())
            """)
            # Try content containers
            text = ""
            for sel in ["article", "main", "[role='main']", ".content", ".post-body", ".entry-content"]:
                el = page.locator(sel).first
                if await el.count() > 0:
                    text = await el.inner_text()
                    if text.strip():
                        break
            if not text.strip():
                text = await page.locator("body").inner_text()

        if url:
            await page.close()

        text = re.sub(r'\n{3,}', '\n\n', text)
        text = re.sub(r' {2,}', ' ', text).strip()

        if len(text) > max_length:
            text = text[:max_length] + "\n...[truncated]"

        return text if text else "未找到内容"

    except Exception as e:
        return f"内容提取失败: {e}"


async def screenshot(url: str = "", full_page: bool = False) -> str:
    """Take a screenshot and return base64 PNG."""
    try:
        _, ctx = await _get_browser()

        if url:
            page = await ctx.new_page()
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        else:
            # Use the last open page or create blank
            pages = ctx.pages
            page = pages[-1] if pages else await ctx.new_page()
            if not page.url or page.url == "about:blank":
                return "没有可截图的页面，请先用 browser_navigate 导航到URL"

        screenshot_bytes = await page.screenshot(full_page=full_page)
        if url:
            await page.close()

        b64 = base64.b64encode(screenshot_bytes).decode()
        size_kb = len(screenshot_bytes) / 1024
        return f"截图成功 ({size_kb:.0f}KB)\nbase64:{b64[:200]}..."

    except Exception as e:
        return f"截图失败: {e}"


async def click(selector: str, url: str = "") -> str:
    """Click an element on the page."""
    try:
        _, ctx = await _get_browser()

        if url:
            page = await ctx.new_page()
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        else:
            pages = ctx.pages
            if not pages:
                return "没有打开的页面，请先用 browser_navigate 导航"
            page = pages[-1]

        el = page.locator(selector).first
        if await el.count() == 0:
            return f"未找到匹配 '{selector}' 的元素"

        await el.click()
        await page.wait_for_load_state("domcontentloaded")
        title = await page.title()
        return f"已点击 '{selector}'，当前页面: {title} ({page.url})"

    except Exception as e:
        return f"点击失败: {e}"


async def type_text(selector: str, text: str, clear_first: bool = True) -> str:
    """Type text into an input element."""
    try:
        _, ctx = await _get_browser()
        pages = ctx.pages
        if not pages:
            return "没有打开的页面"
        page = pages[-1]

        el = page.locator(selector).first
        if await el.count() == 0:
            return f"未找到匹配 '{selector}' 的元素"

        if clear_first:
            await el.clear()
        await el.fill(text)
        return f"已在 '{selector}' 中输入文本"

    except Exception as e:
        return f"输入失败: {e}"


async def evaluate(script: str, url: str = "") -> str:
    """Execute JavaScript in the page context."""
    try:
        _, ctx = await _get_browser()

        if url:
            page = await ctx.new_page()
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        else:
            pages = ctx.pages
            if not pages:
                return "没有打开的页面"
            page = pages[-1]

        result = await page.evaluate(script)
        if url:
            await page.close()

        if result is None:
            return "执行成功 (无返回值)"
        return str(result)

    except Exception as e:
        return f"JS执行失败: {e}"


async def close_browser() -> str:
    """Close the browser to free resources."""
    await _cleanup()
    return "浏览器已关闭"
