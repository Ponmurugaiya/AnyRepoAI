"""Temporary debug script for Neo4j neighbor queries."""
import asyncio
import os

from neo4j import AsyncGraphDatabase

REPO_ID = "54d7db65-1700-4c4c-98ae-b804e91e0a39"
APP_NODE_ID = "7d9900e3-432f-460b-a8e6-ac88ba1eb761"


async def main() -> None:
    driver = AsyncGraphDatabase.driver(
        os.environ["NEO4J_URI"],
        auth=(os.environ["NEO4J_USER"], os.environ["NEO4J_PASSWORD"]),
    )
    async with driver.session() as session:
        q = (
            "MATCH (n:_GraphNode {id: $nid, repository_id: $rid}) "
            "OPTIONAL MATCH (n)-[r]->(out:_GraphNode) "
            "RETURN count(out) AS outgoing"
        )
        rec = await (await session.run(q, nid=APP_NODE_ID, rid=REPO_ID)).single()
        print("outgoing:", rec["outgoing"])

        q2 = (
            "MATCH (n:_GraphNode {id: $nid, repository_id: $rid}) "
            "OPTIONAL MATCH (n)<-[r]-(inc:_GraphNode) "
            "RETURN count(inc) AS incoming"
        )
        rec2 = await (await session.run(q2, nid=APP_NODE_ID, rid=REPO_ID)).single()
        print("incoming:", rec2["incoming"])

        # Same query as get_neighbors API
        cypher = (
            "MATCH (n:_GraphNode {id: $nid, repository_id: $rid}) "
            "MATCH (n)-[r]-(neighbor:_GraphNode) "
            "WHERE neighbor.repository_id = $rid "
            "RETURN neighbor.name AS name, type(r) AS rel "
            "LIMIT 5"
        )
        rows = await (await session.run(cypher, nid=APP_NODE_ID, rid=REPO_ID, limit=5)).data()
        print("both-direction neighbors:", rows)

    await driver.close()


if __name__ == "__main__":
    asyncio.run(main())
