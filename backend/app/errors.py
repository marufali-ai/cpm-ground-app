"""Consistent, human-readable error envelope (PRD 64 error codes, PRD 84 readable messages)."""
from fastapi import HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


class ApiError(HTTPException):
    def __init__(self, status_code: int, code: str, message: str, detail=None):
        super().__init__(status_code=status_code, detail=message)
        self.code = code
        self.payload = detail


def _envelope(code: str, message: str, detail=None) -> dict:
    body = {"error": {"code": code, "message": message}}
    if detail is not None:
        body["error"]["detail"] = detail
    return body


async def api_error_handler(_: Request, exc: ApiError):
    return JSONResponse(status_code=exc.status_code,
                        content=_envelope(exc.code, exc.detail, exc.payload))


async def http_error_handler(_: Request, exc: HTTPException):
    code = {
        400: "BAD_REQUEST", 401: "UNAUTHENTICATED", 403: "FORBIDDEN",
        404: "NOT_FOUND", 409: "CONFLICT", 413: "PAYLOAD_TOO_LARGE",
        422: "VALIDATION_ERROR", 429: "RATE_LIMITED",
    }.get(exc.status_code, "ERROR")
    return JSONResponse(status_code=exc.status_code,
                        content=_envelope(code, str(exc.detail)),
                        headers=getattr(exc, "headers", None))


async def validation_error_handler(_: Request, exc: RequestValidationError):
    fields = [{"loc": ".".join(str(p) for p in e["loc"]), "msg": e["msg"]} for e in exc.errors()]
    return JSONResponse(
        status_code=422,
        content=_envelope("VALIDATION_ERROR", "Some fields were missing or invalid.", fields),
    )
