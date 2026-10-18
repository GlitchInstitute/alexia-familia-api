"""Fetching HTML pages and JSON feeds that the portal's pages load."""

from dataclasses import dataclass
from typing import Final

from alexia_api.domain.errors import (
    PortalError,
    PortalMaintenance,
    SessionExpired,
    UnexpectedReply,
)
from alexia_api.portal.session import PortalRequest, PortalResponse, Tx
from alexia_api.portal.ws import MAINTENANCE_STATUSES, looks_like_logon_page

COMUNICADOS_PAGE: Final = "/ACWeb/paginas/Comunicacion/Comunicados.aspx"
COMUNICADO_PAGE: Final = "/ACWeb/paginas/Comunicacion/Comunicado.aspx"

PAGE_ACCEPT: Final = "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
FEED_ACCEPT: Final = "application/json, text/javascript, */*; q=0.01"


@dataclass(frozen=True, slots=True)
class PageRequest:
    name: str
    path: str
    referer: str
    accept: str
    xhr: bool = False


async def get_page(tx: Tx, request: PageRequest) -> PortalResponse:
    """Fetch a page without following redirects and map every unusual answer to a typed error.

    A redirect to the logon page means the session expired. Any other redirect is unexpected,
    because the portal's own pages never redirect a signed-in guardian.
    """
    headers = {"accept": request.accept}
    if request.xhr:
        headers["x-requested-with"] = "XMLHttpRequest"
    response = await tx.request(
        PortalRequest(
            method="GET",
            path=request.path,
            headers=headers,
            referer=request.referer,
            follow=False,
        )
    )

    if 300 <= response.status < 400:
        expired = looks_like_logon_page(response.location or "")
        raise PortalError(
            SessionExpired() if expired else UnexpectedReply(where=f"page:{request.name} redirect")
        )
    if response.status == 401:
        raise PortalError(SessionExpired())
    if response.status in MAINTENANCE_STATUSES:
        raise PortalError(PortalMaintenance(status=response.status))
    if response.status != 200:
        raise PortalError(UnexpectedReply(where=f"page:{request.name} HTTP {response.status}"))
    return response
