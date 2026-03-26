from pathlib import Path
from typing import Type

from crewai.tools import BaseTool
from pydantic import BaseModel, Field

from multi_dev.tools.git_github_tools import target_repository_root


def template_root() -> Path:
    return Path(__file__).resolve().parents[1] / "templates" / "cicd"


def read_template(name: str) -> str:
    return (template_root() / name).read_text(encoding="utf-8")


def apply_replacements(content: str, replacements: dict[str, str]) -> str:
    rendered = content
    for key, value in replacements.items():
        rendered = rendered.replace(key, value)
    return rendered


class ScaffoldThinCICDWorkflowsInput(BaseModel):
    template_repo: str = Field(
        ...,
        description="中心模板仓库，例如 `owner/multi_dev`。",
    )
    template_ref: str = Field(
        default="main",
        description="模板仓库引用分支或 tag。",
    )
    python_version: str = Field(default="3.12", description="Python 版本。")
    node_version: str = Field(default="20", description="Node.js 版本。")
    backend_install_command: str = Field(
        default="uv sync --extra dev",
        description="后端依赖安装命令。",
    )
    backend_test_command: str = Field(
        default="uv run pytest -q",
        description="CI 后端检查命令。",
    )
    backend_verify_command: str = Field(
        default="uv run pytest -q",
        description="Deploy 前后端校验命令。",
    )
    frontend_workdir: str = Field(
        default="frontend",
        description="前端目录；无前端时传空字符串。",
    )
    frontend_install_command: str = Field(
        default="npm install",
        description="前端安装命令。",
    )
    frontend_build_command: str = Field(
        default="npm run build",
        description="前端构建命令。",
    )
    remote_deploy_command: str = Field(
        default="bash scripts/deploy.sh",
        description="远端部署命令。",
    )


class ScaffoldThinCICDWorkflowsTool(BaseTool):
    name: str = "scaffold_thin_cicd_workflows"
    description: str = (
        "在目标项目中生成两个超薄 GitHub Actions workflow，"
        "统一引用 multi_dev 中央模板仓库的 reusable workflows。"
    )
    args_schema: Type[BaseModel] = ScaffoldThinCICDWorkflowsInput

    def _run(
        self,
        template_repo: str,
        template_ref: str = "main",
        python_version: str = "3.12",
        node_version: str = "20",
        backend_install_command: str = "uv sync --extra dev",
        backend_test_command: str = "uv run pytest -q",
        backend_verify_command: str = "uv run pytest -q",
        frontend_workdir: str = "frontend",
        frontend_install_command: str = "npm install",
        frontend_build_command: str = "npm run build",
        remote_deploy_command: str = "bash scripts/deploy.sh",
    ) -> str:
        root = target_repository_root()
        workflows_dir = root / ".github" / "workflows"
        workflows_dir.mkdir(parents=True, exist_ok=True)

        replacements = {
            "__TEMPLATE_REPO__": template_repo,
            "__TEMPLATE_REF__": template_ref,
            "__PYTHON_VERSION__": python_version,
            "__NODE_VERSION__": node_version,
            "__BACKEND_INSTALL_COMMAND__": backend_install_command,
            "__BACKEND_TEST_COMMAND__": backend_test_command,
            "__BACKEND_VERIFY_COMMAND__": backend_verify_command,
            "__FRONTEND_WORKDIR__": frontend_workdir,
            "__FRONTEND_INSTALL_COMMAND__": frontend_install_command,
            "__FRONTEND_BUILD_COMMAND__": frontend_build_command,
            "__REMOTE_DEPLOY_COMMAND__": remote_deploy_command,
        }

        ci_path = workflows_dir / "ci.yml"
        deploy_path = workflows_dir / "deploy.yml"

        ci_path.write_text(
            apply_replacements(read_template("ci.thin.yml"), replacements),
            encoding="utf-8",
        )
        deploy_path.write_text(
            apply_replacements(read_template("deploy.thin.yml"), replacements),
            encoding="utf-8",
        )

        return (
            "已生成超薄 CI/CD workflows：\n"
            f"- {ci_path}\n"
            f"- {deploy_path}\n"
            f"- template_repo: {template_repo}\n"
            f"- template_ref: {template_ref}"
        )
