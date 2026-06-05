"""Real-model smoke eval for Super Agent.

This script exercises the OpenAI-compatible model path with a small number of
cases and writes a JSON summary that can be quoted in the README or resume.
"""

from __future__ import annotations

import json
import os
import statistics
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.llm import DeterministicToolCallingLLM


@dataclass(frozen=True)
class EvalResult:
    case: str
    latency_ms: float
    passed: bool
    detail: str


def _require_env() -> tuple[str, str]:
    base_url = os.getenv("OPENAI_BASE_URL", "").strip()
    model = os.getenv("OPENAI_MODEL", "").strip()
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key or not base_url:
        raise RuntimeError(
            "OPENAI_API_KEY / OPENAI_BASE_URL are required for real-model eval."
        )
    if not model:
        model = "unknown"
    return base_url, model


def _is_real_answer(answer: str) -> bool:
    normalized = " ".join(answer.split())
    if not normalized:
        return False
    if "当前先使用本地降级回答流程" in normalized:
        return False
    if "请确认 OPENAI_API_KEY" in normalized:
        return False
    return True


def _case_direct_chat() -> EvalResult:
    llm = DeterministicToolCallingLLM()
    start = time.perf_counter()
    decision = llm.invoke(
        [
            HumanMessage(
                content="请用中文简要解释什么是 API 契约测试，以及它为什么能减少前后端联调问题。"
            )
        ]
    )
    latency_ms = round((time.perf_counter() - start) * 1000, 2)
    passed = decision.next_step == "emit_answer" and _is_real_answer(decision.answer)
    detail = decision.answer[:160].replace("\n", " ")
    return EvalResult("direct_chat_answer", latency_ms, passed, detail)


def _case_architecture_summary() -> EvalResult:
    llm = DeterministicToolCallingLLM()
    start = time.perf_counter()
    decision = llm.invoke(
        [
            HumanMessage(
                content="请用中文概括一个带 RAG、工具调用和人工审批的智能体工作台，重点说明它适合解决什么问题。"
            )
        ]
    )
    latency_ms = round((time.perf_counter() - start) * 1000, 2)
    passed = decision.next_step == "emit_answer" and _is_real_answer(decision.answer)
    detail = decision.answer[:160].replace("\n", " ")
    return EvalResult("architecture_summary", latency_ms, passed, detail)


def _case_tool_result_synthesis() -> EvalResult:
    llm = DeterministicToolCallingLLM(available_tool_names={"mcp_web_search"})
    tool_call_id = "call_real_eval"
    start = time.perf_counter()
    decision = llm.invoke(
        [
            HumanMessage(
                content="请基于工具返回的内容，总结今天 AI 方向最值得关注的一条动态。"
            ),
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "id": tool_call_id,
                        "name": "mcp_web_search",
                        "args": {"query": "today AI news"},
                        "type": "tool_call",
                    }
                ],
            ),
            ToolMessage(
                tool_call_id=tool_call_id,
                name="mcp_web_search",
                content=json.dumps(
                    {
                        "results": [
                            {
                                "title": "AI startup ships a coding assistant for enterprise teams",
                                "url": "https://example.com/news-1",
                                "content": "The release focuses on code review and workflow automation.",
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
            ),
        ]
    )
    latency_ms = round((time.perf_counter() - start) * 1000, 2)
    passed = decision.next_step == "emit_answer" and _is_real_answer(decision.answer)
    detail = decision.answer[:160].replace("\n", " ")
    return EvalResult("tool_result_synthesis", latency_ms, passed, detail)


def run_eval() -> dict[str, object]:
    base_url, model = _require_env()
    results = [
        _case_direct_chat(),
        _case_architecture_summary(),
        _case_tool_result_synthesis(),
    ]
    latencies = [result.latency_ms for result in results]
    passed = [result.passed for result in results]
    return {
        "provider_base_url": base_url,
        "model": model,
        "case_count": len(results),
        "success_rate": round(sum(passed) / len(results), 4),
        "latency_p50_ms": round(statistics.median(latencies), 2),
        "latency_p95_ms": round(max(latencies), 2),
        "results": [asdict(result) for result in results],
    }


if __name__ == "__main__":
    print(json.dumps(run_eval(), indent=2, ensure_ascii=False))
