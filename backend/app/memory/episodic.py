import re
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.memory.contracts import EpisodicMemoryQuery, EpisodicMemoryResult
from app.memory.repositories import MemoryRepository

_TOKEN = re.compile(r"[A-Za-z_][A-Za-z0-9_.:/-]*|[一-鿿]{2,}")


class EpisodicMemoryService:
    def __init__(self, session: AsyncSession, *, minimum_score: float = 0.35) -> None:
        self._repository = MemoryRepository(session)
        self._minimum_score = minimum_score

    async def search(
        self, owner_id: str, query: EpisodicMemoryQuery
    ) -> tuple[EpisodicMemoryResult, ...]:
        candidates = await self._repository.episodic_candidates(
            owner_id=owner_id,
            scope_id=query.scope_id,
            memory_types=query.memory_types,
            facets=query.facets,
            limit=query.limit,
        )
        query_tokens = {token.casefold() for token in _TOKEN.findall(query.text)}
        requested_facets = {
            (kind, value.casefold()) for kind, values in query.facets.items() for value in values
        }
        ranked: list[EpisodicMemoryResult] = []
        now = datetime.now(UTC)
        for memory, facets in candidates:
            text_tokens = {
                token.casefold()
                for token in _TOKEN.findall(
                    " ".join(
                        (
                            memory.title,
                            memory.problem_text,
                            memory.resolution_text,
                            memory.search_text,
                        )
                    )
                )
            }
            token_score = len(query_tokens & text_tokens) / max(len(query_tokens), 1)
            facet_score = len(requested_facets & facets) / max(len(requested_facets), 1)
            scope_score = 1.0 if query.scope_id and memory.scope_id == query.scope_id else 0.5
            validation_score = min(memory.validation_count / 3, 1.0)
            age_days = max(
                0,
                (now - (memory.last_validated_at or memory.created_at).replace(tzinfo=UTC)).days,
            )
            recency_score = max(0.0, 1.0 - age_days / 365)
            contradiction_penalty = min(memory.contradiction_count * 0.2, 0.8)
            score = max(
                0.0,
                token_score * 0.30
                + facet_score * 0.25
                + scope_score * 0.20
                + validation_score * 0.15
                + recency_score * 0.10
                - contradiction_penalty,
            )
            if score < self._minimum_score:
                continue
            ranked.append(
                EpisodicMemoryResult(
                    id=memory.id,
                    memory_type=memory.memory_type,
                    title=memory.title,
                    problem=memory.problem_text,
                    resolution=memory.resolution_text,
                    applicability=memory.applicability,
                    score=round(score, 6),
                    score_breakdown={
                        "text": token_score,
                        "facet": facet_score,
                        "scope": scope_score,
                        "validation": validation_score,
                        "recency": recency_score,
                        "contradiction_penalty": contradiction_penalty,
                    },
                )
            )
        ranked.sort(key=lambda item: (-item.score, str(item.id)))
        return tuple(ranked[: query.limit])


def normalize_facet(value: str) -> str:
    return value.strip().replace("\\", "/").casefold()
