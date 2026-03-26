import unittest

from multi_dev.crew import default_worktree_path_for, normalize_worker_lane_name
from multi_dev.main import review_body_for_pr, should_skip_review
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


if __name__ == "__main__":
    unittest.main()
