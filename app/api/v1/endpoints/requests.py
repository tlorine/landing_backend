from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import SessionFactory, get_session
from app.repositories.notification_outbox import NotificationOutboxRepository
from app.repositories.service_requests import ServiceRequestRepository
from app.schemas.service_request import ServiceRequestCreate, ServiceRequestCreated
from app.services.submissions import SubmissionService

router = APIRouter(prefix="/requests", tags=["requests"])

_submission_service = SubmissionService(
    request_repository=ServiceRequestRepository(),
    outbox_repository=NotificationOutboxRepository(SessionFactory),
)


@router.post("", response_model=ServiceRequestCreated, status_code=status.HTTP_201_CREATED)
async def create_request(
    payload: ServiceRequestCreate,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ServiceRequestCreated:
    request = await _submission_service.create(session, payload)
    return ServiceRequestCreated(id=request.id, created_at=request.created_at)
