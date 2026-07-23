"""Temporary debug script for Neo4j neighbor queries."""
import asyncio
import os

from neo4j import AsyncGraphDatabase

REPO_ID = "54d7db65-1700-4c4c-98ae-b804e91e0a39"
APP_NODE_ID = "7d9900e3-432f-460b-a8e6-ac88ba1eb761"
FUNC_NODE_ID = "b64f8045-2329-4cbc-89c1-906fb8dc6d1f"


async def main() -> None:
    driver = AsyncGraphDatabase.driver(
        os.environ["NEO4J_URI"],
        auth=(os.environ["NEO4J_USER"], os.environ["NEO4J_PASSWORD"]),
    )
    async with driver.session() as session:
        for label, nid in [("App", APP_NODE_ID), ("create_app", FUNC_NODE_ID)]:
            print(f"\n=== {label} ({nid}) ===")
            q = (
                "MATCH (n:_GraphNode {id: $nid, repository_id: $rid}) "
                "OPTIONAL MATCH (n)-[r]->(out:_GraphNode) "
                "RETURN count(out) AS outgoing"
            )
            rec = await (await session.run(q, nid=nid, rid=REPO_ID)).single()
            print("outgoing:", rec["outgoing"])

            q2 = (
                "MATCH (n:_GraphNode {id: $nid, repository_id: $rid}) "
                "OPTIONAL MATCH (n)<-[r]-(inc:_GraphNode) "
                "RETURN count(inc) AS incoming"
            )
            rec2 = await (await session.run(q2, nid=nid, rid=REPO_ID)).single()
            print("incoming:", rec2["incoming"])

            q3 = (
                "MATCH (n:_GraphNode {id: $nid, repository_id: $rid}) "
                "MATCH (n)-[r:DEFINES]->(m) "
                "RETURN m.name, m.qualified_name LIMIT 5"
            )
            rows = await (await session.run(q3, nid=nid, rid=REPO_ID)).data()
            print("DEFINES children:", rows)

    await driver.close()


if __name__ == "__main__":
    asyncio.run(main())
