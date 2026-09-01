"""Turn a library template into a real Strategy + StrategyVersion.

The seeded version's ``source_code`` is a one-line import shim
(``from app.strategies.library.<mod> import <Class> as Strategy``) so the
existing registry loader, strategy versioning, change log and audit log all
work with zero special-casing — a library strategy is just a normal
strategy whose logic happens to live in a shared module.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.strategy import Strategy
from app.schemas.strategy import StrategyCreate, StrategyVersionCreate
from app.services import strategy_service
from app.strategies.library import TEMPLATES, TemplateStrategy, get_template


def shim_source(template: type[TemplateStrategy]) -> str:
    return f"from {template.__module__} import {template.__name__} as Strategy\n"


def build_parameters(
    template: type[TemplateStrategy],
    *,
    preset: str | None = None,
    overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Full, validated parameter dict for a new version: template defaults,
    then the named research preset, then explicit overrides."""
    supplied: dict[str, Any] = {}
    if preset:
        presets = template.presets()
        if preset not in presets:
            raise KeyError(f"{template.SLUG}: unknown preset '{preset}' ({sorted(presets)})")
        supplied.update(presets[preset])
    if overrides:
        supplied.update(overrides)
    return template.resolve_params(supplied)


def create_strategy_from_template(
    db: Session,
    slug: str,
    *,
    name: str | None = None,
    preset: str | None = "balanced",
    overrides: dict[str, Any] | None = None,
) -> Strategy:
    template = get_template(slug)
    parameters = build_parameters(template, preset=preset, overrides=overrides)
    summary = f"Created from library template '{slug}'"
    if preset:
        summary += f" ({preset} research preset)"
    payload = StrategyCreate(
        name=name or template.NAME,
        description=template.METADATA.description,
        initial_version=StrategyVersionCreate(
            source_code=shim_source(template),
            parameters=parameters,
            entry_point="Strategy",
            change_summary=summary,
        ),
    )
    return strategy_service.create_strategy(db, payload)


def seed_strategy_library(db: Session) -> dict[str, list[str]]:
    """Idempotent: create one Strategy per template if not already present
    (matched by the template's default name). Returns {created, skipped}."""
    existing = set(db.execute(select(Strategy.name)).scalars().all())
    created: list[str] = []
    skipped: list[str] = []
    for template in TEMPLATES:
        if template.NAME in existing:
            skipped.append(template.SLUG)
            continue
        create_strategy_from_template(db, template.SLUG, preset="balanced")
        created.append(template.SLUG)
    return {"created": created, "skipped": skipped}
