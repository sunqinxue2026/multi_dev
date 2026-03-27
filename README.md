# MultiDev Crew

Welcome to the MultiDev Crew project, powered by [crewAI](https://crewai.com). This template is designed to help you set up a multi-agent AI system with ease, leveraging the powerful and flexible framework provided by crewAI. Our goal is to enable your agents to collaborate effectively on complex tasks, maximizing their collective intelligence and capabilities.

## Installation

Ensure you have Python >=3.10 <3.14 installed on your system. This project uses [UV](https://docs.astral.sh/uv/) for dependency management and package handling, offering a seamless setup and execution experience.

First, if you haven't already, install uv:

```bash
pip install uv
```

Next, navigate to your project directory and install the dependencies:

(Optional) Lock the dependencies and install them by using the CLI command:
```bash
crewai install
```
### Customizing

**Add your LLM settings into the `.env` file**

You now have two supported paths:

- OpenAI / compatible gateway with key:
  - `OPENAI_API_KEY=...`
  - Optional: `OPENAI_MODEL_NAME=...`
  - Optional: `OPENAI_BASE_URL=...`
- Ollama or any OpenAI-compatible Ollama gateway:
  - `OPENAI_BASE_URL=https://ollama-api.office.ihousejapan.cn/v1`
  - `OPENAI_MODEL_NAME=qwen2.5:7b`
  - `OPENAI_API_KEY` can be omitted; the app will use a placeholder token internally when only a compatible base URL is provided.

- Modify `src/multi_dev/config/agents.yaml` to define your agents
- Modify `src/multi_dev/config/tasks.yaml` to define your tasks
- Modify `src/multi_dev/crew.py` to add your own logic, tools and specific args
- Modify `src/multi_dev/main.py` to add custom inputs for your agents and tasks

## Running the Project

To kickstart your crew of AI agents and begin task execution, run this from the root folder of your project:

```bash
$ crewai run
```

This command initializes the multi-dev Crew, assembles the agents, and writes stage outputs to markdown files so you can inspect the pipeline without scrolling through the terminal:

- `outputs/repo_analysis.md`
- `outputs/product_blueprint.md`
- `outputs/module_boundaries.md`
- `outputs/issues.md`
- `outputs/workspace_plan.md`
- `outputs/master_intake.md`
- `outputs/master_dispatch.md`
- `outputs/backend_node.md`
- `outputs/frontend_node.md`
- `outputs/tester_node.md`
- `outputs/node_lanes/*.md`（当同类 node 池大小大于 1 时）
- `outputs/pr_drafts.md`
- `outputs/execution_summary.md`
- `outputs/execution_log.jsonl`
- `outputs/github_state.json`
- `outputs/node_workspaces.json`
- `outputs/dispatch_rounds.json`
- `outputs/work_items.json`
- `outputs/pr_bindings.json`
- `outputs/ownership_rules.json`
- `outputs/github_automation.md`
- `outputs/reviewer_audit.md`
- `outputs/master_decision.md`

After each successful run, the CLI prints the generated artifact paths.

By default, generated markdown artifacts use `简体中文`. You can override this with the `OUTPUT_LANGUAGE` environment variable.

The prompts are grounded to the visible repository snapshot. New files or interfaces should be labeled as proposals rather than stated as existing facts.

Quick smoke tests are usually faster with `CREW_RUN_MODE=fast`. In fast mode, the crew uses sequential execution, disables planning, lowers the default token budget, and trims the repository snapshot before sending context to the model.

Set `CREW_EXECUTION_MODE=write` if you want backend/frontend/tester nodes to be allowed to modify the target repository through guarded file tools. The default is `plan`, which keeps the workflow in analysis-and-planning mode only.

For Ollama-compatible gateways, the simplest setup is:

```bash
OPENAI_BASE_URL=https://ollama-api.office.ihousejapan.cn/v1
OPENAI_MODEL_NAME=qwen2.5:7b
```

This project will treat that endpoint as an OpenAI-compatible backend and no longer hard-require `OPENAI_API_KEY` if a compatible base URL is present.

For stronger role isolation, you can also set comma-separated path scopes:

- `CREW_BACKEND_PATHS=web-flask,web-file`
- `CREW_FRONTEND_PATHS=web-vue`
- `CREW_TEST_PATHS=tests,web-flask`

When these are set, write tools reject edits outside the assigned prefixes.
In `write` mode, the latest `outputs/master_dispatch.md` also acts as a dynamic approval layer: if `master` explicitly approves concrete `targets` for a node in `dispatch_contract.work_items`, that node may write those paths during the current run even when they are outside its static env prefix. This lets `master` truly authorize one-round bootstrap targets such as `tests/` without permanently widening the node's scope.

## Mature Parallel Dispatch

`multi_dev` 现在已经进入可运行的并行执行形态，不再只是蓝图：

- `master` 在 `dispatch_contract.work_items` 中可以为同类 node 派发多个 work item
- 每个 work item 现在支持 `worker_lane`，用于把任务绑定到具体执行 lane，例如 `backend_node__1`
- backend / frontend lane 可以并行执行；tester lane 在依赖 backend/frontend 输出时会自动后置收口
- 每个 lane 都有自己独立的 worktree、branch、PR 绑定；运行态会持续写入：
  - `outputs/dispatch_rounds.json`
  - `outputs/work_items.json`
  - `outputs/pr_bindings.json`
  - `outputs/ownership_rules.json`

可通过环境变量控制同类 node 池大小：

```bash
CREW_BACKEND_POOL_SIZE=2
CREW_FRONTEND_POOL_SIZE=2
CREW_TESTER_POOL_SIZE=2
```

当需求文本明显属于零食/零售/购物场景时，如果你没有手动指定 lane 数量，框架会自动采用更激进的默认并行度：

- `CREW_BACKEND_POOL_SIZE=3`
- `CREW_FRONTEND_POOL_SIZE=3`
- `CREW_TESTER_POOL_SIZE=2`

这样 `master` 更容易把“商品发现 / 购物车结算 / 营销复购 / 质量验证”拆成多个可并行 work item。

如果 `master_dispatch.md` 漏写了 `worker_lane`，框架会在 `master_dispatch` 落盘后做一次正规化分配，避免多个 lane 抢同一个 work item。

## First-Version GitHub Integration

The project now includes a first pass of **real Git/GitHub execution tools** for the workflow you described:

- `master` can bootstrap a real GitHub repository and create real issues
- `node` can prepare its own branch + local worktree, write code in that worktree, commit and push
- `node` can create or update a real PR
- `reviewer` / `master` can inspect branch diff summaries and the persisted GitHub state
- `master` can submit native GitHub PR reviews (`COMMENT`, `APPROVE`, `REQUEST_CHANGES`)
- `master` can merge a real PR when the final decision is `MERGE`
- merged PR 对应的远端 branch 默认保留，便于用户查看 node 改动；只有明确要求时才删除

Required environment variables:

```bash
GITHUB_TOKEN=ghp_xxx
GITHUB_OWNER=your-user-or-org
# Optional
GITHUB_REPO=repo-name
GITHUB_BASE_BRANCH=main
GITHUB_REPO_VISIBILITY=private
```

Important implementation note:

- `gh` CLI is **not required**; the current first version uses the GitHub REST API directly.
- `git` **is required** locally for branch / worktree / commit / push.
- When `GITHUB_TOKEN` is present, git push/fetch to `github.com` uses the token at runtime; it does not require `gh auth login`.
- Node workspaces are stored under `outputs/worktrees/`, and are namespaced by target repository to avoid cross-run collisions.
- The live issue / branch / PR / workspace mapping is persisted to `outputs/github_state.json`.
- The local workspace registry used by file tools is persisted to `outputs/node_workspaces.json`.

## First-Version Real CI/CD

The project now includes a first pass of **real GitHub Actions CI/CD integration** on top of the Git/GitHub flow:

- `master` can sync deployment secrets into GitHub repository secrets before dispatching CI/CD work
- `node` can write real workflow files such as `.github/workflows/ci.yml` and `.github/workflows/deploy.yml`
- `node` can commit, push, and open PRs for CI/CD changes in its own branch + worktree
- `reviewer` / `master` can verify whether workflow files and repo secrets were actually configured

## Central CI/CD Templates

`multi_dev` 现在也可以作为统一 CI/CD 模板中心：

- 中心模板仓库提供 reusable workflows：
  - `.github/workflows/reusable_ci.yml`
  - `.github/workflows/reusable_deploy.yml`
- 新项目仓库只需生成两个超薄 workflow 文件：
  - `.github/workflows/ci.yml`
  - `.github/workflows/deploy.yml`
- 这两个超薄文件统一 `uses:` 中心模板，项目侧只保留项目自己的命令参数

建议配套环境变量：

```bash
CREW_CICD_TEMPLATE_REPO=your-owner/multi_dev
CREW_CICD_TEMPLATE_REF=main
```

当 `CREW_CICD_TEMPLATE_REPO` 已明确时，优先生成超薄 workflow，而不是在每个项目里重复写整套 CI/CD。

Recommended deployment environment variables:

```bash
DEPLOY_HOST=35.217.150.106
DEPLOY_PORT=22
DEPLOY_USER=service
DEPLOY_PATH=/srv/your-app
DEPLOY_SSH_PRIVATE_KEY="-----BEGIN OPENSSH PRIVATE KEY-----..."
# Optional
DEPLOY_SUDO_PASSWORD=...
DEPLOY_SERVICE_NAME=your-app
CREW_CICD_ENABLED=true
```

Implementation note:

- CI/CD secrets are uploaded through the GitHub Actions secrets API, not by writing plaintext into the repository.
- `DEPLOY_SSH_PRIVATE_KEY` should live in local env / `.env`, then be synced to GitHub by `master`; do not commit it.
- The synced secret names are tracked in `outputs/github_state.json` without storing their values.

## Master-Node Workflow

This project is now aligned to a single-entry `master/node` engineering workflow:

1. `master` receives the requirement
2. Internal specialists analyze the repo and boundaries
3. `master` creates an intake summary and dispatch order
4. `master` assigns work to backend / frontend / tester nodes
5. Nodes work inside their scoped paths and optionally modify code in `write` mode
6. `master` collects execution summaries and PR drafts
7. `reviewer` performs an internal audit for `master`
8. `master` makes the final decision: `MERGE`, `REWORK`, or `CONTINUE_DISPATCH`

Two important execution principles now apply:

- In `write` mode, approved bootstrap targets should be written first instead of being deferred out of caution.
- `reviewer` is expected to send incorrect or overreaching work back; `master` can then narrow the next round and re-dispatch specific nodes.

Important:

- This is no longer only a planning shell: with valid GitHub credentials, the first version can perform **real** repo / issue / branch / worktree / commit / push / PR / merge actions.
- It is still **not** a full remote runner platform yet: there are no isolated cloud runners, no automatic sandbox provisioning, and no production-grade permission model.

## Parallel Dispatch Blueprint

面向更进一步演进的“单 `master` + 多 backend / frontend / tester node 并行协作”设计蓝图已写入：

- `docs/parallel_dispatch_blueprint.md`

这份蓝图重点定义了：

- `work_item` 状态机
- `issue ↔ node ↔ branch ↔ worktree ↔ PR` 映射
- ownership / 路径授权规则
- 新项目 bootstrap 与已有项目迭代的并行调度差异
- 建议新增的运行态文件与代码挂载点

## Understanding Your Crew

The multi-dev Crew is composed of multiple AI agents, each with unique roles, goals, and tools. These agents collaborate on a series of tasks, defined in `config/tasks.yaml`, leveraging their collective skills to achieve complex objectives. The `config/agents.yaml` file outlines the capabilities and configurations of each agent in your crew.

## Support

For support, questions, or feedback regarding the MultiDev Crew or crewAI.
- Visit our [documentation](https://docs.crewai.com)
- Reach out to us through our [GitHub repository](https://github.com/joaomdmoura/crewai)
- [Join our Discord](https://discord.com/invite/X4JWnZnxPb)
- [Chat with our docs](https://chatg.pt/DWjSBZn)

Let's create wonders together with the power and simplicity of crewAI.
