from pathlib import Path
from typing import Dict, Optional
import logging

logger = logging.getLogger(__name__)


class KnowledgeService:
    """
    Singleton-like service to load and cache industry standard documents
    from the domain_knowledge directory.
    """

    _instance = None
    _cache: Dict[str, str] = {}

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(KnowledgeService, cls).__new__(cls)
            cls._instance._load_knowledge_base()
        return cls._instance

    def _load_knowledge_base(self):
        """Loads all markdown files from the domain_knowledge directory into memory."""
        # Adjust path based on execution context
        base_dir = Path(__file__).parent.parent / "app" / "domain_knowledge"

        if not base_dir.exists():
            logger.warning(f"Knowledge base directory {base_dir} not found.")
            return

        for file_path in base_dir.glob("*.md"):
            try:
                category = file_path.stem.replace("_standards", "").lower()
                content = file_path.read_text(encoding="utf-8")
                self._cache[category] = content
                logger.info(f"Loaded knowledge base for: {category}")
            except Exception as e:
                logger.error(f"Failed to load knowledge file {file_path}: {e}")

    def get_domain_context(self, category: Optional[str] = None) -> str:
        """
        Returns the specific rules text for a category, or all combined if category is None.
        """
        if category:
            return self._cache.get(category.lower(), "")

        # Return all combined if no specific category requested
        return "\n\n".join(self._cache.values())

    def refresh(self):
        """Force reload from disk (useful for dev)."""
        self._cache.clear()
        self._load_knowledge_base()


# Global singleton instance
knowledge_service = KnowledgeService()
