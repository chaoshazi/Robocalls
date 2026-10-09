'''CRM 网关：按配置在 fake / rest 之间选实现，上层只认这个入口。'''

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from app.core.config import Settings
from app.integrations.crm.client import RestCrm
from app.integrations.crm.fake import FakeCrm


@runtime_checkable
class CrmGateway(Protocol):
    name: str

    def list_records(
        self,
        crm_object: str,
        *,
        limit: int | None = None,
        cursor: str | None = None,
        filters: dict | None = None,
        search: str | None = None,
    ) -> dict[str, Any]: ...

    def get_record(self, crm_object: str, record_id: str) -> dict[str, Any] | None: ...

    def create_record(
        self, crm_object: str, payload: dict[str, Any], idempotency_key: str | None = None
    ) -> dict[str, Any]: ...

    def health(self) -> dict[str, Any]: ...


def build_gateway(settings: Settings) -> CrmGateway:
    if settings.crm_mode == 'rest':
        return RestCrm(
            base_url=settings.crm_base_url,
            api_token=settings.crm_api_token,
            actor_id=settings.crm_actor_id,
            page_size=settings.crm_page_size,
            rate_limit_per_sec=settings.crm_rate_limit_per_sec,
            max_retries=settings.crm_max_retries,
            timeout_seconds=settings.crm_timeout_seconds,
        )
    return FakeCrm()