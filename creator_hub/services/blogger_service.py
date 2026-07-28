"""Blogger service facade."""
from ..legacy_app import (
    get_blogs,
    upsert_blogger_post,
    article_content_for_blogger,
    blogger_service,
)

__all__ = [
    "get_blogs",
    "upsert_blogger_post",
    "article_content_for_blogger",
    "blogger_service",
]
