from sqlalchemy import String, and_, cast, distinct, exists, func, literal, select
from sqlalchemy.orm import aliased

from app.models.analytics import AnalyticsCoverage
from app.models.analytics import AnalyticsEvent as E
from app.models.analytics import AnalyticsSession as S
from app.services.analytics_manifest import CASES


class AnalyticsReportsRepository:
    async def coverage(self, session, source_site=None):
        statement = select(AnalyticsCoverage).order_by(AnalyticsCoverage.started_at)
        if source_site:
            statement = statement.where(AnalyticsCoverage.source_site == source_site)
        return list((await session.execute(statement)).scalars())

    def scoped(self, filters, start, end):
        conditions = [
            E.source_site == filters.source_site,
            E.occurred_at >= start,
            E.occurred_at < end,
        ]
        if filters.locale:
            conditions.append(E.locale == filters.locale)
        if filters.case_id:
            conditions.append(E.case_id == filters.case_id)
        if filters.country:
            conditions.append(
                S.country.is_(None)
                if filters.country == "unknown"
                else S.country == filters.country
            )
        if filters.source_type:
            conditions.append(S.source_type == filters.source_type)
        if filters.source_value:
            conditions.append(S.source_value == filters.source_value)
        return (
            select(E, S.country.label("entry_country"), S.source_type, S.source_value)
            .outerjoin(S, and_(S.source_site == E.source_site, S.session_id == E.session_id))
            .where(*conditions)
            .cte()
        )

    def counts(self, events, sessions):
        return [
            func.count().filter(events.c.event_type == "page_view").label("page_views"),
            (func.count(distinct(events.c.session_id)) if sessions else literal(None)).label(
                "sessions"
            ),
            func.count()
            .filter(and_(events.c.event_type == "page_view", events.c.case_id.is_not(None)))
            .label("case_views"),
            func.count()
            .filter(events.c.event_type == "case_outbound_click")
            .label("outbound_clicks"),
        ]

    async def totals(self, session, filters, start, end, sessions):
        events = self.scoped(filters, start, end)
        return dict(
            (await session.execute(select(*self.counts(events, sessions)).select_from(events)))
            .mappings()
            .one()
        )

    async def has_sessions(self, session, filters, start, end):
        events = self.scoped(filters, start, end)
        result = await session.execute(
            select(events.c.event_id).where(events.c.session_id.is_not(None)).limit(1)
        )
        return result.scalar_one_or_none() is not None

    async def daily(self, session, filters, start, end, sessions):
        events = self.scoped(filters, start, end)
        day = cast(func.timezone(filters.timezone, events.c.occurred_at), String)
        # PostgreSQL to_char keeps date keys independent from connection timezone.
        day = func.to_char(func.timezone(filters.timezone, events.c.occurred_at), "YYYY-MM-DD")
        rows = await session.execute(
            select(day.label("date"), *self.counts(events, sessions))
            .select_from(events)
            .group_by(day)
            .order_by(day)
        )
        return [dict(row) for row in rows.mappings()]

    async def breakdown(self, session, filters, start, end, dimension):
        events = self.scoped(filters, start, end)
        columns = (
            [events.c.entry_country]
            if dimension == "country"
            else [events.c.source_value, events.c.source_type]
        )
        count = func.count(distinct(events.c.session_id))
        rows = (
            await session.execute(
                select(*columns, count.label("count"))
                .where(events.c.session_id.is_not(None))
                .group_by(*columns)
                .order_by(count.desc())
            )
        ).all()
        total = sum(row[-1] for row in rows)
        result = []
        for row in rows[:20]:
            item = {"key": row[0], "count": row[-1], "share": row[-1] / total if total else 0}
            if dimension == "source":
                item["source_type"] = row[1] or "direct_unknown"
            result.append(item)
        rest = sum(row[-1] for row in rows[20:])
        if rest:
            result.append(
                {
                    "key": "other",
                    "count": rest,
                    "share": rest / total,
                    **({"source_type": "other"} if dimension == "source" else {}),
                }
            )
        return result

    async def cases(self, session, filters, start, end, sessions):
        events = self.scoped(filters, start, end)
        view = and_(events.c.event_type == "page_view", events.c.case_id.is_not(None))
        click = aliased(E)
        converted = exists(
            select(click.event_id).where(
                click.source_site == events.c.source_site,
                click.page_view_id == events.c.page_view_id,
                click.case_id == events.c.case_id,
                click.session_id == events.c.session_id,
                click.locale == events.c.locale,
                click.event_type == "case_outbound_click",
                click.occurred_at >= events.c.occurred_at,
                click.occurred_at < end,
                click.sequence > events.c.sequence,
            )
        )
        rows = await session.execute(
            select(
                events.c.case_id,
                func.count().filter(events.c.event_type == "case_open").label("case_opens"),
                func.count().filter(view).label("case_views"),
                func.count(distinct(events.c.session_id)).filter(view).label("case_view_sessions"),
                func.count()
                .filter(events.c.event_type == "case_outbound_click")
                .label("outbound_clicks"),
                func.count(distinct(events.c.session_id))
                .filter(and_(view, converted))
                .label("outbound_sessions"),
            )
            .where(events.c.case_id.is_not(None))
            .group_by(events.c.case_id)
        )
        indexed = {row["case_id"]: dict(row) for row in rows.mappings()}
        result = []
        for case_id, manifest in CASES.items():
            if filters.case_id and case_id != filters.case_id:
                continue
            row = indexed.get(
                case_id,
                {
                    "case_id": case_id,
                    "case_opens": 0,
                    "case_views": 0,
                    "case_view_sessions": 0,
                    "outbound_clicks": 0,
                    "outbound_sessions": 0,
                },
            )
            row["id"] = row.pop("case_id")
            row["has_outbound_link"] = manifest["has_outbound_link"]
            row["conversion"] = (
                row["outbound_sessions"] / row["case_view_sessions"]
                if sessions and row["case_view_sessions"] and manifest["has_outbound_link"]
                else None
            )
            if not sessions:
                row["case_view_sessions"] = row["outbound_sessions"] = None
            result.append(row)
        return sorted(result, key=lambda row: (-row["case_views"], row["id"]))

    async def funnel(self, session, filters, start, end):
        opens = self.scoped(filters, start, end)
        target = aliased(E)
        click = aliased(E)
        matched_view = and_(
            target.source_site == opens.c.source_site,
            target.event_type == "page_view",
            target.case_id == opens.c.case_id,
            target.navigation_id == opens.c.navigation_id,
            target.locale == opens.c.locale,
            target.occurred_at >= opens.c.occurred_at,
            target.occurred_at
            <= opens.c.occurred_at + literal(__import__("datetime").timedelta(minutes=10)),
            target.occurred_at < end,
        )
        identity = func.coalesce(cast(opens.c.session_id, String), cast(opens.c.event_id, String))
        views = exists(select(target.event_id).where(matched_view))
        outbound = exists(
            select(target.event_id).where(
                matched_view,
                exists(
                    select(click.event_id).where(
                        click.source_site == target.source_site,
                        click.case_id == target.case_id,
                        click.locale == target.locale,
                        click.page_view_id == target.page_view_id,
                        click.event_type == "case_outbound_click",
                        click.sequence > target.sequence,
                        click.occurred_at >= target.occurred_at,
                        click.occurred_at < end,
                    )
                ),
            )
        )
        row = (
            (
                await session.execute(
                    select(
                        func.count(distinct(identity)).label("opens"),
                        func.count(distinct(identity)).filter(views).label("views"),
                        func.count(distinct(identity)).filter(outbound).label("outbound"),
                    ).where(opens.c.event_type == "case_open")
                )
            )
            .mappings()
            .one()
        )
        return dict(row)

    async def links(self, session, filters, start, end):
        events = self.scoped(filters, start, end)
        rows = await session.execute(
            select(events.c.link_id, func.count().label("count"))
            .where(events.c.event_type == "case_outbound_click")
            .group_by(events.c.link_id)
        )
        return [dict(row) for row in rows.mappings()]
