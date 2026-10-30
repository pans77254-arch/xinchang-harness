from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ai.agents.skill_loader import list_skills, load_skill, read_skill_text, save_skill_text
from ai.workflow.runner import clear_cache, read_workflow_text, save_workflow_text

router = APIRouter()


class SkillTextBody(BaseModel):
    yaml: str = Field(min_length=1)
    workflow_yaml: str | None = None


class ReviseBody(BaseModel):
    text: str = Field(min_length=1)


@router.get("/skills")
def skills():
    return [
        {
            "id": s.get("id"),
            "name": s.get("name"),
            "pack": s.get("pack"),
            "enabled": s.get("enabled", True),
            "needs": s.get("needs") or [],
            "basis": " ".join(str(s.get("basis") or "").split()),
            "workflow": s.get("workflow") or s.get("id"),
        }
        for s in list_skills()
        if not str(s.get("id", "")).startswith("pack.example")
    ]


@router.get("/skills/{skill_id}")
def skill_detail(skill_id: str):
    text = read_skill_text(skill_id)
    if text is None:
        raise HTTPException(status_code=404, detail="没有这个审查点")
    skill = load_skill(skill_id) or {}
    workflow_id = str(skill.get("workflow") or skill_id)
    return {
        "id": skill_id,
        "yaml": text,
        "workflow_id": workflow_id,
        "workflow_yaml": read_workflow_text(workflow_id) or "",
    }


@router.post("/skills/{skill_id}/revise")
def skill_revise(skill_id: str, body: ReviseBody):
    from ai.compile.compiler import revise_review_point

    result = revise_review_point(body.text, skill_id)
    if result.get("summary") == "没有这个审查点":
        raise HTTPException(status_code=404, detail="没有这个审查点")
    # 兼容前端旧字段
    result["yaml"] = result.get("skill_yaml") or ""
    return result


@router.put("/skills/{skill_id}")
def skill_save(skill_id: str, body: SkillTextBody):
    try:
        save_skill_text(skill_id, body.yaml)
        if body.workflow_yaml:
            skill = load_skill(skill_id) or {}
            workflow_id = str(skill.get("workflow") or skill_id)
            save_workflow_text(workflow_id, body.workflow_yaml)
            clear_cache(workflow_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="没有这个审查点或工作流") from None
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    return {"id": skill_id, "saved": True}
