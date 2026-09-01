"""Deployment lifecycle: create, deploy/pause/resume/stop/clone.

Every transition is audited. LIVE-mode creation is the one path in this
service that gets extra scrutiny — see `create_deployment` — because it's
the human-facing half of requirement #14 (app.execution.guard is the
runtime-facing half).
"""

from sqlalchemy.orm import Session

from app.audit.service import record as record_audit
from app.core.exceptions import ConflictError, NotFoundError
from app.execution.guard import now_utc
from app.models.deployment import Deployment
from app.models.enums import AuditAction, ChangeEntityType, DeploymentStatus, TradingMode
from app.models.strategy import StrategyVersion
from app.repositories.deployment_repository import DeploymentRepository
from app.schemas.deployment import DeploymentCloneRequest, DeploymentCreate


def create_deployment(db: Session, payload: DeploymentCreate) -> Deployment:
    version = db.get(StrategyVersion, payload.strategy_version_id)
    if version is None:
        raise NotFoundError(f"Strategy version {payload.strategy_version_id} not found")

    deployment = Deployment(
        strategy_version_id=payload.strategy_version_id,
        name=payload.name,
        mode=payload.mode,
        instrument_universe=payload.instrument_universe,
        config=payload.config,
        status=DeploymentStatus.PENDING,
    )

    if payload.mode == TradingMode.LIVE:
        # payload validation already enforced the confirmation phrase; this
        # is where that confirmation becomes a permanent, auditable fact
        # on the row itself, which app.execution.guard re-checks on every
        # single order (never trusting this creation-time flag alone).
        deployment.live_trading_confirmed = True
        deployment.live_trading_confirmed_at = now_utc()

    db.add(deployment)
    db.flush()

    record_audit(
        db,
        action=AuditAction.CREATE,
        entity_type=ChangeEntityType.DEPLOYMENT,
        entity_id=deployment.id,
        mode=deployment.mode,
        summary=f"Created {deployment.mode.value} deployment '{deployment.name}'",
        after={
            "mode": deployment.mode.value,
            "strategy_version_id": str(deployment.strategy_version_id),
            "live_trading_confirmed": deployment.live_trading_confirmed,
        },
    )
    db.commit()
    db.refresh(deployment)
    return deployment


def _transition(
    db: Session,
    deployment_id,
    *,
    expected_from: set[DeploymentStatus],
    to: DeploymentStatus,
    action: AuditAction,
    timestamp_field: str | None,
) -> Deployment:
    deployment = db.get(Deployment, deployment_id)
    if deployment is None:
        raise NotFoundError(f"Deployment {deployment_id} not found")
    if deployment.status not in expected_from:
        raise ConflictError(
            f"Cannot {action.value} deployment in status {deployment.status.value} "
            f"(expected one of {[s.value for s in expected_from]})"
        )

    before_status = deployment.status
    deployment.status = to
    if timestamp_field:
        setattr(deployment, timestamp_field, now_utc())

    record_audit(
        db,
        action=action,
        entity_type=ChangeEntityType.DEPLOYMENT,
        entity_id=deployment.id,
        mode=deployment.mode,
        summary=f"Deployment '{deployment.name}' {before_status.value} -> {to.value}",
        before={"status": before_status.value},
        after={"status": to.value},
    )
    db.commit()
    db.refresh(deployment)
    return deployment


def deploy(db: Session, deployment_id) -> Deployment:
    return _transition(
        db,
        deployment_id,
        expected_from={DeploymentStatus.PENDING, DeploymentStatus.STOPPED},
        to=DeploymentStatus.RUNNING,
        action=AuditAction.DEPLOY,
        timestamp_field="deployed_at",
    )


def pause(db: Session, deployment_id) -> Deployment:
    return _transition(
        db,
        deployment_id,
        expected_from={DeploymentStatus.RUNNING},
        to=DeploymentStatus.PAUSED,
        action=AuditAction.PAUSE,
        timestamp_field="paused_at",
    )


def resume(db: Session, deployment_id) -> Deployment:
    return _transition(
        db,
        deployment_id,
        expected_from={DeploymentStatus.PAUSED},
        to=DeploymentStatus.RUNNING,
        action=AuditAction.RESUME,
        timestamp_field="deployed_at",
    )


def stop(db: Session, deployment_id) -> Deployment:
    return _transition(
        db,
        deployment_id,
        expected_from={DeploymentStatus.RUNNING, DeploymentStatus.PAUSED, DeploymentStatus.ERROR},
        to=DeploymentStatus.STOPPED,
        action=AuditAction.STOP,
        timestamp_field="stopped_at",
    )


def clone(db: Session, deployment_id, payload: DeploymentCloneRequest) -> Deployment:
    source = db.get(Deployment, deployment_id)
    if source is None:
        raise NotFoundError(f"Deployment {deployment_id} not found")

    create_payload = DeploymentCreate(
        strategy_version_id=source.strategy_version_id,
        name=payload.name,
        mode=payload.mode,
        instrument_universe=source.instrument_universe,
        config=source.config,
        live_trading_confirmation_phrase=payload.live_trading_confirmation_phrase,
    )
    cloned = create_deployment(db, create_payload)
    cloned.cloned_from_deployment_id = source.id

    record_audit(
        db,
        action=AuditAction.CLONE,
        entity_type=ChangeEntityType.DEPLOYMENT,
        entity_id=cloned.id,
        mode=cloned.mode,
        summary=f"Cloned deployment '{source.name}' -> '{cloned.name}'",
        before={"source_deployment_id": str(source.id)},
    )
    db.commit()
    db.refresh(cloned)
    return cloned


def list_deployments(db: Session) -> list[Deployment]:
    return DeploymentRepository(db).list()


def get_deployment(db: Session, deployment_id) -> Deployment:
    deployment = DeploymentRepository(db).get(deployment_id)
    if deployment is None:
        raise NotFoundError(f"Deployment {deployment_id} not found")
    return deployment
