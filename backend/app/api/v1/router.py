"""API v1 router aggregation."""

from fastapi import APIRouter

from app.api.v1 import channels, health, journey, officer

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(journey.router)
api_router.include_router(channels.router)
api_router.include_router(officer.router)
