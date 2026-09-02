"""Read-only catalogue of strategy templates + a helper to instantiate one.

The catalogue (metadata, parameter schema, research presets) is served
straight from the Python template classes — no database, no duplicated
config — so the frontend renders its parameter forms entirely from this
response. Creating a strategy from a template goes through the normal
strategy service, so versioning / change log / audit all apply.
"""

from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from app.backtesting.adhoc import run_adhoc
from app.backtesting.report_pdf import render_pdf
from app.config import Settings, get_settings
from app.core.deps import get_db
from app.core.exceptions import NotFoundError, ValidationError
from app.schemas.strategy import StrategyRead
from app.schemas.strategy_library import (
    BacktestReportRequest,
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


@router.get("/universe/nifty200")
def nifty200_universe() -> dict:
    """The NIFTY 200 tradingsymbols the backtest report defaults to. Names
    resolve against the live instrument master; unresolvable ones are
    dropped at run time."""
    from app.market_data.nse_universe import NIFTY_200

    return {"universe": "nifty200", "symbols": [f"NSE:{s}" for s in NIFTY_200]}


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


def _report(slug: str, payload: BacktestReportRequest, db: Session, settings: Settings):
    try:
        get_template(slug)
    except KeyError as exc:
        raise NotFoundError(str(exc)) from exc
    return run_adhoc(
        db, settings, slug=slug, symbols=payload.symbols, timeframe=payload.timeframe,
        start=payload.start, end=payload.end, preset=payload.preset,
        capital=payload.capital, overrides=payload.parameters,
    )


@router.post("/{slug}/backtest-report")
def backtest_report_json(
    slug: str,
    payload: BacktestReportRequest,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict:
    """Run the template over the chosen symbols and return metrics + chart
    data for on-screen review. Same engine/cost model as saved backtests."""
    return _report(slug, payload, db, settings).as_dict()


@router.post("/{slug}/backtest-report.pdf")
def backtest_report_pdf(
    slug: str,
    payload: BacktestReportRequest,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Response:
    """Same run as ``/backtest-report`` but streamed back as a downloadable PDF."""
    report = _report(slug, payload, db, settings)
    pdf = render_pdf(report)
    fname = f"{slug}_{'_'.join(report.used_symbols[:3])}_{report.start}_{report.end}.pdf"
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


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
