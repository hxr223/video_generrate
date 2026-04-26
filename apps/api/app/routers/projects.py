import uuid

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from packages.core.database import get_session
from packages.core.models import Project
from packages.core.schemas import ProjectCreate, ProjectRead, ProjectScriptDraftRead, ProjectScriptDraftRequest, ProjectUpdate
from packages.core.status import sync_project_status
from packages.timeline.script_generator import generate_project_script_draft

router = APIRouter(prefix="/projects", tags=["projects"])


@router.post("", response_model=ProjectRead, status_code=status.HTTP_201_CREATED)
def create_project(payload: ProjectCreate, session: Session = Depends(get_session)) -> Project:
    project = Project(**payload.model_dump())
    session.add(project)
    session.commit()
    session.refresh(project)
    return project


@router.post("/script-draft", response_model=ProjectScriptDraftRead)
def generate_script_draft(payload: ProjectScriptDraftRequest) -> ProjectScriptDraftRead:
    script_text, beats = generate_project_script_draft(
        title=payload.title,
        topic=payload.topic,
        target_duration=payload.target_duration,
        style=payload.style,
        platform=payload.platform,
        language=payload.language,
    )
    return ProjectScriptDraftRead(script_text=script_text, beats=beats)


@router.get("", response_model=list[ProjectRead])
def list_projects(session: Session = Depends(get_session)) -> list[Project]:
    statement = select(Project).order_by(Project.created_at.desc())
    projects = list(session.scalars(statement).all())
    for project in projects:
        sync_project_status(session, project.id)
    session.commit()
    return projects


@router.get("/{project_id}", response_model=ProjectRead)
def get_project(project_id: uuid.UUID, session: Session = Depends(get_session)) -> Project:
    project = session.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    sync_project_status(session, project.id)
    session.commit()
    session.refresh(project)
    return project


@router.patch("/{project_id}", response_model=ProjectRead)
def update_project(
    project_id: uuid.UUID,
    payload: ProjectUpdate,
    session: Session = Depends(get_session),
) -> Project:
    project = session.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")

    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(project, key, value)

    session.commit()
    session.refresh(project)
    return project


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_project(project_id: uuid.UUID, session: Session = Depends(get_session)) -> Response:
    project = session.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")

    session.delete(project)
    session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
