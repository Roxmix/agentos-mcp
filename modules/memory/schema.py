"""
Memory Module - Data Models
"""

from pydantic import BaseModel
from datetime import datetime
from typing import Optional, List


class Memory(BaseModel):
    id: str
    agent_id: str
    content: str
    summary: str
    importance: float
    memory_type: str
    tags: List[str]
    embedding: List[float]
    created_at: datetime
    last_accessed: datetime
    access_count: int
    decay_score: float
