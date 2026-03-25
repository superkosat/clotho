# create projects (sessions)
from uuid import UUID
from pathlib import Path

from agent.models.turn import AssistantTurn, CompactionTurn, SystemTurn, ToolTurn, Turn, UserTurn


def append_to_project_file(id: UUID, input_turn: UserTurn | ToolTurn, assistant_turn: AssistantTurn) -> bool:
    try:
        project_file = Path.home() / ".clotho" / "projects" / f"{id}.jsonl"
        with open(project_file, "a", encoding="utf-8") as f:
            f.write(input_turn.model_dump_json() + "\n")
            f.write(assistant_turn.model_dump_json() + "\n")
        return True
    except Exception:
        return False


def append_compaction_record(id: UUID, compaction_turn: CompactionTurn, new_context: list[Turn]) -> bool:
    """Append a compaction marker followed by the full new context.

    On load, read_content_from_project_file will seek to the last compaction
    marker and return only the turns that follow it.
    """
    try:
        project_file = Path.home() / ".clotho" / "projects" / f"{id}.jsonl"
        with open(project_file, "a", encoding="utf-8") as f:
            f.write(compaction_turn.model_dump_json() + "\n")
            for turn in new_context:
                f.write(turn.model_dump_json() + "\n")
        return True
    except Exception:
        return False


def create_project_file(id: UUID, system_turn: SystemTurn) -> bool:
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
    """Read turns from a project file.

    If a CompactionTurn marker is present, returns only the turns that follow
    the last marker (the active compacted context). Everything before the last
    CompactionTurn is ignored.
    """
    from pydantic import TypeAdapter
    turn_adapter = TypeAdapter(Turn)

    try:
        project_file = Path.home() / ".clotho" / "projects" / f"{id}.jsonl"
        with open(project_file, "r", encoding="utf-8") as f:
            all_turns = [turn_adapter.validate_json(line) for line in f if line.strip()]

        # Find last compaction marker; load only what follows it
        last_compaction_idx = None
        for i, turn in enumerate(all_turns):
            if isinstance(turn, CompactionTurn):
                last_compaction_idx = i

        if last_compaction_idx is not None:
            return all_turns[last_compaction_idx + 1:]

        return all_turns
    except Exception:
        return None


def delete_project_file(id: UUID) -> bool:
    project_file = Path.home() / ".clotho" / "projects" / f"{id}.jsonl"
    try:
        project_file.unlink(missing_ok=True)
        return True
    except Exception:
        return False
