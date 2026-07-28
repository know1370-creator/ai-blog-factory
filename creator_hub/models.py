"""V9 model migration map.

Production models currently live in legacy_app to preserve the existing
database tables and migrations. Re-exporting them here gives new modules a
stable import path without creating duplicate SQLAlchemy model definitions.
"""
from .legacy_app import Article, PublishLog, ContentIdea, AppSetting

__all__ = ["Article", "PublishLog", "ContentIdea", "AppSetting"]
