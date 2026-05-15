"""
Memory Module - Importance Scoring Logic
"""

import re


def calculate_importance(
    content: str,
    memory_type: str,
    user_score: float
) -> float:
    """
    Combines:
    - user-provided score (weight: 0.5)
    - content length heuristic (weight: 0.2)
    - memory type weight:
        procedural = 0.9 (high — learned skills)
        semantic   = 0.7 (medium — facts)
        episodic   = 0.5 (base — events)
    - keyword signals: "important", "never forget", "always" → boost
    Returns float 0.0–1.0
    """
    # Clamp user score
    user_score = max(0.0, min(1.0, user_score))

    # Memory type weight
    type_weights = {
        "procedural": 0.9,
        "semantic": 0.7,
        "episodic": 0.5
    }
    type_weight = type_weights.get(memory_type, 0.5)

    # Content length heuristic (0.0 to 1.0)
    # More detailed content tends to be more important
    length_score = min(len(content) / 500, 1.0)

    # Keyword signals boost
    keyword_boost = 0.0
    important_keywords = [
        "important", "never forget", "always", "critical", 
        "essential", "crucial", "must remember", "key"
    ]
    content_lower = content.lower()
    for keyword in important_keywords:
        if keyword in content_lower:
            keyword_boost += 0.05
    keyword_boost = min(keyword_boost, 0.2)  # Cap at 0.2

    # Calculate composite score
    composite = (
        user_score * 0.5 +
        length_score * 0.2 +
        type_weight * 0.2 +
        keyword_boost
    )

    return round(max(0.0, min(1.0, composite)), 4)
