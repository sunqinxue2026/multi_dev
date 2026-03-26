from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class DispatchRoundRecord:
    round_index: int
    mode: str
    execution_mode: str
    bootstrap_mode: str
    bootstrap_fast_track: bool
    user_interface: str
    active_nodes: list[str] = field(default_factory=list)
    active_logical_nodes: list[str] = field(default_factory=list)
    inactive_nodes: list[str] = field(default_factory=list)
    work_item_ids: list[str] = field(default_factory=list)
    retry_nodes: list[str] = field(default_factory=list)
    retry_reason: str = ""
    previous_round_summary: str = ""
    reviewer_verdict: str = ""
    decision: str = ""
    rerun_nodes: list[str] = field(default_factory=list)
    stop_reason: str = ""
    real_write_nodes: list[str] = field(default_factory=list)
    real_write_count: int = 0
    updated_at: str = ""


@dataclass(slots=True)
class WorkItemRecord:
    work_item_id: str
    round_index: int
    state: str
    node: str
    action: str
    issue_id: str
    logical_node_id: str = ""
    worker_lane: str = ""
    depends_on: list[str] = field(default_factory=list)
    github_issue_number: int = 0
    pr_number: int = 0
    pr_status: str = ""
    issue_status: str = ""
    branch_name: str = ""
    worktree_path: str = ""
    pr_title: str = ""
    targets: list[str] = field(default_factory=list)
    must_use_tools: list[str] = field(default_factory=list)
    done_when: list[str] = field(default_factory=list)
    write_paths: list[str] = field(default_factory=list)
    write_count: int = 0
    last_round_index: int = 0
    attempt_count: int = 1
    updated_at: str = ""
