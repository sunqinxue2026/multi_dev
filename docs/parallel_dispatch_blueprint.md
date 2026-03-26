# 多 Node 并行调度蓝图（第一版）

## 1. 目标

当前 `multi_dev` 已具备单 `master`、单 `backend_node`、单 `frontend_node`、单 `tester_node`、单 `reviewer` 的基础链路。下一阶段目标不是改成“更多 agent 名字”，而是把系统升级为：

- 单入口：仍然只和 `master` 交互
- 多执行者：允许多个后端 / 前端 / 测试 node 并行工作
- 真隔离：每个 node 绑定自己的 `issue ↔ branch ↔ worktree ↔ PR`
- 真审查：`reviewer` 负责审查，`master` 决定 `MERGE / REWORK / CONTINUE_DISPATCH`
- 真落盘：`write` 模式下必须优先写代码，不能只停在文档阶段

## 2. 当前基线

从现有实现可以确认：

- `master` 已能调用 GitHub/Git 工具与文件工具
- node 已能准备 branch、worktree、commit、push、创建/更新 PR
- `reviewer` 已能读取 GitHub 状态并查看 diff 摘要
- 写权限目前仍以 `backend_node`、`frontend_node`、`tester_node` 三类静态角色为中心
- `outputs/github_state.json` 与 `outputs/node_workspaces.json` 已承担第一版运行态落盘职责

这意味着第二版无需推倒重来，而是要把“单节点角色”升级为“节点池 + 工作项状态机”。

## 3. 目标架构

### 3.1 角色层

- `master`
  - 接收用户一句话需求
  - 拆出可执行工作项
  - 为工作项选择 node 类型与依赖顺序
  - 决定 `MERGE / REWORK / CONTINUE_DISPATCH`
- `reviewer`
  - 审查 PR、diff、测试结果、状态机一致性
  - 输出 `COMMENT / REQUEST_CHANGES / approve suggestion`
  - 不直接拍板 merge
- `backend_pool`
  - 例如：`backend_node_catalog`、`backend_node_order`
- `frontend_pool`
  - 例如：`frontend_node_catalog`、`frontend_node_cart`
- `tester_pool`
  - 例如：`tester_node_api`、`tester_node_e2e`

### 3.2 数据层

建议把运行态从“按 node 记一份工作区”升级为“按工作项持久化”：

- `dispatch_round`
  - 一轮 master 派单的总上下文
- `work_item`
  - 一个可执行子任务
- `node_assignment`
  - 某个 work item 当前分配给哪个 node
- `workspace_binding`
  - 某个 node 的 branch/worktree 绑定
- `pr_binding`
  - work item 对应的 PR 状态
- `ownership_rule`
  - work item 可修改路径列表

## 4. 核心状态机

### 4.1 `work_item` 状态机

```text
DRAFT
  -> READY
  -> DISPATCHED
  -> IN_PROGRESS
  -> IN_REVIEW
  -> APPROVED
  -> MERGED

DISPATCHED / IN_PROGRESS / IN_REVIEW
  -> REWORK_REQUIRED
  -> REDISPATCHED
  -> IN_PROGRESS
```

建议定义：

- `DRAFT`
  - master 刚拆出来，尚未满足执行前置条件
- `READY`
  - 依赖满足，可派发
- `DISPATCHED`
  - 已绑定 node，但 node 尚未开始写
- `IN_PROGRESS`
  - 已创建 worktree 且出现真实写入/commit
- `IN_REVIEW`
  - PR 已创建或已更新，等待 reviewer/master
- `APPROVED`
  - 审查通过，可进入 merge 阶段
- `MERGED`
  - 已合入主线
- `REWORK_REQUIRED`
  - 被 reviewer 或 master 打回，必须继续改
- `REDISPATCHED`
  - 已重新绑定 node 或重新进入同一 node 的下一次执行

### 4.2 `issue ↔ node ↔ branch ↔ worktree ↔ PR` 映射

每个 `work_item` 必须唯一对应：

- 1 个 GitHub issue
- 1 个主责任 node
- 1 条 branch
- 1 个 worktree
- 1 个当前活动 PR

允许：

- 一个需求拆成多个 `work_item`
- 一个 node 在不同轮次处理多个 `work_item`

不允许：

- 多个活跃 `work_item` 共用同一个 branch
- 多个 node 同时写同一个 worktree
- 没有真实写入却把状态推进到 `IN_REVIEW`

## 5. Ownership 规则

并行版最关键的不是“多几个 agent”，而是“谁能改哪些文件”。

### 5.1 Ownership 设计原则

- 以 `work_item.targets[]` 为第一准绳
- 以 node 类型默认前缀为第二准绳
- `master` 可以在单轮 dispatch 中临时扩权
- `reviewer` 发现越界路径时可直接判定 `REWORK`

### 5.2 路径授权建议

- 后端类 work item
  - 允许：`src/`、`backend/`、`app/` 下经 master 批准的子路径
- 前端类 work item
  - 允许：`frontend/`、`web/`、`ui/` 下经 master 批准的子路径
- 测试类 work item
  - 允许：`tests/`、项目内测试配置、经 master 明确批准的 README/工作流文件

### 5.3 冲突处理

若两个 work item 目标路径重叠：

- 优先由 `master` 在派单前拆分成更细的 ownership
- 若无法拆开，则标记为有依赖关系，不进入并行
- reviewer 发现跨 work item 改动重叠时，可要求其中一个 PR 回退重提

## 6. 新项目与已有项目的调度差异

### 6.1 新项目 + `write` 模式

必须优先进入最小落盘路径：

1. `master` 判断为 bootstrap 场景
2. 快速生成最小执行单
3. 至少一个 node 先完成真实写入
4. 若本轮无真实写入，则 `master` 直接判定 `REWORK`

在该模式下：

- 禁止过长的前置分析链
- 禁止 node 未经批准自行发明技术栈
- 技术栈、目录、框架应来自：
  - 用户明确要求
  - `master` 在模板中的明确批准
  - 仓库中已有事实

### 6.2 已有项目迭代

已有仓库时，master 可以更依赖：

- 现有目录结构
- 真实文件引用关系
- 既有 issue / PR / CI 状态

但依然必须遵守：

- 未见文件不能当事实
- 未批准路径不能写
- 未真实写入不能假装进入开发完成阶段

## 7. Reviewer 与 Master 的职责边界

### 7.1 Reviewer

负责判断：

- 是否越界修改
- 是否与 work item 的 targets 不一致
- 是否存在无真实写入却宣称完成
- 是否存在 PR 描述与真实 diff 不一致
- 是否满足最基本测试或验证要求

输出建议状态：

- `COMMENT`
- `REQUEST_CHANGES`
- `APPROVE_SUGGESTION`

### 7.2 Master

负责最终决策：

- `MERGE`
  - reviewer 无阻塞问题，且依赖链满足
- `REWORK`
  - 任意关键路径失败、越界、无真实写入、状态机不一致
- `CONTINUE_DISPATCH`
  - 当前结果可接受，但仍需派发后续 work item

## 8. 建议新增的运行态文件

以下均为拟新增：

- `outputs/dispatch_rounds.json`
  - 记录每一轮 dispatch 摘要
- `outputs/work_items.json`
  - 记录 work item 状态机、依赖、targets、当前 node
- `outputs/pr_bindings.json`
  - 记录 issue / branch / worktree / PR 对应关系
- `outputs/ownership_rules.json`
  - 记录每个 work item 当前生效的路径授权

现有文件继续保留并逐步收敛职责：

- `outputs/github_state.json`
- `outputs/node_workspaces.json`
- `outputs/execution_log.jsonl`

## 9. 建议新增的代码挂载点

以下均为拟新增：

- `src/multi_dev/models/dispatch.py`
  - `DispatchRound`、`WorkItem`、`PRBinding`、`OwnershipRule`
- `src/multi_dev/services/dispatch_state.py`
  - 负责读写 `outputs/*.json`
- `src/multi_dev/services/work_item_planner.py`
  - 把需求拆成可并行 work item
- `src/multi_dev/services/ownership.py`
  - 统一判断路径是否越界
- `src/multi_dev/services/dependency_graph.py`
  - 计算哪些 work item 可并行、哪些必须串行
- `src/multi_dev/tools/dispatch_state_tools.py`
  - 暴露给 master/reviewer 的状态查询与更新工具

## 10. 实现顺序建议

### Phase 1：先把状态机立住

- 引入 `work_item` 结构
- 引入 `dispatch_round`
- 用文件落盘状态，而不是只靠 markdown

### Phase 2：把单节点角色升级成节点池

- `backend_node` -> `backend_pool[*]`
- `frontend_node` -> `frontend_pool[*]`
- `tester_node` -> `tester_pool[*]`

这里不一定要求先生成真实多个 Agent 方法，也可以先让 `master` 在派单合同中显式声明逻辑 node id，例如：

- `backend_node.catalog`
- `backend_node.order`
- `frontend_node.catalog`

### Phase 3：把 ownership 真接到写工具

- `write_repo_file`
- `replace_repo_text`
- `make_repo_directory`

都应同时校验：

- node 类型允许范围
- work item 批准 targets
- 当前 dispatch round 的 ownership 规则

### Phase 4：把 review/merge 决策挂到 work item 状态

- reviewer 的输出更新 `work_items.json`
- master 的 merge/rework/continue 也更新同一状态机
- 所有 GitHub 动作都反写状态文件

## 11. 第一版并行规模建议

不要一开始就做无限并行，建议先支持：

- 2 个后端 node
- 2 个前端 node
- 1 个 tester node
- 1 个 reviewer

这已经足够验证：

- 并行派单
- branch/worktree 隔离
- ownership 防踩踏
- reviewer 打回
- master 合流

## 12. 验收标准

并行版第一阶段完成时，应至少满足：

- 用户仍然只需要对 `master` 说一句需求
- `master` 能拆出多个 work item
- 每个 work item 都有独立的 issue / branch / worktree / PR 绑定
- node 在 `write` 模式下会真实写文件，而不是只产出文档
- reviewer 能按 work item 打回
- master 能针对单个 work item 做 `merge / rework / continue`
- 任意并行 node 越界写路径会被工具层拦截或被 reviewer 打回

## 13. 推荐下一步

下一步不要直接大改全部 agent prompt，建议先做最小闭环：

1. 增加 `work_items.json` 与 `dispatch_rounds.json`
2. 让 `master_dispatch.md` 同时输出结构化 work item JSON
3. 让 `GitPrepareWorkspaceTool` 支持按 `work_item_id` 创建 branch/worktree
4. 让写工具读取 `work_item_id -> ownership`
5. 只挑一个真实项目跑“两后端 + 一前端 + 一测试”的 smoke run

这样我们可以先把“并行调度骨架”跑通，再逐步扩成通用多节点池。
