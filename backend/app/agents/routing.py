import re
from dataclasses import dataclass
from typing import Literal

from app.contracts.collaboration import CollaborationMode
from app.harness.registry import AgentRegistry

RouteSource = Literal["explicit", "rule", "fallback"]
_MENTION = re.compile(r"(?<![\w@])@([\w-]+)", re.UNICODE)
_SIDE_EFFECT_PATTERNS = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"(?:修改|编辑|写入|创建|删除|覆盖).{0,12}(?:文件|代码|配置|数据库)",
        r"(?:运行|执行).{0,8}(?:命令|脚本|测试|部署|迁移)",
        r"(?:commit|push|deploy|delete|remove|write|execute|run)\b",
    )
)


@dataclass(frozen=True, slots=True)
class RouteDecision:
    agent_ids: tuple[str, ...]
    mode: CollaborationMode
    source: RouteSource
    confidence: float
    reason_code: str
    mentions: tuple[str, ...]
    requires_execution: bool


class AgentRouter:
    def __init__(self, registry: AgentRegistry, max_auto_agents: int = 2) -> None:
        if max_auto_agents < 1:
            raise ValueError("max_auto_agents must be positive")
        self._registry = registry
        self._max_auto_agents = max_auto_agents

    def route(self, text: str) -> RouteDecision:
        mentions = self.parse_mentions(text)
        if mentions:
            return RouteDecision(
                agent_ids=mentions,
                mode=CollaborationMode.PARALLEL if len(mentions) > 1 else CollaborationMode.SINGLE,
                source="explicit",
                confidence=1.0,
                reason_code="explicit_mentions",
                mentions=mentions,
                requires_execution=self.requires_execution(text),
            )

        normalized = text.casefold()
        scored: list[tuple[int, int, str]] = []
        for order, definition in enumerate(self._registry.all()):
            score = sum(
                normalized.count(keyword.casefold()) for keyword in definition.routing_keywords
            )
            if score:
                scored.append((score, -order, definition.agent_id))
        scored.sort(reverse=True)
        selected = tuple(item[2] for item in scored[: self._max_auto_agents])
        if selected:
            return RouteDecision(
                agent_ids=selected,
                mode=CollaborationMode.PARALLEL if len(selected) > 1 else CollaborationMode.SINGLE,
                source="rule",
                confidence=min(0.95, 0.65 + scored[0][0] * 0.1),
                reason_code="keyword_capability_match",
                mentions=(),
                requires_execution=self.requires_execution(text),
            )

        return RouteDecision(
            agent_ids=(self._registry.get("delegate").agent_id,),
            mode=CollaborationMode.SINGLE,
            source="fallback",
            confidence=0.4,
            reason_code="default_delegate",
            mentions=(),
            requires_execution=self.requires_execution(text),
        )

    def parse_mentions(self, text: str) -> tuple[str, ...]:
        resolved: list[str] = []
        seen: set[str] = set()
        for match in _MENTION.finditer(text):
            definition = self._registry.resolve_mention(match.group(1))
            if definition is None or definition.agent_id in seen:
                continue
            seen.add(definition.agent_id)
            resolved.append(definition.agent_id)
        return tuple(resolved)

    @staticmethod
    def requires_execution(text: str) -> bool:
        return any(pattern.search(text) is not None for pattern in _SIDE_EFFECT_PATTERNS)
