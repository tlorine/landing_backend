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
