from fastapi import APIRouter

from app.api.v1.endpoints import health, requests, visits

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(requests.router)
api_router.include_router(visits.router)
