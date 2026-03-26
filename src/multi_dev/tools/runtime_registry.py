from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

EXECUTION_NODE_TYPES = ("backend_node", "frontend_node", "tester_node")


def project_root() -> Path:
    return Path(__file__).resolve().parents[3]


def outputs_dir() -> Path:
    path = project_root() / "outputs"
    path.mkdir(parents=True, exist_ok=True)
    return path


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


def extract_json_block(markdown_text: str) -> dict[str, object] | None:
    patterns = [
        r"```json\s*(\{.*?\})\s*```",
        r"```JSON\s*(\{.*?\})\s*```",
    ]
    for pattern in patterns:
        matches = re.findall(pattern, markdown_text, flags=re.DOTALL)
        for candidate in reversed(matches):
            try:
                parsed = json.loads(candidate)
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict):
                return parsed
    return None


def dispatch_contract_path() -> Path:
    return outputs_dir() / "master_dispatch.md"


def dispatch_contract_or_none() -> dict[str, object] | None:
    path = dispatch_contract_path()
    if not path.exists():
        return None
    return extract_json_block(path.read_text(encoding="utf-8", errors="ignore"))


def node_workspaces_path() -> Path:
    return outputs_dir() / "node_workspaces.json"


def empty_workspace_registry() -> dict[str, Any]:
    return {
        "schema_version": 2,
        "by_node": {},
        "by_work_item": {},
        "active_work_item_by_node": {},
    }


def normalize_workspace_registry(payload: Any) -> dict[str, Any]:
    default = empty_workspace_registry()
    if not isinstance(payload, dict):
        return default

    if (
        "schema_version" in payload
        or "by_node" in payload
        or "by_work_item" in payload
        or "active_work_item_by_node" in payload
    ):
        return {
            "schema_version": int(payload.get("schema_version", 2) or 2),
            "by_node": payload.get("by_node", {}) if isinstance(payload.get("by_node", {}), dict) else {},
            "by_work_item": payload.get("by_work_item", {}) if isinstance(payload.get("by_work_item", {}), dict) else {},
            "active_work_item_by_node": (
                payload.get("active_work_item_by_node", {})
                if isinstance(payload.get("active_work_item_by_node", {}), dict)
                else {}
            ),
        }

    legacy_by_node: dict[str, Any] = {}
    for key, value in payload.items():
        if not isinstance(value, dict):
            continue
        legacy_by_node[str(key).strip()] = value

    return {
        "schema_version": 2,
        "by_node": legacy_by_node,
        "by_work_item": {},
        "active_work_item_by_node": {},
    }


def load_workspace_registry() -> dict[str, Any]:
    return normalize_workspace_registry(
        load_json_file(node_workspaces_path(), empty_workspace_registry())
    )


def save_workspace_registry(payload: dict[str, Any]) -> None:
    save_json_file(node_workspaces_path(), normalize_workspace_registry(payload))


def workspace_binding_for(
    *,
    node_name: str = "",
    work_item_id: str = "",
) -> dict[str, Any]:
    registry = load_workspace_registry()
    by_work_item = registry.get("by_work_item", {})
    if work_item_id and isinstance(by_work_item, dict):
        binding = by_work_item.get(work_item_id, {})
        if isinstance(binding, dict) and binding:
            return binding

    active = registry.get("active_work_item_by_node", {})
    if node_name and isinstance(active, dict):
        active_work_item_id = str(active.get(node_name, "")).strip()
        if active_work_item_id and isinstance(by_work_item, dict):
            binding = by_work_item.get(active_work_item_id, {})
            if isinstance(binding, dict) and binding:
                return binding

    by_node = registry.get("by_node", {})
    if node_name and isinstance(by_node, dict):
        binding = by_node.get(node_name, {})
        if isinstance(binding, dict):
            return binding

    return {}


def active_work_item_id_for_node(node_name: str) -> str:
    if not node_name:
        return ""
    registry = load_workspace_registry()
    active = registry.get("active_work_item_by_node", {})
    if not isinstance(active, dict):
        return ""
    return str(active.get(node_name, "")).strip()


def set_workspace_binding(
    *,
    node_name: str,
    payload: dict[str, Any],
    work_item_id: str = "",
) -> dict[str, Any]:
    registry = load_workspace_registry()
    normalized_payload = dict(payload)
    if work_item_id:
        normalized_payload["work_item_id"] = work_item_id
    registry.setdefault("by_node", {})[node_name] = normalized_payload
    if work_item_id:
        registry.setdefault("by_work_item", {})[work_item_id] = normalized_payload
        registry.setdefault("active_work_item_by_node", {})[node_name] = work_item_id
    save_workspace_registry(registry)
    return registry


def list_of_strings(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def base_node_name(node_name: str) -> str:
    clean = str(node_name).strip()
    if not clean:
        return ""
    for base_name in EXECUTION_NODE_TYPES:
        if clean == base_name:
            return base_name
        if clean.startswith(f"{base_name}.") or clean.startswith(f"{base_name}__"):
            return base_name
        if clean.startswith(f"{base_name}_"):
            return base_name
    return clean


def lane_index_for_node_name(node_name: str) -> int:
    clean = str(node_name).strip()
    match = re.search(r"__(\d+)$", clean)
    if match:
        try:
            return max(1, int(match.group(1)))
        except ValueError:
            return 1
    return 1


def dispatched_work_items_for_node(
    node_name: str,
    *,
    work_item_id: str = "",
    logical_node_id: str = "",
) -> list[dict[str, Any]]:
    contract = dispatch_contract_or_none()
    if not isinstance(contract, dict):
        return []

    work_items = contract.get("work_items", [])
    if not isinstance(work_items, list):
        return []

    clean_node_name = str(node_name).strip()
    requested_base_node = base_node_name(clean_node_name)
    requested_lane = lane_index_for_node_name(clean_node_name)
    lane_mode = requested_base_node != clean_node_name

    matches: list[dict[str, Any]] = []
    for item in work_items:
        if not isinstance(item, dict):
            continue
        item_node = str(item.get("node", "")).strip()
        item_base_node = base_node_name(item_node)
        if item_node != clean_node_name and item_base_node != requested_base_node:
            continue
        item_work_item_id = str(
            item.get("work_item_id") or item.get("issue_id") or ""
        ).strip()
        item_logical_node_id = str(item.get("logical_node_id", "")).strip()
        item_worker_lane = str(item.get("worker_lane", "")).strip()
        if lane_mode:
            if item_worker_lane:
                if item_worker_lane != clean_node_name:
                    continue
            elif requested_lane != 1:
                continue
        if work_item_id and item_work_item_id != work_item_id:
            continue
        if logical_node_id and item_logical_node_id != logical_node_id:
            continue
        matches.append(item)
    return matches


def approved_targets_for_node(
    node_name: str,
    *,
    work_item_id: str = "",
    logical_node_id: str = "",
) -> tuple[str, ...]:
    approved_targets: list[str] = []
    for item in dispatched_work_items_for_node(
        node_name,
        work_item_id=work_item_id,
        logical_node_id=logical_node_id,
    ):
        targets = item.get("targets", [])
        if not isinstance(targets, list):
            continue
        for target in targets:
            if isinstance(target, str) and target.strip():
                approved_targets.append(target.strip().strip("/"))
    return tuple(dict.fromkeys(target for target in approved_targets if target))
