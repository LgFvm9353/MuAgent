import re
from dataclasses import dataclass

from app.contracts.agents import AgentHandoff, HandoffIntent
from app.harness.registry import AgentRegistry

_ACTION_MENTION = re.compile(
    r"^\s*@(?P<alias>[\w\-一-鿿]+)(?:\s+|[：:])(?P<objective>\S.*)$"  # noqa: RUF001
)
_INTENT_PREFIXES: tuple[tuple[HandoffIntent, tuple[str, ...]], ...] = (
    ("review", ("请审查", "审查", "review")),
    ("revise", ("请修订", "修订", "revise")),
    ("question", ("请回答", "回答", "请确认", "确认", "question")),
    ("execute", ("请执行", "执行", "execute")),
    ("done_notify", ("已完成", "完成通知", "done")),
)


@dataclass(frozen=True, slots=True)
class MentionRejection:
    line_number: int
    alias: str
    reason: str


@dataclass(frozen=True, slots=True)
class MentionParseResult:
    handoffs: tuple[AgentHandoff, ...]
    rejections: tuple[MentionRejection, ...]


def parse_action_mentions(
    text: str,
    *,
    registry: AgentRegistry,
    source_agent_id: str,
) -> MentionParseResult:
    """Parse actionable line-leading mentions from a completed agent response."""
    source = registry.get(source_agent_id)
    handoffs: list[AgentHandoff] = []
    rejections: list[MentionRejection] = []
    seen_targets: set[str] = set()

    for line_number, line in enumerate(text.splitlines(), start=1):
        match = _ACTION_MENTION.match(line)
        if match is None:
            continue
        alias = match.group("alias")
        target = registry.resolve_mention(alias)
        if target is None:
            rejections.append(MentionRejection(line_number, alias, "unknown_target"))
            continue
        if target.agent_id == source.agent_id:
            rejections.append(MentionRejection(line_number, alias, "self_mention"))
            continue
        if target.agent_id in seen_targets:
            rejections.append(MentionRejection(line_number, alias, "duplicate_target"))
            continue
        if len(handoffs) >= source.max_handoff_targets:
            rejections.append(MentionRejection(line_number, alias, "target_limit_exceeded"))
            continue

        objective = match.group("objective").strip()
        intent = _infer_intent(objective)
        try:
            registry.validate_handoff(source.agent_id, target.agent_id, intent)
        except ValueError:
            rejections.append(MentionRejection(line_number, alias, "handoff_not_allowed"))
            continue

        seen_targets.add(target.agent_id)
        handoffs.append(
            AgentHandoff(
                target_agent_id=target.agent_id,
                intent=intent,
                objective=objective,
            )
        )

    return MentionParseResult(tuple(handoffs), tuple(rejections))


def _infer_intent(objective: str) -> HandoffIntent:
    normalized = objective.casefold()
    for intent, prefixes in _INTENT_PREFIXES:
        if any(normalized.startswith(prefix.casefold()) for prefix in prefixes):
            return intent
    return "delegate"
