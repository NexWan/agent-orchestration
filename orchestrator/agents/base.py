from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any
from enum import Enum

class AgentRole(Enum):
    ARCHITECT = "architect"
    IMPLEMENTER = "implementer"
    REVIEWER = "reviewer"
    TESTER = "tester"
    DEVOPS = "devops"
    QA = "qa"

@dataclass
class AgentResult:
    success: bool
    agent_name: str
    role: AgentRole
    output: str = ""
    files_written = list[str] = field(default_factory=list)
    error: str | None = None
    tokens_used: int = 0

    def __bool__(self) -> bool:
        return self.success
    

class AgentAdapter(ABC):
    @property
    @abstractmethod
    def name(self) -> str:
        pass

    @property
    @abstractmethod
    def role(self) -> AgentRole:
        pass

    @abstractmethod
    async def execute(self, prompt: str, context: dict[str, Any]) -> AgentResult:
        pass

    def build_prompt(self, task: str, context: dict[str, Any]) -> str:
        project = context.get("project_description", "")
        artifacts = context.get("artifacts", {})
        phase = context.get("current_phase", 0)

        artifact_summary = ""
        if artifacts:
            artifact_summary = "\n\nArtifacts from previous phases:\n"
            for name, content in artifacts.items():
                preview = str(content)[:300] + "..." if len(str(content)) > 300 else str(content)
                artifact_summary += f"- {name}: {preview}\n"

        return f"""Project: {project}
Current Phase: {phase}
Your Role: {self.role.value}
{artifact_summary}
 
 Your task: {task}

IMPORTANT:
- Write all files directly to the filesystem or the workspace. Do not return file contents in the output.
- Once finished, list exactly what files you have written or modified in the "files_written" field of the AgentResult. Do not include any file contents in the output.
- Be concise in your output. Only include necessary information and the list of files written. Do not include any file contents or lengthy explanations in the output.
"""
    

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} role={self.role.value}>"