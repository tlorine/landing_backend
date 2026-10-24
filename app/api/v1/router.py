from fastapi import APIRouter

from app.api.v1.endpoints import admin_analytics, admin_auth, analytics, health, requests, visits

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(requests.router)
api_router.include_router(visits.router)

api_router.include_router(analytics.router)
api_router.include_router(admin_auth.router)
api_router.include_router(admin_analytics.router)
