"""Pydantic response models for the Plex Custom Metadata Provider protocol.

These models reflect the JSON envelope structure Plex expects from a registered
metadata provider agent.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class MediaProviderScheme(BaseModel):
    """A URI scheme supported by a media type."""

    model_config = ConfigDict(populate_by_name=True)

    scheme: str


class MediaProviderType(BaseModel):
    """A media type (e.g., 1 = Movie, 2 = TV Show) with its supported schemes."""

    model_config = ConfigDict(populate_by_name=True)

    type: int
    Scheme: list[MediaProviderScheme] = Field(default_factory=list)


class MediaProviderFeature(BaseModel):
    """A capability feature advertised by the provider (e.g., match, metadata)."""

    model_config = ConfigDict(populate_by_name=True)

    type: str
    key: str


class MediaProviderResponse(BaseModel):
    """Root MediaProvider object returned by the GET / manifest endpoint."""

    model_config = ConfigDict(populate_by_name=True)

    identifier: str
    title: str
    version: str
    Types: list[MediaProviderType] = Field(default_factory=list)
    Feature: list[MediaProviderFeature] = Field(default_factory=list)


class MediaContainerResponse(BaseModel):
    """Generic MediaContainer wrapper returned by match and metadata endpoints."""

    model_config = ConfigDict(populate_by_name=True)

    size: int = 0
    identifier: str = ""
    Metadata: list = Field(default_factory=list)
    offset: int | None = None
    totalSize: int | None = None
