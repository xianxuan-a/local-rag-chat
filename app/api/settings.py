"""Read and update the supported non-secret product settings."""

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.dependencies import AdminUser, CurrentUser
from app.core.config import Settings, get_settings
from app.core.response import ApiResponse, success_response
from app.database.sqlite import get_db
from app.schemas.settings import ProductSettingsResponse, ProductSettingsUpdate
from app.services.product_settings_service import ProductSettingsService
from app.services.runtime_coordinator import RuntimeCoordinator, get_runtime_coordinator


router = APIRouter(prefix="/settings", tags=["settings"])
DatabaseSession = Annotated[Session, Depends(get_db)]
AppSettings = Annotated[Settings, Depends(get_settings)]
RagRuntime = Annotated[RuntimeCoordinator, Depends(get_runtime_coordinator)]


@router.get("", response_model=ApiResponse[ProductSettingsResponse])
def get_product_settings(
    db: DatabaseSession,
    settings: AppSettings,
    runtime: RagRuntime,
    user: CurrentUser,
):
    return success_response(
        ProductSettingsService(db, settings).response(
            runtime.product_settings,
            current_user_role=user.role,
            web_search_provider=runtime.web_search_provider.name,
            web_search_provider_configured=(
                runtime.web_search_provider.configured
            ),
        )
    )


@router.put("", response_model=ApiResponse[ProductSettingsResponse])
def update_product_settings(
    payload: ProductSettingsUpdate,
    db: DatabaseSession,
    settings: AppSettings,
    runtime: RagRuntime,
    user: AdminUser,
):
    with runtime.business_write("update_product_settings"):
        response = ProductSettingsService(db, settings).update(
            payload,
            updated_by_id=user.id,
            manager=runtime.product_settings,
            web_search_provider=runtime.web_search_provider.name,
            web_search_provider_configured=(
                runtime.web_search_provider.configured
            ),
        )
    return success_response(response)
