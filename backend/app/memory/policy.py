from dataclasses import dataclass
from typing import Any, Literal

from pydantic import TypeAdapter

MemorySource = Literal["settings_ui", "explicit_user", "confirmed_candidate"]


@dataclass(frozen=True, slots=True)
class HardMemoryField:
    adapter: TypeAdapter[Any]
    writable_sources: frozenset[MemorySource]
    visible_to: frozenset[str]
    hard_constraint: bool = False


_ALL_SOURCES: frozenset[MemorySource] = frozenset(
    {"settings_ui", "explicit_user", "confirmed_candidate"}
)
_ALL_AGENTS = frozenset(
    {
        "scout",
        "researcher",
        "planner",
        "worker",
        "reviewer",
        "context-builder",
        "oracle",
        "delegate",
    }
)

HARD_MEMORY_FIELDS: dict[tuple[str, str], HardMemoryField] = {
    ("response", "language"): HardMemoryField(TypeAdapter(str), _ALL_SOURCES, _ALL_AGENTS),
    ("response", "verbosity"): HardMemoryField(TypeAdapter(str), _ALL_SOURCES, _ALL_AGENTS),
    ("coding", "preferred_languages"): HardMemoryField(
        TypeAdapter(tuple[str, ...]), _ALL_SOURCES, _ALL_AGENTS
    ),
    ("coding", "require_tests"): HardMemoryField(
        TypeAdapter(bool), _ALL_SOURCES, _ALL_AGENTS, hard_constraint=True
    ),
    ("coding", "comment_style"): HardMemoryField(TypeAdapter(str), _ALL_SOURCES, _ALL_AGENTS),
    ("security", "forbidden_operations"): HardMemoryField(
        TypeAdapter(tuple[str, ...]), _ALL_SOURCES, _ALL_AGENTS, hard_constraint=True
    ),
    ("execution", "require_confirmation"): HardMemoryField(
        TypeAdapter(bool), _ALL_SOURCES, _ALL_AGENTS, hard_constraint=True
    ),
}


def validate_hard_memory_value(
    namespace: str,
    key: str,
    value: Any,
    source: MemorySource,
) -> tuple[Any, str]:
    try:
        field = HARD_MEMORY_FIELDS[(namespace, key)]
    except KeyError as error:
        raise ValueError(f"unregistered hard memory field: {namespace}.{key}") from error
    if source not in field.writable_sources:
        raise ValueError(f"source {source} cannot write {namespace}.{key}")
    validated = field.adapter.validate_python(value)
    return validated, field.adapter.core_schema.get("type", type(validated).__name__)
