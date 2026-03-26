import os

from crewai import Agent, Crew, LLM, Process, Task
from crewai.agents.agent_builder.base_agent import BaseAgent
from crewai.project import CrewBase, agent, crew, task
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
        default_max_tokens = "1000" if self.run_mode() == "fast" else "2200"
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

    def node_allowed_prefixes(self, env_name: str) -> tuple[str, ...]:
        raw_value = os.getenv(env_name, "").strip()
        if not raw_value:
            return ()
        return tuple(
            item.strip().strip("/")
            for item in raw_value.split(",")
            if item.strip()
        )

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
            tools=self.master_tools(),
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
        run_mode = self.run_mode()
        process = Process.sequential if run_mode == "fast" else Process.hierarchical
        manager_agent = None if run_mode == "fast" else self.master_manager()
        tasks = self.tasks
        if self.bootstrap_fast_track_enabled():
            tasks = [
                self.master_intake_task(),
                self.master_dispatch_task(),
                self.backend_node_task(),
                self.frontend_node_task(),
                self.tester_node_task(),
                self.execution_summary_task(),
                self.reviewer_audit_task(),
                self.master_decision_task(),
            ]

        return Crew(
            agents=self.agents,
            tasks=tasks,
            process=process,
            manager_agent=manager_agent,
            planning=planning_enabled,
            planning_llm=self.shared_llm() if planning_enabled else None,
            output_log_file=output_log_file,
            verbose=True,
        )
