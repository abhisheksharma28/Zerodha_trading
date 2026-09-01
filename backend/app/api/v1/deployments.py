import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.deps import get_db
from app.schemas.deployment import DeploymentCloneRequest, DeploymentCreate, DeploymentRead
from app.services import deployment_service

router = APIRouter(prefix="/deployments", tags=["deployments"])


@router.get("", response_model=list[DeploymentRead])
def list_deployments(db: Session = Depends(get_db)):
    return deployment_service.list_deployments(db)


@router.post("", response_model=DeploymentRead, status_code=201)
def create_deployment(payload: DeploymentCreate, db: Session = Depends(get_db)):
    """mode == 'live' requires live_trading_confirmation_phrase == 'DEPLOY LIVE
    TRADING' (enforced by the request schema itself) — this is the explicit,
    separately-recorded human confirmation requirement #14 depends on. See
    app.execution.guard for how this is re-checked before every live order,
    not just trusted from this creation step."""
    return deployment_service.create_deployment(db, payload)


@router.get("/{deployment_id}", response_model=DeploymentRead)
def get_deployment(deployment_id: uuid.UUID, db: Session = Depends(get_db)):
    return deployment_service.get_deployment(db, deployment_id)


@router.post("/{deployment_id}/deploy", response_model=DeploymentRead)
def deploy(deployment_id: uuid.UUID, db: Session = Depends(get_db)):
    return deployment_service.deploy(db, deployment_id)


@router.post("/{deployment_id}/pause", response_model=DeploymentRead)
def pause(deployment_id: uuid.UUID, db: Session = Depends(get_db)):
    return deployment_service.pause(db, deployment_id)


@router.post("/{deployment_id}/resume", response_model=DeploymentRead)
def resume(deployment_id: uuid.UUID, db: Session = Depends(get_db)):
    return deployment_service.resume(db, deployment_id)


@router.post("/{deployment_id}/stop", response_model=DeploymentRead)
def stop(deployment_id: uuid.UUID, db: Session = Depends(get_db)):
    return deployment_service.stop(db, deployment_id)


@router.post("/{deployment_id}/clone", response_model=DeploymentRead, status_code=201)
def clone(deployment_id: uuid.UUID, payload: DeploymentCloneRequest, db: Session = Depends(get_db)):
    return deployment_service.clone(db, deployment_id, payload)
