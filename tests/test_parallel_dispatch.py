import os
import unittest
from unittest import mock

from multi_dev.crew import MultiDev, default_worktree_path_for, normalize_worker_lane_name
from multi_dev.main import (
    auto_scale_lane_pool_sizes,
    enrich_product_requirement,
    requirement_matches_snack_app,
    review_body_for_pr,
    should_skip_review,
)
from multi_dev.tools.runtime_registry import worker_lane_aliases_for_node_name


class ParallelDispatchTests(unittest.TestCase):
    def test_default_worktree_path_stays_inside_repo_outputs(self) -> None:
        path = default_worktree_path_for(
            "frontend_node__1",
            "MVP-002",
            "frontend_node__1.hero",
            "codex/mvp-002",
        )
        self.assertIn("/multi_dev/outputs/worktrees/", path)

    def test_normalize_worker_lane_keeps_lane_node_name(self) -> None:
        normalized = normalize_worker_lane_name(
            "frontend_node__1",
            "frontend_node__1.hero",
            "frontend_1",
            1,
        )
        self.assertEqual(normalized, "frontend_node__1")

    def test_worker_lane_aliases_match_lane_and_legacy_aliases(self) -> None:
        aliases = worker_lane_aliases_for_node_name("frontend_node__2")
        self.assertIn("frontend_node__2", aliases)
        self.assertIn("frontend_2", aliases)
        self.assertIn("frontend", aliases)

    def test_review_body_for_rework_contains_matching_rework_item(self) -> None:
        body = review_body_for_pr(
            decision="REWORK",
            pr_payload={
                "node": "frontend_node__2",
                "logical_node_id": "frontend_node__2.cart",
                "work_item_id": "MVP-003",
            },
            reviewer_contract={
                "rework_items": [
                    "frontend_node__2 需要改回真实购物车入口文件",
                    "backend_node 需要补 health version",
                ]
            },
            decision_contract={"stop_reason": "review_failed"},
        )
        self.assertIn("REQUEST_CHANGES", body)
        self.assertIn("frontend_node__2", body)
        self.assertNotIn("backend_node 需要补 health version", body)

    def test_should_skip_review_only_skips_same_event(self) -> None:
        reviews = [
            {"pull_request_number": 41, "event": "COMMENT"},
            {"pull_request_number": 42, "event": "APPROVE"},
        ]
        self.assertTrue(should_skip_review(reviews=reviews, pr_number=41, event="COMMENT"))
        self.assertFalse(should_skip_review(reviews=reviews, pr_number=41, event="REQUEST_CHANGES"))

    def test_requirement_matches_snack_app(self) -> None:
        self.assertTrue(requirement_matches_snack_app("请设计并优化一个零食APP"))
        self.assertFalse(requirement_matches_snack_app("请优化日志采集系统"))

    def test_enrich_product_requirement_adds_snack_appendix(self) -> None:
        enriched = enrich_product_requirement("请详细设计零食APP功能")
        self.assertIn("[零食APP优化补充要求]", enriched)
        self.assertIn("购物车", enriched)
        self.assertIn("会员积分", enriched)

    @mock.patch.dict(os.environ, {}, clear=True)
    def test_auto_scale_lane_pool_sizes_for_snack_app(self) -> None:
        applied = auto_scale_lane_pool_sizes("请先详细设计零食APP功能")
        self.assertEqual(os.environ["CREW_BACKEND_POOL_SIZE"], "3")
        self.assertEqual(os.environ["CREW_FRONTEND_POOL_SIZE"], "3")
        self.assertEqual(os.environ["CREW_TESTER_POOL_SIZE"], "2")
        self.assertEqual(
            applied,
            {
                "CREW_BACKEND_POOL_SIZE": "3",
                "CREW_FRONTEND_POOL_SIZE": "3",
                "CREW_TESTER_POOL_SIZE": "2",
            },
        )

    @mock.patch.dict(os.environ, {"CREW_FRONTEND_POOL_SIZE": "5"}, clear=True)
    def test_auto_scale_lane_pool_sizes_keeps_explicit_values(self) -> None:
        applied = auto_scale_lane_pool_sizes("snack app checkout redesign")
        self.assertEqual(os.environ["CREW_FRONTEND_POOL_SIZE"], "5")
        self.assertEqual(os.environ["CREW_BACKEND_POOL_SIZE"], "3")
        self.assertEqual(os.environ["CREW_TESTER_POOL_SIZE"], "2")
        self.assertNotIn("CREW_FRONTEND_POOL_SIZE", applied)

    @mock.patch.dict(os.environ, {}, clear=True)
    def test_shared_llm_requires_key_or_base_url(self) -> None:
        with self.assertRaises(ValueError):
            MultiDev().shared_llm()

    @mock.patch.dict(
        os.environ,
        {
            "OPENAI_BASE_URL": "https://ollama-api.office.ihousejapan.cn/v1",
            "OPENAI_MODEL_NAME": "qwen2.5:7b",
        },
        clear=True,
    )
    def test_shared_llm_accepts_openai_compatible_ollama_endpoint(self) -> None:
        llm = MultiDev().shared_llm()
        self.assertEqual(llm.base_url, "https://ollama-api.office.ihousejapan.cn/v1")
        self.assertEqual(llm.model, "qwen2.5:7b")
        self.assertEqual(llm.api_key, "ollama")


if __name__ == "__main__":
    unittest.main()
