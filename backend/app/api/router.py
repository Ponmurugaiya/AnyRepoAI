"""API v1 root router aggregator.

All route modules are combined here and included under the /api/v1 prefix.
"""

from fastapi import APIRouter

from backend.app.api.v1 import health
from backend.app.api.v1 import repositories
from backend.app.api.v1 import scanner
from backend.app.api.v1 import parser
from backend.app.symbol_index.api.router import router as symbol_index_router

api_v1_router = APIRouter()

# Register all v1 route modules
api_v1_router.include_router(health.router)
api_v1_router.include_router(repositories.router)
api_v1_router.include_router(scanner.router)
api_v1_router.include_router(parser.router)
api_v1_router.include_router(symbol_index_router)

# Future route modules will be added here, e.g.:
# api_v1_router.include_router(embeddings.router)
