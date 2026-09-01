"""Read-only catalogue of strategy templates + a helper to instantiate one.

The catalogue (metadata, parameter schema, research presets) is served
straight from the Python template classes — no database, no duplicated
config — so the frontend renders its parameter forms entirely from this
response. Creating a strategy from a template goes through the normal
strategy service, so versioning / change log / audit all apply.
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.deps import get_db
from app.core.exceptions import NotFoundError, ValidationError
from app.schemas.strategy import StrategyRead
from app.schemas.strategy_library import (
    SeedResult,
    StrategyFromTemplateRequest,
    TemplateDetail,
    TemplateSummary,
)
from app.strategies.library import TEMPLATES, get_template
from app.strategies.library.base import ParamError, merge_metadata_defaults
from app.strategies.library.seeding import create_strategy_from_template, seed_strategy_library

router = APIRouter(prefix="/strategy-library", tags=["strategy-library"])


def _detail_dict(template) -> dict:
    return merge_metadata_defaults(template.METADATA, template)


@router.get("", response_model=list[TemplateSummary])
def list_templates():
    return [_detail_dict(t) for t in TEMPLATES]


@router.post("/seed", response_model=SeedResult)
def seed(db: Session = Depends(get_db)):
    result = seed_strategy_library(db)
    db.commit()
    return result


@router.get("/{slug}", response_model=TemplateDetail)
def get_template_detail(slug: str):
    try:
        template = get_template(slug)
    except KeyError as exc:
        raise NotFoundError(str(exc)) from exc
    return _detail_dict(template)


@router.post("/{slug}/strategies", response_model=StrategyRead, status_code=201)
def create_from_template(
    slug: str, payload: StrategyFromTemplateRequest, db: Session = Depends(get_db)
):
    try:
        get_template(slug)
    except KeyError as exc:
        raise NotFoundError(str(exc)) from exc
    try:
        return create_strategy_from_template(
            db,
            slug,
            name=payload.name,
            preset=payload.preset,
            overrides=payload.parameters,
        )
    except (ParamError, KeyError) as exc:
        raise ValidationError(f"Invalid strategy parameters: {exc}") from exc
