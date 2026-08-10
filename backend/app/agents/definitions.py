from pathlib import Path

from pydantic import BaseModel

from app.config import AgentId, Settings
from app.contracts.agents import ChatAgentReply, VerificationReport
from app.harness.registry import AgentDefinition, AgentRegistry


def build_agent_registry(settings: Settings, prompts_root: Path) -> AgentRegistry:
    docs_tools = frozenset({"mcp.context7.resolve-library-id", "mcp.context7.query-docs"})
    delegation_tools = frozenset({"subagent"})
    supervisor_tools = frozenset({"contact_supervisor", "subagent_supervisor"})
    workspace_tools = settings.mention_execution_tool_set
    read_workspace_tools = frozenset(
        {
            "list_workspace_files",
            "read_workspace_file",
            "search_workspace_files",
            "run_allowlisted_check",
        }
    ) & workspace_tools

    def definition(
        agent_id: AgentId,
        role: str,
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
            model=settings.agent_model(agent_id),
            prompt_path=prompts_root / "subagents" / f"{agent_id}.txt",
            # v3 aligns the role prompts with the pi-subagents builtin contracts.
            prompt_version="v3",
            schema_version="v2",
            output_model=ChatAgentReply,
            allowed_tools=allowed_tools | supervisor_tools,
            timeout_seconds=settings.model_timeout_seconds,
            max_retries=2,
            display_name=display_name,
            description=description,
            capabilities=capabilities,
            mention_aliases=mention_aliases,
            routing_keywords=routing_keywords,
            can_request_execution=can_request_execution,
            stage_prompts={
                stage: prompts_root / "subagents" / path
                for stage, path in (stage_prompts or {}).items()
            }
            or None,
            stage_output_models=stage_output_models,
        )

    return AgentRegistry(
        (
            definition(
                "supervisor",
                "root agent orchestration and final synthesis",
                display_name="Supervisor",
                description=(
                    "Own the user request, delegate bounded work, and synthesize the final answer."
                ),
                capabilities=frozenset({"orchestration", "delegation", "synthesis"}),
                mention_aliases=("supervisor",),
                routing_keywords=(),
                allowed_tools=workspace_tools | docs_tools | delegation_tools,
            ),
            definition(
                "scout",
                "fast local codebase reconnaissance",
                display_name="Scout",
                description="Locate relevant files, entry points, data flow, and risks.",
                capabilities=frozenset({"codebase", "recon", "analysis"}),
                allowed_tools=read_workspace_tools,
                mention_aliases=("侦察", "代码侦察"),
                routing_keywords=("代码库", "调用链", "入口", "定位", "scout", "recon"),
            ),
            definition(
                "researcher",
                "external documentation and evidence research",
                display_name="Researcher",
                description=(
                    "Research official documentation and current external facts with sources."
                ),
                capabilities=frozenset({"research", "documentation", "standards"}),
                mention_aliases=("研究员", "资料研究"),
                routing_keywords=("官方文档", "最新", "主流", "规范", "版本", "research", "docs"),
                allowed_tools=docs_tools | read_workspace_tools,
            ),
            definition(
                "worker",
                "implementation and validation",
                display_name="Worker",
                description="Implement approved work, validate it, and report evidence.",
                capabilities=frozenset({"implementation", "coding", "execution"}),
                mention_aliases=("执行者", "开发者"),
                routing_keywords=(
                    "实现",
                    "修改",
                    "修复",
                    "编写",
                    "执行",
                    "worker",
                    "implement",
                    "fix",
                ),
                allowed_tools=workspace_tools | docs_tools,
                can_request_execution=True,
            ),
            definition(
                "reviewer",
                "independent review, testing, and verification",
                display_name="Reviewer",
                description="Review plans and changes for correctness, tests, risk, and scope.",
                capabilities=frozenset({"review", "testing", "security", "verification"}),
                mention_aliases=("审查员", "评审"),
                routing_keywords=("审查", "评审", "测试", "安全", "风险", "review", "test", "bug"),
                allowed_tools=docs_tools | read_workspace_tools,
                stage_prompts={"verification": "verifier.txt"},
                stage_output_models={"verification": VerificationReport},
            ),
            definition(
                "oracle",
                "adversarial second opinion before action",
                display_name="Oracle",
                description=(
                    "Challenge assumptions and recommend the safest next move without editing."
                ),
                capabilities=frozenset({"second-opinion", "decision", "risk"}),
                mention_aliases=("顾问", "第二意见"),
                routing_keywords=(
                    "第二意见",
                    "是否合理",
                    "挑战",
                    "决策",
                    "权衡",
                    "oracle",
                    "opinion",
                ),
                allowed_tools=docs_tools | read_workspace_tools,
            ),
            definition(
                "delegate",
                "general-purpose bounded delegation",
                display_name="Delegate",
                description=(
                    "Handle a clearly scoped task that does not require a specialized profile."
                ),
                capabilities=frozenset({"general", "analysis", "delegation"}),
                mention_aliases=("委派", "助手"),
                routing_keywords=("委派", "独立处理", "帮忙", "delegate"),
                allowed_tools=docs_tools | read_workspace_tools,
            ),
        )
    )
