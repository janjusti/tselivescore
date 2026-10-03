import os
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

from extras.poller import MIN_WAIT_SECONDS, SESSION_TTL_SECONDS, ElectionPoller, PanelConfig
from extras.ratelimit import build_rate_limiter, client_ip
from extras.tse_client import UFS, dashboard_categories, resolve_panel

STATIC_DIR = Path(__file__).parent / "static"
DEFAULT_WAIT = max(int(os.environ.get("TSELIVESCORE_WAIT", "5")), MIN_WAIT_SECONDS)
DEBUG_ENDPOINTS = os.environ.get("TSELIVESCORE_DEBUG", "").lower() in ("1", "true", "yes")

app = FastAPI(
    title="TSELiveScore",
    docs_url="/docs" if DEBUG_ENDPOINTS else None,
    redoc_url="/redoc" if DEBUG_ENDPOINTS else None,
    openapi_url="/openapi.json" if DEBUG_ENDPOINTS else None,
)
poller = ElectionPoller()
rate_limiter = build_rate_limiter()


class PanelRequest(BaseModel):
    id: str
    key: str
    printables: int = Field(default=5, ge=1, le=50)

    @field_validator("key")
    @classmethod
    def normalize_key(cls, value: str) -> str:
        return resolve_panel(value)[0]


class SessionRequest(BaseModel):
    session_id: str
    panels: list[PanelRequest] = Field(default_factory=list)
    wait: int = Field(default=DEFAULT_WAIT, ge=MIN_WAIT_SECONDS, le=60)


class SessionEndRequest(BaseModel):
    session_id: str


def enforce_rate_limit(request: Request) -> None:
    if rate_limiter is None:
        return
    if not rate_limiter.allow(client_ip(request)):
        raise HTTPException(status_code=429, detail="rate limit exceeded")


@app.get("/api/meta")
def meta():
    return {
        "ufs": UFS,
        "categories": dashboard_categories(),
        "default_wait": DEFAULT_WAIT,
        "min_wait": MIN_WAIT_SECONDS,
        "session_ttl_seconds": SESSION_TTL_SECONDS,
    }


@app.post("/api/session")
def heartbeat(body: SessionRequest, request: Request):
    enforce_rate_limit(request)
    panels = [PanelConfig(key=p.key, printables=p.printables) for p in body.panels]
    snapshot = poller.touch_session(body.session_id, panels, body.wait)
    return {
        "wait": body.wait,
        "session_ttl_seconds": SESSION_TTL_SECONDS,
        "active_sessions": poller.active_session_count(),
        "panels": snapshot,
    }


@app.post("/api/session/end")
def end_session(body: SessionEndRequest, request: Request):
    enforce_rate_limit(request)
    poller.end_session(body.session_id)
    return Response(status_code=204)


@app.get("/api/status")
def status():
    if not DEBUG_ENDPOINTS:
        raise HTTPException(status_code=404)
    return poller.debug_status()


@app.get("/")
def index():
    return FileResponse(
        STATIC_DIR / "index.html",
        headers={"Cache-Control": "no-cache"},
    )


class NoCacheStaticFiles(StaticFiles):
    async def get_response(self, path, scope):
        response = await super().get_response(path, scope)
        if response.status_code == 200:
            response.headers["Cache-Control"] = "no-cache"
        return response


app.mount("/static", NoCacheStaticFiles(directory=STATIC_DIR), name="static")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "webapp:app" if DEBUG_ENDPOINTS else app,
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "8080")),
        reload=DEBUG_ENDPOINTS,
        reload_dirs=[str(Path(__file__).parent)] if DEBUG_ENDPOINTS else None,
    )
