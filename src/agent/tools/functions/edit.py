import os

def edit_func(file_path: str, old_string: str, new_string: str, replace_all: bool = False):

    if not os.path.isabs(file_path):
        return f"Error: Path must be absolute. Received: {file_path}"

    if not os.path.exists(file_path):
        return f"Error: File not found: {file_path}"

    if not os.path.isfile(file_path):
        return f"Error: Path is not a file: {file_path}"

    try:
        with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
            file_content = f.read()
    except Exception as e:
        return f"Error reading file: {e}"

    if old_string not in file_content:
        return f"Error: old_string not found in {file_path}. Make sure you have read the file first and the string matches exactly."

    if not replace_all and file_content.count(old_string) > 1:
        return f"Error: old_string appears {file_content.count(old_string)} times in {file_path}. Provide more surrounding context to make the match unique, or set replace_all to true."

    try:
        if replace_all:
            new_content = file_content.replace(old_string, new_string)
        else:
            new_content = file_content.replace(old_string, new_string, 1)

        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(new_content)

        return "Edited file content successfully"

    except Exception as e:
        return f"Error writing file: {e}"
