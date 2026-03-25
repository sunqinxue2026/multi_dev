import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Type

from crewai.tools import BaseTool
from pydantic import BaseModel, Field


IGNORED_PARTS = {
    ".git",
    ".venv",
    "venv",
    "node_modules",
    "dist",
    "build",
    "coverage",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".idea",
    ".next",
    ".turbo",
}

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


def project_root() -> Path:
    return Path(__file__).resolve().parents[3]


def outputs_dir() -> Path:
    path = project_root() / "outputs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def execution_log_path() -> Path:
    return outputs_dir() / "execution_log.jsonl"


def node_workspaces_path() -> Path:
    return outputs_dir() / "node_workspaces.json"


def load_node_workspaces() -> dict[str, object]:
    path = node_workspaces_path()
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def target_repository_root(node_name: str = "") -> Path:
    if node_name:
        workspace = load_node_workspaces().get(node_name, {})
        if isinstance(workspace, dict):
            worktree_path = str(workspace.get("worktree_path", "")).strip()
            if worktree_path:
                root = Path(worktree_path).expanduser().resolve()
                if root.exists() and root.is_dir():
                    return root

    root = Path(
        os.getenv("TARGET_REPOSITORY_ROOT", str(Path.cwd()))
    ).expanduser().resolve()
    if not root.exists() or not root.is_dir():
        raise FileNotFoundError(
            f"TARGET_REPOSITORY_ROOT is invalid or missing: {root}"
        )
    return root


def execution_mode() -> str:
    value = os.getenv("CREW_EXECUTION_MODE", "plan").strip().lower()
    return "write" if value == "write" else "plan"


def bootstrap_mode() -> str:
    value = (
        os.getenv("CREW_EFFECTIVE_BOOTSTRAP_MODE")
        or os.getenv("CREW_BOOTSTRAP_MODE", "")
    ).strip().lower()
    return "new" if value == "new" else "existing"


def bootstrap_fast_track_enabled() -> bool:
    return bootstrap_mode() == "new" and execution_mode() == "write"


def bootstrap_package_name() -> str:
    value = os.getenv("BOOTSTRAP_PACKAGE_NAME", "").strip()
    if value:
        return value
    return "app"


def ensure_within_target(path: Path, root: Path) -> None:
    if path != root and root not in path.parents:
        raise ValueError(f"Path escapes target repository: {path}")


def relative_path_string(path: Path, root: Path) -> str:
    return str(path.relative_to(root))


def is_textlike_path(path: Path) -> bool:
    if path.suffix.lower() in TEXTLIKE_SUFFIXES:
        return True
    if path.name in {"README", ".gitignore"}:
        return True
    return False


def should_ignore(relative_path: Path) -> bool:
    return any(part in IGNORED_PARTS for part in relative_path.parts)


def append_execution_log(action: str, relative_path: str, details: dict[str, str]) -> None:
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "action": action,
        "path": relative_path,
        "details": details,
    }
    with execution_log_path().open("a", encoding="utf-8") as file_handle:
        file_handle.write(json.dumps(entry, ensure_ascii=False) + "\n")


def resolve_repo_path(
    relative_path: str,
    node_name: str = "",
) -> tuple[Path, Path, Path]:
    root = target_repository_root(node_name=node_name)
    clean = relative_path.strip().lstrip("/")
    path = (root / clean).resolve()
    ensure_within_target(path, root)

    if should_ignore(path.relative_to(root)):
        raise ValueError(f"Path is inside an ignored directory: {relative_path}")

    return root, path, path.relative_to(root)


def normalize_prefixes(prefixes: tuple[str, ...]) -> tuple[str, ...]:
    cleaned = [prefix.strip().strip("/") for prefix in prefixes if prefix.strip()]
    return tuple(cleaned)


def path_matches_prefix(relative: Path, prefix: str) -> bool:
    normalized_prefix = prefix.strip().strip("/")
    if not normalized_prefix:
        return False

    relative_str = str(relative).replace("\\", "/")
    return relative_str == normalized_prefix or relative_str.startswith(
        normalized_prefix + "/"
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


def approved_targets_for_node(node_name: str) -> tuple[str, ...]:
    if not node_name:
        return ()

    dispatch_path = outputs_dir() / "master_dispatch.md"
    if not dispatch_path.exists():
        return ()

    contract = extract_json_block(
        dispatch_path.read_text(encoding="utf-8", errors="ignore")
    )
    if not contract:
        return ()

    work_items = contract.get("work_items", [])
    if not isinstance(work_items, list):
        return ()

    approved_targets: list[str] = []
    for item in work_items:
        if not isinstance(item, dict):
            continue
        if str(item.get("node", "")).strip() != node_name:
            continue

        targets = item.get("targets", [])
        if isinstance(targets, list):
            for target in targets:
                if isinstance(target, str) and target.strip():
                    approved_targets.append(target.strip().strip("/"))

    targets = tuple(dict.fromkeys(target for target in approved_targets if target))
    if not bootstrap_fast_track_enabled():
        return targets

    allowed = set(bootstrap_template_targets_for_node(node_name))
    return tuple(target for target in targets if target in allowed)


def bootstrap_template_targets_for_node(node_name: str) -> tuple[str, ...]:
    package_name = bootstrap_package_name()
    shared_backend = (
        "pyproject.toml",
        f"src/{package_name}",
        f"src/{package_name}/__init__.py",
        f"src/{package_name}/app.py",
        f"src/{package_name}/catalog.py",
    )
    shared_frontend = (
        "frontend",
        "frontend/index.html",
        "frontend/app.js",
        "frontend/styles.css",
    )
    shared_tester = (
        "tests",
        "tests/__init__.py",
        "tests/smoke_test.py",
        ".github",
        ".github/workflows",
        ".github/workflows/ci.yml",
        ".github/workflows/deploy.yml",
    )

    if node_name == "backend_node":
        return shared_backend
    if node_name == "frontend_node":
        return shared_frontend
    if node_name == "tester_node":
        return shared_tester
    return ()


def ensure_allowed_prefix(
    relative: Path,
    allowed_prefixes: tuple[str, ...],
    node_name: str = "",
) -> None:
    normalized = normalize_prefixes(allowed_prefixes)
    approved_targets = approved_targets_for_node(node_name)
    if bootstrap_fast_track_enabled() and node_name:
        candidates = approved_targets or bootstrap_template_targets_for_node(node_name)
    else:
        candidates = (*normalized, *approved_targets)
    if not candidates:
        return

    relative_str = str(relative).replace("\\", "/")
    for prefix in candidates:
        if path_matches_prefix(relative, prefix):
            return

    raise ValueError(
        f"Path `{relative}` is outside allowed prefixes: {', '.join(candidates)}"
    )


class ListRepoFilesInput(BaseModel):
    glob_pattern: str = Field(
        default="**/*",
        description="相对仓库根目录的 glob 模式，例如 `web-flask/**/*.py`。",
    )
    max_results: int = Field(
        default=200,
        ge=1,
        le=1000,
        description="最多返回多少个路径。",
    )


class ListRepoFilesTool(BaseTool):
    name: str = "list_repo_files"
    description: str = (
        "列出 TARGET_REPOSITORY_ROOT 下与 glob 模式匹配的可见路径。"
        "用于让 agent 基于真实文件路径工作，避免猜测文件名。"
    )
    args_schema: Type[BaseModel] = ListRepoFilesInput
    allowed_prefixes: tuple[str, ...] = Field(default_factory=tuple, exclude=True)
    node_name: str = Field(default="", exclude=True)

    def _run(self, glob_pattern: str = "**/*", max_results: int = 200) -> str:
        root = target_repository_root(node_name=self.node_name)
        matches: list[str] = []

        for path in sorted(root.glob(glob_pattern)):
            try:
                relative = path.relative_to(root)
            except ValueError:
                continue

            if should_ignore(relative):
                continue

            try:
                ensure_allowed_prefix(
                    relative,
                    self.allowed_prefixes,
                    node_name=self.node_name,
                )
            except ValueError:
                continue

            if path.is_file() and not is_textlike_path(path):
                continue

            kind = "dir" if path.is_dir() else "file"
            matches.append(f"[{kind}] {relative}")
            if len(matches) >= max_results:
                break

        if not matches:
            return "未找到匹配路径。"

        return "\n".join(matches)


class ReadRepoFileInput(BaseModel):
    relative_path: str = Field(..., description="相对 TARGET_REPOSITORY_ROOT 的文件路径。")
    start_line: int = Field(default=1, ge=1, description="起始行号，1 开始。")
    end_line: int = Field(default=200, ge=1, le=2000, description="结束行号。")


class ReadRepoFileTool(BaseTool):
    name: str = "read_repo_file"
    description: str = (
        "读取 TARGET_REPOSITORY_ROOT 下某个文本文件的内容，并附带行号。"
        "只能读取真实存在的文件。"
    )
    args_schema: Type[BaseModel] = ReadRepoFileInput
    allowed_prefixes: tuple[str, ...] = Field(default_factory=tuple, exclude=True)
    node_name: str = Field(default="", exclude=True)

    def _run(self, relative_path: str, start_line: int = 1, end_line: int = 200) -> str:
        _, path, relative = resolve_repo_path(relative_path, node_name=self.node_name)
        ensure_allowed_prefix(
            relative,
            self.allowed_prefixes,
            node_name=self.node_name,
        )

        if not path.exists() or not path.is_file():
            raise FileNotFoundError(f"文件不存在：{relative_path}")

        if not is_textlike_path(path):
            raise ValueError(f"不是受支持的文本文件：{relative_path}")

        lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
        start = max(start_line - 1, 0)
        end = max(end_line, start_line)
        selected = lines[start:end]

        if not selected:
            return f"{relative}\n<empty range>"

        numbered = [
            f"{index + start + 1}: {line}"
            for index, line in enumerate(selected)
        ]
        return f"{relative}\n" + "\n".join(numbered)


class WriteRepoFileInput(BaseModel):
    relative_path: str = Field(..., description="相对 TARGET_REPOSITORY_ROOT 的文件路径。")
    content: str = Field(..., description="要写入文件的完整文本内容。")


class MakeRepoDirectoryInput(BaseModel):
    relative_path: str = Field(..., description="相对 TARGET_REPOSITORY_ROOT 的目录路径。")


class MakeRepoDirectoryTool(BaseTool):
    name: str = "make_repo_directory"
    description: str = (
        "在 CREW_EXECUTION_MODE=write 时，创建 TARGET_REPOSITORY_ROOT 下的目录。"
        "若目录已存在则保持幂等，并记录执行日志。"
    )
    args_schema: Type[BaseModel] = MakeRepoDirectoryInput
    allowed_prefixes: tuple[str, ...] = Field(default_factory=tuple, exclude=True)
    node_name: str = Field(default="", exclude=True)

    def _run(self, relative_path: str) -> str:
        if execution_mode() != "write":
            return "拒绝创建目录：当前 CREW_EXECUTION_MODE 不是 `write`。"

        _, path, relative = resolve_repo_path(relative_path, node_name=self.node_name)
        ensure_allowed_prefix(
            relative,
            self.allowed_prefixes,
            node_name=self.node_name,
        )

        path.mkdir(parents=True, exist_ok=True)
        append_execution_log(
            action="mkdir",
            relative_path=str(relative),
            details={
                "created": str(path.exists() and path.is_dir()).lower(),
                "node": self.node_name or "unknown",
            },
        )
        return f"已创建目录：{relative}"


class WriteRepoFileTool(BaseTool):
    name: str = "write_repo_file"
    description: str = (
        "在 CREW_EXECUTION_MODE=write 时，向 TARGET_REPOSITORY_ROOT 写入一个文本文件。"
        "仅允许写入文本文件，并会记录执行日志。"
    )
    args_schema: Type[BaseModel] = WriteRepoFileInput
    allowed_prefixes: tuple[str, ...] = Field(default_factory=tuple, exclude=True)
    node_name: str = Field(default="", exclude=True)

    def _run(self, relative_path: str, content: str) -> str:
        if execution_mode() != "write":
            return "拒绝写入：当前 CREW_EXECUTION_MODE 不是 `write`。"

        _, path, relative = resolve_repo_path(relative_path, node_name=self.node_name)
        ensure_allowed_prefix(
            relative,
            self.allowed_prefixes,
            node_name=self.node_name,
        )
        if not is_textlike_path(path):
            raise ValueError(f"仅允许写入文本文件：{relative_path}")

        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        append_execution_log(
            action="write_file",
            relative_path=str(relative),
            details={
                "bytes": str(len(content.encode("utf-8"))),
                "node": self.node_name or "unknown",
            },
        )
        return f"已写入文件：{relative}"


class ReplaceRepoTextInput(BaseModel):
    relative_path: str = Field(..., description="相对 TARGET_REPOSITORY_ROOT 的文件路径。")
    old_text: str = Field(..., description="必须精确匹配的旧文本。")
    new_text: str = Field(..., description="替换后的新文本。")
    replace_all: bool = Field(default=False, description="是否替换全部匹配。")


class ReplaceRepoTextTool(BaseTool):
    name: str = "replace_repo_text"
    description: str = (
        "在 CREW_EXECUTION_MODE=write 时，对某个文本文件执行精确字符串替换。"
        "若旧文本不存在，将直接报错，避免模糊改动。"
    )
    args_schema: Type[BaseModel] = ReplaceRepoTextInput
    allowed_prefixes: tuple[str, ...] = Field(default_factory=tuple, exclude=True)
    node_name: str = Field(default="", exclude=True)

    def _run(
        self,
        relative_path: str,
        old_text: str,
        new_text: str,
        replace_all: bool = False,
    ) -> str:
        if execution_mode() != "write":
            return "拒绝替换：当前 CREW_EXECUTION_MODE 不是 `write`。"

        _, path, relative = resolve_repo_path(relative_path, node_name=self.node_name)
        ensure_allowed_prefix(
            relative,
            self.allowed_prefixes,
            node_name=self.node_name,
        )

        if not path.exists() or not path.is_file():
            raise FileNotFoundError(f"文件不存在：{relative_path}")

        if not is_textlike_path(path):
            raise ValueError(f"仅允许替换文本文件：{relative_path}")

        original = path.read_text(encoding="utf-8", errors="ignore")
        if old_text not in original:
            raise ValueError("old_text 未在目标文件中找到，已拒绝修改。")

        if replace_all:
            updated = original.replace(old_text, new_text)
            replacements = original.count(old_text)
        else:
            updated = original.replace(old_text, new_text, 1)
            replacements = 1

        path.write_text(updated, encoding="utf-8")
        append_execution_log(
            action="replace_text",
            relative_path=str(relative),
            details={
                "replacements": str(replacements),
                "node": self.node_name or "unknown",
            },
        )
        return f"已更新文件：{relative}（替换次数：{replacements}）"


class ReadExecutionLogInput(BaseModel):
    max_entries: int = Field(default=200, ge=1, le=2000, description="最多读取多少条执行日志。")


class ReadExecutionLogTool(BaseTool):
    name: str = "read_execution_log"
    description: str = (
        "读取 `outputs/execution_log.jsonl`，查看 node 在目标仓库上的实际写入与替换记录。"
    )
    args_schema: Type[BaseModel] = ReadExecutionLogInput

    def _run(self, max_entries: int = 200) -> str:
        path = execution_log_path()
        if not path.exists():
            return "当前没有执行日志。"

        lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
        if not lines:
            return "当前没有执行日志。"

        selected = lines[-max_entries:]
        return "\n".join(selected)
