import base64
import os

IMAGE_EXTENSIONS = {'.png', '.jpg', '.jpeg', '.gif', '.bmp', '.webp', '.svg'}
MAX_LINES = 100

def read_func(file_path: str, start_line: int = 1, end_line: int | None = None) -> str:
    if not os.path.isabs(file_path):
        return f"Error: Path must be absolute. Received: {file_path}"

    if not os.path.exists(file_path):
        return f"Error: File not found: {file_path}"

    if not os.path.isfile(file_path):
        return f"Error: Path is not a file: {file_path}"

    ext = os.path.splitext(file_path)[1].lower()

    if ext in IMAGE_EXTENSIONS:
        try:
            with open(file_path, 'rb') as f:
                data = base64.b64encode(f.read()).decode('ascii')
            return f"[Image file: {os.path.basename(file_path)}, base64:{data}]"
        except Exception as e:
            return f"Error reading image: {e}"

    try:
        with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
            lines = f.readlines()
    except Exception as e:
        return f"Error reading file: {e}"

    total_lines = len(lines)
    start = max(1, start_line) - 1  # convert to 0-indexed
    end = end_line if end_line is not None else start + MAX_LINES
    end = min(end, total_lines)

    if end - start > MAX_LINES:
        end = start + MAX_LINES

    selected = lines[start:end]
    header = f"[Lines {start + 1}-{end} of {total_lines}]\n"
    return header + ''.join(f"{i}: {line}" for i, line in enumerate(selected, start=start + 1))
