from typing import Literal

from pydantic import Field

from app.contracts.base import ContractModel


class ContextSummaryItem(ContractModel):
    text: str = Field(min_length=1, max_length=8_000)
    source_message_ids: tuple[int, ...] = ()
    importance: Literal["critical", "high", "normal"] = "normal"


class ConversationContextDigest(ContractModel):
    facts: tuple[ContextSummaryItem, ...] = ()
    user_constraints: tuple[ContextSummaryItem, ...] = ()
    decisions: tuple[ContextSummaryItem, ...] = ()
    open_items: tuple[ContextSummaryItem, ...] = ()
    tool_outcomes: tuple[ContextSummaryItem, ...] = ()
    errors_and_failed_attempts: tuple[ContextSummaryItem, ...] = ()
    files_and_resources: tuple[ContextSummaryItem, ...] = ()
    participants: tuple[ContextSummaryItem, ...] = ()
    continuity_notes: tuple[ContextSummaryItem, ...] = ()

    def referenced_message_ids(self) -> frozenset[int]:
        groups = (
            self.facts,
            self.user_constraints,
            self.decisions,
            self.open_items,
            self.tool_outcomes,
            self.errors_and_failed_attempts,
            self.files_and_resources,
            self.participants,
            self.continuity_notes,
        )
        return frozenset(
            item
            for group in groups
            for entry in group
            for item in entry.source_message_ids
        )

    def critical_message_ids(self) -> tuple[int, ...]:
        groups = (
            self.facts,
            self.user_constraints,
            self.decisions,
            self.open_items,
            self.tool_outcomes,
            self.errors_and_failed_attempts,
            self.files_and_resources,
            self.participants,
            self.continuity_notes,
        )
        return tuple(
            sorted(
                {
                    message_id
                    for group in groups
                    for entry in group
                    if entry.importance == "critical"
                    for message_id in entry.source_message_ids
                }
            )
        )
