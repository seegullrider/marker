#!/usr/bin/env python3
"""
Merge all 10-page markdown chunks into a single large markdown file.
Reads from D:\Maker\output_chunks\datta\p****-**** directories
and outputs to a combined markdown file.
"""

import os
from pathlib import Path
import re


def extract_page_range(dirname: str) -> tuple:
    """Extract start and end page numbers from directory name like 'p0000-0009'."""
    match = re.match(r'p(\d{4})-(\d{4})', dirname)
    if match:
        return (int(match.group(1)), int(match.group(2)))
    return (float('inf'), float('inf'))  # Sort to end if invalid


def find_markdown_in_chunk(chunk_dir: Path) -> Path | None:
    """Find the main markdown file in a chunk directory."""
    # Search for .md files recursively
    md_files = list(chunk_dir.rglob('*.md'))
    if md_files:
        # Return the largest one (main content file)
        return max(md_files, key=lambda x: x.stat().st_size)
    return None


def merge_chunks(input_dir: str, output_file: str, add_page_separator: bool = True):
    """
    Merge all markdown chunks into a single file.
    
    Args:
        input_dir: Path to directory containing chunk folders (e.g., 'D:\\Maker\\output_chunks\\datta')
        output_file: Path to output merged markdown file
        add_page_separator: If True, add a separator between chunks
    """
    input_path = Path(input_dir)
    if not input_path.exists():
        print(f"Error: Input directory '{input_dir}' does not exist.")
        return False
    
    # Find all chunk directories
    chunk_dirs = []
    for item in input_path.iterdir():
        if item.is_dir() and re.match(r'p\d{4}-\d{4}', item.name):
            chunk_dirs.append(item)
    
    if not chunk_dirs:
        print(f"Error: No chunk directories found in '{input_dir}'")
        return False
    
    # Sort by page range
    chunk_dirs.sort(key=lambda x: extract_page_range(x.name))
    
    print(f"Found {len(chunk_dirs)} chunks to merge.")
    
    # Merge all markdown files
    output_path = Path(output_file)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    total_lines = 0
    with open(output_path, 'w', encoding='utf-8') as outf:
        for i, chunk_dir in enumerate(chunk_dirs):
            md_file = find_markdown_in_chunk(chunk_dir)
            if not md_file:
                print(f"  Warning: No markdown file found in {chunk_dir.name}, skipping.")
                continue
            
            print(f"  [{i+1}/{len(chunk_dirs)}] Merging {chunk_dir.name} from {md_file.name}")
            
            # Add separator before each chunk (except first)
            if i > 0 and add_page_separator:
                page_range = extract_page_range(chunk_dir.name)
                outf.write(f"\n\n---\n\n**Pages {page_range[0]}-{page_range[1]}**\n\n")
            
            # Append markdown content
            with open(md_file, 'r', encoding='utf-8') as inf:
                content = inf.read()
                outf.write(content)
                if not content.endswith('\n'):
                    outf.write('\n')
                total_lines += len(content.splitlines())
    
    print(f"\nSuccess! Merged {len(chunk_dirs)} chunks into {output_file}")
    print(f"Total lines: {total_lines}")
    print(f"Output file size: {output_path.stat().st_size / 1024 / 1024:.2f} MB")
    return True


if __name__ == '__main__':
    # Configuration
    INPUT_DIR = r'D:\Maker\output_chunks\datta'
    OUTPUT_FILE = r'D:\Maker\datta_merged_full.md'
    
    print(f"Merging markdown chunks from: {INPUT_DIR}")
    print(f"Output file: {OUTPUT_FILE}\n")
    
    success = merge_chunks(INPUT_DIR, OUTPUT_FILE, add_page_separator=True)
    exit(0 if success else 1)
