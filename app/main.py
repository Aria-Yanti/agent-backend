from __future__ import annotations

import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .routes import router
from .runtime import llm_gateway
from .settings_bridge import apply_structured_settings, normalize_structured_settings
from .store import store


PUBLIC_IP = os.getenv("PUBLIC_IP", "127.0.0.1")

app = FastAPI(
    title="Agent Playground API",
    description="Backend service for agent/workflow/trace playground demos.",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        f"http://{PUBLIC_IP}:3000",
        f"http://{PUBLIC_IP}:5173",
        "http://localhost:3000",
        "http://localhost:5173",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:5173",
        "null",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def on_startup() -> None:
    store.seed_defaults()
    store.ensure_auditbrain_defaults()
    stored_settings = store.get_app_settings_payload()
    if stored_settings:
        normalized = normalize_structured_settings(stored_settings)
        apply_structured_settings(stored_settings, normalized)
        llm_gateway.refresh_client()


app.include_router(router)
