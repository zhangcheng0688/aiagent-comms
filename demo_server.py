"""迷你静态服务，专门给 demo.html 用。端口 8767。"""
from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

app = FastAPI()
FRONTEND = Path(__file__).resolve().parent / "frontend"

app.mount("/static", StaticFiles(directory=str(FRONTEND)), name="static")


@app.get("/")
async def root():
    return FileResponse(FRONTEND / "index.html")


@app.get("/{name}.html")
async def html(name: str):
    p = FRONTEND / f"{name}.html"
    if p.exists():
        return FileResponse(p)
    return {"error": "not found"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8767, log_level="warning")
