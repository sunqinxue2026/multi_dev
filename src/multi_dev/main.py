#!/usr/bin/env python
import json
import os
import re
import shutil
import sys
import warnings

import crewai

from datetime import datetime
from pathlib import Path

from multi_dev.crew import MultiDev
from multi_dev.services import sync_dispatch_runtime_state
from multi_dev.tools.runtime_registry import base_node_name
from multi_dev.tools.git_github_tools import (
    GitHubMergePRTool,
    GitHubReviewPRTool,
)

warnings.filterwarnings("ignore", category=SyntaxWarning, module="pysbd")

DEFAULT_REQUIREMENT = (
    "Design and implement the second version of a master/node multi-agent "
    "development orchestration system that reads a real repository, identifies "
    "module boundaries, drafts issues, assigns node workspaces, prepares PR "
    "drafts, and defines a future GitHub automation path."
)

DEFAULT_PROJECT_CONTEXT = (
    "This is version 2 of a CrewAI-based orchestration prototype. The current "
    "goal is local master/node execution simulation: read repository structure, "
    "split work by module, produce issue drafts, workspace plans, node work "
    "cards, PR drafts, and a GitHub automation blueprint. Do not pretend real "
    "GitHub API, auto-branching, auto-PR, sandbox runners, or auto-merge "
    "already exist unless the repository snapshot proves it."
)

DEFAULT_OUTPUT_LANGUAGE = "简体中文"

SNACK_APP_HINT_MARKER = "[零食APP优化补充要求]"
SNACK_APP_AUTO_POOL_SIZES = {
    "CREW_BACKEND_POOL_SIZE": "3",
    "CREW_FRONTEND_POOL_SIZE": "3",
    "CREW_TESTER_POOL_SIZE": "2",
}
SNACK_APP_REQUIREMENT_APPENDIX = """
[零食APP优化补充要求]
- 在任何 issue 拆分与 node 派发之前，必须先完成一份详细产品蓝图，优先考虑“更容易发现零食、更快完成下单、更愿意再次复购”。
- 功能设计至少覆盖：首页导购、分类导航、搜索与筛选、商品详情、规格选择、组合购/凑单、优惠券与满减、购物车、结算、订单追踪、复购入口、会员积分、评价晒单、收藏与分享。
- 商品信息设计必须体现零食场景特征，例如口味、规格、品牌、场景、健康标签、甜咸辣偏好、礼盒/囤货属性、新品与爆款标签。
- 派单时优先把工作拆成可并行功能簇，例如：商品发现与导购、购物车与结算、营销与复购、测试与质量门禁。
- 若 lane 足够，frontend 优先分拆首页/分类与购物车结算，backend 优先分拆商品目录与营销交易，tester 重点覆盖下单主链路与回归验收。
""".strip()

SNACK_APP_KEYWORDS = (
    "零食",
    "零食app",
    "零食商城",
    "零食店",
    "休闲食品",
    "食品电商",
    "snack",
    "snacks",
    "snack app",
    "snack shop",
)


def run_mode() -> str:
    value = os.getenv("CREW_RUN_MODE", "full").strip().lower()
    return "fast" if value == "fast" else "full"


def execution_mode() -> str:
    value = os.getenv("CREW_EXECUTION_MODE", "plan").strip().lower()
    return "write" if value == "write" else "plan"


def requirement_matches_snack_app(requirement: str) -> bool:
    normalized = requirement.strip().lower()
    if not normalized:
        return False
    return any(keyword in normalized for keyword in SNACK_APP_KEYWORDS)


def enrich_product_requirement(requirement: str) -> str:
    cleaned = requirement.strip()
    if not cleaned:
        return cleaned
    if not requirement_matches_snack_app(cleaned):
        return cleaned
    if SNACK_APP_HINT_MARKER in cleaned:
        return cleaned
    return f"{cleaned}\n\n{SNACK_APP_REQUIREMENT_APPENDIX}"


def auto_scale_lane_pool_sizes(product_requirement: str) -> dict[str, str]:
    if not requirement_matches_snack_app(product_requirement):
        return {}

    applied: dict[str, str] = {}
    for env_name, default_value in SNACK_APP_AUTO_POOL_SIZES.items():
        if os.getenv(env_name, "").strip():
            continue
        os.environ[env_name] = default_value
        applied[env_name] = default_value
    return applied


def resolved_pool_size(env_name: str) -> str:
    raw_value = os.getenv(env_name, "").strip()
    if not raw_value:
        raw_value = os.getenv("CREW_NODE_POOL_SIZE", "").strip()
    if not raw_value:
        raw_value = "2"
    try:
        value = int(raw_value)
    except ValueError:
        value = 2
    return str(max(1, min(value, 6)))


IGNORED_NAMES = {
    ".git",
    ".venv",
    "venv",
    "node_modules",
    "dist",
    "build",
    "coverage",
    "outputs",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".idea",
    ".next",
    ".turbo",
}

KEY_FILES = [
    "README.md",
    "README",
    "pyproject.toml",
    "package.json",
    "requirements.txt",
    "Cargo.toml",
    "go.mod",
    "AGENTS.md",
]

MAX_SNAPSHOT_DEPTH = 4
MAX_SNAPSHOT_ENTRIES = 40
README_EXCERPT_LINES = 6
TEXTLIKE_SUFFIXES = {
    ".py",
    ".md",
    ".txt",
    ".json",
    ".yaml",
    ".yml",
    ".toml",
    ".ini",
    ".cfg",
    ".conf",
    ".sh",
    ".sql",
    ".html",
    ".htm",
    ".css",
    ".js",
    ".jsx",
    ".ts",
    ".tsx",
    ".vue",
    ".svelte",
    ".java",
    ".go",
    ".rs",
    ".c",
    ".cc",
    ".cpp",
    ".h",
    ".hpp",
}
ARTIFACT_PATHS = [
    "outputs/repo_analysis.md",
    "outputs/product_blueprint.md",
    "outputs/module_boundaries.md",
    "outputs/issues.md",
    "outputs/workspace_plan.md",
    "outputs/master_intake.md",
    "outputs/master_dispatch.md",
    "outputs/backend_node.md",
    "outputs/frontend_node.md",
    "outputs/tester_node.md",
    "outputs/pr_drafts.md",
    "outputs/execution_summary.md",
    "outputs/execution_log.jsonl",
    "outputs/github_state.json",
    "outputs/node_workspaces.json",
    "outputs/dispatch_rounds.json",
    "outputs/work_items.json",
    "outputs/pr_bindings.json",
    "outputs/ownership_rules.json",
    "outputs/github_automation.md",
    "outputs/reviewer_audit.md",
    "outputs/master_decision.md",
]

LEGACY_ARTIFACT_PATHS = [
    "outputs/task_plan.md",
    "outputs/requirement_breakdown.md",
    "outputs/implementation_plan.md",
    "outputs/final_review.md",
]


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def crewai_version() -> str:
    return getattr(crewai, "__version__", "unknown")


def artifact_paths() -> list[Path]:
    root = project_root()
    return [root / relative_path for relative_path in ARTIFACT_PATHS]


def legacy_artifact_paths() -> list[Path]:
    root = project_root()
    return [root / relative_path for relative_path in LEGACY_ARTIFACT_PATHS]


def outputs_root() -> Path:
    path = project_root() / "outputs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def rounds_root() -> Path:
    path = outputs_root() / "rounds"
    path.mkdir(parents=True, exist_ok=True)
    return path


def worktrees_root() -> Path:
    path = outputs_root() / "worktrees"
    path.mkdir(parents=True, exist_ok=True)
    return path


def output_path(relative_path: str) -> Path:
    return project_root() / relative_path


def clean_previous_artifacts() -> None:
    for path in [*artifact_paths(), *legacy_artifact_paths()]:
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            path.unlink()
    lane_root = outputs_root() / "node_lanes"
    if lane_root.exists():
        shutil.rmtree(lane_root)
    if rounds_root().exists():
        shutil.rmtree(rounds_root())
        rounds_root().mkdir(parents=True, exist_ok=True)
    if worktrees_root().exists():
        shutil.rmtree(worktrees_root())
        worktrees_root().mkdir(parents=True, exist_ok=True)


def print_artifact_summary() -> None:
    generated = [path for path in artifact_paths() if path.exists()]
    if not generated:
        return

    print(f"\nGenerated artifacts (mode: {run_mode()}):")
    primary_output = project_root() / "outputs/master_decision.md"
    if primary_output.exists():
        print(f"- 主输出: {primary_output}")
    for path in generated:
        if path == primary_output:
            continue
        print(f"- {path}")


def max_rounds() -> int:
    raw_value = os.getenv("CREW_MAX_ROUNDS", "3").strip()
    try:
        value = int(raw_value)
    except ValueError:
        value = 3
    return max(1, min(value, 10))


def resolve_repository_root() -> Path:
    repository_root = Path(
        os.getenv("TARGET_REPOSITORY_ROOT", str(Path.cwd()))
    ).expanduser().resolve()

    if not repository_root.exists():
        raise FileNotFoundError(
            "TARGET_REPOSITORY_ROOT does not exist: "
            f"{repository_root}. Set it to a real local repository path before running."
        )

    if not repository_root.is_dir():
        raise NotADirectoryError(
            f"TARGET_REPOSITORY_ROOT is not a directory: {repository_root}"
        )

    return repository_root


def build_repository_snapshot(repository_root: Path) -> str:
    lines: list[str] = []
    key_files_found: list[str] = []

    for key_file in KEY_FILES:
        path = repository_root / key_file
        if path.exists():
            key_files_found.append(key_file)

    readme_excerpt = ""
    for readme_name in ("README.md", "README"):
        readme_path = repository_root / readme_name
        if readme_path.exists() and readme_path.is_file():
            content = readme_path.read_text(errors="ignore").splitlines()
            excerpt_lines = [
                line.strip() for line in content if line.strip()
            ][:README_EXCERPT_LINES]
            readme_excerpt = "\n".join(excerpt_lines)
            break

    snapshot_depth = 4 if run_mode() == "fast" else MAX_SNAPSHOT_DEPTH
    snapshot_entries = 30 if run_mode() == "fast" else MAX_SNAPSHOT_ENTRIES

    def path_priority(path: Path) -> tuple[int, int, str]:
        try:
            relative = path.relative_to(repository_root)
        except ValueError:
            return (99, 99, str(path))

        top = relative.parts[0] if relative.parts else ""
        is_key_file = relative.name in KEY_FILES

        if is_key_file:
            return (0, len(relative.parts), str(relative))

        if top in {"src", "app", "apps", "server", "backend", "frontend", "api"}:
            return (1, len(relative.parts), str(relative))

        if top in {"web-flask", "web-file", "routes", "clients", "utils"}:
            return (2, len(relative.parts), str(relative))

        if top in {"docs", "logs"}:
            return (5, len(relative.parts), str(relative))

        return (3, len(relative.parts), str(relative))

    for path in sorted(repository_root.rglob("*"), key=path_priority):
        try:
            relative = path.relative_to(repository_root)
        except ValueError:
            continue

        if any(part in IGNORED_NAMES for part in relative.parts):
            continue

        if len(relative.parts) > snapshot_depth:
            continue

        if path.is_file():
            is_key_file = relative.name in KEY_FILES
            is_textlike_file = path.suffix.lower() in TEXTLIKE_SUFFIXES
            if not is_key_file and not is_textlike_file:
                continue

        entry_type = "dir" if path.is_dir() else "file"
        lines.append(f"- [{entry_type}] {relative}")
        if len(lines) >= snapshot_entries:
            lines.append("- [truncated] Snapshot truncated to keep context focused.")
            break

    if not lines:
        lines.append("- [empty] No visible files found within the snapshot depth.")

    parts = [
        f"Repository root: {repository_root}",
        f"Run mode: {run_mode()}",
        f"Execution mode: {execution_mode()}",
        f"Key files: {', '.join(key_files_found) if key_files_found else 'None detected'}",
        f"Snapshot policy: depth<={snapshot_depth}, entries<={snapshot_entries}",
        "Structure:",
        *lines[:snapshot_entries],
    ]

    if readme_excerpt:
        parts.extend(["README excerpt:", readme_excerpt])

    return "\n".join(parts)


def build_inputs() -> dict[str, str]:
    cli_requirement = " ".join(sys.argv[1:]).strip()
    product_requirement = (
        cli_requirement
        or os.getenv("PRODUCT_REQUIREMENT", "").strip()
        or DEFAULT_REQUIREMENT
    )
    product_requirement = enrich_product_requirement(product_requirement)
    auto_scaled_pools = auto_scale_lane_pool_sizes(product_requirement)
    project_context = os.getenv("PROJECT_CONTEXT", "").strip() or DEFAULT_PROJECT_CONTEXT
    output_language = os.getenv("OUTPUT_LANGUAGE", "").strip() or DEFAULT_OUTPUT_LANGUAGE

    repository_root = resolve_repository_root()
    repository_snapshot = build_repository_snapshot(repository_root)
    explicit_bootstrap_mode = os.getenv("CREW_BOOTSTRAP_MODE", "").strip().lower()
    visible_entries = [
        path for path in repository_root.iterdir() if path.name not in IGNORED_NAMES
    ]
    if explicit_bootstrap_mode in {"new", "existing"}:
        bootstrap_mode = explicit_bootstrap_mode
    elif not visible_entries:
        bootstrap_mode = "new"
    elif len(visible_entries) == 1 and visible_entries[0].name in {"README", "README.md"}:
        bootstrap_mode = "new"
    else:
        bootstrap_mode = "existing"

    explicit_package_name = os.getenv("BOOTSTRAP_PACKAGE_NAME", "").strip()
    raw_package_name = explicit_package_name or repository_root.name
    bootstrap_package_name = re.sub(r"[^0-9A-Za-z]+", "_", raw_package_name).strip("_").lower()
    if not bootstrap_package_name:
        bootstrap_package_name = "app"
    if bootstrap_package_name[0].isdigit():
        bootstrap_package_name = f"app_{bootstrap_package_name}"

    bootstrap_fast_track = (
        "true" if bootstrap_mode == "new" and execution_mode() == "write" else "false"
    )

    github_owner = os.getenv("GITHUB_OWNER", "").strip()
    github_repo = os.getenv("GITHUB_REPO", "").strip()
    if not github_repo:
        github_repo = re.sub(r"[^0-9A-Za-z._-]+", "-", repository_root.name).strip("-")
    if not github_repo:
        github_repo = "multi-dev-target"
    github_base_branch = os.getenv("GITHUB_BASE_BRANCH", "main").strip() or "main"
    github_visibility = os.getenv("GITHUB_REPO_VISIBILITY", "private").strip().lower()
    if github_visibility not in {"private", "public"}:
        github_visibility = "private"
    github_token_present = bool(
        (os.getenv("GITHUB_TOKEN") or os.getenv("GH_TOKEN") or "").strip()
    )
    github_enabled = (
        "true"
        if execution_mode() == "write" and github_owner and github_token_present
        else "false"
    )
    deploy_host = os.getenv("DEPLOY_HOST", "").strip()
    deploy_port = os.getenv("DEPLOY_PORT", "").strip() or "22"
    deploy_user = os.getenv("DEPLOY_USER", "").strip()
    deploy_path = os.getenv("DEPLOY_PATH", "").strip()
    deploy_service_name = os.getenv("DEPLOY_SERVICE_NAME", "").strip() or "app"
    deploy_key_present = bool(os.getenv("DEPLOY_SSH_PRIVATE_KEY", "").strip())
    deploy_sudo_present = bool(os.getenv("DEPLOY_SUDO_PASSWORD", "").strip())
    explicit_cicd = os.getenv("CREW_CICD_ENABLED", "").strip().lower()
    if explicit_cicd in {"1", "true", "yes", "on"}:
        cicd_enabled = "true"
    elif explicit_cicd in {"0", "false", "no", "off"}:
        cicd_enabled = "false"
    else:
        cicd_enabled = (
            "true"
            if github_enabled == "true"
            and deploy_host
            and deploy_user
            and deploy_path
            and deploy_key_present
            else "false"
        )
    os.environ["CREW_EFFECTIVE_BOOTSTRAP_MODE"] = bootstrap_mode
    os.environ["CREW_BOOTSTRAP_FAST_TRACK"] = bootstrap_fast_track

    return {
        "product_requirement": product_requirement,
        "project_context": project_context,
        "output_language": output_language,
        "run_mode": run_mode(),
        "execution_mode": execution_mode(),
        "crewai_version": crewai_version(),
        "repository_root": str(repository_root),
        "repository_snapshot": repository_snapshot,
        "bootstrap_mode": bootstrap_mode,
        "bootstrap_fast_track": bootstrap_fast_track,
        "bootstrap_package_name": bootstrap_package_name,
        "backend_pool_size": resolved_pool_size("CREW_BACKEND_POOL_SIZE"),
        "frontend_pool_size": resolved_pool_size("CREW_FRONTEND_POOL_SIZE"),
        "tester_pool_size": resolved_pool_size("CREW_TESTER_POOL_SIZE"),
        "auto_scaled_pools": ",".join(
            f"{env_name}={value}" for env_name, value in sorted(auto_scaled_pools.items())
        )
        or "none",
        "github_enabled": github_enabled,
        "github_owner": github_owner or "未设置",
        "github_repo": github_repo,
        "github_base_branch": github_base_branch,
        "github_visibility": github_visibility,
        "cicd_enabled": cicd_enabled,
        "deploy_host": deploy_host or "未设置",
        "deploy_port": deploy_port,
        "deploy_user": deploy_user or "未设置",
        "deploy_path": deploy_path or "未设置",
        "deploy_service_name": deploy_service_name,
        "deploy_ssh_key_present": "true" if deploy_key_present else "false",
        "deploy_sudo_password_present": "true" if deploy_sudo_present else "false",
        "round_index": "1",
        "previous_round_summary": "",
        "retry_nodes": "all",
        "retry_reason": "",
        "max_rounds": str(max_rounds()),
        "current_year": str(datetime.now().year),
    }


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


def fallback_contract_for_artifact(
    path: Path,
    content: str,
) -> dict[str, object] | None:
    upper_content = content.upper()

    if path.name == "master_decision.md":
        if "MERGE" in upper_content:
            decision = "MERGE"
        elif "CONTINUE_DISPATCH" in upper_content:
            decision = "CONTINUE_DISPATCH"
        elif "REWORK" in upper_content:
            decision = "REWORK"
        else:
            return None
        return {
            "decision": decision,
            "round_index": 1,
            "rerun_nodes": [],
            "next_round_goal": "",
            "stop_reason": "missing_decision_contract_json",
        }

    if path.name == "reviewer_audit.md":
        if "ESCALATE" in upper_content:
            verdict = "ESCALATE"
        elif "PASS" in upper_content:
            verdict = "PASS"
        elif "REWORK" in upper_content:
            verdict = "REWORK"
        else:
            return None
        return {
            "verdict": verdict,
            "failed_nodes": [],
            "passed_nodes": [],
            "blocking_issues": [],
            "rework_items": [],
            "merge_ready": verdict == "PASS",
        }

    return None


def load_json_contract(path: Path) -> dict[str, object]:
    if not path.exists():
        raise FileNotFoundError(f"Structured contract file not found: {path}")

    content = path.read_text(encoding="utf-8", errors="ignore")
    contract = extract_json_block(content)
    if contract is None:
        fallback = fallback_contract_for_artifact(path, content)
        if fallback is None:
            raise ValueError(
                f"Structured JSON contract missing in artifact: {path}"
            )
        return fallback
    return contract


def archive_round_artifacts(round_index: int) -> None:
    round_dir = rounds_root() / f"round_{round_index:02d}"
    round_dir.mkdir(parents=True, exist_ok=True)
    for path in artifact_paths():
        if path.exists():
            shutil.copy2(path, round_dir / path.name)
    lane_root = outputs_root() / "node_lanes"
    if lane_root.exists():
        shutil.copytree(
            lane_root,
            round_dir / "node_lanes",
            dirs_exist_ok=True,
        )


def execution_log_entries() -> list[dict[str, object]]:
    path = output_path("outputs/execution_log.jsonl")
    if not path.exists():
        return []

    entries: list[dict[str, object]] = []
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        if not line.strip():
            continue
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            entries.append(parsed)
    return entries


def github_state_or_none() -> dict[str, object] | None:
    path = output_path("outputs/github_state.json")
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8", errors="ignore"))
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def dispatch_contract_or_none() -> dict[str, object] | None:
    dispatch_path = output_path("outputs/master_dispatch.md")
    if not dispatch_path.exists():
        return None
    return extract_json_block(
        dispatch_path.read_text(encoding="utf-8", errors="ignore")
    )


def dispatched_execution_nodes(contract: dict[str, object] | None) -> list[str]:
    if not contract:
        return []

    work_items = contract.get("work_items", [])
    if not isinstance(work_items, list):
        return []

    nodes: list[str] = []
    for item in work_items:
        if not isinstance(item, dict):
            continue
        node = str(item.get("node", "")).strip()
        if node in {"backend_node", "frontend_node", "tester_node"}:
            nodes.append(node)
    return list(dict.fromkeys(nodes))


def nodes_with_real_writes(entries: list[dict[str, object]]) -> set[str]:
    nodes: set[str] = set()
    for entry in entries:
        action = str(entry.get("action", "")).strip()
        if action not in {"mkdir", "write_file", "replace_text"}:
            continue
        details = entry.get("details", {})
        if not isinstance(details, dict):
            continue
        node = base_node_name(str(details.get("node", "")).strip())
        if node:
            nodes.add(node)
    return nodes


def dispatch_targets_by_node(
    contract: dict[str, object] | None,
) -> dict[str, list[str]]:
    if not contract:
        return {}

    work_items = contract.get("work_items", [])
    if not isinstance(work_items, list):
        return {}

    targets_by_node: dict[str, list[str]] = {}
    for item in work_items:
        if not isinstance(item, dict):
            continue
        node = str(item.get("node", "")).strip()
        if not node:
            continue
        targets = item.get("targets", [])
        if not isinstance(targets, list):
            continue
        bucket = targets_by_node.setdefault(node, [])
        for target in targets:
            if isinstance(target, str) and target.strip():
                cleaned = target.strip().strip("/")
                if cleaned and cleaned not in bucket:
                    bucket.append(cleaned)
    return targets_by_node


def looks_like_file_target(target: str) -> bool:
    name = Path(target).name
    return "." in name


def write_entries_by_node(
    entries: list[dict[str, object]],
) -> dict[str, list[dict[str, object]]]:
    grouped: dict[str, list[dict[str, object]]] = {}
    for entry in entries:
        details = entry.get("details", {})
        if not isinstance(details, dict):
            continue
        node = base_node_name(str(details.get("node", "")).strip())
        if not node:
            continue
        grouped.setdefault(node, []).append(entry)
    return grouped


def aggregate_node_lane_outputs() -> None:
    outputs = outputs_root()
    lane_root = outputs / "node_lanes"
    if not lane_root.exists():
        return

    for base_node in ("backend_node", "frontend_node", "tester_node"):
        segments: list[str] = []
        for lane_file in sorted(lane_root.glob(f"{base_node}*.md")):
            body = lane_file.read_text(encoding="utf-8", errors="ignore").strip()
            if not body:
                continue
            segments.append(f"## {lane_file.stem}\n\n{body}")

        target_path = outputs / f"{base_node}.md"
        if segments:
            target_path.write_text(
                "# 聚合节点输出\n\n" + "\n\n".join(segments) + "\n",
                encoding="utf-8",
            )


def path_authorized_for_targets(
    action: str,
    path: str,
    approved_targets: list[str],
) -> bool:
    normalized_path = path.strip().strip("/")
    for target in approved_targets:
        normalized_target = target.strip().strip("/")
        if normalized_path == normalized_target:
            return True
        if action == "mkdir" and normalized_target.startswith(normalized_path + "/"):
            return True
    return False


def target_satisfied(
    target: str,
    node_entries: list[dict[str, object]],
) -> bool:
    normalized_target = target.strip().strip("/")
    if looks_like_file_target(normalized_target):
        for entry in node_entries:
            action = str(entry.get("action", "")).strip()
            path = str(entry.get("path", "")).strip().strip("/")
            if action in {"write_file", "replace_text"} and path == normalized_target:
                return True
        return False

    for entry in node_entries:
        action = str(entry.get("action", "")).strip()
        path = str(entry.get("path", "")).strip().strip("/")
        if action == "mkdir" and path == normalized_target:
            return True
        if path.startswith(normalized_target + "/"):
            return True
    return False


def bootstrap_fast_track_expectations(
    inputs: dict[str, str],
) -> dict[str, dict[str, list[str]]]:
    package_name = inputs.get("bootstrap_package_name", "app").strip() or "app"
    package_root = f"src/{package_name}"
    return {
        "backend_node": {
            "required_exact": [
                "pyproject.toml",
                f"{package_root}/__init__.py",
            ],
            "required_one_of": [
                [
                    f"{package_root}/app.py",
                    f"{package_root}/catalog.py",
                    f"{package_root}/main.py",
                ]
            ],
            "optional_exact": [
                f"{package_root}/app.py",
                f"{package_root}/catalog.py",
                f"{package_root}/main.py",
            ],
            "allowed_dirs": [package_root],
        },
        "frontend_node": {
            "required_exact": [
                "frontend/index.html",
                "frontend/app.js",
            ],
            "required_one_of": [],
            "optional_exact": ["frontend/styles.css"],
            "allowed_dirs": ["frontend"],
        },
        "tester_node": {
            "required_exact": ["tests/__init__.py"],
            "required_one_of": [["tests/smoke_test.py", "tests/test_smoke.py"]],
            "optional_exact": ["tests/smoke_test.py", "tests/test_smoke.py"],
            "allowed_dirs": ["tests"],
        },
    }


def node_has_written_path(
    node_entries: list[dict[str, object]],
    target: str,
) -> bool:
    normalized_target = target.strip().strip("/")
    for entry in node_entries:
        action = str(entry.get("action", "")).strip()
        path = str(entry.get("path", "")).strip().strip("/")
        if action in {"write_file", "replace_text"} and path == normalized_target:
            return True
    return False


def node_has_created_dir(
    node_entries: list[dict[str, object]],
    target: str,
) -> bool:
    normalized_target = target.strip().strip("/")
    for entry in node_entries:
        action = str(entry.get("action", "")).strip()
        path = str(entry.get("path", "")).strip().strip("/")
        if action == "mkdir" and path == normalized_target:
            return True
    return False


def path_authorized_for_expectation(
    action: str,
    path: str,
    expectation: dict[str, list[str]],
) -> bool:
    normalized_path = path.strip().strip("/")
    required_exact = expectation.get("required_exact", [])
    optional_exact = expectation.get("optional_exact", [])
    allowed_dirs = expectation.get("allowed_dirs", [])
    required_one_of = expectation.get("required_one_of", [])

    allowed_files = {
        target.strip().strip("/")
        for target in [*required_exact, *optional_exact]
        if target.strip()
    }
    for group in required_one_of:
        for target in group:
            if isinstance(target, str) and target.strip():
                allowed_files.add(target.strip().strip("/"))

    if action == "mkdir":
        return normalized_path in {
            target.strip().strip("/") for target in allowed_dirs if target.strip()
        }

    return normalized_path in allowed_files


def expectation_satisfied(
    expectation: dict[str, list[str]],
    node_entries: list[dict[str, object]],
) -> tuple[list[str], list[str]]:
    missing_targets: list[str] = []
    rework_items: list[str] = []

    for target in expectation.get("required_exact", []):
        if not node_has_written_path(node_entries, target):
            missing_targets.append(target)

    for group in expectation.get("required_one_of", []):
        candidates = [
            candidate.strip().strip("/")
            for candidate in group
            if isinstance(candidate, str) and candidate.strip()
        ]
        if candidates and not any(
            node_has_written_path(node_entries, candidate) for candidate in candidates
        ):
            missing_targets.append(" | ".join(candidates))

    allowed_dirs = [
        target.strip().strip("/")
        for target in expectation.get("allowed_dirs", [])
        if target.strip()
    ]
    for directory in allowed_dirs:
        if not (
            node_has_created_dir(node_entries, directory)
            or any(
                str(entry.get("path", "")).strip().strip("/").startswith(directory + "/")
                for entry in node_entries
            )
        ):
            rework_items.append(f"未发现目录落盘痕迹：{directory}")

    return missing_targets, rework_items


def stabilize_bootstrap_fast_track_outputs(
    round_index: int,
    inputs: dict[str, str],
) -> None:
    if inputs.get("bootstrap_mode") != "new":
        return
    if inputs.get("execution_mode") != "write":
        return
    if inputs.get("bootstrap_fast_track") != "true":
        return

    entries = execution_log_entries()
    grouped_entries = write_entries_by_node(entries)
    expectations = bootstrap_fast_track_expectations(inputs)
    contract = dispatch_contract_or_none()
    targets_by_node = dispatch_targets_by_node(contract)
    use_dispatch_contract = bool(targets_by_node)
    expected_nodes = (
        list(targets_by_node.keys()) if use_dispatch_contract else list(expectations.keys())
    )

    failed_nodes: list[str] = []
    passed_nodes: list[str] = []
    blocking_issues: list[str] = []
    rework_items: list[str] = []

    for node in expected_nodes:
        node_entries = grouped_entries.get(node, [])
        unauthorized_paths: list[str] = []
        missing_targets: list[str] = []
        node_rework_items: list[str] = []

        if use_dispatch_contract:
            targets = targets_by_node.get(node, [])
            for entry in node_entries:
                action = str(entry.get("action", "")).strip()
                path = str(entry.get("path", "")).strip()
                if action not in {"mkdir", "write_file", "replace_text"}:
                    continue
                if not path_authorized_for_targets(action, path, targets):
                    unauthorized_paths.append(path)

            missing_targets = [
                target for target in targets if not target_satisfied(target, node_entries)
            ]
        else:
            expectation = expectations.get(node, {})
            for entry in node_entries:
                action = str(entry.get("action", "")).strip()
                path = str(entry.get("path", "")).strip()
                if action not in {"mkdir", "write_file", "replace_text"}:
                    continue
                if not path_authorized_for_expectation(action, path, expectation):
                    unauthorized_paths.append(path)

            missing_targets, node_rework_items = expectation_satisfied(
                expectation,
                node_entries,
            )

        if unauthorized_paths or missing_targets or node_rework_items:
            failed_nodes.append(node)
            if unauthorized_paths:
                blocking_issues.append(f"{node}_unauthorized_write")
                rework_items.append(
                    f"{node} 写入了未批准路径：{', '.join(sorted(dict.fromkeys(unauthorized_paths)))}"
                )
            if missing_targets:
                blocking_issues.append(f"{node}_missing_targets")
                rework_items.append(
                    f"{node} 未完成批准目标：{', '.join(missing_targets)}"
                )
            if node_rework_items:
                blocking_issues.append(f"{node}_directory_evidence_missing")
                rework_items.extend(f"{node} {item}" for item in node_rework_items)
            continue

        passed_nodes.append(node)

    verdict = "PASS" if not failed_nodes else "REWORK"
    merge_ready = verdict == "PASS"

    reviewer_path = output_path("outputs/reviewer_audit.md")
    reviewer_body = [
        "# 内部审计报告",
        "",
        "## 审计结论",
        f"**{verdict}**",
        "",
        "## 客观审计结果",
        f"- 审计方式：基于 `dispatch_contract` 与 `execution_log.jsonl` 的客观对账。",
        f"- 通过节点：{', '.join(passed_nodes) if passed_nodes else '无'}",
        f"- 失败节点：{', '.join(failed_nodes) if failed_nodes else '无'}",
    ]
    if rework_items:
        reviewer_body.extend(
            [
                "",
                "## 需打回项",
                *[f"- {item}" for item in rework_items],
            ]
        )
    else:
        reviewer_body.extend(
            [
                "",
                "## 通过说明",
                "- 所有被批准目标均已真实写入，且未发现越界写入。",
            ]
        )
    reviewer_body.extend(
        [
            "",
            "```json",
            json.dumps(
                {
                    "verdict": verdict,
                    "failed_nodes": failed_nodes,
                    "passed_nodes": passed_nodes,
                    "blocking_issues": blocking_issues,
                    "rework_items": rework_items,
                    "merge_ready": merge_ready,
                },
                ensure_ascii=False,
                indent=2,
            ),
            "```",
            "",
        ]
    )
    reviewer_path.write_text("\n".join(reviewer_body), encoding="utf-8")

    decision = "MERGE" if merge_ready else "REWORK"
    decision_path = output_path("outputs/master_decision.md")
    decision_body = [
        "# Master 决策报告",
        "",
        "## 最终结论",
        f"**{decision}**",
        "",
        "## Master 判断依据",
        "- 本裁决基于 `dispatch_contract` 与 `execution_log.jsonl` 的客观对账结果。",
        f"- 已完成节点：{', '.join(passed_nodes) if passed_nodes else '无'}",
        f"- 待打回节点：{', '.join(failed_nodes) if failed_nodes else '无'}",
    ]
    if failed_nodes:
        decision_body.extend(
            [
                "",
                "## 打回动作",
                *[f"- {item}" for item in rework_items],
            ]
        )
    else:
        decision_body.extend(
            [
                "",
                "## 合并动作",
                "- 本轮最小骨架已按批准路径全部落盘，可视为当前范围完成。",
            ]
        )
    decision_body.extend(
        [
            "",
            "```json",
            json.dumps(
                {
                    "decision": decision,
                    "round_index": round_index,
                    "rerun_nodes": failed_nodes,
                    "next_round_goal": (
                        ""
                        if merge_ready
                        else "仅重派失败节点，严格对齐批准路径并补齐缺失目标"
                    ),
                    "stop_reason": (
                        "bootstrap_targets_written"
                        if merge_ready
                        else "bootstrap_targets_mismatch"
                    ),
                },
                ensure_ascii=False,
                indent=2,
            ),
            "```",
            "",
        ]
    )
    decision_path.write_text("\n".join(decision_body), encoding="utf-8")


def write_bootstrap_no_write_failure(
    round_index: int,
    rerun_nodes: list[str],
    stop_reason: str,
    message: str,
) -> None:
    reviewer_path = output_path("outputs/reviewer_audit.md")
    reviewer_path.write_text(
        (
            "# 内部审计报告\n\n"
            "## 审计结论\n"
            "**REWORK**\n\n"
            "## 主要问题\n"
            f"- {message}\n"
            "- 在空仓初始化场景下，本轮目标应当是先落盘最小骨架；若仍停留在分析、issue、workspace 或调度文档阶段，视为未达成交付要求。\n"
            "- reviewer 仅以执行日志中的真实写入为准；被派发但未写入的 node 必须直接打回。\n\n"
            "## 建议给 master 的动作\n"
            "- 立即判定本轮为 `REWORK`。\n"
            "- 仅重派未完成真实写入的 node，要求下一轮先落盘再汇报。\n\n"
            "```json\n"
            "{\n"
            f'  "verdict": "REWORK",\n'
            f'  "failed_nodes": {json.dumps(rerun_nodes, ensure_ascii=False)},\n'
            '  "passed_nodes": [],\n'
            f'  "blocking_issues": ["{stop_reason}"],\n'
            f'  "rework_items": ["{message}"],\n'
            '  "merge_ready": false\n'
            "}\n"
            "```\n"
        ),
        encoding="utf-8",
    )

    decision_path = output_path("outputs/master_decision.md")
    decision_path.write_text(
        (
            "# Master 决策报告\n\n"
            "## 最终结论\n"
            "**REWORK**\n\n"
            "## Master 判断依据\n"
            f"- {message}\n"
            "- 在该场景下，系统必须先让 node 落盘最小骨架；被派发但未写入的 node 不视为有效执行。\n"
            "- 因此本轮直接判定为 `REWORK`，并缩小到具体失败 node。\n\n"
            "## 下一步安排\n"
            "- 重新收紧 master 调度单，确保下一轮首先下发最小真实写入项。\n"
            "- 仅重派本轮没有留下真实写入记录的 node。\n\n"
            "```json\n"
            "{\n"
            f'  "decision": "REWORK",\n'
            f'  "round_index": {round_index},\n'
            f'  "rerun_nodes": {json.dumps(rerun_nodes, ensure_ascii=False)},\n'
            '  "next_round_goal": "仅重派未落盘节点，要求先真实写入再汇报",\n'
            f'  "stop_reason": "{stop_reason}"\n'
            "}\n"
            "```\n"
        ),
        encoding="utf-8",
    )


def enforce_bootstrap_write_progress(round_index: int, inputs: dict[str, str]) -> None:
    if inputs.get("bootstrap_mode") != "new":
        return
    if inputs.get("execution_mode") != "write":
        return
    entries = execution_log_entries()
    contract = dispatch_contract_or_none()
    expected_nodes = dispatched_execution_nodes(contract)
    if not expected_nodes:
        expected_nodes = ["backend_node", "frontend_node", "tester_node"]

    if not entries:
        write_bootstrap_no_write_failure(
            round_index=round_index,
            rerun_nodes=expected_nodes,
            stop_reason="bootstrap_write_no_changes",
            message="当前轮次处于 `bootstrap_mode=new` + `execution_mode=write`，但执行日志为空，说明没有任何 node 完成真实写入。",
        )
        return

    written_nodes = nodes_with_real_writes(entries)
    failed_nodes = [node for node in expected_nodes if node not in written_nodes]
    if not failed_nodes:
        return

    write_bootstrap_no_write_failure(
        round_index=round_index,
        rerun_nodes=failed_nodes,
        stop_reason="bootstrap_partial_write_failure",
        message=(
            "当前轮次已出现部分真实写入，但仍有被派发的 node 没有任何 `mkdir`、`write_file` 或 `replace_text` 日志，"
            f"失败节点：{', '.join(failed_nodes)}。"
        ),
    )


def build_round_summary(
    round_index: int,
    decision_contract: dict[str, object],
    reviewer_contract: dict[str, object] | None,
) -> str:
    summary = {
        "completed_round": round_index,
        "decision": decision_contract.get("decision", "UNKNOWN"),
        "rerun_nodes": decision_contract.get("rerun_nodes", []),
        "next_round_goal": decision_contract.get("next_round_goal", ""),
        "review_verdict": reviewer_contract.get("verdict") if reviewer_contract else "",
        "failed_nodes": reviewer_contract.get("failed_nodes", []) if reviewer_contract else [],
        "blocking_issues": reviewer_contract.get("blocking_issues", []) if reviewer_contract else [],
    }
    return json.dumps(summary, ensure_ascii=False)


def review_body_for_pr(
    *,
    decision: str,
    pr_payload: dict[str, object],
    reviewer_contract: dict[str, object] | None,
    decision_contract: dict[str, object],
) -> str:
    node_name = str(pr_payload.get("node", "")).strip()
    logical_node_id = str(pr_payload.get("logical_node_id", "")).strip()
    work_item_id = str(pr_payload.get("work_item_id", "")).strip()
    stop_reason = str(decision_contract.get("stop_reason", "")).strip()
    rework_items = reviewer_contract.get("rework_items", []) if reviewer_contract else []
    if not isinstance(rework_items, list):
        rework_items = []
    related_items = [
        str(item).strip()
        for item in rework_items
        if str(item).strip()
        and (
            node_name in str(item)
            or logical_node_id in str(item)
            or work_item_id in str(item)
        )
    ]

    if decision == "REWORK":
        lines = [
            "master 已审阅本 PR，本轮结论为 `REQUEST_CHANGES`。",
            "",
            "需要修复后再提交：",
        ]
        if related_items:
            lines.extend(f"- {item}" for item in related_items)
        elif stop_reason:
            lines.append(f"- {stop_reason}")
        else:
            lines.append("- 本 PR 未满足本轮调度单与 reviewer 审计要求。")
        return "\n".join(lines)

    if decision == "CONTINUE_DISPATCH":
        lines = [
            "master 已审阅本 PR，本轮暂不合并，保留为后续继续派发的输入。",
        ]
        if stop_reason:
            lines.extend(["", f"- 当前阶段说明：{stop_reason}"])
        return "\n".join(lines)

    return "master 已审阅本 PR，允许进入合并阶段。"


def should_skip_review(
    *,
    reviews: list[dict[str, object]],
    pr_number: int,
    event: str,
) -> bool:
    for review in reviews:
        if not isinstance(review, dict):
            continue
        if int(review.get("pull_request_number", 0) or 0) != pr_number:
            continue
        if str(review.get("event", "")).upper() == event:
            return True
    return False


def apply_github_decision_actions(
    *,
    inputs: dict[str, str],
    decision_contract: dict[str, object],
    reviewer_contract: dict[str, object] | None,
) -> None:
    if inputs.get("github_enabled") != "true":
        return

    state = github_state_or_none()
    if not state:
        return

    pull_requests = state.get("pull_requests", [])
    if not isinstance(pull_requests, list) or not pull_requests:
        return

    decision = str(decision_contract.get("decision", "")).upper()
    rerun_nodes = decision_contract.get("rerun_nodes", [])
    if not isinstance(rerun_nodes, list):
        rerun_nodes = []
    rerun_nodes = [str(node).strip() for node in rerun_nodes if str(node).strip()]

    failed_nodes = reviewer_contract.get("failed_nodes", []) if reviewer_contract else []
    if not isinstance(failed_nodes, list):
        failed_nodes = []
    failed_nodes = [str(node).strip() for node in failed_nodes if str(node).strip()]

    if decision == "REWORK":
        target_nodes = set(rerun_nodes or failed_nodes)
        event = "REQUEST_CHANGES"
    elif decision == "CONTINUE_DISPATCH":
        target_nodes = set(rerun_nodes or failed_nodes)
        event = "COMMENT"
    elif decision == "MERGE":
        target_nodes = set()
        event = "APPROVE"
    else:
        return

    reviews = state.get("pull_request_reviews", [])
    if not isinstance(reviews, list):
        reviews = []

    review_tool = GitHubReviewPRTool()
    merge_tool = GitHubMergePRTool()

    for pr in pull_requests:
        if not isinstance(pr, dict):
            continue
        pr_number = int(pr.get("number", 0) or 0)
        if not pr_number:
            continue
        node_name = base_node_name(str(pr.get("node", "")).strip())
        if decision in {"REWORK", "CONTINUE_DISPATCH"} and target_nodes and node_name not in target_nodes:
            continue
        if decision == "MERGE" and failed_nodes and node_name in set(failed_nodes):
            continue
        if should_skip_review(reviews=reviews, pr_number=pr_number, event=event):
            continue

        body = review_body_for_pr(
            decision=decision,
            pr_payload=pr,
            reviewer_contract=reviewer_contract,
            decision_contract=decision_contract,
        )
        review_event = event
        try:
            review_tool._run(pr_number=pr_number, event=review_event, body=body)
        except Exception as exc:
            fallback_body = body
            if review_event != "COMMENT":
                fallback_body = (
                    f"{body}\n\n"
                    f"> 注：原计划执行 `{review_event}`，但当前 GitHub 身份/权限返回错误：{exc}。"
                    " 已自动降级为 `COMMENT` 留痕。"
                )
            review_event = "COMMENT"
            review_tool._run(pr_number=pr_number, event=review_event, body=fallback_body)

        if decision == "MERGE":
            merge_tool._run(pr_number=pr_number, merge_method="squash", delete_branch=False)


def kickoff_round(inputs: dict[str, str]) -> None:
    MultiDev().crew().kickoff(inputs=inputs)


def run_round_loop(base_inputs: dict[str, str]) -> None:
    current_inputs = dict(base_inputs)

    for round_index in range(1, max_rounds() + 1):
        current_inputs["round_index"] = str(round_index)
        print(f"\n===== Round {round_index}/{max_rounds()} =====")
        kickoff_round(current_inputs)
        aggregate_node_lane_outputs()
        enforce_bootstrap_write_progress(round_index=round_index, inputs=current_inputs)
        stabilize_bootstrap_fast_track_outputs(
            round_index=round_index,
            inputs=current_inputs,
        )
        decision_contract = load_json_contract(output_path("outputs/master_decision.md"))
        reviewer_contract: dict[str, object] | None = None
        reviewer_path = output_path("outputs/reviewer_audit.md")
        if reviewer_path.exists():
            reviewer_contract = extract_json_block(
                reviewer_path.read_text(encoding="utf-8", errors="ignore")
            )
        sync_dispatch_runtime_state(
            round_index=round_index,
            inputs=current_inputs,
            dispatch_contract=dispatch_contract_or_none(),
            reviewer_contract=reviewer_contract,
            decision_contract=decision_contract,
            execution_entries=execution_log_entries(),
        )
        apply_github_decision_actions(
            inputs=current_inputs,
            decision_contract=decision_contract,
            reviewer_contract=reviewer_contract,
        )
        archive_round_artifacts(round_index)

        decision = str(decision_contract.get("decision", "")).upper()
        rerun_nodes = decision_contract.get("rerun_nodes", [])
        if not isinstance(rerun_nodes, list):
            rerun_nodes = []

        if decision == "MERGE":
            return

        if round_index >= max_rounds():
            return

        if decision not in {"REWORK", "CONTINUE_DISPATCH"}:
            return

        if decision == "REWORK" and not rerun_nodes:
            return

        current_inputs["retry_nodes"] = ",".join(rerun_nodes) if rerun_nodes else "all"
        current_inputs["retry_reason"] = str(
            decision_contract.get("stop_reason")
            or decision_contract.get("reason_summary")
            or ""
        )
        current_inputs["previous_round_summary"] = build_round_summary(
            round_index=round_index,
            decision_contract=decision_contract,
            reviewer_contract=reviewer_contract,
        )
        current_inputs["repository_snapshot"] = build_repository_snapshot(
            resolve_repository_root()
        )


def run():
    """Run the crew."""
    clean_previous_artifacts()
    inputs = build_inputs()

    try:
        run_round_loop(inputs)
        print_artifact_summary()
    except Exception as e:
        raise Exception(f"An error occurred while running the crew: {e}")


def train():
    """Train the crew for a given number of iterations."""
    clean_previous_artifacts()
    inputs = build_inputs()
    try:
        MultiDev().crew().train(
            n_iterations=int(sys.argv[1]), filename=sys.argv[2], inputs=inputs
        )
    except Exception as e:
        raise Exception(f"An error occurred while training the crew: {e}")


def replay():
    """Replay the crew execution from a specific task."""
    try:
        MultiDev().crew().replay(task_id=sys.argv[1])
    except Exception as e:
        raise Exception(f"An error occurred while replaying the crew: {e}")


def test():
    """Test the crew execution and returns the results."""
    clean_previous_artifacts()
    inputs = build_inputs()

    try:
        MultiDev().crew().test(
            n_iterations=int(sys.argv[1]), eval_llm=sys.argv[2], inputs=inputs
        )
    except Exception as e:
        raise Exception(f"An error occurred while testing the crew: {e}")


def run_with_trigger():
    """Run the crew with trigger payload."""
    import json

    if len(sys.argv) < 2:
        raise Exception("No trigger payload provided. Please provide JSON payload as argument.")

    try:
        trigger_payload = json.loads(sys.argv[1])
    except json.JSONDecodeError:
        raise Exception("Invalid JSON payload provided as argument")

    repository_root = Path(
        trigger_payload.get("repository_root")
        or os.getenv("TARGET_REPOSITORY_ROOT", str(Path.cwd()))
    ).expanduser().resolve()

    if not repository_root.exists() or not repository_root.is_dir():
        raise Exception(
            f"Invalid repository_root for trigger payload: {repository_root}"
        )

    clean_previous_artifacts()

    inputs = {
        "crewai_trigger_payload": trigger_payload,
        "product_requirement": trigger_payload.get("product_requirement", DEFAULT_REQUIREMENT),
        "project_context": trigger_payload.get("project_context", DEFAULT_PROJECT_CONTEXT),
        "output_language": trigger_payload.get("output_language")
        or os.getenv("OUTPUT_LANGUAGE", "").strip()
        or DEFAULT_OUTPUT_LANGUAGE,
        "run_mode": trigger_payload.get("run_mode") or run_mode(),
        "execution_mode": trigger_payload.get("execution_mode") or execution_mode(),
        "crewai_version": trigger_payload.get("crewai_version") or crewai_version(),
        "repository_root": str(repository_root),
        "repository_snapshot": trigger_payload.get(
            "repository_snapshot", build_repository_snapshot(repository_root)
        ),
        "bootstrap_mode": trigger_payload.get("bootstrap_mode")
        or os.getenv("CREW_BOOTSTRAP_MODE", "").strip()
        or ("new" if len(list(repository_root.iterdir())) <= 1 else "existing"),
        "bootstrap_package_name": trigger_payload.get("bootstrap_package_name")
        or os.getenv("BOOTSTRAP_PACKAGE_NAME", "").strip()
        or re.sub(r"[^0-9A-Za-z]+", "_", repository_root.name).strip("_").lower()
        or "app",
        "round_index": str(trigger_payload.get("round_index", 1)),
        "previous_round_summary": trigger_payload.get("previous_round_summary", ""),
        "retry_nodes": trigger_payload.get("retry_nodes", "all"),
        "retry_reason": trigger_payload.get("retry_reason", ""),
        "max_rounds": str(trigger_payload.get("max_rounds", max_rounds())),
        "current_year": str(datetime.now().year),
    }
    inputs["bootstrap_fast_track"] = (
        "true"
        if inputs["bootstrap_mode"] == "new" and inputs["execution_mode"] == "write"
        else "false"
    )
    os.environ["CREW_EFFECTIVE_BOOTSTRAP_MODE"] = str(inputs["bootstrap_mode"])
    os.environ["CREW_BOOTSTRAP_FAST_TRACK"] = str(inputs["bootstrap_fast_track"])

    try:
        run_round_loop(inputs)
        print_artifact_summary()
    except Exception as e:
        raise Exception(f"An error occurred while running the crew with trigger: {e}")
