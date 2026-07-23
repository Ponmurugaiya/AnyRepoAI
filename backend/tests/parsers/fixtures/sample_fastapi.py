"""Sample FastAPI application used to test route detection."""

from fastapi import APIRouter, FastAPI

app = FastAPI(title="Sample API")
router = APIRouter(prefix="/api/v1")


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy"}


@router.post("/users")
async def create_user(body: dict):
    """Create a new user."""
    return {"id": 1, **body}


@router.get("/users/{user_id}")
async def get_user(user_id: int):
    """Get a user by ID."""
    return {"id": user_id}


@router.put("/users/{user_id}")
async def update_user(user_id: int, body: dict):
    """Update a user."""
    return {"id": user_id, **body}


@router.delete("/users/{user_id}")
async def delete_user(user_id: int):
    """Delete a user."""
    return {"deleted": user_id}
