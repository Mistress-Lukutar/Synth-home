"""Network router: Zigbee network management (permit join)."""

from typing import Annotated

from fastapi import APIRouter, Depends

from app.dependencies import require_connection
from app.models.schemas import PermitJoinRequest, StatusResponse
from app.services.hub_service import HubService

router = APIRouter()


@router.post("/api/network/permit-join")
async def permit_join(
    req: PermitJoinRequest,
    service: Annotated[HubService, Depends(require_connection)],
) -> StatusResponse:
    """Open the Zigbee network for joining."""
    result = await service.permit_join(req.duration)
    return StatusResponse(success=True, data=result)
