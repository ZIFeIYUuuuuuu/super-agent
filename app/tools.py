from __future__ import annotations

import asyncio
import ipaddress
import json
import os
import socket
import textwrap
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup
from langchain_core.tools import tool
from pydantic import BaseModel, Field
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

try:
    from playwright.sync_api import Error as PlaywrightError
    from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
    from playwright.sync_api import sync_playwright
except ImportError:  # pragma: no cover - dependency guard for partial installs
    PlaywrightError = RuntimeError
    PlaywrightTimeoutError = RuntimeError
    sync_playwright = None


class ToolEnvelope(BaseModel):
    """Stable JSON wrapper returned by every tool."""

    ok: bool = Field(..., description="Whether the tool completed successfully.")
    tool_name: str = Field(..., description="Stable tool identifier.")
    summary: str = Field(..., description="Short natural-language summary of the result.")
    data: dict[str, Any] = Field(
        default_factory=dict,
        description="Structured tool payload for follow-up reasoning.",
    )
    error: str | None = Field(
        default=None,
        description="Error message when ok is false.",
    )


class TavilySearchInput(BaseModel):
    """Input schema for the Tavily-backed search tool."""

    query: str = Field(
        ...,
        min_length=3,
        description="Natural-language search query to send to Tavily.",
    )
    topic: Literal["general", "news", "finance"] = Field(
        default="news",
        description="Tavily topic selector. Use 'news' for recent headlines.",
    )
    time_range: Literal["day", "week", "month", "year"] = Field(
        default="day",
        description="Relative freshness filter for Tavily results.",
    )
    max_results: int = Field(
        default=3,
        ge=1,
        le=5,
        description="Maximum number of result entries to return.",
    )
    include_raw_content: bool = Field(
        default=False,
        description="Whether Tavily should return cleaned article content when available.",
    )


class WebScrapeInput(BaseModel):
    """Input schema for webpage scraping."""

    url: str = Field(
        ...,
        min_length=8,
        description="Absolute HTTP or HTTPS URL of the page to fetch and summarize.",
    )
    extract_focus: str = Field(
        default="headline, main article body, and the most important factual details",
        min_length=3,
        description="Human-readable extraction intent to guide content selection.",
    )
    max_chars: int = Field(
        default=1800,
        ge=400,
        le=6000,
        description="Maximum number of cleaned text characters to keep in the summary.",
    )


class PdfSummaryInput(BaseModel):
    """Input schema for PDF summary generation."""

    title: str = Field(
        ...,
        min_length=3,
        description="Document title that will appear at the top of the PDF.",
    )
    bullet_points: list[str] = Field(
        default_factory=list,
        description="Important bullet points to render near the top of the PDF.",
    )
    body: str = Field(
        ...,
        min_length=10,
        description="Main narrative body for the generated PDF summary.",
    )
    output_filename: str | None = Field(
        default=None,
        description="Optional filename override. .pdf will be added if omitted.",
    )


@dataclass(slots=True)
class ToolSettings:
    """Environment-driven settings shared by the agent tools."""

    tavily_api_key: str | None
    tavily_api_url: str
    pdf_output_dir: Path
    request_timeout_seconds: float = 20.0
    playwright_timeout_ms: int = 15_000
    allow_local_network_tools: bool = False

    @classmethod
    def from_env(cls) -> ToolSettings:
        """Read the current tool configuration from environment variables."""
        tavily_api_url = (
            os.getenv("TAVILY_API_URL")
            or os.getenv("TAVILY_SEARCH_URL")
            or os.getenv("AGENT_TAVILY_SEARCH_URL")
            or os.getenv("AGENT_TOOL_SEARCH_URL")
            or os.getenv("AGENT_TOOL_MOCK_BASE_URL")
            or (
                f"{os.getenv('TAVILY_BASE_URL').rstrip('/')}/search"
                if os.getenv("TAVILY_BASE_URL")
                else None
            )
            or "https://api.tavily.com/search"
        )
        output_dir = Path(
            os.getenv("AGENT_PDF_OUTPUT_DIR")
            or os.getenv("PDF_OUTPUT_DIR")
            or "generated-pdfs"
        ).expanduser()
        return cls(
            tavily_api_key=os.getenv("TAVILY_API_KEY"),
            tavily_api_url=tavily_api_url,
            pdf_output_dir=output_dir.resolve(),
            allow_local_network_tools=os.getenv(
                "ALLOW_LOCAL_TOOL_URLS", "false"
            ).lower()
            in {"1", "true", "yes"},
        )


def _serialize_envelope(envelope: ToolEnvelope) -> str:
    """Return a JSON string with stable UTF-8 semantics for tool messages."""
    return json.dumps(envelope.model_dump(), ensure_ascii=False)


def _success(tool_name: str, summary: str, **data: Any) -> str:
    """Build a successful tool response."""
    return _serialize_envelope(
        ToolEnvelope(
            ok=True,
            tool_name=tool_name,
            summary=summary,
            data=data,
        )
    )


def _failure(tool_name: str, error: str, **data: Any) -> str:
    """Build a failed tool response without raising into the agent loop."""
    return _serialize_envelope(
        ToolEnvelope(
            ok=False,
            tool_name=tool_name,
            summary=f"{tool_name} failed: {error}",
            data=data,
            error=error,
        )
    )


def _is_local_endpoint(url: str) -> bool:
    """Return whether the configured URL points to localhost for testing."""
    parsed = urlparse(url)
    return parsed.hostname in {"127.0.0.1", "localhost"}


def _validate_outbound_url(url: str, settings: ToolSettings) -> None:
    """Reject dangerous or unsupported outbound URLs before fetching them."""
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("Only http and https URLs are allowed")

    hostname = parsed.hostname
    if not hostname:
        raise ValueError("URL must contain a hostname")

    if settings.allow_local_network_tools:
        return

    lowered = hostname.lower()
    blocked_names = {
        "localhost",
        "localhost.localdomain",
        "metadata.google.internal",
    }
    if lowered in blocked_names:
        raise ValueError(f"Blocked hostname: {hostname}")

    try:
        resolved = socket.getaddrinfo(hostname, parsed.port or 80, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise ValueError(f"Unable to resolve hostname: {hostname}") from exc

    for _, _, _, _, sockaddr in resolved:
        ip = ipaddress.ip_address(sockaddr[0])
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_reserved
            or ip.is_multicast
            or ip.is_unspecified
        ):
            raise ValueError(f"Blocked IP address: {ip}")


def _normalize_filename(value: str) -> str:
    """Turn arbitrary user/model text into a filesystem-safe PDF name."""
    safe = "".join(
        character if character.isalnum() or character in {"-", "_"} else "-"
        for character in value.strip()
    )
    compact = "-".join(part for part in safe.split("-") if part)
    return compact or "agent-summary"


def _extract_text_from_html(html: str, max_chars: int) -> tuple[str, str, list[str]]:
    """Parse HTML into a title, cleaned excerpt, and a few discovered links."""
    soup = BeautifulSoup(html, "html.parser")
    for unwanted in soup(["script", "style", "noscript", "svg"]):
        unwanted.decompose()

    title = (
        soup.title.get_text(" ", strip=True)
        if soup.title is not None
        else "Untitled page"
    )

    paragraphs: list[str] = []
    for selector in ("article p", "main p", "p"):
        for paragraph in soup.select(selector):
            text = paragraph.get_text(" ", strip=True)
            if text and text not in paragraphs:
                paragraphs.append(text)

    if not paragraphs:
        fallback_blocks = [
            node.get_text(" ", strip=True)
            for node in soup.select("main, article, section, li")
            if node.get_text(" ", strip=True)
        ]
        if fallback_blocks:
            paragraphs.extend(fallback_blocks)

    combined_text = " ".join(paragraphs).strip()
    if not combined_text:
        combined_text = soup.get_text(" ", strip=True)
    excerpt = combined_text[:max_chars].strip()
    links = []
    for anchor in soup.find_all("a", href=True):
        href = str(anchor["href"]).strip()
        if href.startswith(("http://", "https://")) and href not in links:
            links.append(href)
        if len(links) >= 5:
            break

    return title, excerpt, links


def _load_html_with_playwright(url: str, timeout_ms: int) -> str:
    """Render a page with Playwright and return the final DOM HTML."""
    if sync_playwright is None:
        raise RuntimeError("Playwright is not installed")

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            page.goto(url, wait_until="networkidle", timeout=timeout_ms)
            return page.content()
        finally:
            browser.close()


async def _load_html_with_httpx_async(url: str, timeout_seconds: float) -> str:
    """Fetch static HTML content directly over HTTP asynchronously."""
    async with httpx.AsyncClient(
        timeout=timeout_seconds,
        follow_redirects=True,
        headers={"User-Agent": "super-agent/1.0"},
    ) as client:
        response = await client.get(url)
        response.raise_for_status()
        return response.text


@tool("tavily_news_search", args_schema=TavilySearchInput)
async def tavily_news_search(
    query: str,
    topic: Literal["general", "news", "finance"] = "news",
    time_range: Literal["day", "week", "month", "year"] = "day",
    max_results: int = 3,
    include_raw_content: bool = False,
) -> str:
    """Search the live web through Tavily and return structured recent-news results.

    Use this tool when the user asks for anything that depends on current or
    changing web information, especially prompts containing words like "today",
    "news", or "headline". Prefer this tool before answering from memory whenever
    the request explicitly asks for fresh internet information.
    """
    settings = ToolSettings.from_env()
    if not settings.tavily_api_key and not _is_local_endpoint(settings.tavily_api_url):
        return _failure(
            "tavily_news_search",
            "TAVILY_API_KEY is missing. Configure it or point TAVILY_API_URL to a local test stub.",
            query=query,
        )

    headers = {"Content-Type": "application/json"}
    if settings.tavily_api_key:
        headers["Authorization"] = f"Bearer {settings.tavily_api_key}"

    payload = {
        "query": query,
        "topic": topic,
        "time_range": time_range,
        "max_results": max_results,
        "include_answer": True,
        "include_raw_content": include_raw_content,
    }

    try:
        async with httpx.AsyncClient(timeout=settings.request_timeout_seconds) as client:
            response = await client.post(
                settings.tavily_api_url,
                json=payload,
                headers=headers,
            )
            response.raise_for_status()
            body: dict[str, Any] = response.json()
    except Exception as exc:
        return _failure(
            "tavily_news_search",
            f"Tavily request failed: {exc}",
            query=query,
        )

    normalized_results: list[dict[str, str]] = []
    for item in body.get("results", [])[:max_results]:
        normalized_results.append(
            {
                "title": str(item.get("title", "")).strip(),
                "url": str(item.get("url", "")).strip(),
                "content": str(item.get("content", "")).strip(),
                "published_date": str(
                    item.get("published_date") or item.get("publishedTime") or ""
                ).strip(),
            }
        )

    if not normalized_results:
        return _failure(
            "tavily_news_search",
            "Tavily returned no results for the requested query.",
            query=query,
        )

    return _success(
        "tavily_news_search",
        f"Found {len(normalized_results)} recent web results for '{query}'.",
        query=query,
        topic=topic,
        time_range=time_range,
        answer=str(body.get("answer", "")).strip(),
        results=normalized_results,
    )


@tool("scrape_webpage", args_schema=WebScrapeInput)
async def scrape_webpage(
    url: str,
    extract_focus: str = "headline, main article body, and the most important factual details",
    max_chars: int = 1800,
) -> str:
    """Open a webpage, render if possible, and extract a clean article summary."""
    settings = ToolSettings.from_env()
    try:
        await asyncio.to_thread(_validate_outbound_url, url, settings)
    except ValueError as exc:
        return _failure(
            "scrape_webpage",
            str(exc),
            url=url,
            extract_focus=extract_focus,
        )

    render_engine = "playwright"
    fallback_reason: str | None = None

    try:
        html = await asyncio.to_thread(
            _load_html_with_playwright,
            url,
            settings.playwright_timeout_ms,
        )
    except (PlaywrightError, PlaywrightTimeoutError, RuntimeError) as exc:
        render_engine = "httpx-fallback"
        fallback_reason = str(exc)
        try:
            html = await _load_html_with_httpx_async(url, settings.request_timeout_seconds)
        except Exception as fallback_exc:
            return _failure(
                "scrape_webpage",
                f"Page fetch failed after Playwright fallback: {fallback_exc}",
                url=url,
                extract_focus=extract_focus,
            )
    except Exception as exc:
        return _failure(
            "scrape_webpage",
            f"Unexpected scraping failure: {exc}",
            url=url,
            extract_focus=extract_focus,
        )

    try:
        title, excerpt, links = await asyncio.to_thread(
            _extract_text_from_html,
            html,
            max_chars,
        )
    except Exception as exc:
        return _failure(
            "scrape_webpage",
            f"HTML parsing failed: {exc}",
            url=url,
            extract_focus=extract_focus,
        )

    if not excerpt:
        return _failure(
            "scrape_webpage",
            "The page loaded but no readable article text was extracted.",
            url=url,
            title=title,
        )

    return _success(
        "scrape_webpage",
        f"Scraped '{title}' using {render_engine} and extracted {len(excerpt)} characters.",
        url=url,
        title=title,
        extract_focus=extract_focus,
        excerpt=excerpt,
        render_engine=render_engine,
        fallback_reason=fallback_reason,
        discovered_links=links,
    )


@tool("generate_pdf_summary", args_schema=PdfSummaryInput)
async def generate_pdf_summary(
    title: str,
    bullet_points: list[str],
    body: str,
    output_filename: str | None = None,
) -> str:
    """Create a simple PDF document containing a concise summary report."""
    settings = ToolSettings.from_env()
    settings.pdf_output_dir.mkdir(parents=True, exist_ok=True)

    base_name = output_filename or title
    normalized_name = _normalize_filename(base_name)
    if not normalized_name.lower().endswith(".pdf"):
        normalized_name = f"{normalized_name}.pdf"

    output_path = settings.pdf_output_dir / normalized_name
    if output_path.exists():
        output_path = settings.pdf_output_dir / f"{output_path.stem}-1.pdf"

    try:
        await asyncio.to_thread(
            _render_pdf_summary,
            output_path,
            title,
            bullet_points,
            body,
        )
    except Exception as exc:
        return _failure(
            "generate_pdf_summary",
            f"PDF generation failed: {exc}",
            title=title,
            output_path=str(output_path),
        )

    return _success(
        "generate_pdf_summary",
        f"Generated PDF summary at {output_path}.",
        title=title,
        output_path=str(output_path),
        file_size_bytes=output_path.stat().st_size,
    )


def get_agent_tools() -> list[Any]:
    """Return the full toolset exposed to the LangGraph ToolNode."""
    return [
        tavily_news_search,
        scrape_webpage,
        generate_pdf_summary,
    ]


def _render_pdf_summary(
    output_path: Path,
    title: str,
    bullet_points: list[str],
    body: str,
) -> None:
    """Render the reportlab PDF in a worker thread to avoid blocking the event loop."""
    safe_bullets = [item.strip()[:180] for item in bullet_points[:8] if item.strip()]
    safe_body = body.strip()[:12_000]

    pdf_canvas = canvas.Canvas(str(output_path), pagesize=A4)
    _, height = A4
    x_margin = 56
    y_position = height - 64

    pdf_canvas.setTitle(title)
    pdf_canvas.setFont("Helvetica-Bold", 16)
    pdf_canvas.drawString(x_margin, y_position, title[:90])
    y_position -= 28

    pdf_canvas.setFont("Helvetica", 11)
    for bullet in safe_bullets:
        for line in textwrap.wrap(f"- {bullet}", width=88):
            if y_position < 72:
                pdf_canvas.showPage()
                pdf_canvas.setFont("Helvetica", 11)
                y_position = height - 64
            pdf_canvas.drawString(x_margin, y_position, line)
            y_position -= 16

    y_position -= 8
    for paragraph in safe_body.splitlines():
        if not paragraph.strip():
            y_position -= 10
            continue
        for line in textwrap.wrap(paragraph.strip(), width=92):
            if y_position < 72:
                pdf_canvas.showPage()
                pdf_canvas.setFont("Helvetica", 11)
                y_position = height - 64
            pdf_canvas.drawString(x_margin, y_position, line)
            y_position -= 16

    pdf_canvas.save()
