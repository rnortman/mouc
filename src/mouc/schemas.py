"""Pydantic schemas for YAML data validation."""

from __future__ import annotations

import sys
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator


class EntitySchema(BaseModel):
    """Schema for unified entity YAML data."""

    type: str | None = None  # Optional for backward compatibility
    name: str
    description: str
    requires: list[str] = Field(default_factory=list)
    enables: list[str] = Field(default_factory=list)
    dependencies: list[str] | None = None  # Deprecated alias for requires
    links: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    meta: dict[str, Any] = Field(default_factory=dict)
    workflow: str | None = None  # Workflow name to expand this entity
    phases: dict[str, dict[str, Any]] | None = None  # Per-phase overrides

    @model_validator(mode="after")
    def handle_dependencies_alias(self) -> EntitySchema:
        """Handle backward compatibility for 'dependencies' field."""
        if self.dependencies is not None:
            if self.requires:
                raise ValueError(
                    "Cannot specify both 'dependencies' and 'requires'. "
                    "Use 'requires' (dependencies is deprecated)."
                )
            # Emit deprecation warning to stderr
            sys.stderr.write(
                "WARNING: 'dependencies' field is deprecated. Use 'requires' instead.\n"
            )
            # Copy dependencies to requires
            self.requires = self.dependencies
            self.dependencies = None
        return self

    @field_validator("requires", "enables", "tags", "links", mode="before")
    @classmethod
    def ensure_list(cls, v: Any) -> list[str]:
        """Ensure value is a list."""
        if v is None:
            return []
        if isinstance(v, list):
            return [str(item) for item in v]  # type: ignore[misc]
        return [str(v)]


class MetadataSchema(BaseModel):
    """Schema for metadata YAML data."""

    version: str = "1.0"
    last_updated: str | None = None
    team: str | None = None

    @field_validator("version", mode="before")
    @classmethod
    def coerce_version_to_string(cls, v: Any) -> str:
        """Ensure version is a string."""
        return str(v)

    @field_validator("last_updated", mode="before")
    @classmethod
    def coerce_date_to_string(cls, v: Any) -> str | None:
        """Convert date objects to string."""
        if v is None:
            return None
        return str(v)


class FeatureMapSchema(BaseModel):
    """Schema for the entire feature map YAML data."""

    metadata: MetadataSchema = Field(default_factory=MetadataSchema)
    # New format: all entities under 'entities' key with explicit type
    entities: dict[str, EntitySchema] = Field(default_factory=dict)
    # Old format: entities grouped by type
    capabilities: dict[str, EntitySchema] = Field(default_factory=dict)
    user_stories: dict[str, EntitySchema] = Field(default_factory=dict)
    outcomes: dict[str, EntitySchema] = Field(default_factory=dict)
