"""Shared extension registry for future route/service extraction.

The current production database object remains in legacy_app during the safe
migration. New modules should import extensions from here only after each
feature is moved and tested.
"""
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()
