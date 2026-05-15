"""
Goals Module - Data Models
"""

from pydantic import BaseModel
from datetime import datetime
from typing import Optional, List, Dict, Any


class Goal(BaseModel):
    id: str
    agent_id: str
    title: str
    description: str
    priority: float
    urgency: float
    status: str
    progress: float
    parent_goal_id: Optional[str]
    tags: List[str]
    deadline: Optional[datetime]
    created_at: datetime
    updated_at: datetime
    completion_notes: Optional[str]
    retry_count: int
    metadata: Dict[str, Any]
