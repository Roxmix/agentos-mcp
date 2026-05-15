"""
Memory Module - Semantic search + keyword fallback

Falls back to keyword/SQLite search when ChromaDB or sentence_transformers
are not available.
"""

from typing import List, Dict, Any, Optional
from database import get_db, parse_tags, row_to_dict, now_utc


async def search_memories(
    agent_id: str,
    query: str,
    limit: int = 5,
    memory_type: Optional[str] = None,
    min_importance: float = 0.0
) -> List[Dict[str, Any]]:
    """
    Semantically search memories. Falls back to keyword search
    when ChromaDB/sentence_transformers are unavailable.
    """
    # Try ChromaDB first
    try:
        from modules.memory.store import _get_chroma, _get_embedding_model
        collection = _get_chroma()
        model = _get_embedding_model()

        if collection is not None and model is not None:
            query_embedding = model.encode(query).tolist()
            where_filter = {"agent_id": agent_id}
            if memory_type:
                where_filter["memory_type"] = memory_type

            try:
                collection_count = collection.count()
            except Exception:
                collection_count = 0

            if collection_count > 0:
                safe_n_results = min(limit * 2, collection_count)
                results = collection.query(
                    query_embeddings=[query_embedding],
                    n_results=safe_n_results,
                    where=where_filter,
                    include=["metadatas", "distances"]
                )

                similarity_scores: Dict[str, float] = {}
                if results["ids"] and len(results["ids"]) > 0:
                    for mem_id, distance in zip(results["ids"][0], results["distances"][0]):
                        similarity_scores[mem_id] = max(0.0, 1.0 - distance)

                if similarity_scores:
                    memories = await _fetch_and_rank(
                        agent_id, similarity_scores, min_importance, limit
                    )
                    if memories:
                        return memories
    except Exception:
        pass

    # Fallback: keyword search in SQLite
    return await _keyword_search(agent_id, query, limit, memory_type, min_importance)


async def _fetch_and_rank(
    agent_id: str,
    similarity_scores: Dict[str, float],
    min_importance: float,
    limit: int,
) -> List[Dict[str, Any]]:
    db = await get_db()
    memories = []
    try:
        for memory_id in similarity_scores:
            cursor = await db.execute(
                "SELECT * FROM memories WHERE id = ? AND importance >= ?",
                (memory_id, min_importance)
            )
            row = await cursor.fetchone()
            if row:
                memory = row_to_dict(row)
                memory["tags"] = parse_tags(memory.get("tags", "[]"))
                memory["_similarity"] = similarity_scores[memory_id]
                memories.append(memory)
    finally:
        await db.close()

    if memories:
        db = await get_db()
        try:
            current_time = now_utc()
            for memory in memories:
                await db.execute(
                    "UPDATE memories SET last_accessed = ?, access_count = access_count + 1 WHERE id = ?",
                    (current_time, memory["id"])
                )
            await db.commit()
        finally:
            await db.close()

    def rank_memory(memory: Dict[str, Any]) -> float:
        similarity = memory.get("_similarity", 0.0)
        importance = memory.get("importance", 0.5)
        decay = memory.get("decay_score", 1.0)
        return (similarity * 0.5) + (importance * 0.3) + (decay * 0.2)

    memories.sort(key=rank_memory, reverse=True)
    for memory in memories:
        memory.pop("_similarity", None)

    return memories[:limit]


async def _keyword_search(
    agent_id: str,
    query: str,
    limit: int,
    memory_type: Optional[str],
    min_importance: float,
) -> List[Dict[str, Any]]:
    """Fallback keyword search using SQLite LIKE."""
    db = await get_db()
    try:
        # Split query into words for multi-word search
        words = query.split()
        conditions = []
        params = [agent_id, min_importance]

        for word in words:
            conditions.append("(content LIKE ? OR summary LIKE ?)")
        params.extend([f"%{word}%", f"%{word}%"] for word in words)

        if memory_type:
            params.append(memory_type)

        where_clause = " AND ".join(conditions)
        type_filter = "AND memory_type = ?" if memory_type else ""

        sql = f"""
            SELECT * FROM memories
            WHERE agent_id = ? AND importance >= ? AND ({where_clause}) {type_filter}
            ORDER BY importance DESC, created_at DESC
            LIMIT ?
        """
        params.append(limit)

        cursor = await db.execute(sql, params)
        rows = await cursor.fetchall()
        memories = []
        for row in rows:
            memory = row_to_dict(row)
            memory["tags"] = parse_tags(memory.get("tags", "[]"))
            memories.append(memory)
        return memories
    finally:
        await db.close()


async def list_memories(
    agent_id: str,
    memory_type: Optional[str] = None,
    limit: int = 20,
    offset: int = 0
) -> List[Dict[str, Any]]:
    """List recent memories with optional type filter."""
    db = await get_db()
    try:
        if memory_type:
            cursor = await db.execute(
                """
                SELECT * FROM memories
                WHERE agent_id = ? AND memory_type = ?
                ORDER BY created_at DESC
                LIMIT ? OFFSET ?
                """,
                (agent_id, memory_type, limit, offset)
            )
        else:
            cursor = await db.execute(
                """
                SELECT * FROM memories
                WHERE agent_id = ?
                ORDER BY created_at DESC
                LIMIT ? OFFSET ?
                """,
                (agent_id, limit, offset)
            )

        rows = await cursor.fetchall()
        memories = []
        for row in rows:
            memory = row_to_dict(row)
            memory["tags"] = parse_tags(memory.get("tags", "[]"))
            memories.append(memory)
        return memories
    finally:
        await db.close()
