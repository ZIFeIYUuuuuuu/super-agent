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


class RetrievalPlanDecision(BaseModel):
    """Planner-agent output for deciding whether retrieval should run."""

    thought: str = Field(..., description="Planning thought text for SSE streaming.")
    next_step: Literal["retrieve_context", "call_model", "finish"] = Field(
        ...,
        description="Next graph node selected by the retrieval planner.",
    )
    retrieval_goal: str = Field(
        default="",
        description="Optional natural-language retrieval goal captured by the planner.",
    )
    planned_queries: list[str] = Field(
        default_factory=list,
        description="Ordered retrieval-plan queries produced before the first retrieval hop.",
    )
    subquestions: list[str] = Field(
        default_factory=list,
        description="Decomposed subquestions extracted from the original user request.",
    )
    initial_query: str = Field(
        default="",
        description="First retrieval query to execute for the planned retrieval pass.",
    )


class EvidenceReviewDecision(BaseModel):
    """Reviewer-agent output for deciding whether retrieved evidence should be kept."""

    thought: str = Field(..., description="Evidence review thought text for SSE streaming.")
    next_step: Literal["rewrite_retrieval_query", "call_model", "finish"] = Field(
        ...,
        description="Next graph node selected by the evidence reviewer.",
    )
    use_retrieval_context: bool = Field(
        ...,
        description="Whether retrieved chunks should be injected into the responder context.",
    )
    retry_query: str = Field(
        default="",
        description="Rewritten retrieval query for the next hop when another retrieval round is needed.",
    )
    evidence_gap: str = Field(
        default="",
        description="Short description of what evidence was missing or why the current hits were rejected.",
    )
    confidence_level: Literal["high", "partial", "low"] = Field(
        default="low",
        description="Confidence tier assigned by the evidence reviewer.",
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

        if birthday_memory and "记住" in latest_user_message:
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

    def plan_retrieval(
        self,
        messages: Sequence[BaseMessage],
        *,
        knowledge_namespace: str,
        knowledge_available: bool | None = None,
        retrieved_chunks: list[dict[str, Any]] | None = None,
    ) -> RetrievalPlanDecision:
        """Planner agent that decides whether this turn should ground on private knowledge."""
        latest_user_message = self._latest_user_message(messages).strip()
        if not latest_user_message:
            return RetrievalPlanDecision(
                thought="No user message is available, so retrieval planning stops for this turn.",
                next_step="finish",
            )

        if retrieved_chunks:
            return RetrievalPlanDecision(
                thought="Retrieved evidence is already attached to this turn, so response synthesis can continue.",
                next_step="call_model",
            )

        if not knowledge_namespace.strip():
            return RetrievalPlanDecision(
                thought="No private knowledge namespace is configured for this turn, so retrieval is skipped.",
                next_step="call_model",
            )

        if knowledge_available is False:
            return RetrievalPlanDecision(
                thought="This namespace has no uploaded private knowledge yet, so retrieval is skipped for now.",
                next_step="call_model",
            )

        if self._should_bypass_retrieval(messages, latest_user_message):
            return RetrievalPlanDecision(
                thought="The planner classified this request as direct chat or tool work, so private retrieval is skipped.",
                next_step="call_model",
            )

        if self._looks_like_smalltalk(latest_user_message):
            return RetrievalPlanDecision(
                thought="The request looks conversational, so the first pass skips private-knowledge retrieval.",
                next_step="call_model",
            )

        if self._looks_like_retrieval_request(latest_user_message) or knowledge_available:
            subquestions = self._build_retrieval_subquestions(latest_user_message)
            planned_queries = self._build_retrieval_plan_queries(latest_user_message)
            return RetrievalPlanDecision(
                thought="The planner wants private knowledge retrieval before the responder writes the answer.",
                next_step="retrieve_context",
                retrieval_goal=latest_user_message[:200],
                planned_queries=planned_queries,
                subquestions=subquestions,
                initial_query=(planned_queries[0] if planned_queries else latest_user_message[:200]),
            )

        return RetrievalPlanDecision(
            thought="The planner found no strong need for private grounding before the first model pass.",
            next_step="call_model",
        )

    def review_retrieval(
        self,
        messages: Sequence[BaseMessage],
        *,
        retrieved_chunks: Sequence[dict[str, Any]],
        retrieval_round: int = 1,
        max_retrieval_rounds: int = 1,
        active_query: str = "",
    ) -> EvidenceReviewDecision:
        """Reviewer agent that decides whether retrieved evidence should remain in context."""
        latest_user_message = self._latest_user_message(messages).strip()
        if not retrieved_chunks:
            retry_query = ""
            if self._should_retry_retrieval(
                latest_user_message,
                retrieval_round=retrieval_round,
                max_retrieval_rounds=max_retrieval_rounds,
            ):
                retry_query = self._rewrite_retrieval_query(
                    user_question=latest_user_message,
                    last_query=active_query or latest_user_message,
                    retrieved_chunks=retrieved_chunks,
                )
            if retry_query:
                return EvidenceReviewDecision(
                    thought="No useful private-knowledge hits were found, so the retriever will try one narrower follow-up query.",
                    next_step="rewrite_retrieval_query",
                    use_retrieval_context=False,
                    retry_query=retry_query,
                    evidence_gap="No relevant private-knowledge hits were found in the first pass.",
                    confidence_level="low",
                )
            return EvidenceReviewDecision(
                thought="The retrieval worker found no private-knowledge evidence, so the responder continues without KB context.",
                next_step="call_model",
                use_retrieval_context=False,
                evidence_gap="No relevant private-knowledge hits were found.",
                confidence_level="low",
            )

        confidence_level, evidence_gap = self._classify_retrieval_confidence(
            latest_user_message,
            retrieved_chunks,
        )
        if confidence_level == "low":
            retry_query = ""
            if self._should_retry_retrieval(
                latest_user_message,
                retrieval_round=retrieval_round,
                max_retrieval_rounds=max_retrieval_rounds,
            ):
                retry_query = self._rewrite_retrieval_query(
                    user_question=latest_user_message,
                    last_query=active_query or latest_user_message,
                    retrieved_chunks=retrieved_chunks,
                )
            if retry_query:
                return EvidenceReviewDecision(
                    thought="The first retrieval hop was too weak, so the retriever will try a rewritten follow-up query.",
                    next_step="rewrite_retrieval_query",
                    use_retrieval_context=False,
                    retry_query=retry_query,
                    evidence_gap=evidence_gap,
                    confidence_level="low",
                )
            return EvidenceReviewDecision(
                thought="Retrieved snippets were too weak or off-topic, so the responder continues without KB context.",
                next_step="call_model",
                use_retrieval_context=False,
                evidence_gap=evidence_gap,
                confidence_level="low",
            )

        if confidence_level == "partial":
            return EvidenceReviewDecision(
                thought="Retrieved evidence is only partially complete, but it is strong enough to answer the supported parts and note the remaining gap.",
                next_step="call_model",
                use_retrieval_context=True,
                evidence_gap=evidence_gap,
                confidence_level="partial",
            )

        return EvidenceReviewDecision(
            thought="The evidence reviewer accepted the retrieved private-knowledge snippets for grounded answering.",
            next_step="call_model",
            use_retrieval_context=True,
            evidence_gap=evidence_gap,
            confidence_level="high",
        )

    def _plan_mcp_delete_file(self, latest_user_message: str) -> LLMDecision | None:
        """Plan a high-risk MCP file deletion task when requested by the user."""
        tool_name = "mcp_dangerous_delete_file"
        if tool_name not in self._available_tool_names:
            return None

        lowered = latest_user_message.lower()
        if not any(token in lowered for token in ("delete", "remove", "删除", "删掉")):
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
        grouped_answer = self._synthesize_grouped_retrieval_answer(
            user_question=user_question,
            retrieved_chunks=retrieved_chunks,
        )
        if grouped_answer is not None:
            return grouped_answer
        structured_answer = self._structured_rag_answer(
            user_question=user_question,
            combined_text=combined_text,
            source=(
                f"{best_chunk.get('filename', 'document')}#chunk-"
                f"{best_chunk.get('chunk_index', 0)}"
            ),
            retrieved_chunks=retrieved_chunks,
        )
        if structured_answer is not None:
            return structured_answer

        source = (
            f"{best_chunk.get('filename', 'document')}#chunk-"
            f"{best_chunk.get('chunk_index', 0)}"
        )
        model_grounded_answer = self._answer_with_retrieval_model(
            user_question=user_question,
            combined_text=combined_text,
            source=source,
        )
        if model_grounded_answer is not None:
            return model_grounded_answer

        question_terms = self._keywords(user_question)
        sentence_pattern = re.compile(r"[.!?。！？]\s*|\n+")
        sentences = [
            self._normalize_candidate_sentence(sentence)
            for sentence in sentence_pattern.split(chunk_text)
            if self._normalize_candidate_sentence(sentence)
        ]
        if not sentences:
            sentences = [chunk_text]

        best_sentence = max(
            sentences,
            key=lambda sentence: self._sentence_score(user_question, question_terms, sentence),
        )
        if self._contains_cjk(user_question):
            return (
                "\u6839\u636e\u5df2\u4e0a\u4f20\u6587\u6863"
                f"[{source}]\uff0c{best_sentence}"
            )
        return f"According to the uploaded document [{source}], {best_sentence}"

    def _answer_with_retrieval_model(
        self,
        *,
        user_question: str,
        combined_text: str,
        source: str,
    ) -> str | None:
        """Use the configured remote chat model to synthesize an answer from retrieved snippets."""
        if not self._remote_chat_available():
            return None

        retrieval_prompt = (
            "You are answering a question strictly from uploaded private knowledge snippets.\n"
            "Rules:\n"
            "- Answer only from the provided snippet text.\n"
            "- Prefer concise factual answers over generic summaries.\n"
            "- Ignore Markdown headings unless they contain the actual answer.\n"
            "- If the answer is not supported by the snippets, say so clearly.\n"
            "- Respond in Simplified Chinese when the question is Chinese.\n\n"
            f"Question:\n{user_question.strip()}\n\n"
            f"Source:\n{source}\n\n"
            "Retrieved snippets:\n"
            f"{combined_text.strip()[:5000]}"
        )
        try:
            remote_message = self._invoke_remote_chat(
                [HumanMessage(content=retrieval_prompt)],
                tools=None,
            )
        except Exception as exc:
            self._log_remote_issue("retrieval-grounded answer failed", exc)
            return None

        content = self._normalize_remote_content(remote_message.get("content", ""))
        if not content:
            return None

        if self._contains_cjk(user_question):
            return f"根据已上传文档[{source}]，{content}"
        return f"According to the uploaded document [{source}], {content}"

    def _synthesize_grouped_retrieval_answer(
        self,
        *,
        user_question: str,
        retrieved_chunks: Sequence[dict[str, Any]],
    ) -> str | None:
        """Synthesize one answer from multiple grouped evidence chunks for compound questions."""
        subquestions = self._build_retrieval_subquestions(user_question)
        if len(subquestions) <= 1 or len(retrieved_chunks) <= 1:
            return None

        grouped_parts: list[str] = []
        grouped_sources: list[str] = []
        seen_sentences: set[str] = set()
        for subquestion in subquestions:
            best_sentence, source = self._best_sentence_with_source(subquestion, retrieved_chunks)
            if not best_sentence:
                continue
            key = best_sentence.lower()
            if key in seen_sentences:
                continue
            seen_sentences.add(key)
            grouped_parts.append(best_sentence)
            if source:
                grouped_sources.append(source)

        if len(grouped_parts) < 2:
            return None

        source_label = self._group_source_refs(grouped_sources)
        separator = "；" if self._contains_cjk(user_question) else "; "
        prefix = "根据已上传文档" if self._contains_cjk(user_question) else "According to the uploaded documents "
        if self._contains_cjk(user_question):
            return f"{prefix}[{source_label}]，{separator.join(grouped_parts)}"
        return f"{prefix}[{source_label}], {separator.join(grouped_parts)}."

    def _best_sentence_with_source(
        self,
        question: str,
        retrieved_chunks: Sequence[dict[str, Any]],
    ) -> tuple[str, str]:
        """Pick the strongest evidence sentence plus its source reference for one subquestion."""
        best_sentence = ""
        best_source = ""
        best_score = float("-inf")
        question_terms = self._keywords(question)
        for chunk in retrieved_chunks:
            if not isinstance(chunk, dict):
                continue
            source = (
                f"{chunk.get('filename', 'document')}#chunk-"
                f"{chunk.get('chunk_index', 0)}"
            )
            chunk_text = str(chunk.get("chunk_text", "")).strip()
            if not chunk_text:
                continue
            sentence_pattern = re.compile(r"[.!?。！？]\s*|\n+")
            sentences = [
                self._normalize_candidate_sentence(sentence)
                for sentence in sentence_pattern.split(chunk_text)
                if self._normalize_candidate_sentence(sentence)
            ]
            if not sentences:
                sentences = [chunk_text]
            for sentence in sentences:
                score = self._sentence_score(question, question_terms, sentence)
                if score > best_score:
                    best_score = score
                    best_sentence = sentence
                    best_source = source
        return best_sentence, best_source

    def _sentence_score(
        self,
        question: str,
        question_terms: Sequence[str],
        sentence: str,
    ) -> float:
        """Score one candidate evidence sentence for a specific user question."""
        lowered = sentence.lower()
        overlap = sum(1.0 for term in question_terms if term in lowered)
        numeric_bonus = 0.0
        for token in re.findall(r"[A-Za-z0-9:-]+", question):
            if token and token.lower() in lowered:
                numeric_bonus += 0.2
        heading_penalty = 2.5 if sentence.lstrip().startswith("#") else 0.0
        markdown_penalty = 0.8 if sentence.startswith(("-", "*", ">")) else 0.0
        short_penalty = 0.6 if len(sentence.strip()) <= 12 else 0.0
        answer_bonus = 0.0
        if self._contains_cjk(question):
            if "谁" in question and any(
                token in sentence for token in ("是", "名为", "叫做", "人物", "英雄")
            ):
                answer_bonus += 1.2
            if "什么" in question and any(
                token in sentence for token in ("是", "指", "由", "包括", "规定")
            ):
                answer_bonus += 0.8
        return overlap + numeric_bonus + answer_bonus - heading_penalty - markdown_penalty - short_penalty

    @staticmethod
    def _normalize_candidate_sentence(sentence: str) -> str:
        """Clean one retrieved text fragment before heuristic answer selection."""
        cleaned = sentence.strip()
        cleaned = re.sub(r"^#{1,6}\s*", "", cleaned)
        cleaned = re.sub(r"^[-*]\s+", "", cleaned)
        cleaned = re.sub(r"^\d+\.\s+", "", cleaned)
        return cleaned.strip()

    def _structured_rag_answer(
        self,
        *,
        user_question: str,
        combined_text: str,
        source: str,
        retrieved_chunks: Sequence[dict[str, Any]],
    ) -> str | None:
        """Prefer field extraction when retrieved text looks like labeled facts."""
        if not combined_text:
            return None

        expected_fields = self._expected_labeled_fields(user_question)
        if not expected_fields:
            return None

        found_fields: list[tuple[str, str, str]] = []
        missing_fields: list[str] = []
        grouped_refs: list[str] = []
        for field_name, labels in expected_fields.items():
            value = self._extract_labeled_value(combined_text, labels)
            if not value:
                missing_fields.append(field_name)
                continue
            found_fields.append((field_name, value, self._best_source_for_labels(retrieved_chunks, labels)))
            grouped_refs.append(self._best_source_for_labels(retrieved_chunks, labels))

        if not found_fields:
            return None

        grouped_sources = self._group_source_refs(grouped_refs) or source

        if self._contains_cjk(user_question):
            translated = [self._translate_structured_field(name, value) for name, value, _ in found_fields]
            answer = (
                "\u6839\u636e\u5df2\u4e0a\u4f20\u6587\u6863"
                f"[{grouped_sources}]\uff0c" + "；".join(translated)
            )
            if missing_fields:
                answer += f"；目前缺少这些字段的可靠证据：{self._translate_missing_fields(missing_fields)}"
            return answer

        parts = [self._format_structured_field(name, value) for name, value, _ in found_fields]
        answer = f"According to the uploaded document [{grouped_sources}], " + "; ".join(parts) + "."
        if missing_fields:
            answer += f" Missing reliable evidence for: {', '.join(missing_fields)}."
        return answer

    def _best_source_for_labels(
        self,
        retrieved_chunks: Sequence[dict[str, Any]],
        labels: tuple[str, ...],
    ) -> str:
        """Find the best source reference containing one of the requested labels."""
        best_ref = ""
        best_score = float("-inf")
        for chunk in retrieved_chunks:
            if not isinstance(chunk, dict):
                continue
            chunk_text = str(chunk.get("chunk_text", ""))
            lowered = chunk_text.lower()
            if not any(label.lower() in lowered for label in labels):
                continue
            score = float(chunk.get("rerank_score", chunk.get("vector_score", 0.0)))
            if score > best_score:
                best_score = score
                best_ref = (
                    f"{chunk.get('filename', 'document')}#chunk-"
                    f"{chunk.get('chunk_index', 0)}"
                )
        return best_ref

    def _expected_labeled_fields(
        self,
        user_question: str,
    ) -> dict[str, tuple[str, ...]]:
        """Return the structured fields explicitly requested by the user question."""
        lowered_question = user_question.lower()
        expected: dict[str, tuple[str, ...]] = {}
        if any(
            token in lowered_question
            for token in ("launch date", "date", "什么时候", "哪天", "日期")
        ):
            expected["launch date"] = ("launch date", "上线时间", "发布日期")
        if any(
            token in lowered_question
            for token in ("security phrase", "phrase", "口令", "短语")
        ):
            expected["security phrase"] = ("security phrase", "安全短语", "口令")
        if any(
            token in lowered_question
            for token in ("program code", "code", "代号")
        ):
            expected["program code"] = ("program code", "项目代号")
        return expected

    @staticmethod
    def _format_structured_field(field_name: str, value: str) -> str:
        """Render one English structured field/value pair."""
        return f"{field_name} is {value}"

    @staticmethod
    def _translate_structured_field(field_name: str, value: str) -> str:
        """Render one Chinese structured field/value pair."""
        translations = {
            "launch date": "上线日期是",
            "security phrase": "安全短语是",
            "program code": "项目代号是",
        }
        return f"{translations.get(field_name, field_name)} {value}"

    @staticmethod
    def _translate_missing_fields(field_names: Sequence[str]) -> str:
        """Translate missing field labels into concise Chinese."""
        translations = {
            "launch date": "上线日期",
            "security phrase": "安全短语",
            "program code": "项目代号",
        }
        return "、".join(translations.get(field_name, field_name) for field_name in field_names)

    @staticmethod
    def _group_source_refs(source_refs: Sequence[str]) -> str:
        """Compress multiple source references into grouped file#chunk labels."""
        grouped: dict[str, set[int]] = {}
        passthrough: list[str] = []
        for ref in source_refs:
            cleaned = str(ref).strip()
            if not cleaned:
                continue
            matched = re.match(r"(.+?)#chunk-(\d+)$", cleaned)
            if not matched:
                passthrough.append(cleaned)
                continue
            filename, chunk_index = matched.group(1), int(matched.group(2))
            grouped.setdefault(filename, set()).add(chunk_index)

        parts = [
            f"{filename}#chunk-{','.join(str(index) for index in sorted(indices))}"
            for filename, indices in grouped.items()
        ]
        parts.extend(item for item in passthrough if item not in parts)
        return "; ".join(parts)

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

    def _should_bypass_retrieval(
        self,
        messages: Sequence[BaseMessage],
        latest_user_message: str,
    ) -> bool:
        """Return whether retrieval should be bypassed for a clearly non-RAG turn."""
        birthday_memory = self._extract_birthday_memory(messages)
        if birthday_memory and (
            self._is_birthday_recall_question(latest_user_message)
            or "记住" in latest_user_message
        ):
            return True
        if self._is_special_char_integrity_probe(latest_user_message):
            return True
        if "QWEN_TOOL_TEST" in latest_user_message:
            return True
        if self._looks_like_delete_request(latest_user_message):
            return True
        if self._is_tech_news_pdf_task(latest_user_message):
            return True
        if self._final_mcp_answer(messages) is not None:
            return True
        return False

    def _looks_like_retrieval_request(self, message: str) -> bool:
        """Return whether a user turn looks like a request for grounded private knowledge."""
        if self._looks_like_private_knowledge_prompt(message):
            return True

        lowered = message.lower()
        question_markers = (
            "?",
            "？",
            "what",
            "when",
            "where",
            "which",
            "who",
            "how",
            "why",
            "exact",
            "according to",
            "from the",
            "是什么",
            "谁",
            "哪",
            "多少",
            "何时",
            "根据",
            "从",
        )
        if any(marker in lowered or marker in message for marker in question_markers):
            return len(self._keywords(message)) >= 2

        return False

    def _retrieval_is_relevant(
        self,
        latest_user_message: str,
        retrieved_chunks: Sequence[dict[str, Any]],
    ) -> bool:
        """Return whether the current retrieval results are strong enough to keep in context."""
        if self._looks_like_smalltalk(latest_user_message):
            return False

        if self._looks_like_private_knowledge_prompt(latest_user_message):
            return True

        normalized_chunks = [item for item in retrieved_chunks if isinstance(item, dict)]
        if not normalized_chunks:
            return False

        best_chunk = max(
            normalized_chunks,
            key=lambda item: float(item.get("rerank_score", item.get("vector_score", 0.0))),
        )
        best_score = float(best_chunk.get("rerank_score", best_chunk.get("vector_score", 0.0)))
        best_text = str(best_chunk.get("chunk_text", "")).lower()
        terms = [term for term in self._keywords(latest_user_message) if len(term) > 1]
        overlap = sum(1 for term in terms if term in best_text)

        if best_score >= 0.55:
            return True
        if overlap >= 2 and best_score >= 0.18:
            return True
        if overlap >= max(1, len(terms) // 2) and best_score >= 0.12:
            return True
        return False

    def _classify_retrieval_confidence(
        self,
        latest_user_message: str,
        retrieved_chunks: Sequence[dict[str, Any]],
    ) -> tuple[Literal["high", "partial", "low"], str]:
        """Classify retrieved evidence into high/partial/low confidence tiers."""
        if not self._retrieval_is_relevant(latest_user_message, retrieved_chunks):
            return "low", "Retrieved snippets were too weak or off-topic for a grounded answer."

        expected_labels = self._expected_labeled_fields(latest_user_message)
        if not expected_labels:
            return "high", ""

        combined_text = "\n".join(
            str(item.get("chunk_text", "")).strip() for item in retrieved_chunks if item
        ).strip()
        found_labels: list[str] = []
        missing_labels: list[str] = []
        for label_name, label_variants in expected_labels.items():
            if self._extract_labeled_value(combined_text, label_variants):
                found_labels.append(label_name)
            else:
                missing_labels.append(label_name)

        if found_labels and missing_labels:
            return "partial", f"Missing supporting evidence for: {', '.join(missing_labels)}."
        if missing_labels and not found_labels:
            return "low", f"Missing supporting evidence for: {', '.join(missing_labels)}."
        return "high", ""

    def _should_retry_retrieval(
        self,
        latest_user_message: str,
        *,
        retrieval_round: int,
        max_retrieval_rounds: int,
    ) -> bool:
        """Return whether a weak retrieval result should trigger another hop."""
        if retrieval_round >= max_retrieval_rounds:
            return False
        if self._should_bypass_retrieval([], latest_user_message):
            return False
        if self._looks_like_smalltalk(latest_user_message):
            return False
        return self._looks_like_retrieval_request(latest_user_message)

    def _build_retrieval_plan_queries(self, user_question: str) -> list[str]:
        """Decompose one user question into a small, normalized retrieval plan."""
        focus = self._extract_focus_from_question(user_question)
        segments = self._build_retrieval_subquestions(user_question)
        candidates = [user_question, focus, *segments]
        return self._normalize_query_plan(candidates, max_queries=4)

    def _build_retrieval_subquestions(self, user_question: str) -> list[str]:
        """Build a bounded list of decomposed subquestions for the retrieval planner."""
        focus = self._extract_focus_from_question(user_question)
        segments = self._split_question_into_subquestions(focus or user_question)
        return self._normalize_query_plan(segments, max_queries=3)

    def _rewrite_retrieval_query(
        self,
        *,
        user_question: str,
        last_query: str,
        retrieved_chunks: Sequence[dict[str, Any]],
    ) -> str:
        """Rewrite the retrieval query for one conservative follow-up hop."""
        extracted_focus = self._extract_focus_from_question(user_question)
        keyword_terms = list(dict.fromkeys(self._keywords(extracted_focus or user_question)))
        keyword_focus = " ".join(keyword_terms[:8])
        source_hint = self._best_retrieval_source_hint(retrieved_chunks)

        candidates = [
            extracted_focus,
            keyword_focus,
            f"{extracted_focus} {source_hint}".strip() if extracted_focus else "",
            f"{keyword_focus} exact detail value".strip() if keyword_focus else "",
        ]
        last_normalized = re.sub(r"\s+", " ", last_query.strip().lower())
        for candidate in candidates:
            normalized = re.sub(r"\s+", " ", candidate.strip())
            if not normalized:
                continue
            if normalized.lower() == last_normalized:
                continue
            return normalized[:200]
        return ""

    def _split_question_into_subquestions(self, text: str) -> list[str]:
        """Split compound retrieval requests into a few focused subquestions."""
        base = text.strip()
        if not base:
            return []

        clauses = re.split(
            r"(?i)\b(?:and|plus|with|also)\b|[，,；;、]|(?:以及|还有|并且|同时|和)",
            base,
        )
        meaningful = [clause.strip(" .:：") for clause in clauses if clause.strip(" .:：")]
        if len(meaningful) <= 1:
            return [base]

        subjects = self._extract_subject_tokens(base)
        subquestions: list[str] = []
        for clause in meaningful:
            clause_tokens = self._keywords(clause)
            if len(clause_tokens) < 2 and subjects:
                clause = f"{' '.join(subjects[:3])} {clause}".strip()
            subquestions.append(clause[:200])
        return subquestions

    def _extract_subject_tokens(self, text: str) -> list[str]:
        """Extract broad entity tokens to keep split subquestions grounded."""
        focus = self._extract_focus_from_question(text)
        tokens = [token for token in self._keywords(focus or text) if len(token) > 2]
        stopwords = {
            "what",
            "when",
            "where",
            "which",
            "who",
            "how",
            "exact",
            "return",
            "both",
            "value",
            "values",
            "detail",
        }
        return [token for token in tokens if token not in stopwords][:4]

    @staticmethod
    def _normalize_query_plan(candidates: Sequence[str], max_queries: int) -> list[str]:
        """Normalize, deduplicate, and cap a retrieval query plan."""
        normalized: list[str] = []
        seen: set[str] = set()
        for candidate in candidates:
            cleaned = re.sub(r"\s+", " ", str(candidate).strip()).strip(" ,，。:")
            if not cleaned:
                continue
            key = cleaned.lower()
            if key in seen:
                continue
            seen.add(key)
            normalized.append(cleaned[:200])
            if len(normalized) >= max_queries:
                break
        return normalized

    def _extract_focus_from_question(self, user_question: str) -> str:
        """Strip broad framing words and keep the concrete entities/fields to retrieve."""
        cleaned = user_question.strip()
        patterns = [
            r"(?i)\bfrom the private knowledge base\b",
            r"(?i)\baccording to the uploaded (document|file)s?\b",
            r"(?i)\bfrom the uploaded (document|file)s?\b",
            r"(?i)\breturn both values\b",
            r"(?i)\bplease\b",
            r"根据已上传[的]?(文档|文件|资料)",
            r"从(私有)?知识库里",
            r"从文档里",
            r"请告诉我",
            r"请问",
        ]
        for pattern in patterns:
            cleaned = re.sub(pattern, " ", cleaned)
        cleaned = re.sub(r"[?？]", " ", cleaned)
        cleaned = re.sub(r"\s+", " ", cleaned).strip(" ,，。:")
        return cleaned[:200]

    @staticmethod
    def _best_retrieval_source_hint(retrieved_chunks: Sequence[dict[str, Any]]) -> str:
        """Extract a small source hint from the strongest retrieved chunk."""
        normalized = [item for item in retrieved_chunks if isinstance(item, dict)]
        if not normalized:
            return ""
        best = max(
            normalized,
            key=lambda item: float(item.get("rerank_score", item.get("vector_score", 0.0))),
        )
        filename = str(best.get("filename", "")).strip()
        stem = re.sub(r"\.[A-Za-z0-9]+$", "", filename)
        return stem[:40]

    @staticmethod
    def _looks_like_delete_request(message: str) -> bool:
        """Return whether the message is primarily asking for file deletion/removal."""
        lowered = message.lower()
        return any(token in lowered for token in ("delete", "remove", "删除", "删掉"))

    @staticmethod
    def _looks_like_private_knowledge_prompt(message: str) -> bool:
        """Return whether the user explicitly refers to uploaded/private knowledge."""
        lowered = message.lower()
        markers = (
            "knowledge base",
            "private knowledge",
            "uploaded document",
            "uploaded file",
            "private doc",
            "private brief",
            "according to the uploaded",
            "from the uploaded",
            "from the private",
            "文档",
            "知识库",
            "资料",
            "上传",
            "私有",
            "根据已上传",
            "根据文档",
        )
        return any(marker in lowered or marker in message for marker in markers)

    @staticmethod
    def _looks_like_smalltalk(message: str) -> bool:
        """Return whether the user message is conversational rather than evidence-seeking."""
        normalized = message.strip().lower()
        if not normalized:
            return True

        markers = (
            "hello",
            "hi",
            "hey",
            "thanks",
            "thank you",
            "你好",
            "您好",
            "谢谢",
            "早上好",
            "晚上好",
            "在吗",
        )
        return any(marker in normalized for marker in markers)

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

