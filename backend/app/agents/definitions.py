from pathlib import Path

from pydantic import BaseModel

from app.config import Settings
from app.contracts.agents import AgentProposal, DesignFeedback, ReviewFeedback, VerificationReport
from app.contracts.execution import ExecutionPlan
from app.harness.registry import AgentDefinition, AgentRegistry


def build_agent_registry(settings: Settings, prompts_root: Path) -> AgentRegistry:
    def definition(
        agent_id: str,
        role: str,
        prompt: str,
        output_model: type[BaseModel],
        model: str,
        *,
        display_name: str,
        description: str,
        capabilities: frozenset[str],
        mention_aliases: tuple[str, ...],
        routing_keywords: tuple[str, ...],
        allowed_tools: frozenset[str] = frozenset(),
        can_request_execution: bool = False,
        stage_prompts: dict[str, str] | None = None,
        stage_output_models: dict[str, type[BaseModel]] | None = None,
    ) -> AgentDefinition:
        return AgentDefinition(
            agent_id=agent_id,
            role=role,
            model=model,
            prompt_path=prompts_root / prompt,
            prompt_version="v1",
            schema_version="v1",
            output_model=output_model,
            allowed_tools=allowed_tools,
            timeout_seconds=settings.model_timeout_seconds,
            max_retries=2,
            display_name=display_name,
            description=description,
            capabilities=capabilities,
            mention_aliases=mention_aliases,
            routing_keywords=routing_keywords,
            can_request_execution=can_request_execution,
            stage_prompts={stage: prompts_root / path for stage, path in stage_prompts.items()}
            if stage_prompts
            else None,
            stage_output_models=stage_output_models,
        )

    return AgentRegistry(
        (
            definition(
                "architect",
                "software architecture, execution planning, and replanning",
                "architect/v1.txt",
                AgentProposal,
                settings.agent_model("architect"),
                display_name="Architect",
                description="负责需求分析、架构设计、实现规划和重规划。",
                capabilities=frozenset({"architecture", "planning", "backend"}),
                mention_aliases=("架构师",),
                routing_keywords=("架构", "后端", "数据库", "性能", "接口", "规划", "实现计划"),
                allowed_tools=frozenset(
                    {"mcp.context7.resolve-library-id", "mcp.context7.query-docs"}
                ),
                can_request_execution=True,
                stage_prompts={
                    "planning": "architect/planner-v1.txt",
                    "replanning": "architect/planner-v1.txt",
                },
                stage_output_models={
                    "planning": ExecutionPlan,
                    "replanning": ExecutionPlan,
                },
            ),
            definition(
                "reviewer",
                "code review, test strategy, and independent verification",
                "reviewer/v1.txt",
                ReviewFeedback,
                settings.agent_model("reviewer"),
                display_name="Reviewer",
                description="负责批判性审查、测试、安全、风险识别和验证。",
                capabilities=frozenset({"review", "testing", "security", "verification"}),
                mention_aliases=("审查员",),
                routing_keywords=("审查", "错误", "bug", "安全", "测试", "验证", "风险"),
                allowed_tools=frozenset(
                    {"mcp.context7.resolve-library-id", "mcp.context7.query-docs"}
                ),
                stage_prompts={"verification": "verifier/v1.txt"},
                stage_output_models={"verification": VerificationReport},
            ),
            definition(
                "designer",
                "creative direction and interface design",
                "designer/v1.txt",
                DesignFeedback,
                settings.agent_model("designer"),
                display_name="Designer",
                description="负责前端体验、交互、布局和视觉设计。",
                capabilities=frozenset({"design", "frontend", "ux"}),
                mention_aliases=("设计师",),
                routing_keywords=(
                    "页面",
                    "组件",
                    "交互",
                    "布局",
                    "样式",
                    "视觉",
                    "用户体验",
                    "ui",
                    "ux",
                ),
                allowed_tools=frozenset(
                    {
                        "mcp.context7.resolve-library-id",
                        "mcp.context7.query-docs",
                        "mcp.playwright.playwright_get_visible_text",
                        "mcp.playwright.playwright_get_visible_html",
                        "mcp.playwright.playwright_console_logs",
                    }
                ),
            ),
        )
    )
