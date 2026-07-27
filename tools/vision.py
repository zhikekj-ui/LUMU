"""Vision tool — multi-modal image understanding.

Supports:
- Image URL analysis (download + send to vision model)
- Base64 image analysis
- Screenshot analysis from browser tool
- OCR-like text extraction from images
- Chart/diagram interpretation

Uses the model's native vision capabilities when available,
falls back to a dedicated vision model if configured.
"""
import base64
import io
import re


def register(registry):
    registry.register(
        name="vision_analyze",
        description=(
            "分析图片内容：支持URL或base64格式。可识别图片中的文字(OCR)、"
            "描述图片内容、解读图表/截图/界面设计等。"
            "支持jpg/png/gif/webp格式。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "source": {
                    "type": "string",
                    "description": "图片来源：URL地址 或 base64编码的图片数据",
                },
                "task": {
                    "type": "string",
                    "enum": ["describe", "ocr", "chart", "screenshot", "compare"],
                    "description": "分析任务类型: describe(描述内容), ocr(提取文字), chart(解读图表), screenshot(分析界面), compare(对比，需配合source2)",
                },
                "prompt": {
                    "type": "string",
                    "description": "可选的自定义提问，如'这张图片里有什么文字？'、'这个图表说明了什么？'",
                },
                "source2": {
                    "type": "string",
                    "description": "第二张图片URL（仅compare模式使用）",
                },
            },
            "required": ["source"],
        },
        handler=analyze_image,
        is_async=True,
        toolset="vision",
        emoji="👁",
    )
    registry.register(
        name="vision_screenshot",
        description=(
            "对当前浏览器页面截图并分析内容。结合截图和视觉理解，"
            "可以'看到'网页的实际样子，包括布局、颜色、文字等。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "task": {
                    "type": "string",
                    "description": "想让AI看什么/分析什么",
                },
                "full_page": {
                    "type": "boolean",
                    "description": "是否截取完整页面（包括滚动区域），默认false",
                },
            },
            "required": ["task"],
        },
        handler=screenshot_and_analyze,
        is_async=True,
        toolset="vision",
        emoji="📸",
    )


async def _load_image_as_base64(source: str) -> tuple[str, str]:
    """Load image from URL or detect base64. Returns (base64_data, media_type)."""
    # Check if it's already base64
    if source.startswith("data:image/"):
        match = re.match(r"data:image/(\w+);base64,(.+)", source, re.DOTALL)
        if match:
            return match.group(2), f"image/{match.group(1)}"

    # Check if it looks like raw base64 (no URL patterns)
    if not source.startswith(("http://", "https://")) and len(source) > 100:
        # Likely base64 data
        return source, "image/png"

    # Download from URL
    import httpx
    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
        resp = await client.get(source)
        resp.raise_for_status()
        content_type = resp.headers.get("content-type", "image/png")
        if "jpeg" in content_type or "jpg" in content_type:
            media_type = "image/jpeg"
        elif "gif" in content_type:
            media_type = "image/gif"
        elif "webp" in content_type:
            media_type = "image/webp"
        else:
            media_type = "image/png"
        b64 = base64.b64encode(resp.content).decode()
        return b64, media_type


async def _call_vision_model(image_contents: list[dict], prompt: str) -> str:
    """Send image(s) to the model's vision API."""
    import os
    from openai import AsyncOpenAI
    from providers.registry import get as get_provider
    import config

    provider = get_provider(config.DEFAULT_PROVIDER)
    api_key = provider.resolve_api_key()
    client = AsyncOpenAI(api_key=api_key, base_url=provider.resolve_base_url())

    # Build content array with images + text
    content = []
    for img in image_contents:
        content.append({
            "type": "image_url",
            "image_url": {
                "url": f"data:{img['media_type']};base64,{img['base64']}",
            },
        })
    content.append({"type": "text", "text": prompt})

    # Try vision-capable models in order
    vision_models = []
    if provider.name == "stepfun":
        vision_models = ["step-1.5v-mini", "step-1v-8k", config.DEFAULT_MODEL]
    else:
        vision_models = [config.DEFAULT_MODEL]

    last_error = None
    for model in vision_models:
        try:
            response = await client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": content}],
                max_tokens=16000,
            )
            return response.choices[0].message.content or "(无法识别内容)"
        except Exception as e:
            last_error = e
            continue

    return f"视觉分析失败: {last_error}"


TASK_PROMPTS = {
    "describe": "请详细描述这张图片的内容，包括主要元素、场景、颜色等。",
    "ocr": "请提取这张图片中所有可见的文字内容，保持原始排版和格式。如果有表格，请用markdown表格格式输出。",
    "chart": "请解读这张图表（柱状图/折线图/饼图等）的数据和趋势，说明关键数据点。",
    "screenshot": "请分析这个界面截图，描述页面布局、功能元素、文字内容等。",
    "compare": "请对比这两张图片的异同，指出主要区别。",
}


async def analyze_image(
    source: str,
    task: str = "describe",
    prompt: str = "",
    source2: str = "",
) -> str:
    """Analyze image content using vision model."""
    try:
        image_contents = []

        # Load primary image
        b64, media_type = await _load_image_as_base64(source)
        image_contents.append({"base64": b64, "media_type": media_type})

        # Load secondary image for comparison
        if task == "compare" and source2:
            b64_2, media_type_2 = await _load_image_as_base64(source2)
            image_contents.append({"base64": b64_2, "media_type": media_type_2})

        # Build prompt
        text_prompt = prompt if prompt else TASK_PROMPTS.get(task, TASK_PROMPTS["describe"])

        return await _call_vision_model(image_contents, text_prompt)

    except Exception as e:
        return f"图像分析失败: {e}"


async def screenshot_and_analyze(task: str, full_page: bool = False) -> str:
    """Take a browser screenshot and analyze it with vision."""
    try:
        # Import browser tools
        from tools.browser import _get_browser, screenshot as take_screenshot

        _, ctx = await _get_browser()
        pages = ctx.pages
        if not pages:
            return "没有打开的浏览器页面，请先用 browser_navigate 导航"

        page = pages[-1]
        if not page.url or page.url == "about:blank":
            return "没有可截图的页面"

        # Take screenshot
        screenshot_bytes = await page.screenshot(full_page=full_page)
        b64 = base64.b64encode(screenshot_bytes).decode()

        # Analyze with vision
        image_contents = [{"base64": b64, "media_type": "image/png"}]
        text_prompt = f"请分析这个网页截图：{task}"

        return await _call_vision_model(image_contents, text_prompt)

    except Exception as e:
        return f"截图分析失败: {e}"
