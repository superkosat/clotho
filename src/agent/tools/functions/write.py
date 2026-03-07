from pathlib import Path

def write_func(file_path: str, content: str, mode: str = "w") -> dict:
    """
    Write content to a file at the specified path.
    
    Args:
        file_path (str): The absolute path to the file to write
        content (str): The content to write to the file
        mode (str): The file write mode ("w" for overwrite, "a" for append)
        
    Returns:
        dict: A dictionary containing success status and message
    """
    try:
        path = Path(file_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        
        if mode == "w":
            with open(path, "w", encoding="utf-8") as f:
                f.write(content)
            return {"success": True, "message": f"Successfully wrote to {file_path}"}
        elif mode == "a":
            with open(path, "a", encoding="utf-8") as f:
                f.write(content)
            return {"success": True, "message": f"Successfully appended to {file_path}"}
        else:
            return {"success": False, "message": "Invalid mode. Use 'w' for write or 'a' for append"}
            
    except Exception as e:
        return {"success": False, "message": f"Failed to write to {file_path}: {str(e)}"}