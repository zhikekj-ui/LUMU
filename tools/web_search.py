"""Web search tool using DuckDuckGo (async, no API key needed)."""
import httpx


def register(registry):
    registry.register(
        name="web_search",
        description="Search the web and return top results with titles, URLs and snippets.",
        parameters={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query",
                },
                "max_results": {
                    "type": "integer",
                    "description": "Max results to return (default 5)",
                },
            },
            "required": ["query"],
        },
        handler=search,
        is_async=True,
        toolset="search",
        emoji="🔍",
    )


async def search(query: str, max_results: int = 5) -> str:
    """Async web search using DuckDuckGo Instant Answer API."""
    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            resp = await client.get(
                "https://api.duckduckgo.com/",
                params={"q": query, "format": "json", "no_html": 1, "skip_disambig": 1},
            )
            data = resp.json()

        results = []

        # Abstract (main answer)
        if data.get("Abstract"):
            results.append(f"[{data['AbstractText']}]({data.get('AbstractURL', '')})")

        # Related topics
        for topic in (data.get("RelatedTopics") or [])[:max_results]:
            if isinstance(topic, dict) and topic.get("Text"):
                results.append(f"[{topic['Text']}]({topic.get('FirstURL', '')})")

        if not results:
            return f"No results found for: {query}"
        return "\n\n".join(results)
    except Exception as e:
        return f"Search error: {e}"
