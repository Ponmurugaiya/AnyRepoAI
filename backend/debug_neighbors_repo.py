"""Debug GraphRepository.get_neighbors."""
import asyncio

from backend.app.infrastructure.neo4j_client import get_neo4j
from backend.app.graph.repositories.graph_repository import GraphRepository

REPO_ID = "54d7db65-1700-4c4c-98ae-b804e91e0a39"
APP_NODE_ID = "7d9900e3-432f-460b-a8e6-ac88ba1eb761"


async def main() -> None:
    driver = get_neo4j()
    repo = GraphRepository(driver)
    records = await repo.get_neighbors(
        REPO_ID,
        APP_NODE_ID,
        direction="both",
        edge_types=None,
        limit=5,
    )
    print("count", len(records))
    for r in records[:3]:
        print(r["node"].get("name"), r["relationship"].get("type"))


if __name__ == "__main__":
    asyncio.run(main())
