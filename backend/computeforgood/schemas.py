from typing import Literal
from pydantic import BaseModel, Field

Risk = Literal["LOW", "NORMAL", "HIGH", "CRITICAL"]
Tier = Literal["BASIC", "STRONG", "FRONTIER"]


class TokenBody(BaseModel):
    token: str = Field(min_length=1, max_length=500)


class CheckpointBody(TokenBody):
    summary: str = Field(min_length=1, max_length=10000)
    branch_url: str | None = Field(default=None, max_length=1000)


class PermitBody(BaseModel):
    lease_token: str = Field(min_length=1, max_length=500)


class SubmissionBody(BaseModel):
    permit_token: str = Field(min_length=1, max_length=500)
    pr_url: str = Field(min_length=1, max_length=1000)
    head_sha: str = Field(pattern=r"^[0-9a-fA-F]{7,64}$")
    summary: str = Field(default="", max_length=10000)


class Finding(BaseModel):
    severity: Risk
    description: str = Field(min_length=1, max_length=10000)


class ReviewBody(BaseModel):
    review_lease_id: str | None = None
    review_lease_token: str | None = None
    head_sha: str = Field(pattern=r"^[0-9a-fA-F]{7,64}$")
    decision: Literal["APPROVE", "REQUEST_CHANGES", "BLOCK"]
    summary: str = Field(min_length=1, max_length=10000)
    findings: list[Finding] = Field(default_factory=list, max_length=100)


class ProjectUpdate(BaseModel):
    status: Literal["VERIFIED", "REJECTED"]
    required_checks: list[str] | None = Field(default=None, max_length=50)
    readiness_confirmed: bool = False


class TaskCreate(BaseModel):
    id: str | None = Field(default=None, max_length=64)
    project_id: str
    title: str = Field(min_length=1, max_length=300)
    description: str = Field(default="", max_length=20000)
    difficulty: Literal["EASY", "MEDIUM", "HARD", "EXPERT"] = "EASY"
    risk: Risk = "LOW"
    required_model_tier: Tier = "BASIC"
    estimated_minutes: int = Field(default=45, ge=1, le=1440)
    status: Literal["DRAFT", "AVAILABLE"] = "AVAILABLE"
    acceptance_criteria: list[str] = Field(min_length=1, max_length=100)
    allowed_paths: list[str] = Field(default_factory=list, max_length=100)
    forbidden_paths: list[str] = Field(default_factory=list, max_length=100)
    verification_commands: list[str] = Field(min_length=1, max_length=100)
