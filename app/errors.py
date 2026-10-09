'''业务异常：路由层统一转成 JSON 错误体 {detail, code}。'''

from __future__ import annotations


class AppError(Exception):
    status_code = 400
    code = 'bad_request'

    def __init__(
        self,
        detail: str,
        *,
        code: str | None = None,
        status_code: int | None = None,
        extra: dict | None = None,
    ) -> None:
        super().__init__(detail)
        self.detail = detail
        if code:
            self.code = code
        if status_code:
            self.status_code = status_code
        self.extra = dict(extra or {})

    def to_body(self) -> dict:
        body = {'detail': self.detail, 'code': self.code}
        body.update(self.extra)
        return body


class AuthError(AppError):
    status_code = 401
    code = 'unauthorized'


class Forbidden(AppError):
    status_code = 403
    code = 'forbidden'


class NotFound(AppError):
    status_code = 404
    code = 'not_found'


class Conflict(AppError):
    status_code = 409
    code = 'conflict'


class ValidationFailed(AppError):
    status_code = 422
    code = 'validation_failed'


class RateLimited(AppError):
    status_code = 429
    code = 'rate_limited'


class Blocked(AppError):
    '''合规拦截：黑名单、免打扰时段、频次超限。'''

    status_code = 409
    code = 'compliance_blocked'


class UpstreamError(AppError):
    status_code = 502
    code = 'upstream_error'