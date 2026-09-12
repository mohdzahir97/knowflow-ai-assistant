"""Aggregates all v1 API routers."""
from fastapi import APIRouter

from app.api.v1.admin import router as admin_router
from app.api.v1.auth import router as auth_router
from app.api.v1.chat import router as chat_router
from app.api.v1.documents import router as documents_router
from app.api.v1.projects import router as projects_router
from app.api.v1.providers import router as providers_router

api_router = APIRouter()
api_router.include_router(auth_router)
api_router.include_router(providers_router)
api_router.include_router(documents_router)
api_router.include_router(chat_router)
api_router.include_router(projects_router)
api_router.include_router(admin_router)
