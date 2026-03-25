import base64
import json
import hashlib
import os
import re
import shutil
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Type

from crewai.tools import BaseTool
from pydantic import BaseModel, Field


def project_root() -> Path:
    return Path(__file__).resolve().parents[3]


def outputs_dir() -> Path:
    path = project_root() / "outputs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def target_repository_root() -> Path:
    root = Path(
        os.getenv("TARGET_REPOSITORY_ROOT", str(Path.cwd()))
    ).expanduser().resolve()
    if not root.exists() or not root.is_dir():
        raise FileNotFoundError(
            f"TARGET_REPOSITORY_ROOT is invalid or missing: {root}"
        )
    return root


def github_state_path() -> Path:
    return outputs_dir() / "github_state.json"


def node_workspaces_path() -> Path:
    return outputs_dir() / "node_workspaces.json"


def worktrees_root() -> Path:
    path = outputs_dir() / "worktrees"
    path.mkdir(parents=True, exist_ok=True)
    return path


def repo_workspace_slug(repo_root: Path) -> str:
    digest = hashlib.sha1(str(repo_root).encode("utf-8")).hexdigest()[:8]
    name = re.sub(r"[^0-9A-Za-z._-]+", "-", repo_root.name).strip("-")
    return f"{name or 'repo'}-{digest}"


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
        {
            "repo": {},
            "issues": [],
            "pull_requests": [],
            "node_workspaces": {},
            "repo_secrets": [],
            "pull_request_reviews": [],
        },
    )


def save_github_state(payload: dict[str, Any]) -> None:
    save_json_file(github_state_path(), payload)


def load_node_workspaces() -> dict[str, Any]:
    return load_json_file(node_workspaces_path(), {})


def save_node_workspaces(payload: dict[str, Any]) -> None:
    save_json_file(node_workspaces_path(), payload)


def github_token() -> str:
    token = (os.getenv("GITHUB_TOKEN") or os.getenv("GH_TOKEN") or "").strip()
    if not token:
        raise EnvironmentError(
            "缺少 GitHub 凭证：请设置 `GITHUB_TOKEN` 或 `GH_TOKEN`。"
        )
    return token


def github_owner() -> str:
    owner = os.getenv("GITHUB_OWNER", "").strip()
    if not owner:
        raise EnvironmentError("缺少 `GITHUB_OWNER`。")
    return owner


def github_repo_name() -> str:
    explicit = os.getenv("GITHUB_REPO", "").strip()
    if explicit:
        return explicit
    derived = re.sub(r"[^0-9A-Za-z._-]+", "-", target_repository_root().name).strip("-")
    return derived or "multi-dev-target"


def github_base_branch() -> str:
    return os.getenv("GITHUB_BASE_BRANCH", "main").strip() or "main"


def github_visibility() -> str:
    value = os.getenv("GITHUB_REPO_VISIBILITY", "private").strip().lower()
    return "public" if value == "public" else "private"


def github_headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {github_token()}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "multi-dev/0.1.0",
    }


def github_api_request(
    method: str,
    path: str,
    payload: dict[str, Any] | None = None,
) -> Any:
    url = path if path.startswith("http") else f"https://api.github.com{path}"
    data = None
    headers = github_headers()
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"

    request = urllib.request.Request(
        url=url,
        data=data,
        headers=headers,
        method=method,
    )

    try:
        with urllib.request.urlopen(request) as response:
            body = response.read().decode("utf-8", errors="ignore")
            return json.loads(body) if body else {}
    except urllib.error.HTTPError as error:
        body = error.read().decode("utf-8", errors="ignore")
        try:
            parsed = json.loads(body)
        except json.JSONDecodeError:
            parsed = {"message": body or error.reason}
        message = parsed.get("message", error.reason)
        raise RuntimeError(f"GitHub API 调用失败：{error.code} {message}") from error


def ensure_local_git_identity(repo_root: Path) -> None:
    name = os.getenv("GIT_AUTHOR_NAME", "multi-dev")
    email = os.getenv("GIT_AUTHOR_EMAIL", "multi-dev@local")

    current_name = run_git(
        ["config", "--get", "user.name"],
        cwd=repo_root,
        check=False,
    ).strip()
    current_email = run_git(
        ["config", "--get", "user.email"],
        cwd=repo_root,
        check=False,
    ).strip()

    if not current_name:
        run_git(["config", "user.name", name], cwd=repo_root)
    if not current_email:
        run_git(["config", "user.email", email], cwd=repo_root)


def run_git(args: list[str], cwd: Path, check: bool = True) -> str:
    env = os.environ.copy()
    env.setdefault("GIT_TERMINAL_PROMPT", "0")
    process = subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if check and process.returncode != 0:
        message = process.stderr.strip() or process.stdout.strip() or "git command failed"
        raise RuntimeError(f"git {' '.join(args)} 失败：{message}")
    return process.stdout.strip()


def ensure_git_repo(repo_root: Path, default_branch: str) -> None:
    if (repo_root / ".git").exists():
        ensure_local_git_identity(repo_root)
        return
    run_git(["init", "-b", default_branch], cwd=repo_root)
    ensure_local_git_identity(repo_root)


def has_git_commits(repo_root: Path) -> bool:
    process = subprocess.run(
        ["git", "rev-parse", "--verify", "HEAD"],
        cwd=str(repo_root),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    return process.returncode == 0


def ensure_initial_commit(repo_root: Path, message: str) -> tuple[bool, str]:
    if has_git_commits(repo_root):
        sha = run_git(["rev-parse", "HEAD"], cwd=repo_root)
        return (False, sha)

    committed, detail = commit_all_changes(repo_root, message)
    if committed:
        return (True, detail)

    run_git(["commit", "--allow-empty", "-m", message], cwd=repo_root)
    sha = run_git(["rev-parse", "HEAD"], cwd=repo_root)
    return (True, sha)


def ensure_remote_origin(repo_root: Path, remote_url: str) -> None:
    current = run_git(["remote"], cwd=repo_root, check=False).splitlines()
    if "origin" in current:
        run_git(["remote", "set-url", "origin", remote_url], cwd=repo_root)
    else:
        run_git(["remote", "add", "origin", remote_url], cwd=repo_root)


def git_remote_url(repo_root: Path, remote_name: str = "origin") -> str:
    return run_git(
        ["remote", "get-url", remote_name],
        cwd=repo_root,
        check=False,
    ).strip()


def authenticated_remote_url(remote_url: str) -> str:
    token = (os.getenv("GITHUB_TOKEN") or os.getenv("GH_TOKEN") or "").strip()
    if not token:
        return remote_url

    parsed = urllib.parse.urlparse(remote_url)
    if parsed.scheme != "https" or parsed.netloc != "github.com":
        return remote_url

    return urllib.parse.urlunparse(
        (
            parsed.scheme,
            f"x-access-token:{token}@{parsed.netloc}",
            parsed.path,
            parsed.params,
            parsed.query,
            parsed.fragment,
        )
    )


def git_fetch_origin(repo_root: Path) -> None:
    remote_url = git_remote_url(repo_root)
    if remote_url:
        run_git(["fetch", authenticated_remote_url(remote_url)], cwd=repo_root, check=False)
        return
    run_git(["fetch", "origin"], cwd=repo_root, check=False)


def git_push_branch(repo_root: Path, branch_name: str, set_upstream: bool = True) -> None:
    remote_url = git_remote_url(repo_root)
    push_target = authenticated_remote_url(remote_url) if remote_url else "origin"
    args = ["push"]
    if set_upstream:
        args.append("-u")
    args.extend([push_target, branch_name])
    run_git(args, cwd=repo_root)


def ensure_local_branch(repo_root: Path, branch_name: str, base_branch: str) -> None:
    local_branches = run_git(["branch", "--list", branch_name], cwd=repo_root, check=False)
    if local_branches.strip():
        return

    base_ref = base_branch
    if not run_git(["branch", "--list", base_branch], cwd=repo_root, check=False).strip():
        remote_base = f"origin/{base_branch}"
        if run_git(["branch", "-r", "--list", remote_base], cwd=repo_root, check=False).strip():
            base_ref = remote_base

    run_git(["branch", branch_name, base_ref], cwd=repo_root)


def sanitized_branch_fragment(value: str) -> str:
    cleaned = value.replace("/", "--")
    cleaned = re.sub(r"[^0-9A-Za-z._-]+", "-", cleaned).strip("-")
    return cleaned or "task"


def ensure_base_branch_checked_out(repo_root: Path, branch_name: str) -> None:
    current = run_git(["branch", "--show-current"], cwd=repo_root, check=False).strip()
    if current != branch_name:
        run_git(["checkout", branch_name], cwd=repo_root)


def commit_all_changes(repo_root: Path, message: str) -> tuple[bool, str]:
    run_git(["add", "-A"], cwd=repo_root)
    status = run_git(["status", "--porcelain"], cwd=repo_root, check=False)
    if not status.strip():
        return (False, "没有需要提交的改动。")
    run_git(["commit", "-m", message], cwd=repo_root)
    sha = run_git(["rev-parse", "HEAD"], cwd=repo_root)
    return (True, sha)


def repo_state() -> tuple[str, str]:
    return (github_owner(), github_repo_name())


def get_repo_or_none(owner: str, repo: str) -> dict[str, Any] | None:
    try:
        response = github_api_request("GET", f"/repos/{owner}/{repo}")
    except RuntimeError as error:
        if "404" in str(error):
            return None
        raise
    if isinstance(response, dict):
        return response
    return None


def detect_owner_type(owner: str) -> str:
    response = github_api_request("GET", f"/users/{owner}")
    owner_type = str(response.get("type", "")).lower()
    return "organization" if owner_type == "organization" else "user"


def sync_state_repo(repo_payload: dict[str, Any]) -> None:
    state = load_github_state()
    state["repo"] = repo_payload
    save_github_state(state)


def upsert_issue_state(issue_payload: dict[str, Any]) -> None:
    state = load_github_state()
    issues = state.setdefault("issues", [])
    number = issue_payload.get("number")
    for index, existing in enumerate(issues):
        if existing.get("number") == number:
            issues[index] = {**existing, **issue_payload}
            save_github_state(state)
            return
    issues.append(issue_payload)
    save_github_state(state)


def upsert_pr_state(pr_payload: dict[str, Any]) -> None:
    state = load_github_state()
    prs = state.setdefault("pull_requests", [])
    number = pr_payload.get("number")
    for index, existing in enumerate(prs):
        if existing.get("number") == number:
            prs[index] = {**existing, **pr_payload}
            save_github_state(state)
            return
    prs.append(pr_payload)
    save_github_state(state)


def upsert_pr_review_state(review_payload: dict[str, Any]) -> None:
    state = load_github_state()
    reviews = state.setdefault("pull_request_reviews", [])
    review_id = review_payload.get("id")
    for index, existing in enumerate(reviews):
        if existing.get("id") == review_id:
            reviews[index] = {**existing, **review_payload}
            save_github_state(state)
            return
    reviews.append(review_payload)
    save_github_state(state)


def upsert_repo_secret_state(secret_payload: dict[str, Any]) -> None:
    state = load_github_state()
    secrets = state.setdefault("repo_secrets", [])
    secret_name = secret_payload.get("name")
    for index, existing in enumerate(secrets):
        if existing.get("name") == secret_name:
            secrets[index] = {**existing, **secret_payload}
            save_github_state(state)
            return
    secrets.append(secret_payload)
    save_github_state(state)


def set_node_workspace_state(node_name: str, payload: dict[str, Any]) -> None:
    state = load_github_state()
    state.setdefault("node_workspaces", {})[node_name] = payload
    save_github_state(state)

    workspaces = load_node_workspaces()
    workspaces[node_name] = payload
    save_node_workspaces(workspaces)


def workspace_for_node(node_name: str) -> dict[str, Any]:
    return load_node_workspaces().get(node_name, {})


def cleanup_worktree_path(repo_root: Path, target_path: Path) -> None:
    try:
        run_git(["worktree", "remove", "--force", str(target_path)], cwd=repo_root, check=False)
    except RuntimeError:
        pass

    if target_path.exists():
        if target_path.is_dir():
            shutil.rmtree(target_path, ignore_errors=True)
        else:
            try:
                target_path.unlink()
            except FileNotFoundError:
                pass


def github_repo_public_key(owner: str, repo: str) -> dict[str, Any]:
    response = github_api_request(
        "GET",
        f"/repos/{owner}/{repo}/actions/secrets/public-key",
    )
    if not isinstance(response, dict):
        raise RuntimeError("获取 GitHub Actions 公钥失败。")
    return response


def encrypt_secret_value(public_key: str, secret_value: str) -> str:
    from nacl import encoding, public

    public_key_bytes = base64.b64decode(public_key)
    sealed_box = public.SealedBox(
        public.PublicKey(public_key_bytes, encoder=encoding.RawEncoder)
    )
    encrypted = sealed_box.encrypt(secret_value.encode("utf-8"))
    return base64.b64encode(encrypted).decode("utf-8")


def upsert_github_repo_secret(
    owner: str,
    repo: str,
    secret_name: str,
    secret_value: str,
    source_env: str = "",
) -> None:
    key_payload = github_repo_public_key(owner, repo)
    key_id = str(key_payload.get("key_id", "")).strip()
    key = str(key_payload.get("key", "")).strip()
    if not key_id or not key:
        raise RuntimeError("GitHub Actions 公钥响应不完整。")

    encrypted_value = encrypt_secret_value(key, secret_value)
    github_api_request(
        "PUT",
        f"/repos/{owner}/{repo}/actions/secrets/{secret_name}",
        {
            "encrypted_value": encrypted_value,
            "key_id": key_id,
        },
    )
    upsert_repo_secret_state(
        {
            "name": secret_name,
            "source_env": source_env,
            "status": "configured",
        }
    )


def cicd_secret_specs() -> list[dict[str, str | bool]]:
    return [
        {"secret_name": "DEPLOY_HOST", "env_name": "DEPLOY_HOST", "required": True},
        {"secret_name": "DEPLOY_PORT", "env_name": "DEPLOY_PORT", "required": False},
        {"secret_name": "DEPLOY_USER", "env_name": "DEPLOY_USER", "required": True},
        {"secret_name": "DEPLOY_PATH", "env_name": "DEPLOY_PATH", "required": True},
        {
            "secret_name": "DEPLOY_SSH_PRIVATE_KEY",
            "env_name": "DEPLOY_SSH_PRIVATE_KEY",
            "required": True,
        },
        {
            "secret_name": "DEPLOY_SUDO_PASSWORD",
            "env_name": "DEPLOY_SUDO_PASSWORD",
            "required": False,
        },
        {
            "secret_name": "DEPLOY_SERVICE_NAME",
            "env_name": "DEPLOY_SERVICE_NAME",
            "required": False,
        },
    ]


class GitHubBootstrapRepoInput(BaseModel):
    repo_name: str = Field(..., description="GitHub 仓库名。")
    description: str = Field(default="", description="仓库描述。")
    visibility: str = Field(default="private", description="`private` 或 `public`。")
    default_branch: str = Field(default="main", description="默认主分支名。")


class GitHubBootstrapRepoTool(BaseTool):
    name: str = "github_bootstrap_repo"
    description: str = (
        "创建或接管 GitHub 仓库，并把 TARGET_REPOSITORY_ROOT 初始化为本地 git 仓库、绑定 origin、"
        "确保默认分支存在并首推到远端。适合由 master 在正式派单前执行。"
    )
    args_schema: Type[BaseModel] = GitHubBootstrapRepoInput

    def _run(
        self,
        repo_name: str,
        description: str = "",
        visibility: str = "private",
        default_branch: str = "main",
    ) -> str:
        owner = github_owner()
        repo = get_repo_or_none(owner, repo_name)
        if repo is None:
            owner_type = detect_owner_type(owner)
            payload = {
                "name": repo_name,
                "description": description,
                "private": visibility != "public",
                "auto_init": False,
            }
            path = "/user/repos" if owner_type == "user" else f"/orgs/{owner}/repos"
            repo = github_api_request("POST", path, payload)

        clone_url = str(repo.get("clone_url", "")).strip()
        html_url = str(repo.get("html_url", "")).strip()
        full_name = str(repo.get("full_name", f"{owner}/{repo_name}")).strip()

        repo_root = target_repository_root()
        ensure_git_repo(repo_root, default_branch)
        ensure_base_branch_checked_out(repo_root, default_branch)
        ensure_remote_origin(repo_root, clone_url)
        ensure_initial_commit(repo_root, "chore: bootstrap repository")
        git_push_branch(repo_root, default_branch, set_upstream=True)

        sync_state_repo(
            {
                "owner": owner,
                "name": repo_name,
                "full_name": full_name,
                "html_url": html_url,
                "clone_url": clone_url,
                "default_branch": default_branch,
                "visibility": visibility,
                "local_root": str(repo_root),
            }
        )

        return (
            f"GitHub 仓库已就绪：{full_name}\n"
            f"- html_url: {html_url}\n"
            f"- clone_url: {clone_url}\n"
            f"- local_root: {repo_root}\n"
            f"- default_branch: {default_branch}"
        )


class GitHubCreateIssueInput(BaseModel):
    title: str = Field(..., description="Issue 标题。")
    body: str = Field(..., description="Issue 正文。")
    labels: list[str] = Field(default_factory=list, description="Issue labels。")
    node_name: str = Field(default="", description="负责的 node。")
    issue_key: str = Field(default="", description="内部 Issue ID，例如 MVP-001。")
    branch_name: str = Field(default="", description="建议绑定的分支名。")


class GitHubCreateIssueTool(BaseTool):
    name: str = "github_create_issue"
    description: str = (
        "在当前 GitHub 仓库创建 issue，并把 issue ↔ node ↔ branch 的映射写入 `outputs/github_state.json`。"
    )
    args_schema: Type[BaseModel] = GitHubCreateIssueInput

    def _run(
        self,
        title: str,
        body: str,
        labels: list[str] | None = None,
        node_name: str = "",
        issue_key: str = "",
        branch_name: str = "",
    ) -> str:
        owner, repo = repo_state()
        payload = {
            "title": title,
            "body": body,
            "labels": labels or [],
        }
        response = github_api_request(
            "POST",
            f"/repos/{owner}/{repo}/issues",
            payload,
        )
        issue_payload = {
            "number": response.get("number"),
            "title": response.get("title", title),
            "html_url": response.get("html_url", ""),
            "node": node_name,
            "issue_key": issue_key,
            "branch_name": branch_name,
            "status": "open",
        }
        upsert_issue_state(issue_payload)
        return (
            f"Issue 已创建：#{issue_payload['number']} {issue_payload['title']}\n"
            f"- url: {issue_payload['html_url']}\n"
            f"- node: {node_name or '未绑定'}\n"
            f"- branch: {branch_name or '未指定'}"
        )


class GitHubSyncCICDSecretsInput(BaseModel):
    include_optional: bool = Field(default=True, description="是否同步可选的部署 secrets。")


class GitHubSyncCICDSecretsTool(BaseTool):
    name: str = "github_sync_cicd_secrets"
    description: str = (
        "把本地环境变量中的部署密钥同步到 GitHub Actions repository secrets。"
        "会读取 `DEPLOY_HOST`、`DEPLOY_PORT`、`DEPLOY_USER`、`DEPLOY_PATH`、"
        "`DEPLOY_SSH_PRIVATE_KEY`、`DEPLOY_SUDO_PASSWORD`、`DEPLOY_SERVICE_NAME`。"
    )
    args_schema: Type[BaseModel] = GitHubSyncCICDSecretsInput

    def _run(self, include_optional: bool = True) -> str:
        owner, repo = repo_state()
        synced: list[str] = []
        missing_required: list[str] = []
        skipped_optional: list[str] = []

        for spec in cicd_secret_specs():
            secret_name = str(spec["secret_name"])
            env_name = str(spec["env_name"])
            required = bool(spec["required"])
            raw_value = os.getenv(env_name, "")

            if not raw_value.strip():
                if required:
                    missing_required.append(env_name)
                else:
                    skipped_optional.append(env_name)
                continue

            if not include_optional and not required:
                skipped_optional.append(env_name)
                continue

            upsert_github_repo_secret(
                owner=owner,
                repo=repo,
                secret_name=secret_name,
                secret_value=raw_value,
                source_env=env_name,
            )
            synced.append(secret_name)

        if missing_required:
            raise RuntimeError(
                "缺少必需的 CI/CD 环境变量："
                + ", ".join(missing_required)
            )

        lines = ["GitHub Actions secrets 已同步："]
        lines.extend(f"- {name}" for name in synced)
        if skipped_optional:
            lines.append("- 跳过可选项：" + ", ".join(skipped_optional))
        return "\n".join(lines)


class GitPrepareWorkspaceInput(BaseModel):
    node_name: str = Field(..., description="节点名称，如 backend_node。")
    branch_name: str = Field(..., description="该 node 专属分支名。")
    issue_number: int = Field(default=0, ge=0, description="关联的 GitHub issue 编号。")
    base_branch: str = Field(default="main", description="从哪个基础分支切出。")
    worktree_path: str = Field(default="", description="可选，显式指定 worktree 目录。")


class GitPrepareWorkspaceTool(BaseTool):
    name: str = "git_prepare_node_workspace"
    description: str = (
        "为某个 node 准备独立 branch + worktree，并把映射写入 `outputs/node_workspaces.json`，"
        "随后该 node 的文件工具会自动切到该 worktree。"
    )
    args_schema: Type[BaseModel] = GitPrepareWorkspaceInput

    def _run(
        self,
        node_name: str,
        branch_name: str,
        issue_number: int = 0,
        base_branch: str = "main",
        worktree_path: str = "",
    ) -> str:
        repo_root = target_repository_root()
        ensure_git_repo(repo_root, base_branch)
        ensure_local_git_identity(repo_root)
        git_fetch_origin(repo_root)
        ensure_local_branch(repo_root, branch_name, base_branch)
        repo_slug = repo_workspace_slug(repo_root)

        target_path = (
            Path(worktree_path).expanduser().resolve()
            if worktree_path.strip()
            else (
                worktrees_root()
                / repo_slug
                / f"{node_name}-{sanitized_branch_fragment(branch_name)}"
            ).resolve()
        )

        if target_path.exists():
            cleanup_worktree_path(repo_root, target_path)

        target_path.parent.mkdir(parents=True, exist_ok=True)

        base_ref = branch_name
        run_git(
            ["worktree", "add", "--force", "-B", branch_name, str(target_path), base_ref],
            cwd=repo_root,
        )
        ensure_local_git_identity(target_path)

        payload = {
            "node_name": node_name,
            "branch_name": branch_name,
            "issue_number": issue_number,
            "base_branch": base_branch,
            "worktree_path": str(target_path),
        }
        set_node_workspace_state(node_name, payload)
        return (
            f"Node workspace 已准备：{node_name}\n"
            f"- branch: {branch_name}\n"
            f"- worktree: {target_path}\n"
            f"- issue_number: {issue_number or '未绑定'}"
        )


class GitCommitAndPushInput(BaseModel):
    node_name: str = Field(..., description="节点名称。")
    commit_message: str = Field(..., description="提交信息。")
    branch_name: str = Field(default="", description="显式分支名；默认取 node workspace 记录。")


class GitCommitAndPushTool(BaseTool):
    name: str = "git_commit_and_push"
    description: str = (
        "在 node 对应的 worktree 中执行 `git add -A`、`git commit`、`git push`。"
    )
    args_schema: Type[BaseModel] = GitCommitAndPushInput

    def _run(
        self,
        node_name: str,
        commit_message: str,
        branch_name: str = "",
    ) -> str:
        workspace = workspace_for_node(node_name)
        if not workspace:
            raise RuntimeError(f"未找到 node workspace：{node_name}")

        repo_root = Path(workspace["worktree_path"]).resolve()
        resolved_branch = branch_name or str(workspace.get("branch_name", "")).strip()
        if not resolved_branch:
            raise RuntimeError(f"未找到 node branch：{node_name}")

        ensure_local_git_identity(repo_root)
        committed, detail = commit_all_changes(repo_root, commit_message)
        if not committed:
            return f"{node_name} 没有需要提交的改动。"

        git_push_branch(repo_root, resolved_branch, set_upstream=True)

        state = load_github_state()
        issues = state.setdefault("issues", [])
        for issue in issues:
            if issue.get("node") == node_name:
                issue["status"] = "in_review"
        save_github_state(state)

        return (
            f"{node_name} 已提交并推送。\n"
            f"- branch: {resolved_branch}\n"
            f"- commit: {detail}"
        )


class GitHubCreateOrUpdatePRInput(BaseModel):
    node_name: str = Field(..., description="节点名称。")
    title: str = Field(..., description="PR 标题。")
    body: str = Field(..., description="PR 正文。")
    head_branch: str = Field(..., description="head branch。")
    base_branch: str = Field(default="main", description="base branch。")
    issue_number: int = Field(default=0, ge=0, description="关联 issue 编号。")
    draft: bool = Field(default=False, description="是否创建 draft PR。")


class GitHubCreateOrUpdatePRTool(BaseTool):
    name: str = "github_create_or_update_pr"
    description: str = (
        "基于 branch 创建或更新 GitHub PR，并把 PR ↔ issue ↔ node 状态写入 `outputs/github_state.json`。"
    )
    args_schema: Type[BaseModel] = GitHubCreateOrUpdatePRInput

    def _run(
        self,
        node_name: str,
        title: str,
        body: str,
        head_branch: str,
        base_branch: str = "main",
        issue_number: int = 0,
        draft: bool = False,
    ) -> str:
        owner, repo = repo_state()
        query = urllib.parse.urlencode(
            {
                "state": "open",
                "head": f"{owner}:{head_branch}",
                "base": base_branch,
            }
        )
        existing = github_api_request(
            "GET",
            f"/repos/{owner}/{repo}/pulls?{query}",
        )

        if isinstance(existing, list) and existing:
            pr = existing[0]
            pr = github_api_request(
                "PATCH",
                f"/repos/{owner}/{repo}/pulls/{pr['number']}",
                {
                    "title": title,
                    "body": body,
                },
            )
        else:
            pr = github_api_request(
                "POST",
                f"/repos/{owner}/{repo}/pulls",
                {
                    "title": title,
                    "body": body,
                    "head": head_branch,
                    "base": base_branch,
                    "draft": draft,
                },
            )

        pr_payload = {
            "number": pr.get("number"),
            "title": pr.get("title", title),
            "html_url": pr.get("html_url", ""),
            "node": node_name,
            "head_branch": head_branch,
            "base_branch": base_branch,
            "issue_number": issue_number,
            "status": "open",
        }
        upsert_pr_state(pr_payload)

        if issue_number:
            state = load_github_state()
            for issue in state.setdefault("issues", []):
                if issue.get("number") == issue_number:
                    issue["pr_number"] = pr_payload["number"]
                    issue["status"] = "in_review"
            save_github_state(state)

        return (
            f"PR 已就绪：#{pr_payload['number']} {pr_payload['title']}\n"
            f"- url: {pr_payload['html_url']}\n"
            f"- node: {node_name}\n"
            f"- head: {head_branch}\n"
            f"- base: {base_branch}"
        )


class GitHubMergePRInput(BaseModel):
    pr_number: int = Field(..., ge=1, description="PR 编号。")
    merge_method: str = Field(default="squash", description="merge / squash / rebase。")
    delete_branch: bool = Field(
        default=False,
        description="合并后是否删除远端分支。默认保留，只有用户明确要求时才删除。",
    )


class GitHubReviewPRInput(BaseModel):
    pr_number: int = Field(..., ge=1, description="PR 编号。")
    event: str = Field(
        ...,
        description="Review 动作：`COMMENT`、`APPROVE`、`REQUEST_CHANGES`。",
    )
    body: str = Field(
        default="",
        description="Review 正文；建议由 master 写成最终对外意见。",
    )


class GitHubReviewPRTool(BaseTool):
    name: str = "github_review_pr"
    description: str = (
        "由 master 在 GitHub PR 上执行原生 review 动作：COMMENT / APPROVE / REQUEST_CHANGES。"
    )
    args_schema: Type[BaseModel] = GitHubReviewPRInput

    def _run(
        self,
        pr_number: int,
        event: str,
        body: str = "",
    ) -> str:
        owner, repo = repo_state()
        normalized_event = event.strip().upper()
        if normalized_event not in {"COMMENT", "APPROVE", "REQUEST_CHANGES"}:
            raise RuntimeError(
                "无效的 review 动作；只支持 COMMENT、APPROVE、REQUEST_CHANGES。"
            )

        payload = {"event": normalized_event}
        if body.strip():
            payload["body"] = body

        review = github_api_request(
            "POST",
            f"/repos/{owner}/{repo}/pulls/{pr_number}/reviews",
            payload,
        )

        review_payload = {
            "id": review.get("id"),
            "pull_request_number": pr_number,
            "event": normalized_event,
            "body": body,
            "html_url": review.get("html_url", ""),
            "state": review.get("state", normalized_event.lower()),
        }
        upsert_pr_review_state(review_payload)

        state = load_github_state()
        for item in state.setdefault("pull_requests", []):
            if item.get("number") == pr_number:
                item["review_state"] = normalized_event
                if body.strip():
                    item["last_review_body"] = body
        for issue in state.setdefault("issues", []):
            if issue.get("pr_number") == pr_number:
                if normalized_event == "REQUEST_CHANGES":
                    issue["status"] = "changes_requested"
                elif normalized_event == "APPROVE":
                    issue["status"] = "approved"
        save_github_state(state)

        return (
            f"PR review 已提交：#{pr_number}\n"
            f"- event: {normalized_event}\n"
            f"- review_id: {review_payload['id']}\n"
            f"- url: {review_payload['html_url']}"
        )


class GitHubMergePRTool(BaseTool):
    name: str = "github_merge_pr"
    description: str = (
        "执行真实 GitHub PR merge，并更新 `outputs/github_state.json`。"
        "默认保留远端分支，方便用户回看 node 的改动；只有显式传入 `delete_branch=true` 才会删除。"
    )
    args_schema: Type[BaseModel] = GitHubMergePRInput

    def _run(
        self,
        pr_number: int,
        merge_method: str = "squash",
        delete_branch: bool = False,
    ) -> str:
        owner, repo = repo_state()
        pr = github_api_request(
            "GET",
            f"/repos/{owner}/{repo}/pulls/{pr_number}",
        )
        result = github_api_request(
            "PUT",
            f"/repos/{owner}/{repo}/pulls/{pr_number}/merge",
            {
                "merge_method": merge_method,
            },
        )

        if delete_branch:
            head_ref = str(pr.get("head", {}).get("ref", "")).strip()
            if head_ref:
                try:
                    github_api_request(
                        "DELETE",
                        f"/repos/{owner}/{repo}/git/refs/heads/{urllib.parse.quote(head_ref, safe='')}",
                    )
                except RuntimeError:
                    pass

        state = load_github_state()
        for item in state.setdefault("pull_requests", []):
            if item.get("number") == pr_number:
                item["status"] = "merged"
        for issue in state.setdefault("issues", []):
            if issue.get("pr_number") == pr_number:
                issue["status"] = "merged"
        save_github_state(state)

        return (
            f"PR 已合并：#{pr_number}\n"
            f"- sha: {result.get('sha', '')}\n"
            f"- message: {result.get('message', '')}"
        )


class ReadGitHubStateInput(BaseModel):
    pretty: bool = Field(default=True, description="是否格式化输出 JSON。")


class ReadGitHubStateTool(BaseTool):
    name: str = "read_github_state"
    description: str = (
        "读取 `outputs/github_state.json`，查看 repo / issue / branch / PR / workspace 的当前状态。"
    )
    args_schema: Type[BaseModel] = ReadGitHubStateInput

    def _run(self, pretty: bool = True) -> str:
        state = load_github_state()
        if pretty:
            return json.dumps(state, ensure_ascii=False, indent=2)
        return json.dumps(state, ensure_ascii=False)


class GitBranchDiffSummaryInput(BaseModel):
    branch_name: str = Field(..., description="要查看的分支名。")
    base_branch: str = Field(default="main", description="对比基线分支。")
    max_lines: int = Field(default=200, ge=20, le=1000, description="最多返回多少行。")


class GitBranchDiffSummaryTool(BaseTool):
    name: str = "git_branch_diff_summary"
    description: str = (
        "读取本地 git 分支相对 base branch 的改动摘要，供 reviewer / master 做审查。"
    )
    args_schema: Type[BaseModel] = GitBranchDiffSummaryInput

    def _run(self, branch_name: str, base_branch: str = "main", max_lines: int = 200) -> str:
        repo_root = target_repository_root()
        ensure_git_repo(repo_root, base_branch)
        stat = run_git(
            ["diff", "--stat", f"{base_branch}...{branch_name}"],
            cwd=repo_root,
            check=False,
        )
        patch = run_git(
            ["diff", f"{base_branch}...{branch_name}"],
            cwd=repo_root,
            check=False,
        )
        patch_lines = patch.splitlines()[:max_lines]
        return "\n".join(
            [
                f"[branch] {branch_name}",
                f"[base] {base_branch}",
                "[stat]",
                stat or "<no diff stat>",
                "[patch]",
                *(patch_lines or ["<no patch>"]),
            ]
        )
