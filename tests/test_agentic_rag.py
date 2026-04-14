import unittest

from langchain_core.messages import HumanMessage

from app.llm import DeterministicToolCallingLLM


class AgenticRagPlannerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.llm = DeterministicToolCallingLLM(
            available_tool_names={"mcp_dangerous_delete_file"},
            tool_definitions=[],
        )

    def test_planner_requests_retrieval_for_private_knowledge_questions(self) -> None:
        decision = self.llm.plan_retrieval(
            [HumanMessage(content="From the private knowledge base, what is the launch date?")],
            knowledge_namespace="rag-thread-1",
            knowledge_available=True,
        )

        self.assertEqual(decision.next_step, "retrieve_context")
        self.assertIn("retrieval", decision.thought.lower())

    def test_query_plan_decomposes_complex_question_into_subquestions(self) -> None:
        decision = self.llm.plan_retrieval(
            [
                HumanMessage(
                    content=(
                        "From the private knowledge base, what are the launch date, "
                        "security phrase, and program code?"
                    )
                )
            ],
            knowledge_namespace="rag-thread-1",
            knowledge_available=True,
        )

        self.assertEqual(decision.next_step, "retrieve_context")
        self.assertGreaterEqual(len(decision.subquestions), 2)
        self.assertGreaterEqual(len(decision.planned_queries), 2)
        self.assertTrue(decision.initial_query)

    def test_query_plan_deduplicates_and_normalizes_queries(self) -> None:
        planned = self.llm._build_retrieval_plan_queries(
            "launch date, launch date, security phrase and security phrase"
        )

        self.assertEqual(len(planned), len({item.lower() for item in planned}))
        self.assertLessEqual(len(planned), 4)

    def test_planner_skips_retrieval_when_namespace_has_no_documents(self) -> None:
        decision = self.llm.plan_retrieval(
            [HumanMessage(content="What is the launch date?")],
            knowledge_namespace="rag-thread-1",
            knowledge_available=False,
        )

        self.assertEqual(decision.next_step, "call_model")

    def test_planner_skips_retrieval_for_delete_requests(self) -> None:
        decision = self.llm.plan_retrieval(
            [
                HumanMessage(
                    content='Use the high-risk delete tool to delete "C:\\temp\\danger.txt" after approval.'
                )
            ],
            knowledge_namespace="rag-thread-1",
            knowledge_available=True,
        )

        self.assertEqual(decision.next_step, "call_model")

    def test_query_plan_respects_max_query_budget(self) -> None:
        planned = self.llm._build_retrieval_plan_queries(
            "launch date and security phrase and program code and owner and region and release window"
        )

        self.assertLessEqual(len(planned), 4)

    def test_group_source_refs_compacts_chunk_indices(self) -> None:
        grouped = self.llm._group_source_refs(
            [
                "brief-a.md#chunk-0",
                "brief-a.md#chunk-2",
                "brief-b.md#chunk-1",
            ]
        )

        self.assertIn("brief-a.md#chunk-0,2", grouped)
        self.assertIn("brief-b.md#chunk-1", grouped)

    def test_evidence_review_keeps_strong_retrieval_hits(self) -> None:
        decision = self.llm.review_retrieval(
            [HumanMessage(content="What is the launch date?")],
            retrieved_chunks=[
                {
                    "chunk_text": "Launch date: 2031-09-17",
                    "rerank_score": 0.82,
                    "filename": "private-brief.md",
                    "chunk_index": 0,
                }
            ],
            retrieval_round=1,
            max_retrieval_rounds=2,
            active_query="What is the launch date?",
        )

        self.assertEqual(decision.next_step, "call_model")
        self.assertTrue(decision.use_retrieval_context)
        self.assertEqual(decision.confidence_level, "high")

    def test_evidence_review_marks_partial_confidence_for_incomplete_structured_hits(self) -> None:
        decision = self.llm.review_retrieval(
            [HumanMessage(content="What are the launch date and security phrase?")],
            retrieved_chunks=[
                {
                    "chunk_text": "Launch date: 2031-09-17",
                    "rerank_score": 0.82,
                    "filename": "private-brief.md",
                    "chunk_index": 0,
                }
            ],
            retrieval_round=1,
            max_retrieval_rounds=2,
            active_query="What are the launch date and security phrase?",
        )

        self.assertEqual(decision.next_step, "call_model")
        self.assertTrue(decision.use_retrieval_context)
        self.assertEqual(decision.confidence_level, "partial")
        self.assertIn("security phrase", decision.evidence_gap)

    def test_review_retrieval_requests_retry_on_weak_evidence(self) -> None:
        original_query = "What is the launch date and security phrase?"
        decision = self.llm.review_retrieval(
            [HumanMessage(content=original_query)],
            retrieved_chunks=[
                {
                    "chunk_text": "Meeting agenda and unrelated notes",
                    "rerank_score": 0.05,
                    "filename": "notes.md",
                    "chunk_index": 0,
                }
            ],
            retrieval_round=1,
            max_retrieval_rounds=2,
            active_query=original_query,
        )

        self.assertEqual(decision.next_step, "rewrite_retrieval_query")
        self.assertFalse(decision.use_retrieval_context)
        self.assertTrue(decision.retry_query)
        self.assertNotEqual(decision.retry_query.lower(), original_query.lower())

    def test_retry_stops_at_max_retrieval_rounds(self) -> None:
        decision = self.llm.review_retrieval(
            [HumanMessage(content="What is the launch date?")],
            retrieved_chunks=[],
            retrieval_round=2,
            max_retrieval_rounds=2,
            active_query="What is the launch date?",
        )

        self.assertEqual(decision.next_step, "call_model")
        self.assertFalse(decision.retry_query)
        self.assertEqual(decision.confidence_level, "low")

    def test_query_rewrite_not_triggered_for_tool_or_approval_intent(self) -> None:
        decision = self.llm.review_retrieval(
            [
                HumanMessage(
                    content='Delete "C:\\temp\\danger.txt" after approval and use the MCP delete tool.'
                )
            ],
            retrieved_chunks=[],
            retrieval_round=1,
            max_retrieval_rounds=2,
            active_query='Delete "C:\\temp\\danger.txt" after approval and use the MCP delete tool.',
        )

        self.assertEqual(decision.next_step, "call_model")
        self.assertFalse(decision.retry_query)

    def test_second_round_retrieval_accepts_strong_evidence(self) -> None:
        decision = self.llm.review_retrieval(
            [HumanMessage(content="What is the security phrase?")],
            retrieved_chunks=[
                {
                    "chunk_text": "Security phrase: cobalt-harbor-1a2b3c4d",
                    "rerank_score": 0.88,
                    "filename": "private-brief.md",
                    "chunk_index": 1,
                }
            ],
            retrieval_round=2,
            max_retrieval_rounds=2,
            active_query="security phrase private-brief exact detail value",
        )

        self.assertEqual(decision.next_step, "call_model")
        self.assertTrue(decision.use_retrieval_context)

    def test_smalltalk_drops_retrieval_context(self) -> None:
        decision = self.llm.review_retrieval(
            [HumanMessage(content="你好")],
            retrieved_chunks=[
                {
                    "chunk_text": "Launch date: 2031-09-17",
                    "rerank_score": 0.82,
                    "filename": "private-brief.md",
                    "chunk_index": 0,
                }
            ],
            retrieval_round=1,
            max_retrieval_rounds=2,
            active_query="你好",
        )

        self.assertEqual(decision.next_step, "call_model")
        self.assertFalse(decision.use_retrieval_context)

    def test_invoke_still_answers_from_retrieval(self) -> None:
        decision = self.llm.invoke(
            [
                HumanMessage(
                    content=(
                        "From the private knowledge base, what are the exact launch date "
                        "and security phrase?"
                    )
                )
            ],
            retrieved_chunks=[
                {
                    "chunk_text": "Program code: ORBIT-ABC123\nLaunch date: 2031-09-17",
                    "rerank_score": 0.91,
                    "filename": "private-brief.md",
                    "chunk_index": 0,
                },
                {
                    "chunk_text": "Security phrase: cobalt-harbor-1a2b3c4d",
                    "rerank_score": 0.88,
                    "filename": "private-brief.md",
                    "chunk_index": 1,
                },
            ],
        )

        self.assertEqual(decision.next_step, "emit_answer")
        self.assertIn("2031-09-17", decision.answer)
        self.assertIn("cobalt-harbor-1a2b3c4d", decision.answer)

    def test_invoke_groups_sources_for_multi_document_retrieval(self) -> None:
        decision = self.llm.invoke(
            [
                HumanMessage(
                    content=(
                        "From the private knowledge base, what are the exact launch date "
                        "and security phrase?"
                    )
                )
            ],
            retrieved_chunks=[
                {
                    "chunk_text": "Launch date: 2031-09-17",
                    "rerank_score": 0.91,
                    "filename": "brief-a.md",
                    "chunk_index": 0,
                },
                {
                    "chunk_text": "Security phrase: cobalt-harbor-1a2b3c4d",
                    "rerank_score": 0.88,
                    "filename": "brief-b.md",
                    "chunk_index": 1,
                },
            ],
        )

        self.assertEqual(decision.next_step, "emit_answer")
        self.assertIn("brief-a.md#chunk-0", decision.answer)
        self.assertIn("brief-b.md#chunk-1", decision.answer)

    def test_invoke_reports_partial_structured_answer_with_gap(self) -> None:
        decision = self.llm.invoke(
            [
                HumanMessage(
                    content=(
                        "From the private knowledge base, what are the exact launch date "
                        "and security phrase?"
                    )
                )
            ],
            retrieved_chunks=[
                {
                    "chunk_text": "Launch date: 2031-09-17",
                    "rerank_score": 0.91,
                    "filename": "brief-a.md",
                    "chunk_index": 0,
                }
            ],
        )

        self.assertEqual(decision.next_step, "emit_answer")
        self.assertIn("2031-09-17", decision.answer)
        self.assertIn("Missing reliable evidence for: security phrase", decision.answer)


if __name__ == "__main__":
    unittest.main()
