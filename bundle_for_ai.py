import os
import sys
import fnmatch
from pathlib import Path

# Fallback defaults to ensure AI noise and version control are kept out
DEFAULT_IGNORE_DIRS = {
    '.git', '__pycache__', 'venv', '.venv', 'env', '.env', 
    'node_modules', '.idea', '.vscode', 'build', 'dist', 
    '.pytest_cache', '.mypy_cache', '.tox', 'site-packages'
}

DEFAULT_IGNORE_EXTS = {
    # Compiled / Binary
    '.pyc', '.pyo', '.pyd', '.so', '.dll', '.class', '.exe', '.bin', 
    # Media / Documents
    '.jpg', '.jpeg', '.png', '.gif', '.pdf', '.ico', '.svg', '.mp4', '.mp3',
    # Archives / Databases
    '.zip', '.tar', '.gz', '.rar', '.7z', '.sqlite', '.sqlite3', '.db'
}

def parse_gitignore(source_dir):
    """Reads .gitignore and parses its lines into a list of patterns."""
    gitignore_path = os.path.join(source_dir, '.gitignore')
    patterns = []
    
    if os.path.exists(gitignore_path):
        with open(gitignore_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                # Ignore empty lines and comments
                if line and not line.startswith('#'):
                    patterns.append(line)
    return patterns

def is_ignored(rel_path, is_dir, patterns):
    """
    Checks if a file or directory should be ignored based on .gitignore patterns
    and standard python built-in fallbacks.
    """
    name = os.path.basename(rel_path)
    
    # 1. Always check hardcoded fallbacks first (fastest and safest)
    if is_dir and name in DEFAULT_IGNORE_DIRS:
        return True
        
    # Explicitly ignore .gitignore itself, along with binaries
    if not is_dir:
        if name == '.gitignore':
            return True
            
        ext = os.path.splitext(name)[1].lower()
        if ext in DEFAULT_IGNORE_EXTS:
            return True

    # 2. Check against .gitignore patterns using standard fnmatch
    for pattern in patterns:
        is_dir_pattern = pattern.endswith('/')
        clean_pattern = pattern[:-1] if is_dir_pattern else pattern
        
        # If the pattern is meant for directories but this is a file, skip
        if is_dir_pattern and not is_dir:
            continue
            
        # If pattern has no slashes, it applies to the filename anywhere in the tree
        if '/' not in clean_pattern:
            if fnmatch.fnmatch(name, clean_pattern):
                return True
        else:
            # Pattern has slashes, match against the relative path
            if clean_pattern.startswith('/'):
                clean_pattern = clean_pattern[1:]
                
            if fnmatch.fnmatch(rel_path, clean_pattern) or fnmatch.fnmatch(rel_path, f"{clean_pattern}/*"):
                return True
                
    return False

def build_context(source_dir, output_file):
    source_dir_path = Path(source_dir).resolve()
    
    # Capture the absolute paths of this running script and the output file
    # This ensures they are never packaged into the context
    script_abs_path = os.path.abspath(__file__)
    output_abs_path = os.path.abspath(output_file)
    
    # Load .gitignore rules
    ignore_patterns = parse_gitignore(source_dir_path)
    
    files_processed = 0
    
    with open(output_abs_path, 'w', encoding='utf-8') as out_f:
        for root, dirs, files in os.walk(source_dir_path):
            rel_root = os.path.relpath(root, source_dir_path)
            if rel_root == '.':
                rel_root = ''
                
            # 1. Filter directories IN-PLACE
            dirs_to_keep = []
            for d in dirs:
                dir_rel_path = os.path.join(rel_root, d).replace('\\', '/')
                if not is_ignored(dir_rel_path, is_dir=True, patterns=ignore_patterns):
                    dirs_to_keep.append(d)
            dirs[:] = dirs_to_keep 
            
            # 2. Process files
            for file in files:
                file_abs_path = os.path.abspath(os.path.join(root, file))
                
                # STRICT EXCLUSION: Ignore this python script itself and the output text file
                if file_abs_path == script_abs_path or file_abs_path == output_abs_path:
                    continue
                    
                file_rel_path = os.path.join(rel_root, file).replace('\\', '/')
                
                # Check if file should be ignored by .gitignore or default rules
                if is_ignored(file_rel_path, is_dir=False, patterns=ignore_patterns):
                    continue
                    
                # 3. Safely read content (implicitly skips anything binary that slipped through)
                try:
                    with open(file_abs_path, 'r', encoding='utf-8') as in_f:
                        content = in_f.read()
                        
                    # 4. Write with a massive, distinct textual separator block
                    separator = "=" * 80
                    
                    out_f.write(f"{separator}\n")
                    out_f.write(f"FILE PATH: {file_abs_path}\n")
                    out_f.write(f"FILE NAME: {file}\n")
                    out_f.write(f"{separator}\n")
                    
                    out_f.write(content)
                    
                    # Ensure separation from the next block
                    if not content.endswith('\n'):
                        out_f.write('\n')
                        
                    out_f.write("\n\n")
                    files_processed += 1
                    
                except UnicodeDecodeError:
                    # File is likely binary/compiled - skip silently
                    pass
                except Exception as e:
                    print(f"Warning: Could not read {file_rel_path}: {e}")

    print(f"Successfully packaged {files_processed} files into {output_file}")

if __name__ == "__main__":
    TARGET_DIRECTORY = "." 
    OUTPUT_FILENAME = "ai_codebase_context.txt"
    
    print(f"Scanning directory: {Path(TARGET_DIRECTORY).resolve()}")
    build_context(TARGET_DIRECTORY, OUTPUT_FILENAME)
