from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from multi_dev.models.dispatch import DispatchRoundRecord, WorkItemRecord
from multi_dev.tools.runtime_registry import load_workspace_registry, workspace_binding_for


def project_root() -> Path:
    return Path(__file__).resolve().parents[3]


def outputs_root() -> Path:
    path = project_root() / "outputs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def dispatch_rounds_path() -> Path:
    return outputs_root() / "dispatch_rounds.json"


def work_items_path() -> Path:
    return outputs_root() / "work_items.json"


def pr_bindings_path() -> Path:
    return outputs_root() / "pr_bindings.json"


def ownership_rules_path() -> Path:
    return outputs_root() / "ownership_rules.json"


def github_state_path() -> Path:
    return outputs_root() / "github_state.json"


def node_workspaces_path() -> Path:
    return outputs_root() / "node_workspaces.json"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_json_file(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return default


def save_json_file(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def load_github_state() -> dict[str, Any]:
    return load_json_file(
        github_state_path(),
        {"repo": {}, "issues": [], "pull_requests": [], "node_workspaces": {}},
    )


def load_node_workspaces() -> dict[str, Any]:
    return load_workspace_registry()


def list_of_strings(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def as_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def active_work_items(contract: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(contract, dict):
        return []
    work_items = contract.get("work_items", [])
    if not isinstance(work_items, list):
        return []

    active_nodes = set(list_of_strings(contract.get("active_nodes", [])))
    if not active_nodes:
        active_nodes = {
            str(item.get("node", "")).strip()
            for item in work_items
            if isinstance(item, dict) and str(item.get("node", "")).strip()
        }

    active_items: list[dict[str, Any]] = []
    for item in work_items:
        if not isinstance(item, dict):
            continue
        node = str(item.get("node", "")).strip()
        action = str(item.get("action", "")).strip().lower()
        if not node or node not in active_nodes:
            continue
        if action in {"skip", "skipped", "inactive", "not_dispatched"}:
            continue
        active_items.append(item)
    return active_items


def write_entries_by_node(
    execution_entries: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for entry in execution_entries:
        if str(entry.get("action", "")).strip() not in {"mkdir", "write_file", "replace_text"}:
            continue
        details = entry.get("details", {})
        if not isinstance(details, dict):
            continue
        node = str(details.get("node", "")).strip()
        if not node:
            continue
        grouped.setdefault(node, []).append(entry)
    return grouped


def write_entries_for_work_item(
    execution_entries: list[dict[str, Any]],
    *,
    node: str,
    work_item_id: str = "",
) -> list[dict[str, Any]]:
    if work_item_id:
        scoped: list[dict[str, Any]] = []
        for entry in execution_entries:
            details = entry.get("details", {})
            if not isinstance(details, dict):
                continue
            if str(details.get("node", "")).strip() != node:
                continue
            if str(details.get("work_item_id", "")).strip() != work_item_id:
                continue
            scoped.append(entry)
        if scoped:
            return scoped

    return write_entries_by_node(execution_entries).get(node, [])


def find_issue(
    github_state: dict[str, Any],
    issue_id: str,
    work_item_id: str,
    issue_number: int,
    node: str,
    branch_name: str,
) -> dict[str, Any] | None:
    issues = github_state.get("issues", [])
    if not isinstance(issues, list):
        return None

    for issue in issues:
        if not isinstance(issue, dict):
            continue
        if issue_number and as_int(issue.get("number")) == issue_number:
            return issue
        if work_item_id and str(issue.get("work_item_id", "")).strip() == work_item_id:
            return issue
        if issue_id and str(issue.get("issue_key", "")).strip() == issue_id:
            return issue
        if branch_name and str(issue.get("branch_name", "")).strip() == branch_name:
            return issue
        if node and str(issue.get("node", "")).strip() == node:
            return issue
    return None


def find_pr(
    github_state: dict[str, Any],
    work_item_id: str,
    issue_number: int,
    node: str,
    branch_name: str,
) -> dict[str, Any] | None:
    pull_requests = github_state.get("pull_requests", [])
    if not isinstance(pull_requests, list):
        return None

    for pr in pull_requests:
        if not isinstance(pr, dict):
            continue
        if issue_number and as_int(pr.get("issue_number")) == issue_number:
            return pr
        if work_item_id and str(pr.get("work_item_id", "")).strip() == work_item_id:
            return pr
        if branch_name and str(pr.get("head_branch", "")).strip() == branch_name:
            return pr
        if node and str(pr.get("node", "")).strip() == node:
            return pr
    return None


def infer_work_item_state(
    decision: str,
    reviewer_verdict: str,
    rerun_nodes: list[str],
    failed_nodes: list[str],
    pr_status: str,
    has_writes: bool,
) -> str:
    normalized_pr_status = pr_status.strip().lower()
    if normalized_pr_status == "merged":
        return "MERGED"
    if decision == "MERGE" and has_writes:
        return "MERGED"
    if decision == "REWORK" and (rerun_nodes or failed_nodes):
        return "REWORK_REQUIRED"
    if reviewer_verdict == "REWORK" and failed_nodes:
        return "REWORK_REQUIRED"
    if normalized_pr_status in {"open", "in_review"}:
        return "IN_REVIEW"
    if has_writes:
        return "IN_PROGRESS"
    return "DISPATCHED"


def build_work_item_record(
    item: dict[str, Any],
    round_index: int,
    decision_contract: dict[str, Any] | None,
    reviewer_contract: dict[str, Any] | None,
    execution_entries: list[dict[str, Any]],
    github_state: dict[str, Any],
    node_workspaces: dict[str, Any],
) -> WorkItemRecord:
    node = str(item.get("node", "")).strip()
    work_item_id = str(item.get("work_item_id") or item.get("issue_id") or "").strip()
    issue_id = str(item.get("issue_id", "")).strip() or work_item_id or f"round-{round_index}-{node}"
    logical_node_id = str(item.get("logical_node_id", "")).strip()
    worker_lane = str(item.get("worker_lane", "")).strip()
    branch_name = str(item.get("branch_name", "")).strip()
    github_issue_number = as_int(item.get("github_issue_number"))
    targets = list_of_strings(item.get("targets", []))
    must_use_tools = list_of_strings(item.get("must_use_tools", []))
    done_when = list_of_strings(item.get("done_when", []))
    depends_on = list_of_strings(item.get("depends_on", []))

    workspace = workspace_binding_for(node_name=node, work_item_id=work_item_id)
    if not workspace and isinstance(node_workspaces, dict):
        by_node = node_workspaces.get("by_node", {})
        if isinstance(by_node, dict):
            workspace = by_node.get(node, {})
    if not isinstance(workspace, dict):
        workspace = {}

    linked_issue = find_issue(
        github_state=github_state,
        issue_id=issue_id,
        work_item_id=work_item_id,
        issue_number=github_issue_number,
        node=node,
        branch_name=branch_name,
    )
    if linked_issue:
        github_issue_number = github_issue_number or as_int(linked_issue.get("number"))

    linked_pr = find_pr(
        github_state=github_state,
        work_item_id=work_item_id,
        issue_number=github_issue_number,
        node=node,
        branch_name=branch_name,
    )

    node_entries = write_entries_for_work_item(
        execution_entries,
        node=node,
        work_item_id=work_item_id,
    )
    write_paths = [
        str(entry.get("path", "")).strip()
        for entry in node_entries
        if str(entry.get("path", "")).strip()
    ]
    decision = str((decision_contract or {}).get("decision", "")).upper()
    reviewer_verdict = str((reviewer_contract or {}).get("verdict", "")).upper()
    rerun_nodes = list_of_strings((decision_contract or {}).get("rerun_nodes", []))
    failed_nodes = list_of_strings((reviewer_contract or {}).get("failed_nodes", []))
    state = infer_work_item_state(
        decision=decision,
        reviewer_verdict=reviewer_verdict,
        rerun_nodes=rerun_nodes if node in rerun_nodes else [],
        failed_nodes=failed_nodes if node in failed_nodes else [],
        pr_status=str((linked_pr or {}).get("status", "")).strip(),
        has_writes=bool(write_paths),
    )

    return WorkItemRecord(
        work_item_id=work_item_id or issue_id,
        round_index=round_index,
        last_round_index=round_index,
        state=state,
        node=node,
        logical_node_id=logical_node_id,
        worker_lane=worker_lane,
        action=str(item.get("action", "")).strip(),
        issue_id=issue_id,
        depends_on=depends_on,
        github_issue_number=github_issue_number,
        pr_number=as_int((linked_pr or {}).get("number")),
        pr_status=str((linked_pr or {}).get("status", "")).strip(),
        issue_status=str((linked_issue or {}).get("status", "")).strip(),
        branch_name=branch_name or str((linked_pr or {}).get("head_branch", "")).strip() or str(workspace.get("branch_name", "")).strip(),
        worktree_path=str(item.get("worktree_path", "")).strip() or str(workspace.get("worktree_path", "")).strip(),
        pr_title=str(item.get("pr_title", "")).strip() or str((linked_pr or {}).get("title", "")).strip(),
        targets=targets,
        must_use_tools=must_use_tools,
        done_when=done_when,
        write_paths=sorted(dict.fromkeys(write_paths)),
        write_count=len(write_paths),
        updated_at=now_iso(),
    )


def upsert_dispatch_rounds(records: list[DispatchRoundRecord]) -> None:
    path = dispatch_rounds_path()
    payload = load_json_file(path, {"rounds": []})
    existing = payload.get("rounds", [])
    if not isinstance(existing, list):
        existing = []

    indexed = {
        as_int(record.get("round_index")): record
        for record in existing
        if isinstance(record, dict)
    }
    for record in records:
        indexed[record.round_index] = asdict(record)

    merged = [indexed[key] for key in sorted(indexed)]
    save_json_file(path, {"rounds": merged})


def upsert_work_items(records: list[WorkItemRecord]) -> None:
    path = work_items_path()
    payload = load_json_file(path, {"work_items": []})
    existing = payload.get("work_items", [])
    if not isinstance(existing, list):
        existing = []

    indexed = {
        str(record.get("work_item_id", "")).strip(): record
        for record in existing
        if isinstance(record, dict) and str(record.get("work_item_id", "")).strip()
    }

    for record in records:
        previous = indexed.get(record.work_item_id)
        if isinstance(previous, dict):
            previous_round = as_int(previous.get("last_round_index"))
            attempt_count = as_int(previous.get("attempt_count")) or 1
            record.attempt_count = (
                attempt_count + 1 if previous_round and previous_round != record.round_index else attempt_count
            )
        indexed[record.work_item_id] = asdict(record)

    merged = [
        indexed[key]
        for key in sorted(
            indexed,
            key=lambda item_id: (
                as_int(indexed[item_id].get("last_round_index")),
                item_id,
            ),
        )
    ]
    save_json_file(path, {"work_items": merged})


def save_pr_bindings(records: list[WorkItemRecord]) -> None:
    payload = {
        "pr_bindings": [
            {
                "work_item_id": record.work_item_id,
                "node": record.node,
                "logical_node_id": record.logical_node_id,
                "worker_lane": record.worker_lane,
                "issue_id": record.issue_id,
                "github_issue_number": record.github_issue_number,
                "pr_number": record.pr_number,
                "pr_status": record.pr_status,
                "branch_name": record.branch_name,
                "worktree_path": record.worktree_path,
                "pr_title": record.pr_title,
            }
            for record in records
        ]
    }
    save_json_file(pr_bindings_path(), payload)


def save_ownership_rules(records: list[WorkItemRecord]) -> None:
    payload = {
        "ownership_rules": [
            {
                "work_item_id": record.work_item_id,
                "node": record.node,
                "logical_node_id": record.logical_node_id,
                "worker_lane": record.worker_lane,
                "targets": record.targets,
                "depends_on": record.depends_on,
                "state": record.state,
            }
            for record in records
        ]
    }
    save_json_file(ownership_rules_path(), payload)


def sync_dispatch_runtime_state(
    *,
    round_index: int,
    inputs: dict[str, str],
    dispatch_contract: dict[str, Any] | None,
    reviewer_contract: dict[str, Any] | None,
    decision_contract: dict[str, Any] | None,
    execution_entries: list[dict[str, Any]],
) -> None:
    github_state = load_github_state()
    node_workspaces = load_node_workspaces()
    active_nodes = list_of_strings((dispatch_contract or {}).get("active_nodes", []))
    inactive_nodes = list_of_strings((dispatch_contract or {}).get("inactive_nodes", []))
    work_item_records = [
        build_work_item_record(
            item=item,
            round_index=round_index,
            decision_contract=decision_contract,
            reviewer_contract=reviewer_contract,
            execution_entries=execution_entries,
            github_state=github_state,
            node_workspaces=node_workspaces,
        )
        for item in active_work_items(dispatch_contract)
    ]

    if not active_nodes:
        active_nodes = sorted(dict.fromkeys(record.node for record in work_item_records))
    active_logical_nodes = sorted(
        dict.fromkeys(
            record.logical_node_id for record in work_item_records if record.logical_node_id
        )
    )

    real_write_nodes = sorted(
        dict.fromkeys(record.node for record in work_item_records if record.write_count > 0)
    )
    decision = str((decision_contract or {}).get("decision", "")).upper()
    rerun_nodes = list_of_strings((decision_contract or {}).get("rerun_nodes", []))
    reviewer_verdict = str((reviewer_contract or {}).get("verdict", "")).upper()

    round_record = DispatchRoundRecord(
        round_index=round_index,
        mode=inputs.get("run_mode", "").strip() or inputs.get("mode", "").strip() or "",
        execution_mode=inputs.get("execution_mode", "").strip(),
        bootstrap_mode=inputs.get("bootstrap_mode", "").strip(),
        bootstrap_fast_track=inputs.get("bootstrap_fast_track", "").strip().lower() == "true",
        user_interface=str((dispatch_contract or {}).get("user_interface", "")).strip(),
        active_nodes=active_nodes,
        active_logical_nodes=active_logical_nodes,
        inactive_nodes=inactive_nodes,
        work_item_ids=[record.work_item_id for record in work_item_records],
        retry_nodes=list_of_strings(inputs.get("retry_nodes", "").split(",")) if inputs.get("retry_nodes") else [],
        retry_reason=inputs.get("retry_reason", "").strip(),
        previous_round_summary=inputs.get("previous_round_summary", "").strip(),
        reviewer_verdict=reviewer_verdict,
        decision=decision,
        rerun_nodes=rerun_nodes,
        stop_reason=str((decision_contract or {}).get("stop_reason", "")).strip(),
        real_write_nodes=real_write_nodes,
        real_write_count=sum(record.write_count for record in work_item_records),
        updated_at=now_iso(),
    )

    upsert_dispatch_rounds([round_record])
    upsert_work_items(work_item_records)
    save_pr_bindings(work_item_records)
    save_ownership_rules(work_item_records)
