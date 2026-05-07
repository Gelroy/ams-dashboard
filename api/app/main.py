from fastapi import FastAPI

from app.api.organizations import router as organizations_router

app = FastAPI(title="AMS Dashboard API", version="0.1.0")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


app.include_router(organizations_router)
