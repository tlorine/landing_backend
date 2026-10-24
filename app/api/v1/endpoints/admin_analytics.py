from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.endpoints.admin_auth import require_admin
from app.api.v1.endpoints.analytics import error
from app.db.session import get_session
from app.schemas.analytics_reports import (
    CapabilitiesResponse,
    CasesResponse,
    DetailResponse,
    ErrorResponse,
    OverviewResponse,
)
from app.services.analytics_reports import AnalyticsReportsService, ReportFilters

router = APIRouter(
    prefix="/admin/analytics",
    tags=["admin-analytics"],
    dependencies=[Depends(require_admin)],
    responses={code: {"model": ErrorResponse} for code in (401, 403, 404, 422, 503)},
)
service = AnalyticsReportsService()


def filters(
    source_site: str = "studio-landing",
    start: date | None = Query(default=None, alias="from"),
    end: date | None = Query(default=None, alias="to"),
    timezone: str | None = None,
    locale: str | None = None,
    country: str | None = None,
    source_type: str | None = None,
    source_value: str | None = None,
    case_id: str | None = None,
):
    from fastapi import HTTPException

    try:
        return ReportFilters.resolve(
            source_site, start, end, timezone, locale, country, source_type, source_value, case_id
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None


@router.get("/capabilities", response_model=CapabilitiesResponse)
async def capabilities(session: AsyncSession = Depends(get_session)):
    return await service.capabilities(session)


@router.get("/overview", response_model=OverviewResponse)
async def overview(
    query: ReportFilters = Depends(filters), session: AsyncSession = Depends(get_session)
):
    return await service.report(session, query)


@router.get("/cases", response_model=CasesResponse)
async def cases(
    query: ReportFilters = Depends(filters),
    session: AsyncSession = Depends(get_session),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    sort: str = "case_views",
    order: str = "desc",
):
    if sort not in ("case_views", "case_opens", "outbound_clicks", "conversion") or order not in (
        "asc",
        "desc",
    ):
        return error(422, "validation_error", "Неизвестная сортировка.")
    payload = (await service.report(session, query)).model_dump(by_alias=True)
    rows = sorted(payload.pop("cases_preview"), key=lambda row: row["id"])
    items = sorted(
        (row for row in rows if row[sort] is not None),
        key=lambda row: row[sort],
        reverse=order == "desc",
    )
    items.extend(row for row in rows if row[sort] is None)
    payload.update(
        items=items[(page - 1) * page_size : page * page_size],
        page=page,
        page_size=page_size,
        total=len(items),
    )
    return payload


@router.get("/cases/{case_id}", response_model=DetailResponse)
async def case_detail(
    case_id: str,
    query: ReportFilters = Depends(filters),
    session: AsyncSession = Depends(get_session),
):
    from dataclasses import replace

    from app.services.analytics_manifest import CASES

    if case_id not in CASES:
        return error(404, "case_not_found", "Кейс не найден.")
    return await service.report(session, replace(query, case_id=case_id), detail=True)
