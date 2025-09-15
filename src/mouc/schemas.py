"""Pydantic schemas for YAML data validation."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, field_validator


class CapabilitySchema(BaseModel):
    """Schema for capability YAML data."""

    name: str
    description: str
    dependencies: list[str] = Field(default_factory=list)
    links: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)

    @field_validator("dependencies", "tags", "links", mode="before")
    @classmethod
    def ensure_list(cls, v: Any) -> list[str]:
        """Ensure value is a list."""
        if v is None:
            return []
        if isinstance(v, list):
            return [str(item) for item in v]  # type: ignore[misc]
        return [str(v)]


class UserStorySchema(BaseModel):
    """Schema for user story YAML data."""

    name: str
    description: str
    dependencies: list[str] = Field(default_factory=list)
    requestor: str | None = None
    links: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)

    @field_validator("dependencies", "tags", "links", mode="before")
    @classmethod
    def ensure_list(cls, v: Any) -> list[str]:
        """Ensure value is a list."""
        if v is None:
            return []
        if isinstance(v, list):
            return [str(item) for item in v]  # type: ignore[misc]
        return [str(v)]


class OutcomeSchema(BaseModel):
    """Schema for outcome YAML data."""

    name: str
    description: str
    dependencies: list[str] = Field(default_factory=list)
    links: list[str] = Field(default_factory=list)
    target_date: str | None = None
    tags: list[str] = Field(default_factory=list)

    @field_validator("dependencies", "tags", "links", mode="before")
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
    capabilities: dict[str, CapabilitySchema] = Field(default_factory=dict)
    user_stories: dict[str, UserStorySchema] = Field(default_factory=dict)
    outcomes: dict[str, OutcomeSchema] = Field(default_factory=dict)
