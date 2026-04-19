"""FastAPI HTTP server — thin wrapper over :class:`CodeIndex`.

Endpoints mirror the MCP tools 1-to-1. All SQL work is dispatched to a
threadpool because :class:`SqliteConnector` is per-thread; the shared
``CodeIndex`` is safe to call from any thread.

Enable by installing the ``http`` extra::

    uv pip install "bindwood[http]"

Then::

    bindwood serve --host 0.0.0.0 --port 8765

Set ``BINDWOOD_API_KEY`` to require ``Authorization: Bearer <key>`` on
every request. Unset → open (single-user localhost default).
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

try:
    from fastapi import Depends, FastAPI, HTTPException, Request, status
    from fastapi.concurrency import run_in_threadpool
    from fastapi.responses import HTMLResponse
    from pydantic import BaseModel, Field
except ImportError as e:  # pragma: no cover - only triggered without the extra
    raise ImportError(
        "The HTTP server requires the 'http' extra. Install with:\n"
        "    uv pip install 'bindwood[http]'"
    ) from e

from bindwood import CodeIndex
from bindwood.config import load_raw_config
from bindwood.config.resolver import resolve_config_path


# ── Request schemas ──────────────────────────────────────────


class SearchRequest(BaseModel):
    query: str
    limit: int = 10
    target: str | None = None


class SliceRequest(BaseModel):
    seeds: list[str] = Field(..., min_length=1)
    depth: int = 2
    direction: str = "out"
    edge_kinds: list[str] | None = None
    max_nodes: int = 200
    target: str | None = None


class TraceRequest(BaseModel):
    from_node: str
    to_node: str
    from_target: str | None = None
    to_target: str | None = None
    max_depth: int = 3


# ── App factory ──────────────────────────────────────────────


def _resolve_api_key() -> str | None:
    """Resolve the API key. Env wins over config; unset means open access.

    Precedence:
      1. ``BINDWOOD_API_KEY`` (or legacy ``GTG_API_KEY``) environment var
      2. ``server.api_key`` in the loaded config file
      3. ``None`` → the server runs unauthenticated
    """
    env_val = os.environ.get("BINDWOOD_API_KEY") or os.environ.get("GTG_API_KEY")
    if env_val:
        return env_val
    cfg_path = resolve_config_path()
    if not cfg_path:
        return None
    cfg = load_raw_config(cfg_path)
    return (cfg.get("server") or {}).get("api_key") or None


def create_app(index: CodeIndex | None = None) -> FastAPI:
    """Build the FastAPI app. ``index`` defaults to a zero-config CodeIndex."""
    idx = index if index is not None else CodeIndex()
    api_key = _resolve_api_key()

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        yield
        idx.close()

    app = FastAPI(
        title="Graph Tree Generator",
        description="HTTP access to the code graph index.",
        version="1.0.0",
        lifespan=lifespan,
    )

    async def require_key(request: Request) -> None:
        if not api_key:
            return
        header = request.headers.get("authorization", "")
        if not header.startswith("Bearer ") or header[7:] != api_key:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or missing Bearer token.",
            )

    auth = [Depends(require_key)]

    # ── Endpoints ────────────────────────────────────────────

    @app.get("/health")
    async def health() -> dict:
        return {"status": "ok", "db_path": str(idx.db_path)}

    @app.get("/v1/overview", dependencies=auth)
    async def overview() -> dict:
        return await run_in_threadpool(idx.overview)

    @app.post("/v1/search", dependencies=auth)
    async def search(req: SearchRequest) -> list[dict]:
        try:
            return await run_in_threadpool(
                idx.search, req.query, req.limit, req.target
            )
        except RuntimeError as e:
            raise HTTPException(status_code=503, detail=str(e))

    @app.get("/v1/find", dependencies=auth)
    async def find(
        type: str | None = None,
        name: str | None = None,
        target: str | None = None,
        file: str | None = None,
        label: str | None = None,
        limit: int = 20,
    ) -> list[dict]:
        try:
            return await run_in_threadpool(
                idx.find_nodes,
                type=type,
                name=name,
                target=target,
                file=file,
                label=label,
                limit=limit,
            )
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

    # Declare the /neighbors subroute *before* the bare {node_id:path}
    # route — Starlette evaluates routes in declaration order and `:path`
    # matches greedily across slashes, which would otherwise swallow it.
    @app.get("/v1/nodes/{node_id:path}/neighbors", dependencies=auth)
    async def neighbors(
        node_id: str,
        target: str | None = None,
        direction: str = "both",
        edge_type: str | None = None,
    ) -> dict:
        try:
            return await run_in_threadpool(
                idx.get_neighbors, node_id, target, direction, edge_type
            )
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

    @app.get("/v1/nodes/{node_id:path}", dependencies=auth)
    async def get_node(node_id: str, target: str | None = None) -> list[dict]:
        return await run_in_threadpool(idx.get_node, node_id, target)

    @app.post("/v1/slice", dependencies=auth)
    async def slice_(req: SliceRequest) -> dict:
        try:
            return await run_in_threadpool(
                idx.slice,
                req.seeds,
                target=req.target,
                depth=req.depth,
                direction=req.direction,
                edge_kinds=req.edge_kinds,
                max_nodes=req.max_nodes,
            )
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

    @app.post("/v1/trace", dependencies=auth)
    async def trace(req: TraceRequest) -> dict:
        return await run_in_threadpool(
            idx.trace_path,
            req.from_node,
            req.to_node,
            from_target=req.from_target,
            to_target=req.to_target,
            max_depth=req.max_depth,
        )

    @app.get("/v1/tables/{name}", dependencies=auth)
    async def table_schema(name: str) -> dict:
        return await run_in_threadpool(idx.get_table_schema, name)

    # ── Visualization (browser UI) ───────────────────────────
    _mount_viz(app, idx)

    return app


# ── Visualization mount ──────────────────────────────────────


def _mount_viz(app: FastAPI, idx: CodeIndex) -> None:
    """Mount the /viz/* HTML routes. Silently skipped if viz extra missing."""
    try:
        from jinja2 import Environment, FileSystemLoader, select_autoescape

        from bindwood.viz import (
            figure_label_heatmap,
            figure_project_graph,
            figure_project_treemap,
        )
    except ImportError:  # pragma: no cover — viz extra not installed
        return

    templates_dir = Path(__file__).resolve().parent.parent / "viz" / "templates"
    env = Environment(
        loader=FileSystemLoader(str(templates_dir)),
        autoescape=select_autoescape(["html"]),
    )

    renderers = {
        "graph": figure_project_graph,
        "treemap": figure_project_treemap,
        "heatmap": figure_label_heatmap,
    }

    def _plot_html(fig) -> str:
        # full_html=False gives just the <div> + init script; plotly.js
        # is loaded from CDN (one <script> tag) so pages stay small.
        return fig.to_html(include_plotlyjs="cdn", full_html=False)

    @app.get("/viz/", response_class=HTMLResponse, include_in_schema=False)
    async def viz_index() -> str:
        overview = await run_in_threadpool(idx.overview)
        tpl = env.get_template("index.html")
        return tpl.render(
            targets=overview["targets"],
            overview=overview,
            db_path=str(idx.db_path),
        )

    @app.get(
        "/viz/{target}/{tab}",
        response_class=HTMLResponse,
        include_in_schema=False,
    )
    async def viz_tab(target: str, tab: str) -> str:
        renderer = renderers.get(tab)
        if not renderer:
            raise HTTPException(
                status_code=404,
                detail=f"Unknown tab {tab!r}. Available: {list(renderers)}",
            )
        fig = await run_in_threadpool(renderer, idx, target)
        tpl = env.get_template("tab.html")
        return tpl.render(
            target=target,
            tab=tab,
            plot=_plot_html(fig),
            db_path=str(idx.db_path),
        )


# ── Runner ───────────────────────────────────────────────────


def run(host: str = "127.0.0.1", port: int = 8765, reload: bool = False) -> None:
    """Entry point for ``bindwood serve``."""
    try:
        import uvicorn
    except ImportError as e:  # pragma: no cover
        raise ImportError(
            "uvicorn is required to run the HTTP server. Install with:\n"
            "    uv pip install 'bindwood[http]'"
        ) from e

    # When reload=True, uvicorn needs an import string (not an app object)
    # so it can reimport after file changes.
    if reload:
        uvicorn.run(
            "bindwood.servers.http:create_app",
            factory=True,
            host=host,
            port=port,
            reload=True,
        )
    else:
        uvicorn.run(create_app(), host=host, port=port)


if __name__ == "__main__":
    run()
