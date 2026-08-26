"""
Strip comments and docstrings from Python files using the tokenize module.
Preserves string literals that are not docstrings.
"""
from __future__ import annotations

import sys
import tokenize
from pathlib import Path


def strip_python_file(input_path: Path, output_path: Path | None = None) -> str:
    with open(input_path, 'rb') as f:
        tokens = list(tokenize.tokenize(f.readline))
    output = []
    prev_toktype = tokenize.INDENT
    last_lineno = -1
    last_col = 0
    for tok in tokens:
        toktype = tok.type
        ttext = tok.string
        slineno, scol = tok.start
        elineno, ecol = tok.end
        if slineno > last_lineno:
            last_col = 0
        if scol > last_col:
            output.append(" " * (scol - last_col))
        if toktype == tokenize.COMMENT:
            pass
        elif toktype == tokenize.STRING:
            if prev_toktype == tokenize.INDENT or prev_toktype == tokenize.NEWLINE:
                pass
            else:
                output.append(ttext)
        else:
            output.append(ttext)
        prev_toktype = toktype
        last_col = ecol
        last_lineno = elineno
    result = "".join(output)
    lines = result.splitlines()
    cleaned_lines = []
    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith('#'):
            cleaned_lines.append(line)
    result = "\n".join(cleaned_lines)
    if output_path:
        with open(output_path, 'w') as f:
            f.write(result)
    return result
def main():
    if len(sys.argv) < 2:
        print("Usage: python strip_python_comments.py <file_or_directory> [--in-place]")
        sys.exit(1)
    target = Path(sys.argv[1])
    in_place = '--in-place' in sys.argv
    if target.is_file():
        files = [target]
    elif target.is_dir():
        files = list(target.rglob("*.py"))
        exclude_dirs = {'.venv', '__pycache__', 'node_modules', '.git', '.mypy_cache'}
        files = [f for f in files if not any(ex in f.parts for ex in exclude_dirs)]
    else:
        print(f"Error: {target} not found")
        sys.exit(1)
    for f in files:
        if in_place:
            strip_python_file(f, f)
            print(f"Processed: {f}")
        else:
            result = strip_python_file(f)
            print(f"=== {f} ===")
            print(result)
if __name__ == "__main__":
    main()