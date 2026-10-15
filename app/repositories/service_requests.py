from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.service_request import ServiceRequest
from app.schemas.service_request import ServiceRequestCreate


class ServiceRequestRepository:
    async def create(
        self,
        session: AsyncSession,
        payload: ServiceRequestCreate,
    ) -> ServiceRequest:
        request = ServiceRequest(**payload.model_dump())
        session.add(request)
        await session.flush()
        return request

    async def count_created_between(
        self,
        session: AsyncSession,
        start: datetime,
        end: datetime,
        source_site: str | None = None,
    ) -> int:
        statement = select(func.count()).where(
            ServiceRequest.created_at >= start, ServiceRequest.created_at < end
        )
        if source_site is not None:
            statement = statement.where(ServiceRequest.source_site == source_site)
        result = await session.execute(statement)
        return result.scalar_one()
