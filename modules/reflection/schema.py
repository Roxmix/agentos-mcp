"""
Reflection Module - Data Models
"""

from pydantic import BaseModel
from datetime import datetime
from typing import Optional, List, Dict, Any


class ReflectionLog(BaseModel):
    id: str
    agent_id: str
    action: str
    outcome: str
    success: bool
    context: str
    tags: List[str]
    goal_id: Optional[str]
    created_at: datetime
    metadata: Dict[str, Any]


class Pattern(BaseModel):
    id: str
    agent_id: str
    pattern_type: str
    description: str
    frequency: int
    first_seen: datetime
    last_seen: datetime
    related_tags: List[str]
    suggested_action: str
