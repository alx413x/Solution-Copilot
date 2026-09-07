from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class CustomerCreate(Input):
    name: Name
    industry: str = Field(default="", max_length=120)
    region: str = Field(default="", max_length=120)
    company_size: str = Field(default="", max_length=80)
    profile: dict = Field(default_factory=dict)


class CustomerUpdate(Input):
    name: Name | None = None
    industry: str | None = Field(default=None, max_length=120)
    region: str | None = Field(default=None, max_length=120)
    company_size: str | None = Field(default=None, max_length=80)
    profile: dict | None = None
    version: int = Field(ge=1)

    @field_validator("name", "industry", "region", "company_size", "profile")
    @classmethod
    def reject_null(cls, value):
        if value is None:
            raise ValueError("Use omitted fields to preserve existing values")
        return value


class VersionInput(Input):
    version: int = Field(ge=1)


class ProjectCreate(Input):
    name: Name
    description: str = Field(default="", max_length=10000)


class ProjectUpdate(Input):
    name: Name | None = None
    description: str | None = Field(default=None, max_length=10000)
    version: int = Field(ge=1)

    @field_validator("name", "description")
    @classmethod
    def reject_null(cls, value):
        if value is None:
            raise ValueError("Use omitted fields to preserve existing values")
        return value


class CustomerOut(CustomerCreate):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    organization_id: UUID
    version: int
    deleted_at: datetime | None
    created_at: datetime
    updated_at: datetime


class ProjectOut(ProjectCreate):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    organization_id: UUID
    customer_id: UUID
    owner_user_id: UUID
    owner_display_name: str
    status: str
    version: int
    settings: dict
    created_at: datetime
    updated_at: datetime


class CustomerPage(BaseModel):
    items: list[CustomerOut]
    next_cursor: UUID | None


class ProjectPage(BaseModel):
    items: list[ProjectOut]
    next_cursor: UUID | None
