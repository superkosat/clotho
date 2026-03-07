# create projects (sessions)
from uuid import UUID
from pathlib import Path

from agent.models.turn import AssistantTurn, SystemTurn, ToolTurn, Turn, UserTurn

def append_to_project_file(id: UUID, input_turn: UserTurn | ToolTurn, assistant_turn: AssistantTurn) -> bool:
    """
    Appends an input turn and assistant turn to the project file.
    """
    try:
        project_file = Path.home() / ".clotho" / "projects" / f"{id}.jsonl"
        with open(project_file, "a", encoding="utf-8") as f:
            f.write(input_turn.model_dump_json() + "\n")
            f.write(assistant_turn.model_dump_json() + "\n")
        return True
    except Exception:
        return False

def create_project_file(id: UUID, system_turn: SystemTurn) -> bool:
    """Create a new project JSONL file and write initial system turn to
    the file

    Returns True if file was created and written to or already exists, 
    False on error.
    """
    try:
        projects_dir = Path.home() / ".clotho" / "projects"
        projects_dir.mkdir(parents=True, exist_ok=True)

        project_file = projects_dir / f"{id}.jsonl"
        if not project_file.exists():
            project_file.touch()
            try:
                with open(project_file, "w", encoding="utf-8") as f:
                    f.write(system_turn.model_dump_json() + "\n")
                return True
            except Exception as e:
                print(f"Failed to write system turn: {e}")
                return False
        return True
    except Exception:
        return False
    
def read_content_from_project_file(id: UUID) -> list[Turn] | None:
    """
    Reads, deserializes, and returns content of the selected project file.
    Returns None on error.
    """
    from pydantic import TypeAdapter
    turn_adapter = TypeAdapter(Turn)

    try:
        project_file = Path.home() / ".clotho" / "projects" / f"{id}.jsonl"
        with open(project_file, "r", encoding="utf-8") as f:
            turns = [turn_adapter.validate_json(line) for line in f if line.strip()]
            return turns
    except Exception:
        return None


def delete_project_file(id: UUID) -> bool:
    """
    Deletes specified file from the filesystem.
    Returns True if successful or file doesn't exist, False on error.
    """
    project_file = Path.home() / ".clotho" / "projects" / f"{id}.jsonl"

    try:
        project_file.unlink(missing_ok=True)
        return True
    except Exception:
        return False