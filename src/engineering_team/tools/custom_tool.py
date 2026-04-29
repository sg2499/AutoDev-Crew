from typing import Type

from crewai.tools import BaseTool
from pydantic import BaseModel, Field


class ProjectNoteInput(BaseModel):
    """Input schema for ProjectNoteTool."""

    note: str = Field(..., description="A short project note to return to the agent.")


class ProjectNoteTool(BaseTool):
    """Simple project-aware placeholder tool retained for future enhancements.

    The dashboard layer focuses on dashboard visibility around the agent team. In future enhancements, this can evolve into tools for
    reading coding standards, inspecting generated files, running tests, packaging output, or
    calculating generated-project quality scores.
    """

    name: str = "project_note_tool"
    description: str = "Returns a project note. Placeholder for future project-aware tools."
    args_schema: Type[BaseModel] = ProjectNoteInput

    def _run(self, note: str) -> str:
        return f"Project note received: {note}"
