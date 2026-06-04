"""
omnicovas.knowledge_base

Knowledge Base module — the AI's only allowed source of truth.

Law 5 (Zero Hallucination Doctrine):
    Every AI prompt must be grounded in KB entries. The AI never
    speaks about game mechanics without citing a KB entry.

Principle 6 (KB Stewardship):
    Every entry is version-tagged and audited. Schema violations
    fail CI. Stale entries are flagged for review.

See: Master Blueprint v4.0 Section 5 (Knowledge Base Stewardship)
See: Phase 1 Development Guide Week 4, Part B
"""

from omnicovas.knowledge_base.loader import (
    KBEntry,
    KnowledgeBase,
    load_knowledge_base,
)

__all__ = ["KBEntry", "KnowledgeBase", "load_knowledge_base"]
