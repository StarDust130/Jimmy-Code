from pydantic import BaseModel, Field


class ProjectFingerprint(BaseModel):
    root: str
    languages: list[str] = Field(default_factory=list)
    frameworks: list[str] = Field(default_factory=list)
    package_managers: list[str] = Field(default_factory=list)
    config_files: list[str] = Field(default_factory=list)
    test_directories: list[str] = Field(default_factory=list)
    important_files: list[str] = Field(default_factory=list)


class ExplorationResult(BaseModel):
    fingerprint: ProjectFingerprint
    tree: list[str] = Field(default_factory=list)
