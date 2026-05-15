"""
Memory Module - Store memories to SQLite + ChromaDB

Lazy-imports sentence_transformers and chromadb so the module
still loads (with degraded functionality) when they aren't installed.
"""

import uuid
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any

from database import get_db, now_utc, serialize_tags, row_to_dict
from config import settings
from modules.memory.importance import calculate_importance

# ── Lazy imports for heavy dependencies ──────────────────────────────────────
_chroma_client = None
_chroma_collection = None
_embedding_model = None

def _get_chroma():
    global _chroma_client, _chroma_collection
    if _chroma_collection is None:
        try:
            import chromadb
            _chroma_client = chromadb.PersistentClient(path=settings.chroma_persist_dir)
            _chroma_collection = _chroma_client.get_or_create_collection(
                name=settings.chroma_collection_name
            )
        except ImportError:
            pass
    return _chroma_collection

def _get_embedding_model():
    global _embedding_model
    if _embedding_model is None:
        try:
            from sentence_transformers import SentenceTransformer
            _embedding_model = SentenceTransformer(settings.embedding_model)
        except ImportError:
            pass
    return _embedding_model


async def store_memory(
    agent_id: str,
    content: str,
    memory_type: str = "episodic",
    importance: float = 0.5,
    tags: List[str] = None
) -> Dict[str, Any]:
    """Store a new memory. Auto-generates embedding if sentence_transformers is available."""
    if tags is None:
        tags = []

    memory_id = str(uuid.uuid4())
    created_at = now_utc()
    final_importance = calculate_importance(content, memory_type, importance)

    # Generate embedding (graceful fallback)
    embedding = []
    model = _get_embedding_model()
    if model is not None:
        try:
            embedding = model.encode(content).tolist()
        except Exception:
            embedding = []

    summary = content[:100] + "..." if len(content) > 100 else content

    # Store in SQLite
    db = await get_db()
    try:
        await db.execute(
            """
            INSERT INTO memories
            (id, agent_id, content, summary, importance, memory_type, tags,
             created_at, last_accessed, access_count, decay_score)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (memory_id, agent_id, content, summary, final_importance, memory_type,
             serialize_tags(tags), created_at, created_at, 0, 1.0)
        )
        await db.commit()
    finally:
        await db.close()

    # Store in ChromaDB (graceful fallback)
    collection = _get_chroma()
    if collection is not None and embedding:
        try:
            collection.add(
                ids=[memory_id],
                embeddings=[embedding],
                metadatas=[{
                    "agent_id": agent_id,
                    "content": content,
                    "memory_type": memory_type,
                    "importance": final_importance,
                    "tags": serialize_tags(tags),
                    "created_at": created_at
                }],
                documents=[content]
            )
        except Exception:
            pass

    return {
        "id": memory_id,
        "agent_id": agent_id,
        "content": content,
        "summary": summary,
        "importance": final_importance,
        "memory_type": memory_type,
        "tags": tags,
        "created_at": created_at,
        "embedding": embedding,
    }


async def delete_memory(agent_id: str, memory_id: str) -> bool:
    """Delete a specific memory."""
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT agent_id FROM memories WHERE id = ?", (memory_id,)
        )
        row = await cursor.fetchone()
        if row is None or row["agent_id"] != agent_id:
            return False
        await db.execute("DELETE FROM memories WHERE id = ?", (memory_id,))
        await db.commit()
    finally:
        await db.close()

    collection = _get_chroma()
    if collection is not None:
        try:
            collection.delete(ids=[memory_id])
        except Exception:
            pass

    return True


async def update_memory_importance(agent_id: str, memory_id: str, importance: float) -> bool:
    """Update the importance score of a specific memory."""
    importance = max(0.0, min(1.0, importance))
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT agent_id FROM memories WHERE id = ?", (memory_id,)
        )
        row = await cursor.fetchone()
        if row is None or row["agent_id"] != agent_id:
            return False
        await db.execute(
            "UPDATE memories SET importance = ? WHERE id = ?",
            (importance, memory_id)
        )
        await db.commit()
    finally:
        await db.close()
    return True
