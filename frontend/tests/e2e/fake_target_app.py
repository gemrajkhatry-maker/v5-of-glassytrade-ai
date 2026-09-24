from __future__ import annotations

from fastapi import FastAPI, WebSocket
from fastapi.responses import HTMLResponse

app = FastAPI()

PAGE = """<!doctype html>
<html><body><main><h1>Target Projection</h1>
<p data-testid="runtime-status">unknown</p></main>
<script>
fetch('/api/v1/runtime').then(r => r.json()).then(body => {
  document.querySelector('[data-testid=runtime-status]').textContent = body.status;
});
</script></body></html>"""


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/", response_class=HTMLResponse)
def page() -> str:
    return PAGE


@app.get("/api/v1/runtime")
def runtime() -> dict[str, str]:
    return {"schemaVersion": "1.0", "status": "degraded"}


@app.websocket("/api/v1/ws/projections")
async def projections(websocket: WebSocket) -> None:
    await websocket.accept()
    await websocket.send_json(
        {
            "schemaVersion": "1.0",
            "projectionVersion": 1,
            "projectionId": "runtime-test",
            "scope": {"type": "runtime"},
            "sequence": 1,
            "baseSequence": None,
            "asOf": "2026-09-24T10:00:00+00:00",
            "releaseId": "test-release",
            "configFingerprint": "test-fingerprint",
            "mode": "paper",
            "type": "snapshot",
            "payload": {"status": "degraded"},
        }
    )
    await websocket.close()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=4173)
