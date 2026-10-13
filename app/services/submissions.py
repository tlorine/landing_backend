from sqlalchemy.ext.asyncio import AsyncSession

from app.models.service_request import ServiceRequest
from app.repositories.notification_outbox import NotificationOutboxRepository
from app.repositories.service_requests import ServiceRequestRepository
from app.schemas.service_request import ServiceRequestCreate


class SubmissionService:
    def __init__(
        self,
        request_repository: ServiceRequestRepository,
        outbox_repository: NotificationOutboxRepository,
    ) -> None:
        self._request_repository = request_repository
        self._outbox_repository = outbox_repository

    async def create(self, session: AsyncSession, payload: ServiceRequestCreate) -> ServiceRequest:
        # The request and its notification job commit together. A Telegram outage cannot
        # cause an accepted request to disappear or force the visitor to submit it again.
        async with session.begin():
            request = await self._request_repository.create(session, payload)
            await self._outbox_repository.enqueue(session, request.id)
        return request
