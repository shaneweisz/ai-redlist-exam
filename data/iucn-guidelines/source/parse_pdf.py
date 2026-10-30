#!/usr/bin/env python3
"""
Convert a PDF to Markdown, extracting its text, tables and images, plus a
source-map JSON of section headers and their page coordinates.

Usage:
    python3 data/iucn-guidelines/source/parse_pdf.py <pdf_file> [output_dir]

output_dir defaults to the PDF's own directory.
"""

import sys
import json
import re
from pathlib import Path


def extract_section_headers(page):
    """
    Extract section headers from a page using pattern matching.
    Returns list of dicts with section number, title, page, and bounding box.

    Looks for patterns like:
    - "4.11 Location (criteria B and D)"
    - "Section 4.7"
    - "4.7.1 Subsection title"
    """
    sections = []

    # Pattern for section numbers: digits.digits optionally followed by more .digits
    # Followed by text (the section title)
    pattern = r'(\d+\.\d+(?:\.\d+)?)\s+([A-Z][^\n]+)'

    try:
        # Search for section header patterns
        matches = page.search(pattern, regex=True, case=True)

        for match in matches:
            section_num = match['groups'][0] if match.get('groups') else ''
            section_title = match['groups'][1] if len(match.get('groups', [])) > 1 else ''

            # Clean up title (remove extra whitespace)
            section_title = ' '.join(section_title.split())

            sections.append({
                'section': section_num,
                'title': section_title,
                'page': page.page_number,
                'bbox': {
                    'x0': match['x0'],
                    'top': match['top'],
                    'x1': match['x1'],
                    'bottom': match['bottom']
                }
            })
    except Exception as e:
        print(f"  Warning: Error extracting sections from page {page.page_number}: {e}")

    return sections


def format_table_as_markdown(table):
    """Convert a table (list of lists) to markdown format."""
    if not table or len(table) == 0:
        return ""

    # Clean cells - replace None with empty string, strip whitespace
    cleaned_table = []
    for row in table:
        cleaned_row = [str(cell).strip() if cell else "" for cell in row]
        cleaned_table.append(cleaned_row)

    # Calculate column widths
    col_widths = []
    for col_idx in range(len(cleaned_table[0])):
        max_width = max(len(cleaned_table[row_idx][col_idx])
                       for row_idx in range(len(cleaned_table)))
        col_widths.append(max(max_width, 3))  # Minimum width of 3

    # Build markdown
    markdown = ""

    # Header row
    header_row = cleaned_table[0]
    markdown += "| " + " | ".join(cell.ljust(col_widths[i]) for i, cell in enumerate(header_row)) + " |\n"

    # Separator row
    markdown += "| " + " | ".join("-" * width for width in col_widths) + " |\n"

    # Data rows
    for row in cleaned_table[1:]:
        # Replace newlines within cells with <br> for markdown compatibility
        cleaned_row = [cell.replace('\n', '<br>') for cell in row]
        markdown += "| " + " | ".join(cell.ljust(col_widths[i]) for i, cell in enumerate(cleaned_row)) + " |\n"

    return markdown


def parse_pdf(pdf_path, output_dir):
    """
    Parse a PDF and extract text, tables, and images to markdown.

    Args:
        pdf_path: Path to the PDF file
        output_dir: Directory where the markdown file and images/ will be created
                   The markdown file will be named to match the PDF (e.g., doc.pdf -> doc.md)
    """
    try:
        import pdfplumber
    except ImportError:
        print("Error: pdfplumber is not installed.")
        print("Install dependencies with: uv sync")
        sys.exit(1)

    pdf_path = Path(pdf_path)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Derive markdown filename from PDF filename (e.g., doc.pdf -> doc.md)
    md_filename = pdf_path.stem + ".md"
    md_path = output_dir / md_filename
    images_dir = output_dir / "images"
    images_dir.mkdir(exist_ok=True)

    print(f"Parsing: {pdf_path.name}")

    try:
        with pdfplumber.open(pdf_path) as pdf:
            full_text = ""
            total_images = 0
            total_tables = 0
            all_sections = []  # Track all section headers

            for i, page in enumerate(pdf.pages):
                page_num = i + 1
                full_text += f"\n{'='*80}\nPage {page_num}\n{'='*80}\n\n"

                # Extract section headers from this page
                page_sections = extract_section_headers(page)
                all_sections.extend(page_sections)

                # Extract images from this page
                images = page.images
                if images:
                    for img_idx, img in enumerate(images):
                        try:
                            # Get image data
                            bbox = (img['x0'], img['top'], img['x1'], img['bottom'])
                            cropped_page = page.crop(bbox)

                            # Convert to image and save
                            img_obj = cropped_page.to_image(resolution=150)
                            img_filename = f"page_{page_num}_img_{img_idx+1}.png"
                            img_path = images_dir / img_filename
                            img_obj.save(str(img_path))

                            # Add reference in markdown
                            full_text += f"![Image from page {page_num}](images/{img_filename})\n\n"
                            total_images += 1
                        except Exception as e:
                            print(f"  Warning: Could not extract image {img_idx+1} from page {page_num}: {e}")

                # Extract tables from this page
                tables = page.extract_tables()
                if tables:
                    for tbl_idx, table in enumerate(tables):
                        if table and len(table) > 1:  # Ensure it's a real table with data
                            # Check if it looks like a real table (has multiple columns)
                            if any(len([cell for cell in row if cell]) > 1 for row in table):
                                full_text += f"\n**Table {tbl_idx+1} (Page {page_num})**\n\n"
                                full_text += format_table_as_markdown(table)
                                full_text += "\n\n"
                                total_tables += 1

                # Extract text
                text = page.extract_text()
                if text:
                    full_text += f"{text}\n"

            with open(md_path, 'w', encoding='utf-8') as f:
                f.write(full_text)

            # Create source map with section information
            source_map = {
                'pdfPath': str(pdf_path),
                'mdPath': str(md_path),
                'totalPages': len(pdf.pages),
                'sections': {}
            }

            # Group sections by section number and determine page ranges
            section_dict = {}
            for section in all_sections:
                section_num = section['section']
                if section_num not in section_dict:
                    section_dict[section_num] = {
                        'title': section['title'],
                        'startPage': section['page'],
                        'endPage': section['page'],
                        'bbox': section['bbox']
                    }
                else:
                    # Update end page if this section appears on multiple pages
                    section_dict[section_num]['endPage'] = max(
                        section_dict[section_num]['endPage'],
                        section['page']
                    )

            source_map['sections'] = section_dict

            # Save source map JSON
            source_map_path = output_dir / f"{pdf_path.stem}-source-map.json"
            with open(source_map_path, 'w', encoding='utf-8') as f:
                json.dump(source_map, f, indent=2)

            pages = len(pdf.pages)
            chars = len(full_text)
            print(f"  ✓ Extracted {pages} pages ({chars:,} characters)")
            print(f"  ✓ Extracted {total_images} images, {total_tables} tables")
            print(f"  ✓ Extracted {len(all_sections)} section headers")
            print(f"  ✓ Output: {md_path}")
            print(f"  ✓ Source map: {source_map_path}")
            return True

    except Exception as e:
        print(f"  ✗ Error parsing PDF: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    """Main entry point."""
    if len(sys.argv) < 2:
        print("Usage: python parse_pdf.py <pdf_file> [output_dir]")
        print()
        print("Examples:")
        print("  python parse_pdf.py docs/user-guidelines/user-guidelines-v16.pdf docs/user-guidelines")
        print("  python parse_pdf.py my-document.pdf ./output")
        sys.exit(1)

    pdf_path = sys.argv[1]

    # If output_dir not specified, use the directory containing the PDF
    if len(sys.argv) > 2:
        output_dir = sys.argv[2]
    else:
        output_dir = Path(pdf_path).parent

    if not Path(pdf_path).exists():
        print(f"Error: PDF file not found: {pdf_path}")
        sys.exit(1)

    success = parse_pdf(pdf_path, output_dir)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
