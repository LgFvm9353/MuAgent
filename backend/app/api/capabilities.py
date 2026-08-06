from typing import Any

from fastapi import APIRouter, Request

router = APIRouter(tags=["capabilities"])


@router.get("/skills")
async def list_skills(request: Request) -> list[dict[str, Any]]:
    registry = request.app.state.skill_registry
    skills: list[dict[str, Any]] = []
    for definition in request.app.state.coordinator.agent_registry.all():
        agent_id = definition.agent_id
        for skill in registry.list_for_agent(agent_id):
            if any(item["id"] == skill.id for item in skills):
                continue
            skills.append(
                {
                    "id": skill.id,
                    "version": skill.manifest.version,
                    "description": skill.manifest.description,
                    "allowed_agents": sorted(skill.manifest.allowed_agents),
                    "allowed_tools": sorted(skill.manifest.allowed_tools),
                    "content_hash": skill.content_hash,
                }
            )
    return sorted(skills, key=lambda item: item["id"])


@router.get("/mcp/servers")
async def list_mcp_servers(request: Request) -> list[dict[str, Any]]:
    manager = request.app.state.mcp_manager
    return [dict(status) for status in manager.statuses()]
