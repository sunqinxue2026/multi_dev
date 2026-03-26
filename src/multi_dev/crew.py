import json
import hashlib
import os
import re
from pathlib import Path

from crewai import Agent, Crew, LLM, Process, Task
from crewai.agents.agent_builder.base_agent import BaseAgent
from crewai.project import CrewBase, agent, crew, task
from multi_dev.tools.runtime_registry import extract_json_block
from multi_dev.tools import (
    ScaffoldThinCICDWorkflowsTool,
    GitBranchDiffSummaryTool,
    GitCommitAndPushTool,
    GitHubBootstrapRepoTool,
    GitHubCreateIssueTool,
    GitHubCreateOrUpdatePRTool,
    GitHubMergePRTool,
    GitHubReviewPRTool,
    GitHubSyncCICDSecretsTool,
    GitPrepareWorkspaceTool,
    ListRepoFilesTool,
    MakeRepoDirectoryTool,
    ReadExecutionLogTool,
    ReadGitHubStateTool,
    ReadRepoFileTool,
    ReplaceRepoTextTool,
    WriteRepoFileTool,
)


def pool_size_for_node(base_node_name: str) -> int:
    env_map = {
        "backend_node": "CREW_BACKEND_POOL_SIZE",
        "frontend_node": "CREW_FRONTEND_POOL_SIZE",
        "tester_node": "CREW_TESTER_POOL_SIZE",
    }
    raw_value = os.getenv(env_map.get(base_node_name, ""), "").strip()
    if not raw_value:
        raw_value = os.getenv("CREW_NODE_POOL_SIZE", "").strip()
    if not raw_value:
        raw_value = "2"
    try:
        value = int(raw_value)
    except ValueError:
        value = 2
    return max(1, min(value, 6))


def lane_name_for_node(base_node_name: str, lane_index: int) -> str:
    if pool_size_for_node(base_node_name) <= 1:
        return base_node_name
    return f"{base_node_name}__{lane_index}"


def repo_workspace_slug(repo_root: Path) -> str:
    digest = hashlib.sha1(str(repo_root).encode("utf-8")).hexdigest()[:8]
    name = re.sub(r"[^0-9A-Za-z._-]+", "-", repo_root.name).strip("-")
    return f"{name or 'repo'}-{digest}"


def sanitized_fragment(value: str) -> str:
    cleaned = str(value).replace("/", "--")
    cleaned = re.sub(r"[^0-9A-Za-z._-]+", "-", cleaned).strip("-")
    return cleaned or "task"


def default_worktree_path_for(
    node_name: str,
    work_item_id: str,
    logical_node_id: str,
    branch_name: str,
) -> str:
    repo_root = Path(
        os.getenv("TARGET_REPOSITORY_ROOT", str(Path.cwd()))
    ).expanduser().resolve()
    target = (
        Path(__file__).resolve().parents[3]
        / "outputs"
        / "worktrees"
        / repo_workspace_slug(repo_root)
        / f"{node_name}-{sanitized_fragment(work_item_id or logical_node_id or branch_name)}"
    )
    return str(target.resolve())


def load_issue_bindings() -> list[dict[str, object]]:
    path = Path(__file__).resolve().parents[3] / "outputs" / "github_state.json"
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    issues = payload.get("issues", [])
    if not isinstance(issues, list):
        return []
    return [issue for issue in issues if isinstance(issue, dict)]


def normalize_worker_lane_name(
    node_name: str,
    logical_node_id: str,
    raw_worker_lane: str,
    lane_index: int,
) -> str:
    candidate = raw_worker_lane.strip()
    if candidate.startswith(f"{node_name}__") or candidate == node_name:
        return candidate
    if logical_node_id.startswith(f"{node_name}__"):
        return logical_node_id.split(".", 1)[0]
    return lane_name_for_node(node_name, lane_index)


def normalize_master_dispatch_artifact_callback(*_args, **_kwargs) -> None:
    dispatch_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
        "outputs",
        "master_dispatch.md",
    )
    if not os.path.exists(dispatch_path):
        return

    content = open(dispatch_path, encoding="utf-8", errors="ignore").read()
    contract = extract_json_block(content)
    if not isinstance(contract, dict):
        return

    work_items = contract.get("work_items", [])
    if not isinstance(work_items, list):
        return

    lane_counters: dict[str, int] = {}
    issues = load_issue_bindings()
    active_nodes: list[str] = []
    for item in work_items:
        if not isinstance(item, dict):
            continue
        node = str(item.get("node", "")).strip()
        if not node:
            continue
        logical_node_id = str(item.get("logical_node_id", "")).strip()
        if logical_node_id and logical_node_id not in active_nodes:
            active_nodes.append(logical_node_id)
        elif node not in active_nodes:
            active_nodes.append(node)

        lane_counters[node] = lane_counters.get(node, 0) + 1
        lane_index = ((lane_counters[node] - 1) % pool_size_for_node(node)) + 1
        worker_lane = normalize_worker_lane_name(
            node,
            logical_node_id,
            str(item.get("worker_lane", "")),
            lane_index,
        )
        item["worker_lane"] = worker_lane
        if not logical_node_id:
            logical_node_id = worker_lane
            item["logical_node_id"] = logical_node_id

        matched_issue = None
        for issue in issues:
            issue_number = str(issue.get("number", "")).strip()
            if issue_number and issue_number == str(
                item.get("github_issue_number") or item.get("issue_id") or ""
            ).strip():
                matched_issue = issue
                break
            if logical_node_id and logical_node_id == str(
                issue.get("logical_node_id", "")
            ).strip():
                matched_issue = issue
                break
            if str(item.get("work_item_id", "")).strip() and str(
                item.get("work_item_id", "")
            ).strip() == str(issue.get("work_item_id", "")).strip():
                matched_issue = issue
                break
        if matched_issue:
            issue_number = int(matched_issue.get("number", 0) or 0)
            if issue_number:
                item["github_issue_number"] = issue_number
                item["issue_id"] = str(issue_number)
            if not str(item.get("branch_name", "")).strip():
                item["branch_name"] = str(matched_issue.get("branch_name", "")).strip()
            if not str(item.get("pr_title", "")).strip():
                item["pr_title"] = str(matched_issue.get("title", "")).strip()

        branch_name = str(item.get("branch_name", "")).strip()
        if not str(item.get("worktree_path", "")).strip():
            item["worktree_path"] = default_worktree_path_for(
                worker_lane,
                str(item.get("work_item_id", "")).strip(),
                logical_node_id,
                branch_name,
            )

        must_use_tools = item.get("must_use_tools", [])
        if not isinstance(must_use_tools, list):
            must_use_tools = []
        for tool_name in (
            "git_prepare_node_workspace",
            "git_commit_and_push",
            "github_create_or_update_pr",
        ):
            if tool_name not in must_use_tools:
                must_use_tools.append(tool_name)
        item["must_use_tools"] = must_use_tools

    if active_nodes and not contract.get("active_nodes"):
        contract["active_nodes"] = active_nodes
    if "inactive_nodes" not in contract:
        contract["inactive_nodes"] = [
            node_name
            for node_name in ("backend_node", "frontend_node", "tester_node")
            if node_name not in active_nodes
        ]
    if not str(contract.get("user_interface", "")).strip():
        contract["user_interface"] = "master_only"

    replacement = "```json\n" + json.dumps(contract, ensure_ascii=False, indent=2) + "\n```"
    pattern = r"```(?:json|JSON)\s*(\{.*?\})\s*```"
    matches = list(re.finditer(pattern, content, flags=re.DOTALL))
    if not matches:
        return
    last_match = matches[-1]
    updated = content[: last_match.start()] + replacement + content[last_match.end() :]
    with open(dispatch_path, "w", encoding="utf-8") as file_handle:
        file_handle.write(updated)


@CrewBase
class MultiDev:
    """MultiDev crew."""

    agents_config = "config/agents.yaml"
    tasks_config = "config/tasks.yaml"

    agents: list[BaseAgent]
    tasks: list[Task]

    def shared_llm(self) -> LLM:
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise ValueError(
                "OPENAI_API_KEY is required. Export it before running `crewai run`."
            )

        model_name = os.getenv("OPENAI_MODEL_NAME", "qwen-plus")
        base_url = os.getenv("OPENAI_API_BASE") or os.getenv("OPENAI_BASE_URL")
        if self.run_mode() == "fast":
            default_max_tokens = (
                "2200"
                if self.direct_dispatch_enabled() and self.execution_mode() == "write"
                else "1000"
            )
        else:
            default_max_tokens = "2200"
        max_tokens = int(os.getenv("CREW_LLM_MAX_TOKENS", default_max_tokens))

        return LLM(
            model=model_name,
            api_key=api_key,
            base_url=base_url,
            temperature=0.2,
            max_tokens=max_tokens,
        )

    def run_mode(self) -> str:
        value = os.getenv("CREW_RUN_MODE", "full").strip().lower()
        return "fast" if value == "fast" else "full"

    def planning_enabled(self) -> bool:
        if self.run_mode() == "fast":
            return False

        value = os.getenv("CREW_ENABLE_PLANNING", "false").strip().lower()
        return value in {"1", "true", "yes", "on"}

    def execution_mode(self) -> str:
        value = os.getenv("CREW_EXECUTION_MODE", "plan").strip().lower()
        return "write" if value == "write" else "plan"

    def bootstrap_mode(self) -> str:
        value = (
            os.getenv("CREW_EFFECTIVE_BOOTSTRAP_MODE")
            or os.getenv("CREW_BOOTSTRAP_MODE", "")
        ).strip().lower()
        return "new" if value == "new" else "existing"

    def bootstrap_fast_track_enabled(self) -> bool:
        return self.bootstrap_mode() == "new" and self.execution_mode() == "write"

    def direct_dispatch_enabled(self) -> bool:
        value = os.getenv("CREW_DIRECT_DISPATCH", "").strip().lower()
        return value in {"1", "true", "yes", "on"}

    def node_allowed_prefixes(self, env_name: str) -> tuple[str, ...]:
        raw_value = os.getenv(env_name, "").strip()
        if not raw_value:
            return ()
        return tuple(
            item.strip().strip("/")
            for item in raw_value.split(",")
            if item.strip()
        )

    def node_pool_size(self, base_node_name: str) -> int:
        return pool_size_for_node(base_node_name)

    def parallel_node_execution_enabled(self) -> bool:
        return any(
            self.node_pool_size(base_node_name) > 1
            for base_node_name in ("backend_node", "frontend_node", "tester_node")
        )

    def lane_node_name(self, base_node_name: str, lane_index: int) -> str:
        return lane_name_for_node(base_node_name, lane_index)

    def lane_output_path(self, base_node_name: str, lane_index: int) -> str:
        lane_node_name = self.lane_node_name(base_node_name, lane_index)
        if lane_node_name == base_node_name:
            return f"outputs/{base_node_name}.md"
        return f"outputs/node_lanes/{lane_node_name}.md"

    def configured_task(
        self,
        task_key: str,
        *,
        agent_instance: Agent,
        context: list[Task] | None = None,
        output_file: str | None = None,
        name: str | None = None,
        async_execution: bool = False,
        description_suffix: str = "",
        callback=None,
    ) -> Task:
        config = dict(self.tasks_config[task_key])  # type: ignore[index]
        if description_suffix:
            description = str(config.get("description", "")).rstrip()
            config["description"] = f"{description}\n\n{description_suffix}".strip()
        if output_file:
            config["output_file"] = output_file
        return Task(
            name=name,
            config=config,
            agent=agent_instance,
            context=context or [],
            markdown=True,
            async_execution=async_execution,
            callback=callback,
        )

    def build_execution_agent(
        self,
        *,
        config_key: str,
        base_node_name: str,
        lane_index: int,
        allowed_prefixes: tuple[str, ...],
    ) -> Agent:
        lane_node_name = self.lane_node_name(base_node_name, lane_index)
        config = dict(self.agents_config[config_key])  # type: ignore[index]
        role = str(config.get("role", "")).strip()
        if lane_node_name != base_node_name:
            config["role"] = f"{role}（{lane_node_name}）"
        return Agent(
            config=config,
            llm=self.shared_llm(),
            tools=self.execution_tools(
                allowed_prefixes=allowed_prefixes,
                node_name=lane_node_name,
            ),
            verbose=True,
            allow_delegation=False,
        )

    def build_execution_lane_specs(self) -> list[dict[str, object]]:
        specs: list[dict[str, object]] = []
        node_definitions = [
            ("backend_node", "backend_node", "backend_node_task", "CREW_BACKEND_PATHS"),
            ("frontend_node", "frontend_node", "frontend_node_task", "CREW_FRONTEND_PATHS"),
            ("tester_node", "tester_node", "tester_node_task", "CREW_TEST_PATHS"),
        ]
        for base_node_name, config_key, task_key, env_name in node_definitions:
            allowed_prefixes = self.node_allowed_prefixes(env_name)
            pool_size = self.node_pool_size(base_node_name)
            for lane_index in range(1, pool_size + 1):
                lane_node_name = self.lane_node_name(base_node_name, lane_index)
                specs.append(
                    {
                        "base_node_name": base_node_name,
                        "config_key": config_key,
                        "task_key": task_key,
                        "lane_index": lane_index,
                        "lane_node_name": lane_node_name,
                        "output_file": self.lane_output_path(base_node_name, lane_index),
                        "allowed_prefixes": allowed_prefixes,
                    }
                )
        return specs

    def read_tools(
        self,
        allowed_prefixes: tuple[str, ...] = (),
        node_name: str = "",
    ) -> list:
        return [
            ListRepoFilesTool(
                allowed_prefixes=allowed_prefixes,
                node_name=node_name,
            ),
            ReadRepoFileTool(
                allowed_prefixes=allowed_prefixes,
                node_name=node_name,
            ),
            ReadExecutionLogTool(),
        ]

    def master_tools(self) -> list:
        return [
            *self.read_tools(),
            ReadGitHubStateTool(),
            GitBranchDiffSummaryTool(),
            ScaffoldThinCICDWorkflowsTool(),
            GitHubBootstrapRepoTool(),
            GitHubCreateIssueTool(),
            GitHubReviewPRTool(),
            GitHubSyncCICDSecretsTool(),
            GitHubMergePRTool(),
        ]

    def node_git_tools(self, node_name: str) -> list:
        return [
            ReadGitHubStateTool(),
            GitPrepareWorkspaceTool(),
            GitCommitAndPushTool(),
            GitHubCreateOrUpdatePRTool(),
        ]

    def reviewer_tools(self) -> list:
        return [
            *self.read_tools(),
            ReadGitHubStateTool(),
            GitBranchDiffSummaryTool(),
        ]

    def execution_tools(
        self,
        allowed_prefixes: tuple[str, ...] = (),
        node_name: str = "",
    ) -> list:
        tools = self.read_tools(
            allowed_prefixes=allowed_prefixes,
            node_name=node_name,
        )
        if self.execution_mode() == "write":
            tools.extend(
                [
                    MakeRepoDirectoryTool(
                        allowed_prefixes=allowed_prefixes,
                        node_name=node_name,
                    ),
                    WriteRepoFileTool(
                        allowed_prefixes=allowed_prefixes,
                        node_name=node_name,
                    ),
                    ReplaceRepoTextTool(
                        allowed_prefixes=allowed_prefixes,
                        node_name=node_name,
                    ),
                ]
            )
        if node_name:
            tools.extend(self.node_git_tools(node_name))
        return tools

    @agent
    def master_controller(self) -> Agent:
        return Agent(
            config=self.agents_config["master_manager"],  # type: ignore[index]
            llm=self.shared_llm(),
            tools=self.master_tools(),
            verbose=True,
            allow_delegation=True,
            reasoning=False,
        )

    def master_manager(self) -> Agent:
        return Agent(
            config=self.agents_config["master_manager"],  # type: ignore[index]
            llm=self.shared_llm(),
            verbose=True,
            allow_delegation=True,
            reasoning=False,
        )

    @agent
    def repo_analyst(self) -> Agent:
        return Agent(
            config=self.agents_config["repo_analyst"],  # type: ignore[index]
            llm=self.shared_llm(),
            tools=self.read_tools(),
            verbose=True,
            allow_delegation=False,
        )

    @agent
    def task_planner(self) -> Agent:
        return Agent(
            config=self.agents_config["task_planner"],  # type: ignore[index]
            llm=self.shared_llm(),
            tools=self.read_tools(),
            verbose=True,
            allow_delegation=False,
        )

    @agent
    def issue_writer(self) -> Agent:
        return Agent(
            config=self.agents_config["issue_writer"],  # type: ignore[index]
            llm=self.shared_llm(),
            tools=self.read_tools(),
            verbose=True,
            allow_delegation=False,
        )

    @agent
    def backend_node(self) -> Agent:
        allowed_prefixes = self.node_allowed_prefixes("CREW_BACKEND_PATHS")
        return Agent(
            config=self.agents_config["backend_node"],  # type: ignore[index]
            llm=self.shared_llm(),
            tools=self.execution_tools(
                allowed_prefixes=allowed_prefixes,
                node_name="backend_node",
            ),
            verbose=True,
            allow_delegation=False,
        )

    @agent
    def frontend_node(self) -> Agent:
        allowed_prefixes = self.node_allowed_prefixes("CREW_FRONTEND_PATHS")
        return Agent(
            config=self.agents_config["frontend_node"],  # type: ignore[index]
            llm=self.shared_llm(),
            tools=self.execution_tools(
                allowed_prefixes=allowed_prefixes,
                node_name="frontend_node",
            ),
            verbose=True,
            allow_delegation=False,
        )

    @agent
    def tester_node(self) -> Agent:
        allowed_prefixes = self.node_allowed_prefixes("CREW_TEST_PATHS")
        return Agent(
            config=self.agents_config["tester_node"],  # type: ignore[index]
            llm=self.shared_llm(),
            tools=self.execution_tools(
                allowed_prefixes=allowed_prefixes,
                node_name="tester_node",
            ),
            verbose=True,
            allow_delegation=False,
        )

    @agent
    def developer_worker(self) -> Agent:
        return Agent(
            config=self.agents_config["developer_worker"],  # type: ignore[index]
            llm=self.shared_llm(),
            tools=[
                *self.read_tools(),
                ReadGitHubStateTool(),
                GitBranchDiffSummaryTool(),
            ],
            verbose=True,
            allow_delegation=False,
        )

    @agent
    def reviewer_worker(self) -> Agent:
        return Agent(
            config=self.agents_config["reviewer_worker"],  # type: ignore[index]
            llm=self.shared_llm(),
            tools=self.reviewer_tools(),
            verbose=True,
            allow_delegation=False,
        )

    @task
    def repo_analysis_task(self) -> Task:
        return Task(
            config=self.tasks_config["repo_analysis_task"],  # type: ignore[index]
            agent=self.repo_analyst(),
            markdown=True,
        )

    @task
    def module_boundary_task(self) -> Task:
        return Task(
            config=self.tasks_config["module_boundary_task"],  # type: ignore[index]
            agent=self.task_planner(),
            context=[self.repo_analysis_task()],
            markdown=True,
        )

    @task
    def issue_drafting_task(self) -> Task:
        return Task(
            config=self.tasks_config["issue_drafting_task"],  # type: ignore[index]
            agent=self.issue_writer(),
            context=[self.repo_analysis_task(), self.module_boundary_task()],
            markdown=True,
        )

    @task
    def workspace_plan_task(self) -> Task:
        return Task(
            config=self.tasks_config["workspace_plan_task"],  # type: ignore[index]
            agent=self.task_planner(),
            context=[
                self.repo_analysis_task(),
                self.module_boundary_task(),
                self.issue_drafting_task(),
            ],
            markdown=True,
        )

    @task
    def master_intake_task(self) -> Task:
        context = []
        if not self.bootstrap_fast_track_enabled():
            context = [
                self.repo_analysis_task(),
                self.module_boundary_task(),
            ]
        return Task(
            config=self.tasks_config["master_intake_task"],  # type: ignore[index]
            agent=self.master_controller(),
            context=context,
            markdown=True,
        )

    @task
    def master_dispatch_task(self) -> Task:
        context = [self.master_intake_task()]
        if not self.bootstrap_fast_track_enabled():
            context.extend(
                [
                    self.issue_drafting_task(),
                    self.workspace_plan_task(),
                ]
            )
        return Task(
            config=self.tasks_config["master_dispatch_task"],  # type: ignore[index]
            agent=self.master_controller(),
            context=context,
            markdown=True,
        )

    @task
    def backend_node_task(self) -> Task:
        return Task(
            config=self.tasks_config["backend_node_task"],  # type: ignore[index]
            agent=self.backend_node(),
            context=[
                self.master_dispatch_task(),
            ],
            markdown=True,
        )

    @task
    def frontend_node_task(self) -> Task:
        return Task(
            config=self.tasks_config["frontend_node_task"],  # type: ignore[index]
            agent=self.frontend_node(),
            context=[
                self.master_dispatch_task(),
            ],
            markdown=True,
        )

    @task
    def tester_node_task(self) -> Task:
        context = [
            self.master_dispatch_task(),
            self.backend_node_task(),
            self.frontend_node_task(),
        ]
        if self.bootstrap_fast_track_enabled():
            context = [self.master_dispatch_task()]
        return Task(
            config=self.tasks_config["tester_node_task"],  # type: ignore[index]
            agent=self.tester_node(),
            context=context,
            markdown=True,
        )

    @task
    def pr_drafting_task(self) -> Task:
        return Task(
            config=self.tasks_config["pr_drafting_task"],  # type: ignore[index]
            agent=self.developer_worker(),
            context=[
                self.master_dispatch_task(),
                self.backend_node_task(),
                self.frontend_node_task(),
                self.tester_node_task(),
            ],
            markdown=True,
        )

    @task
    def execution_summary_task(self) -> Task:
        return Task(
            config=self.tasks_config["execution_summary_task"],  # type: ignore[index]
            agent=self.developer_worker(),
            context=[
                self.backend_node_task(),
                self.frontend_node_task(),
                self.tester_node_task(),
            ],
            markdown=True,
        )

    @task
    def github_automation_task(self) -> Task:
        return Task(
            config=self.tasks_config["github_automation_task"],  # type: ignore[index]
            agent=self.developer_worker(),
            context=[
                self.master_dispatch_task(),
                self.backend_node_task(),
                self.frontend_node_task(),
                self.tester_node_task(),
                self.pr_drafting_task(),
                self.execution_summary_task(),
            ],
            markdown=True,
        )

    @task
    def reviewer_audit_task(self) -> Task:
        context = [
            self.master_intake_task(),
            self.master_dispatch_task(),
            self.backend_node_task(),
            self.frontend_node_task(),
            self.tester_node_task(),
            self.execution_summary_task(),
        ]
        if not self.bootstrap_fast_track_enabled():
            context.extend(
                [
                    self.pr_drafting_task(),
                    self.github_automation_task(),
                ]
            )
        return Task(
            config=self.tasks_config["reviewer_audit_task"],  # type: ignore[index]
            agent=self.reviewer_worker(),
            context=context,
            markdown=True,
        )

    @task
    def master_decision_task(self) -> Task:
        context = [
            self.master_intake_task(),
            self.master_dispatch_task(),
            self.backend_node_task(),
            self.frontend_node_task(),
            self.tester_node_task(),
            self.execution_summary_task(),
            self.reviewer_audit_task(),
        ]
        if not self.bootstrap_fast_track_enabled():
            context.extend(
                [
                    self.pr_drafting_task(),
                    self.github_automation_task(),
                ]
            )
        return Task(
            config=self.tasks_config["master_decision_task"],  # type: ignore[index]
            agent=self.master_controller(),
            context=context,
            markdown=True,
        )

    @crew
    def crew(self) -> Crew:
        """Creates the MultiDev crew."""

        planning_enabled = self.planning_enabled()
        output_log_file = os.getenv("CREW_OUTPUT_LOG_FILE") or None
        process = Process.sequential
        manager_agent = None

        master_controller = self.master_controller()
        repo_analyst = self.repo_analyst()
        task_planner = self.task_planner()
        issue_writer = self.issue_writer()
        developer_worker = self.developer_worker()
        reviewer_worker = self.reviewer_worker()

        repo_analysis_task = self.configured_task(
            "repo_analysis_task",
            agent_instance=repo_analyst,
            name="repo_analysis_task",
        )
        module_boundary_task = self.configured_task(
            "module_boundary_task",
            agent_instance=task_planner,
            context=[repo_analysis_task],
            name="module_boundary_task",
        )
        issue_drafting_task = self.configured_task(
            "issue_drafting_task",
            agent_instance=issue_writer,
            context=[repo_analysis_task, module_boundary_task],
            name="issue_drafting_task",
        )
        workspace_plan_task = self.configured_task(
            "workspace_plan_task",
            agent_instance=task_planner,
            context=[repo_analysis_task, module_boundary_task, issue_drafting_task],
            name="workspace_plan_task",
        )

        master_intake_context: list[Task] = []
        if not self.bootstrap_fast_track_enabled() and not self.direct_dispatch_enabled():
            master_intake_context = [repo_analysis_task, module_boundary_task]
        master_intake_suffix = ""
        if self.direct_dispatch_enabled() and self.execution_mode() == "write":
            master_intake_suffix = (
                "当前为 `direct_dispatch + write`，不得停留在“证据不足，先不派发”。\n"
                "- 你必须先真实调用工具补齐最小证据：至少探测根级、后端、前端、测试/验证四类路径；\n"
                "- 若用户需求已经点名具体能力（例如 `/health`、Hero 文案、购物车按钮、smoke 测试），你应围绕这些能力去定位真实文件，而不是只输出未知项；\n"
                "- 输出必须压缩：只保留本轮真实需要的证据、风险和可派发结论，不要展开长篇规划。"
            )
        master_intake_task = self.configured_task(
            "master_intake_task",
            agent_instance=master_controller,
            context=master_intake_context,
            name="master_intake_task",
            description_suffix=master_intake_suffix,
        )

        master_dispatch_context = [master_intake_task]
        if not self.bootstrap_fast_track_enabled() and not self.direct_dispatch_enabled():
            master_dispatch_context.extend([issue_drafting_task, workspace_plan_task])
        master_dispatch_suffix = ""
        if self.direct_dispatch_enabled() and self.execution_mode() == "write":
            master_dispatch_suffix = (
                "当前为 `direct_dispatch + write`，你的首要目标是生成可立即执行的最小真实派单，而不是继续做探测计划。\n"
                "- 若 `master_intake` 已拿到真实文件证据，你必须直接派发真实写入 work item；\n"
                "- 若 `github_enabled=true`，对每个实际派发的 work item 都必须先创建真实 GitHub issue，再把 `github_issue_number` 写入 `dispatch_contract`；\n"
                "- 你的正文应保持简短，只保留：派单原则、精简分工表、必要风险；\n"
                "- 输出末尾必须附带完整 `dispatch_contract` JSON 代码块，且不得省略 `worker_lane`、`branch_name`、`worktree_path`、`github_issue_number`。"
            )
        master_dispatch_task = self.configured_task(
            "master_dispatch_task",
            agent_instance=master_controller,
            context=master_dispatch_context,
            name="master_dispatch_task",
            callback=normalize_master_dispatch_artifact_callback,
            description_suffix=master_dispatch_suffix,
        )

        lane_specs = self.build_execution_lane_specs()
        execution_lane_agents: list[Agent] = []
        backend_tasks: list[Task] = []
        frontend_tasks: list[Task] = []
        tester_tasks: list[Task] = []
        async_lanes = self.parallel_node_execution_enabled()

        for spec in lane_specs:
            base_node_name = str(spec["base_node_name"])
            lane_index = int(spec["lane_index"])
            lane_node_name = str(spec["lane_node_name"])
            task_key = str(spec["task_key"])
            config_key = str(spec["config_key"])
            output_file = str(spec["output_file"])
            allowed_prefixes = tuple(spec["allowed_prefixes"])
            lane_agent = self.build_execution_agent(
                config_key=config_key,
                base_node_name=base_node_name,
                lane_index=lane_index,
                allowed_prefixes=allowed_prefixes,
            )
            execution_lane_agents.append(lane_agent)
            context = [master_dispatch_task]
            if base_node_name == "tester_node" and not self.bootstrap_fast_track_enabled():
                context = [master_dispatch_task, *backend_tasks, *frontend_tasks]
            lane_description = (
                f"当前执行 lane 标识：`{lane_node_name}`。\n"
                f"- 你只处理 `dispatch_contract.work_items` 中 `node=\"{base_node_name}\"`，且 `worker_lane=\"{lane_node_name}\"` 的项；"
                "若当前 contract 未显式给出 `worker_lane`，仅 `__1` lane 可兜底接单，其余 lane 必须输出 `skipped`。\n"
                f"- 所有 Git/GitHub 工具调用里的 `node_name` 参数必须使用 `{lane_node_name}`。\n"
                "- 每个 work item 必须独立走完整链路：准备 worktree、真实写入、commit/push、创建或更新 PR；"
                "不得把多个 work item 混到同一条 branch、同一个 worktree 或同一个 PR 中。"
            )
            lane_task = self.configured_task(
                task_key,
                agent_instance=lane_agent,
                context=context,
                output_file=output_file,
                name=f"{lane_node_name}_task",
                async_execution=(
                    async_lanes
                    and (
                        base_node_name in {"backend_node", "frontend_node"}
                        or self.bootstrap_fast_track_enabled()
                    )
                ),
                description_suffix=lane_description,
            )
            if base_node_name == "backend_node":
                backend_tasks.append(lane_task)
            elif base_node_name == "frontend_node":
                frontend_tasks.append(lane_task)
            else:
                tester_tasks.append(lane_task)

        node_execution_tasks = [*backend_tasks, *frontend_tasks, *tester_tasks]

        pr_drafting_task = self.configured_task(
            "pr_drafting_task",
            agent_instance=developer_worker,
            context=[master_dispatch_task, *node_execution_tasks],
            name="pr_drafting_task",
        )
        execution_summary_task = self.configured_task(
            "execution_summary_task",
            agent_instance=developer_worker,
            context=node_execution_tasks,
            name="execution_summary_task",
        )
        github_automation_task = self.configured_task(
            "github_automation_task",
            agent_instance=developer_worker,
            context=[
                master_dispatch_task,
                *node_execution_tasks,
                pr_drafting_task,
                execution_summary_task,
            ],
            name="github_automation_task",
        )

        reviewer_context = [
            master_intake_task,
            master_dispatch_task,
            *node_execution_tasks,
            execution_summary_task,
        ]
        if not self.bootstrap_fast_track_enabled():
            reviewer_context.extend([pr_drafting_task, github_automation_task])
        reviewer_audit_task = self.configured_task(
            "reviewer_audit_task",
            agent_instance=reviewer_worker,
            context=reviewer_context,
            name="reviewer_audit_task",
        )

        master_decision_context = [
            master_intake_task,
            master_dispatch_task,
            *node_execution_tasks,
            execution_summary_task,
            reviewer_audit_task,
        ]
        if not self.bootstrap_fast_track_enabled():
            master_decision_context.extend([pr_drafting_task, github_automation_task])
        master_decision_task = self.configured_task(
            "master_decision_task",
            agent_instance=master_controller,
            context=master_decision_context,
            name="master_decision_task",
        )

        if self.bootstrap_fast_track_enabled() or self.direct_dispatch_enabled():
            tasks = [
                master_intake_task,
                master_dispatch_task,
                *node_execution_tasks,
                execution_summary_task,
                reviewer_audit_task,
                master_decision_task,
            ]
        else:
            tasks = [
                repo_analysis_task,
                module_boundary_task,
                issue_drafting_task,
                workspace_plan_task,
                master_intake_task,
                master_dispatch_task,
                *node_execution_tasks,
                pr_drafting_task,
                execution_summary_task,
                github_automation_task,
                reviewer_audit_task,
                master_decision_task,
            ]

        agents = [
            master_controller,
            repo_analyst,
            task_planner,
            issue_writer,
            developer_worker,
            reviewer_worker,
            *execution_lane_agents,
        ]

        return Crew(
            agents=agents,
            tasks=tasks,
            process=process,
            manager_agent=manager_agent,
            planning=planning_enabled,
            planning_llm=self.shared_llm() if planning_enabled else None,
            output_log_file=output_log_file,
            verbose=True,
        )
