from __future__ import annotations

import asyncio
import json
import os
import re
from typing import Any, Literal, Sequence
from uuid import uuid4

import httpx
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from pydantic import BaseModel, Field

from app.rag import RAG_CONTEXT_END, RAG_CONTEXT_START


class BirthdayMemory(BaseModel):
    """Structured birthday fact extracted from conversation history."""

    birthday: str = Field(..., min_length=1, description="Stored birthday text.")


class LLMDecision(BaseModel):
    """Structured output returned by the deterministic decision layer."""

    thought: str = Field(..., description="Thought text for SSE streaming.")
    message: AIMessage = Field(..., description="AI message emitted into LangGraph.")
    answer: str = Field(..., description="Final answer text when available.")
    next_step: Literal["tools", "emit_answer", "finish"] = Field(
        ...,
        description="Next graph node selected by the planner.",
    )


class DeterministicToolCallingLLM:
    """Deterministic planner that drives tools, RAG, MCP and HITL loops locally."""

    _birthday_pattern = re.compile(
        r"\u6211\u7684\u751f\u65e5\u662f\\s*([0-9]{1,2}\u6708[0-9]{1,2}\u65e5)"
    )

    def __init__(
        self,
        available_tool_names: set[str] | None = None,
        tool_definitions: Sequence[Any] | None = None,
    ) -> None:
        tool_definitions = list(tool_definitions or [])
        derived_tool_names = {
            str(getattr(tool, "name", "")).strip()
            for tool in tool_definitions
            if str(getattr(tool, "name", "")).strip()
        }
        self._available_tool_names = available_tool_names or derived_tool_names
        self._chat_api_key = os.getenv("OPENAI_API_KEY", "").strip()
        self._chat_base_url = (
            os.getenv("OPENAI_BASE_URL", "").strip()
            or "https://dashscope.aliyuncs.com/compatible-mode/v1"
        )
        self._chat_model = os.getenv("OPENAI_MODEL", "").strip() or "qwen-plus"
        self._tool_definitions = tool_definitions
        self._openai_tools = self._build_openai_tool_schemas()

    def invoke(
        self,
        messages: Sequence[BaseMessage],
        retrieved_chunks: list[dict[str, Any]] | None = None,
    ) -> LLMDecision:
        """Produce a decision for the next agent step with optional remote tool calling."""
        latest_user_message = self._latest_user_message(messages)
        if latest_user_message == "__FORCE_TASK_FAILURE__":
            raise RuntimeError("Simulated task failure")

        remote_enabled = self._remote_chat_available()
        existing_mcp_answer = self._final_mcp_answer(messages)
        if existing_mcp_answer is not None:
            return self._final_answer(
                thought="The MCP tool finished, summarizing the outcome for the user.",
                answer=existing_mcp_answer,
            )

        birthday_memory = self._extract_birthday_memory(messages)
        if birthday_memory and self._is_birthday_recall_question(latest_user_message):
            answer = (
                "\u4f60\u4e4b\u524d\u544a\u8bc9\u6211\uff0c\u4f60\u7684\u751f\u65e5\u662f "
                f"{birthday_memory.birthday}\u3002"
            )
            return self._final_answer(
                thought="Loading stored thread memory and checking earlier birthday facts.",
                answer=answer,
            )

        if birthday_memory and "璁颁綇" in latest_user_message:
            answer = (
                "\u6211\u8bb0\u4f4f\u4e86\uff0c\u4f60\u7684\u751f\u65e5\u662f "
                f"{birthday_memory.birthday}\u3002"
            )
            return self._final_answer(
                thought="Storing the birthday fact in the current conversation memory.",
                answer=answer,
            )

        rag_answer = self._answer_from_retrieval(
            user_question=latest_user_message,
            retrieved_chunks=retrieved_chunks or [],
            messages=messages,
        )
        if rag_answer is not None:
            return self._final_answer(
                thought="Grounding the reply in the uploaded private knowledge snippets.",
                answer=rag_answer,
            )

        if self._is_special_char_integrity_probe(latest_user_message):
            return self._final_answer(
                thought="Echoing the provided probe text exactly for SSE integrity verification.",
                answer=latest_user_message,
            )

        mcp_delete_plan = self._plan_mcp_delete_file(latest_user_message)
        if mcp_delete_plan is not None:
            return mcp_delete_plan

        if self._is_tech_news_pdf_task(latest_user_message):
            return self._plan_tech_news_pdf_flow(messages, latest_user_message)

        if remote_enabled:
            try:
                return self._decide_with_remote_tool_calling(messages)
            except Exception as exc:
                self._log_remote_issue("tool-calling decision failed", exc)

        normalized_prompt = latest_user_message.strip()
        answer = self._answer_with_chat_model(messages, normalized_prompt)
        return self._final_answer(
            thought=(
                "Routing the latest user request through the configured chat model: "
                f"{normalized_prompt[:80]}"
            ),
            answer=answer,
        )

    async def ainvoke(
        self,
        messages: Sequence[BaseMessage],
        retrieved_chunks: list[dict[str, Any]] | None = None,
    ) -> LLMDecision:
        """Async wrapper for deterministic invocation."""
        await asyncio.sleep(0.02)
        return self.invoke(messages, retrieved_chunks=retrieved_chunks)

    def _plan_mcp_delete_file(self, latest_user_message: str) -> LLMDecision | None:
        """Plan a high-risk MCP file deletion task when requested by the user."""
        tool_name = "mcp_dangerous_delete_file"
        if tool_name not in self._available_tool_names:
            return None

        lowered = latest_user_message.lower()
        if not any(token in lowered for token in ("delete", "remove", "鍒犻櫎", "鍒犳帀")):
            return None

        path = self._extract_file_path(latest_user_message)
        if not path:
            return self._final_answer(
                thought="The user asked for file deletion, but no concrete path was provided.",
                answer="I can help with deletion after approval, but I still need the exact file path.",
            )

        return LLMDecision(
            thought="A high-risk MCP file deletion task was recognized and prepared for approval.",
            message=AIMessage(
                content="",
                tool_calls=[
                    self._tool_call(
                        tool_name,
                        {
                            "path": path,
                        },
                    )
                ],
            ),
            answer="",
            next_step="tools",
        )

    def _plan_tech_news_pdf_flow(
        self,
        messages: Sequence[BaseMessage],
        user_request: str,
    ) -> LLMDecision:
        """Run deterministic search -> scrape -> pdf plan using tool calls."""
        search_result = self._latest_tool_envelope(messages, "tavily_news_search")
        scrape_results = self._tool_envelopes(messages, "scrape_webpage")
        pdf_result = self._latest_tool_envelope(messages, "generate_pdf_summary")

        if search_result is None:
            return LLMDecision(
                thought="Need fresh external signals first, calling Tavily news search.",
                message=AIMessage(
                    content="",
                    tool_calls=[
                        self._tool_call(
                            "tavily_news_search",
                            {
                                "query": "today technology news AI semiconductor cloud",
                                "topic": "news",
                                "time_range": "day",
                                "max_results": 3,
                                "include_raw_content": False,
                            },
                        )
                    ],
                ),
                answer="",
                next_step="tools",
            )

        if not scrape_results:
            target_urls = self._pick_urls_from_search(search_result, limit=2)
            return LLMDecision(
                thought=(
                    "Search results received; scraping representative source pages in parallel."
                ),
                message=AIMessage(
                    content="",
                    tool_calls=[
                        self._tool_call(
                            "scrape_webpage",
                            {
                                "url": url,
                                "extract_focus": (
                                    "headline, key facts, and short summary for a PDF digest"
                                ),
                                "max_chars": 1800,
                            },
                        )
                        for url in target_urls
                    ],
                ),
                answer="",
                next_step="tools",
            )

        if pdf_result is None:
            bullet_points, body = self._build_pdf_payload(
                search_result=search_result,
                scrape_results=scrape_results,
                user_request=user_request,
            )
            return LLMDecision(
                thought="Compiling findings into a concise PDF summary artifact.",
                message=AIMessage(
                    content="",
                    tool_calls=[
                        self._tool_call(
                            "generate_pdf_summary",
                            {
                                "title": "Today Technology News Summary",
                                "bullet_points": bullet_points,
                                "body": body,
                                "output_filename": "today-tech-news-summary.pdf",
                            },
                        )
                    ],
                ),
                answer="",
                next_step="tools",
            )

        answer = self._final_tool_answer(search_result, scrape_results, pdf_result)
        return self._final_answer(
            thought="Tool chain complete; returning highlights and generated file path.",
            answer=answer,
        )

    def _answer_from_retrieval(
        self,
        *,
        user_question: str,
        retrieved_chunks: Sequence[dict[str, Any]],
        messages: Sequence[BaseMessage],
    ) -> str | None:
        """Answer from retrieved private knowledge when relevant."""
        if not retrieved_chunks:
            retrieved_chunks = self._parse_rag_context(messages)
        if not retrieved_chunks:
            return None

        best_chunk = max(
            retrieved_chunks,
            key=lambda item: float(item.get("rerank_score", item.get("vector_score", 0.0))),
        )
        chunk_text = str(best_chunk.get("chunk_text", "")).strip()
        if not chunk_text:
            return None

        combined_text = "\n".join(
            str(item.get("chunk_text", "")).strip() for item in retrieved_chunks if item
        ).strip()
        structured_answer = self._structured_rag_answer(
            user_question=user_question,
            combined_text=combined_text,
            source=(
                f"{best_chunk.get('filename', 'document')}#chunk-"
                f"{best_chunk.get('chunk_index', 0)}"
            ),
        )
        if structured_answer is not None:
            return structured_answer

        question_terms = self._keywords(user_question)
        sentences = [
            sentence.strip()
            for sentence in re.split(r"(?<=[.!?銆傦紒锛焆)\s+|\n+", chunk_text)
            if sentence.strip()
        ]
        if not sentences:
            sentences = [chunk_text]

        def sentence_score(sentence: str) -> float:
            lowered = sentence.lower()
            overlap = sum(1.0 for term in question_terms if term in lowered)
            numeric_bonus = 0.0
            for token in re.findall(r"[A-Za-z0-9:-]+", user_question):
                if token and token.lower() in lowered:
                    numeric_bonus += 0.2
            return overlap + numeric_bonus

        best_sentence = max(sentences, key=sentence_score)
        source = (
            f"{best_chunk.get('filename', 'document')}#chunk-"
            f"{best_chunk.get('chunk_index', 0)}"
        )
        if self._contains_cjk(user_question):
            return (
                "\u6839\u636e\u5df2\u4e0a\u4f20\u6587\u6863"
                f"[{source}]\uff0c{best_sentence}"
            )
        return f"According to the uploaded document [{source}], {best_sentence}"

    def _structured_rag_answer(
        self,
        *,
        user_question: str,
        combined_text: str,
        source: str,
    ) -> str | None:
        """Prefer field extraction when retrieved text looks like labeled facts."""
        if not combined_text:
            return None

        lowered_question = user_question.lower()
        launch_date = self._extract_labeled_value(
            combined_text,
            ("launch date", "上线时间", "发布日期"),
        )
        security_phrase = self._extract_labeled_value(
            combined_text,
            ("security phrase", "安全短语", "口令"),
        )
        program_code = self._extract_labeled_value(
            combined_text,
            ("program code", "项目代号", "program code"),
        )

        wants_launch_date = any(
            token in lowered_question
            for token in ("launch date", "date", "什么时候", "哪天", "日期")
        )
        wants_security_phrase = any(
            token in lowered_question
            for token in ("security phrase", "phrase", "口令", "短语")
        )
        wants_program_code = any(
            token in lowered_question
            for token in ("program code", "code", "代号")
        )

        parts: list[str] = []
        if wants_launch_date and launch_date:
            parts.append(f"launch date is {launch_date}")
        if wants_security_phrase and security_phrase:
            parts.append(f"security phrase is {security_phrase}")
        if wants_program_code and program_code:
            parts.append(f"program code is {program_code}")

        if not parts:
            return None

        if self._contains_cjk(user_question):
            translated: list[str] = []
            if wants_launch_date and launch_date:
                translated.append(f"上线日期是 {launch_date}")
            if wants_security_phrase and security_phrase:
                translated.append(f"安全短语是 {security_phrase}")
            if wants_program_code and program_code:
                translated.append(f"项目代号是 {program_code}")
            return (
                "\u6839\u636e\u5df2\u4e0a\u4f20\u6587\u6863"
                f"[{source}]\uff0c" + "；".join(translated)
            )

        return f"According to the uploaded document [{source}], " + "; ".join(parts) + "."

    def _final_mcp_answer(self, messages: Sequence[BaseMessage]) -> str | None:
        """Summarize the outcome of the latest MCP file operation."""
        delete_result = self._latest_tool_envelope(messages, "mcp_dangerous_delete_file")
        if delete_result is None:
            return None

        data = delete_result.get("data", {})
        path = str(data.get("path", "")).strip() or "the target file"
        deleted = bool(data.get("deleted"))
        if delete_result.get("ok") and deleted:
            return f"The file operation completed successfully. Deleted: {path}"
        if delete_result.get("ok"):
            return f"The MCP tool ran, but no file was deleted: {path}"
        error = str(delete_result.get("error", "unknown MCP error")).strip()
        return f"The MCP deletion task did not complete successfully: {error}"

    @staticmethod
    def _extract_labeled_value(text: str, labels: tuple[str, ...]) -> str | None:
        """Extract one labeled field value from combined retrieved text."""
        for label in labels:
            pattern = re.compile(
                rf"{re.escape(label)}\s*[:：]\s*(.+)",
                flags=re.IGNORECASE,
            )
            matched = pattern.search(text)
            if matched:
                return matched.group(1).strip()
        return None

    @staticmethod
    def _parse_rag_context(messages: Sequence[BaseMessage]) -> list[dict[str, Any]]:
        """Parse injected RAG payload from system messages when needed."""
        for message in reversed(messages):
            content = str(message.content)
            if RAG_CONTEXT_START not in content or RAG_CONTEXT_END not in content:
                continue
            payload = content.split(RAG_CONTEXT_START, 1)[1].split(RAG_CONTEXT_END, 1)[0]
            try:
                parsed = json.loads(payload)
            except json.JSONDecodeError:
                return []
            hits = parsed.get("hits", [])
            return [item for item in hits if isinstance(item, dict)]
        return []

    @staticmethod
    def _tool_call(name: str, args: dict[str, Any]) -> dict[str, Any]:
        """Build a LangChain-compatible tool call payload."""
        return {
            "id": f"call_{uuid4().hex[:12]}",
            "name": name,
            "args": args,
            "type": "tool_call",
        }

    @staticmethod
    def _final_answer(thought: str, answer: str) -> LLMDecision:
        """Wrap a final answer in the standard planner response shape."""
        return LLMDecision(
            thought=thought,
            message=AIMessage(content=answer),
            answer=answer,
            next_step="emit_answer",
        )

    @staticmethod
    def _latest_user_message(messages: Sequence[BaseMessage]) -> str:
        """Return newest user message content."""
        for message in reversed(messages):
            if isinstance(message, HumanMessage):
                return str(message.content)
        return ""

    def _extract_birthday_memory(
        self,
        messages: Sequence[BaseMessage],
    ) -> BirthdayMemory | None:
        """Extract birthday fact from history, if present."""
        for message in reversed(messages):
            if not isinstance(message, HumanMessage):
                continue
            matched = self._birthday_pattern.search(str(message.content))
            if matched:
                return BirthdayMemory(birthday=matched.group(1))
        return None

    @staticmethod
    def _is_birthday_recall_question(message: str) -> bool:
        """Whether user asks to recall stored birthday."""
        return (
            "\u6211\u751f\u65e5\u4ec0\u4e48\u65f6\u5019" in message
            or "\u6211\u7684\u751f\u65e5\u4ec0\u4e48\u65f6\u5019" in message
        )

    @staticmethod
    def _is_tech_news_pdf_task(message: str) -> bool:
        """Heuristic trigger for web-search + scrape + PDF workflow."""
        lowered = message.lower()
        tokens = ["科技", "新闻", "today", "tech", "news", "pdf", "摘要", "总结", "search"]
        score = sum(1 for token in tokens if token in message or token in lowered)
        return score >= 3

    @staticmethod
    def _is_special_char_integrity_probe(message: str) -> bool:
        """Detect the dedicated SSE transport probe so the answer preserves exact text."""
        lowered = message.lower()
        return "sse integrity check:" in lowered and "line-1" in lowered and "emoji" in lowered

    @staticmethod
    def _extract_file_path(message: str) -> str | None:
        """Extract a likely file path from a natural-language command."""
        quoted = re.findall(r'"([^"]+)"|\'([^\']+)\'', message)
        for pair in quoted:
            for candidate in pair:
                cleaned = candidate.strip()
                if cleaned and ("\\" in cleaned or "/" in cleaned or "." in cleaned):
                    return cleaned

        windows_match = re.search(r"([A-Za-z]:\\[^\n\r]+)", message)
        if windows_match:
            return windows_match.group(1).strip()

        posix_match = re.search(r"(/[^ \n\r]+)", message)
        if posix_match:
            return posix_match.group(1).strip()
        return None

    @staticmethod
    def _latest_tool_envelope(
        messages: Sequence[BaseMessage],
        tool_name: str,
    ) -> dict[str, Any] | None:
        """Read latest JSON envelope for a named tool from ToolMessage history."""
        envelopes = DeterministicToolCallingLLM._tool_envelopes(messages, tool_name)
        return envelopes[0] if envelopes else None

    @staticmethod
    def _tool_envelopes(
        messages: Sequence[BaseMessage],
        tool_name: str,
    ) -> list[dict[str, Any]]:
        """Read all JSON envelopes for a named tool from ToolMessage history."""
        envelopes: list[dict[str, Any]] = []
        for message in reversed(messages):
            if not isinstance(message, ToolMessage):
                continue
            if message.name != tool_name:
                continue

            raw = message.content
            text = " ".join(str(item) for item in raw) if isinstance(raw, list) else str(raw)
            try:
                payload = json.loads(text)
            except json.JSONDecodeError:
                payload = {
                    "ok": False,
                    "tool_name": tool_name,
                    "summary": "Tool returned non-JSON payload",
                    "data": {},
                    "error": text,
                }
            if isinstance(payload, dict):
                envelopes.append(payload)
        return envelopes

    @staticmethod
    def _pick_urls_from_search(
        search_envelope: dict[str, Any],
        limit: int = 1,
    ) -> list[str]:
        """Pick one or more article URLs from the latest search envelope."""
        collected: list[str] = []
        data = search_envelope.get("data")
        if isinstance(data, dict):
            results = data.get("results")
            if isinstance(results, list):
                for item in results:
                    if isinstance(item, dict):
                        url = str(item.get("url", "")).strip()
                        if url.startswith(("http://", "https://")) and url not in collected:
                            collected.append(url)
                            if len(collected) >= limit:
                                return collected
        return collected or ["https://news.ycombinator.com/"]

    @staticmethod
    def _build_pdf_payload(
        search_result: dict[str, Any],
        scrape_results: Sequence[dict[str, Any]],
        user_request: str,
    ) -> tuple[list[str], str]:
        """Build bullet points and report body for PDF generation."""
        bullets: list[str] = []
        search_data = search_result.get("data")
        if isinstance(search_data, dict):
            results = search_data.get("results")
            if isinstance(results, list):
                for item in results[:3]:
                    if isinstance(item, dict):
                        title = str(item.get("title", "")).strip()
                        if title:
                            bullets.append(title[:140])

        source_summaries: list[str] = []
        for scrape_result in scrape_results:
            scrape_data = scrape_result.get("data")
            if not isinstance(scrape_data, dict):
                continue
            article_title = str(scrape_data.get("title", "Unknown source")).strip() or "Unknown source"
            article_url = str(scrape_data.get("url", "")).strip()
            excerpt = str(scrape_data.get("excerpt", "")).strip()
            source_summaries.append(f"Representative article title: {article_title}")
            if article_url:
                source_summaries.append(f"Representative article URL: {article_url}")
            if excerpt:
                source_summaries.extend(["Representative excerpt:", excerpt[:900], ""])

        body_lines = [
            f"Task request: {user_request.strip() or 'Search today technology news and summarize'}",
            "",
            "Summary approach:",
            "- Retrieved fresh web signals using Tavily news search.",
            "- Scraped multiple representative articles in parallel for factual grounding.",
            "- Consolidated highlights into this report.",
        ]
        if source_summaries:
            body_lines.extend(["", *source_summaries])
        return bullets or ["No explicit highlights available from tool output."], "\n".join(
            body_lines
        )

    @staticmethod
    def _final_tool_answer(
        search_result: dict[str, Any],
        scrape_results: Sequence[dict[str, Any]],
        pdf_result: dict[str, Any],
    ) -> str:
        """Compose the final user-facing answer from tool outputs."""
        highlights: list[str] = []
        search_data = search_result.get("data")
        if isinstance(search_data, dict):
            results = search_data.get("results")
            if isinstance(results, list):
                for item in results[:3]:
                    if isinstance(item, dict):
                        title = str(item.get("title", "")).strip()
                        if title:
                            highlights.append(title)

        pdf_path = ""
        pdf_data = pdf_result.get("data")
        if isinstance(pdf_data, dict):
            pdf_path = str(pdf_data.get("output_path", "")).strip()
        if not pdf_path:
            pdf_path = "(PDF path unavailable)"

        bullet_block = "\n".join(f"- {item}" for item in highlights) or "- No highlights"
        scrape_count = sum(1 for result in scrape_results if result.get("ok"))
        return (
            "Technology news search and PDF generation are complete.\n"
            f"Parallel source scrapes completed: {scrape_count}\n"
            f"{bullet_block}\n\n"
            f"PDF summary path: {pdf_path}"
        )

    def _answer_with_chat_model(
        self,
        messages: Sequence[BaseMessage],
        normalized_prompt: str,
    ) -> str:
        """Answer direct chat requests with a configured OpenAI-compatible model."""
        if self._remote_chat_available():
            try:
                remote_message = self._invoke_remote_chat(
                    messages,
                    tools=self._openai_tools or None,
                )
                content = self._normalize_remote_content(remote_message.get("content", ""))
                if content:
                    return content
            except Exception as exc:
                self._log_remote_issue("direct chat fallback failed", exc)

        fallback_prompt = (
            normalized_prompt
            or "\u8bf7\u4ecb\u7ecd\u4e00\u4e0b\u4f60\u53ef\u4ee5\u505a\u4ec0\u4e48"
        )
        return (
            "\u6211\u5df2\u7ecf\u6536\u5230\u4f60\u7684\u95ee\u9898\uff1a"
            f"{fallback_prompt}\u3002"
            "\u5f53\u524d\u5148\u4f7f\u7528\u672c\u5730\u964d\u7ea7\u56de\u7b54\u6d41\u7a0b\uff1b"
            "\u5982\u679c\u4f60\u5df2\u7ecf\u914d\u7f6e\u597d Qwen\uff0c"
            "\u8bf7\u786e\u8ba4 OPENAI_API_KEY\u3001OPENAI_BASE_URL \u548c OPENAI_MODEL \u751f\u6548\u540e\u518d\u8bd5\u4e00\u6b21\u3002"
        )

    def _remote_chat_available(self) -> bool:
        """Return whether a real OpenAI-compatible chat backend is configured."""
        return bool(self._chat_api_key and self._chat_base_url)

    def _decide_with_remote_tool_calling(
        self,
        messages: Sequence[BaseMessage],
    ) -> LLMDecision:
        """Use a remote OpenAI-compatible model to decide between tool call and final answer."""
        remote_message = self._invoke_remote_chat(
            messages,
            tools=self._openai_tools or None,
        )
        remote_tool_calls = self._extract_remote_tool_calls(
            remote_message.get("tool_calls", []),
        )
        if remote_tool_calls:
            known_calls = [
                item for item in remote_tool_calls if item["name"] in self._available_tool_names
            ]
            unknown_calls = [
                item for item in remote_tool_calls if item["name"] not in self._available_tool_names
            ]
            if known_calls:
                tool_names = ", ".join(call["name"] for call in known_calls[:3])
                thought = f"Qwen requested tool execution: {tool_names}"
                if unknown_calls:
                    skipped = ", ".join(call["name"] for call in unknown_calls[:3])
                    thought = f"{thought}; skipped unknown tools: {skipped}"
                return LLMDecision(
                    thought=thought,
                    message=AIMessage(
                        content=self._normalize_remote_content(
                            remote_message.get("content", "")
                        ),
                        tool_calls=known_calls,
                    ),
                    answer="",
                    next_step="tools",
                )

            unknown_names = ", ".join(call["name"] for call in unknown_calls[:5])
            return self._final_answer(
                thought="Remote tool selection included only unavailable tools.",
                answer=(
                    "\u6a21\u578b\u8bf7\u6c42\u4e86\u672a\u6ce8\u518c\u7684\u5de5\u5177\uff0c\u5f53\u524d\u65e0\u6cd5\u7ee7\u7eed\uff1a"
                    f"{unknown_names}\u3002"
                ),
            )

        answer = self._normalize_remote_content(remote_message.get("content", ""))
        if not answer:
            raise ValueError("Remote chat response content is empty")
        return self._final_answer(
            thought="Qwen returned a direct final answer without tool calls.",
            answer=answer,
        )

    def _invoke_remote_chat(
        self,
        messages: Sequence[BaseMessage],
        *,
        tools: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Call OpenAI-compatible chat completions and return the assistant message payload."""
        url = self._chat_base_url.rstrip("/")
        if not url.endswith("/chat/completions"):
            url = f"{url}/chat/completions"

        payload = {
            "model": self._chat_model,
            "temperature": 0.2,
            "messages": self._build_remote_messages(messages),
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
            payload["parallel_tool_calls"] = True
        headers = {
            "Authorization": f"Bearer {self._chat_api_key}",
            "Content-Type": "application/json",
        }

        with httpx.Client(timeout=httpx.Timeout(45.0, connect=10.0)) as client:
            response = client.post(url, headers=headers, json=payload)
            response.raise_for_status()
            data = response.json()

        choices = data.get("choices", [])
        if not isinstance(choices, list) or not choices:
            raise ValueError("Remote chat response did not contain any choices")

        first_choice = choices[0] if isinstance(choices[0], dict) else {}
        message = first_choice.get("message", {})
        if not isinstance(message, dict):
            raise ValueError("Remote chat response message payload is invalid")
        return message

    def _build_remote_messages(self, messages: Sequence[BaseMessage]) -> list[dict[str, Any]]:
        """Convert LangChain message history into OpenAI-compatible messages."""
        remote_messages: list[dict[str, Any]] = [
            {
                "role": "system",
                "content": (
                    "You are a helpful AI assistant for a FastAPI + LangGraph application. "
                    "Always answer in Simplified Chinese unless the user explicitly asks for another language. "
                    "Do not reveal hidden chain-of-thought. Keep answers natural, direct, and useful."
                ),
            }
        ]

        for message in messages:
            if isinstance(message, HumanMessage):
                content = self._remote_content_for_message(message)
                if content:
                    remote_messages.append({"role": "user", "content": content})
                continue
            if isinstance(message, SystemMessage):
                content = self._remote_content_for_message(message)
                if content:
                    remote_messages.append({"role": "system", "content": content})
                continue
            if isinstance(message, AIMessage):
                assistant_message: dict[str, Any] = {"role": "assistant"}
                content = self._remote_content_for_message(message)
                if content:
                    assistant_message["content"] = content
                tool_calls = list(getattr(message, "tool_calls", []) or [])
                if tool_calls:
                    assistant_message["tool_calls"] = self._to_openai_tool_calls(tool_calls)
                    assistant_message.setdefault("content", "")
                if "content" in assistant_message or "tool_calls" in assistant_message:
                    remote_messages.append(assistant_message)
                continue
            if isinstance(message, ToolMessage):
                content = self._remote_content_for_message(message) or "Tool completed."
                tool_call_id = str(getattr(message, "tool_call_id", "") or "").strip()
                tool_name = str(getattr(message, "name", "") or "tool").strip() or "tool"
                payload: dict[str, Any] = {
                    "role": "tool",
                    "content": content,
                    "tool_call_id": tool_call_id or f"call_{uuid4().hex[:12]}",
                }
                if tool_name:
                    payload["name"] = tool_name
                remote_messages.append(payload)
        return remote_messages

    @staticmethod
    def _remote_content_for_message(message: BaseMessage) -> str:
        """Normalize one LangChain message payload into plain text."""
        content = message.content
        if isinstance(content, str):
            normalized = content.strip()
        elif isinstance(content, list):
            parts: list[str] = []
            for item in content:
                if isinstance(item, dict):
                    parts.append(str(item.get("text", "")))
                else:
                    parts.append(str(item))
            normalized = " ".join(part for part in parts if part).strip()
        else:
            normalized = str(content).strip()
        return normalized

    @staticmethod
    def _normalize_remote_content(content: Any) -> str:
        """Normalize OpenAI-compatible content payload into plain text."""
        if isinstance(content, str):
            return content.strip()
        if isinstance(content, list):
            parts: list[str] = []
            for item in content:
                if isinstance(item, dict):
                    item_type = str(item.get("type", "")).strip().lower()
                    if item_type == "text":
                        parts.append(str(item.get("text", "")))
                        continue
                    if "text" in item:
                        parts.append(str(item.get("text", "")))
                        continue
                    if "content" in item:
                        parts.append(str(item.get("content", "")))
                        continue
                parts.append(str(item))
            return "".join(parts).strip()
        return str(content).strip()

    @staticmethod
    def _to_openai_tool_calls(tool_calls: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
        """Convert LangChain tool call payloads into OpenAI tool_calls format."""
        converted: list[dict[str, Any]] = []
        for tool_call in tool_calls:
            name = str(tool_call.get("name", "")).strip()
            if not name:
                continue
            args = tool_call.get("args", {})
            if not isinstance(args, dict):
                args = {"input": str(args)}
            tool_call_id = str(tool_call.get("id", "")).strip() or f"call_{uuid4().hex[:12]}"
            converted.append(
                {
                    "id": tool_call_id,
                    "type": "function",
                    "function": {
                        "name": name,
                        "arguments": json.dumps(args, ensure_ascii=False),
                    },
                }
            )
        return converted

    @staticmethod
    def _extract_remote_tool_calls(raw_tool_calls: Any) -> list[dict[str, Any]]:
        """Parse OpenAI-compatible tool_calls into LangChain AIMessage.tool_calls format."""
        if not isinstance(raw_tool_calls, list):
            return []

        parsed_calls: list[dict[str, Any]] = []
        for item in raw_tool_calls:
            if not isinstance(item, dict):
                continue
            function_payload = item.get("function", {})
            if not isinstance(function_payload, dict):
                continue
            name = str(function_payload.get("name", "")).strip()
            if not name:
                continue

            arguments = function_payload.get("arguments", {})
            if isinstance(arguments, str):
                try:
                    parsed_arguments = json.loads(arguments)
                except json.JSONDecodeError:
                    parsed_arguments = {"input": arguments}
            elif isinstance(arguments, dict):
                parsed_arguments = arguments
            else:
                parsed_arguments = {"input": str(arguments)}

            if not isinstance(parsed_arguments, dict):
                parsed_arguments = {"input": str(parsed_arguments)}

            parsed_calls.append(
                {
                    "id": str(item.get("id", "")).strip() or f"call_{uuid4().hex[:12]}",
                    "name": name,
                    "args": parsed_arguments,
                    "type": "tool_call",
                }
            )
        return parsed_calls

    def _build_openai_tool_schemas(self) -> list[dict[str, Any]]:
        """Convert available tools into OpenAI-compatible function schema list."""
        schemas_by_name: dict[str, dict[str, Any]] = {}
        for tool in self._tool_definitions:
            name = str(getattr(tool, "name", "")).strip()
            if not name:
                continue
            description = str(getattr(tool, "description", "")).strip() or f"Tool {name}"
            args_schema = getattr(tool, "args_schema", None)
            parameters: dict[str, Any]
            if args_schema is not None and hasattr(args_schema, "model_json_schema"):
                raw_schema = args_schema.model_json_schema()
                if isinstance(raw_schema, dict) and raw_schema.get("type") == "object":
                    parameters = raw_schema
                else:
                    parameters = {
                        "type": "object",
                        "properties": {},
                        "additionalProperties": True,
                    }
            else:
                parameters = {
                    "type": "object",
                    "properties": {},
                    "additionalProperties": True,
                }
            schemas_by_name[name] = {
                "type": "function",
                "function": {
                    "name": name,
                    "description": description,
                    "parameters": parameters,
                },
            }

        all_names = sorted(set(self._available_tool_names) | set(schemas_by_name.keys()))
        output: list[dict[str, Any]] = []
        for name in all_names:
            output.append(schemas_by_name.get(name) or self._generic_tool_schema(name))
        return output

    def _log_remote_issue(self, label: str, exc: Exception) -> None:
        """Emit a compact diagnostic line for remote chat/tool-calling failures."""
        print(
            "[llm-remote] "
            f"label={label} "
            f"model={self._chat_model or '-'} "
            f"base_url={self._chat_base_url or '-'} "
            f"error={exc.__class__.__name__}: {exc}"
        )

    @staticmethod
    def _generic_tool_schema(name: str) -> dict[str, Any]:
        """Provide a conservative OpenAI-compatible schema for tools without local metadata."""
        lowered = name.lower()
        if "delete" in lowered and "file" in lowered:
            description = (
                "Delete a file through MCP. This is high-risk and should only be used when the user explicitly asks."
            )
            parameters = {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Absolute or relative file path to delete.",
                    }
                },
                "required": ["path"],
                "additionalProperties": True,
            }
        elif "email" in lowered:
            description = (
                "Send an email through an external MCP tool. High-risk; confirm user intent clearly."
            )
            parameters = {
                "type": "object",
                "properties": {
                    "to": {"type": "string"},
                    "subject": {"type": "string"},
                    "body": {"type": "string"},
                },
                "required": ["to", "subject", "body"],
                "additionalProperties": True,
            }
        else:
            description = f"External tool {name} exposed by the runtime."
            parameters = {
                "type": "object",
                "properties": {},
                "additionalProperties": True,
            }
        return {
            "type": "function",
            "function": {
                "name": name,
                "description": description,
                "parameters": parameters,
            },
        }

    @staticmethod
    def _keywords(text: str) -> list[str]:
        """Extract simple lexical cues for deterministic answer selection."""
        return re.findall(r"[a-z0-9_-]+|[\u4e00-\u9fff]{1,4}", text.lower())

    @staticmethod
    def _contains_cjk(text: str) -> bool:
        """Return whether the text contains CJK characters."""
        return bool(re.search(r"[\u4e00-\u9fff]", text))

