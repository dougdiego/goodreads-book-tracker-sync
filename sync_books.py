#!/usr/bin/env python3
"""
Sync books between Goodreads and Book Tracker apps.

Compares CSV exports from both platforms and generates import files
for books missing from each platform. Supports multiple reads of the
same book with 30-day date tolerance.
"""

import argparse
import csv
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path


@dataclass
class ReadInstance:
    """Represents a single read of a book."""
    title: str
    author: str
    isbn10: str
    isbn13: str
    read_date: datetime | None  # Primary date (end date or single date)
    start_date: datetime | None  # Start date if available
    raw_data: dict  # Original row data for export


def parse_goodreads_isbn(value: str) -> str:
    """Parse Goodreads ISBN format like '="0385351402"' to '0385351402'."""
    if not value:
        return ""
    # Remove ="..." wrapper
    match = re.match(r'^="?([^"]*)"?$', value)
    if match:
        return match.group(1).strip()
    return value.strip()


def parse_date(date_str: str, formats: list[str]) -> datetime | None:
    """Try to parse a date string using multiple formats."""
    if not date_str or not date_str.strip():
        return None
    date_str = date_str.strip()
    for fmt in formats:
        try:
            return datetime.strptime(date_str, fmt)
        except ValueError:
            continue
    return None


def normalize_text(text: str) -> str:
    """Normalize text for comparison: lowercase, strip punctuation, collapse whitespace."""
    if not text:
        return ""
    # Lowercase
    text = text.lower()
    # Remove punctuation
    text = re.sub(r'[^\w\s]', '', text)
    # Collapse whitespace
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def normalize_title(title: str) -> str:
    """Normalize book title: strip subtitles, series info, then normalize text.
    
    Examples:
        "Morning Star (Red Rising Saga, #3)" -> "morning star"
        "The Handmaid's Tale (The Handmaid's Tale, #1)" -> "the handmaids tale"
        "Co-Intelligence: Living and Working with AI" -> "cointelligence"
    """
    if not title:
        return ""
    # Remove subtitle after colon (e.g., "Co-Intelligence: Living and Working with AI")
    if ':' in title:
        title = title.split(':')[0]
    # Remove parenthetical series info like "(Red Rising Saga, #3)"
    # This pattern matches content in parentheses that looks like series info
    title = re.sub(r'\s*\([^)]*#\d+[^)]*\)\s*$', '', title)
    # Also remove other trailing parenthetical content that might be series names
    title = re.sub(r'\s*\([^)]*(?:series|saga|trilogy|book|volume|#)[^)]*\)\s*$', '', title, flags=re.IGNORECASE)
    return normalize_text(title)


def normalize_author(author: str) -> str:
    """Normalize author name for comparison."""
    if not author:
        return ""
    # Handle "Lastname,Firstname" format from Book Tracker
    if ',' in author and not ' ' in author.split(',')[0]:
        parts = author.split(',')
        if len(parts) == 2:
            author = f"{parts[1].strip()} {parts[0].strip()}"
    return normalize_text(author)


def get_book_key(read: ReadInstance) -> tuple[str, str, str, str]:
    """Get matching keys for a book: (isbn13, isbn10, title_author, normalized_title)."""
    norm_title = normalize_title(read.title)
    norm_author = normalize_author(read.author)
    title_author = f"{norm_title}|{norm_author}"
    return (read.isbn13, read.isbn10, title_author, norm_title)


def dates_match(read1: ReadInstance, read2: ReadInstance, tolerance_days: int = 30) -> bool:
    """Check if two read instances overlap in time.
    
    Handles cases where one platform records start date and another records end date.
    A match occurs if either:
    - The dates are within tolerance of each other
    - One date falls within the other's reading period (start to end) plus tolerance
    """
    # If both have no dates, consider it a match (rely on book identity)
    if read1.read_date is None and read1.start_date is None and read2.read_date is None and read2.start_date is None:
        return True
    
    # Get the date ranges for each read
    # For read1: use start_date to read_date if available, otherwise just the available date
    r1_start = read1.start_date or read1.read_date
    r1_end = read1.read_date or read1.start_date
    
    r2_start = read2.start_date or read2.read_date
    r2_end = read2.read_date or read2.start_date
    
    # If we still have no dates for either, consider it a match
    if r1_start is None or r2_start is None:
        return True
    
    # Expand ranges by tolerance
    tolerance = timedelta(days=tolerance_days)
    r1_start_expanded = r1_start - tolerance
    r1_end_expanded = r1_end + tolerance
    r2_start_expanded = r2_start - tolerance
    r2_end_expanded = r2_end + tolerance
    
    # Check if the ranges overlap
    # Ranges overlap if one starts before the other ends
    return r1_start_expanded <= r2_end_expanded and r2_start_expanded <= r1_end_expanded


def load_goodreads_csv(filepath: Path) -> list[ReadInstance]:
    """Load and parse Goodreads CSV export."""
    reads = []
    with open(filepath, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            # Only include books marked as "read"
            if row.get('Exclusive Shelf', '').strip().lower() != 'read':
                continue
            
            # Parse read date
            read_date = parse_date(
                row.get('Date Read', ''),
                ['%Y/%m/%d', '%Y-%m-%d', '%m/%d/%Y', '%d/%m/%Y']
            )
            
            # Parse ISBNs
            isbn10 = parse_goodreads_isbn(row.get('ISBN', ''))
            isbn13 = parse_goodreads_isbn(row.get('ISBN13', ''))
            
            reads.append(ReadInstance(
                title=row.get('Title', '').strip(),
                author=row.get('Author', '').strip(),
                isbn10=isbn10,
                isbn13=isbn13,
                read_date=read_date,
                start_date=None,  # Goodreads only has one date
                raw_data=row
            ))
    return reads


def load_booktracker_csv(filepath: Path) -> list[ReadInstance]:
    """Load and parse Book Tracker CSV export."""
    reads = []
    with open(filepath, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f, delimiter=';')
        for row in reader:
            # Only include books marked as "read"
            if row.get('readingStatus', '').strip().lower() != 'read':
                continue
            
            # Parse read dates
            date_formats = ['%Y-%m-%d', '%Y/%m/%d', '%m/%d/%Y', '%d/%m/%Y']
            start_date = parse_date(row.get('startReading', ''), date_formats)
            end_date = parse_date(row.get('endReading', ''), date_formats)
            
            # Get author (first author if multiple)
            authors_str = row.get('authors', '')
            # Authors are comma-separated as "Lastname,Firstname,Lastname2,Firstname2"
            # Take the first author pair
            author_parts = authors_str.split(',')
            if len(author_parts) >= 2:
                author = f"{author_parts[0]},{author_parts[1]}"
            else:
                author = authors_str
            
            reads.append(ReadInstance(
                title=row.get('title', '').strip(),
                author=author.strip(),
                isbn10=row.get('isbn10', '').strip(),
                isbn13=row.get('isbn13', '').strip(),
                read_date=end_date,
                start_date=start_date,
                raw_data=row
            ))
    return reads


def find_matching_read(read: ReadInstance, other_reads: list[ReadInstance]) -> ReadInstance | None:
    """Find a matching read instance in another list."""
    read_key = get_book_key(read)
    
    for other in other_reads:
        other_key = get_book_key(other)
        
        # Check if books match by any identifier
        book_matches = False
        
        # Match by ISBN-13
        if read_key[0] and other_key[0] and read_key[0] == other_key[0]:
            book_matches = True
        # Match by ISBN-10
        elif read_key[1] and other_key[1] and read_key[1] == other_key[1]:
            book_matches = True
        # Match by title+author (exact match)
        elif read_key[2] and other_key[2] and read_key[2] == other_key[2]:
            book_matches = True
        # Match by title prefix + same author (for cases like "Gironimo!" vs "Gironimo! Riding the...")
        elif read_key[3] and other_key[3]:
            read_author = normalize_author(read.author)
            other_author = normalize_author(other.author)
            if read_author and other_author and read_author == other_author:
                # Check if one title starts with the other (prefix match)
                if read_key[3].startswith(other_key[3]) or other_key[3].startswith(read_key[3]):
                    book_matches = True
        
        if book_matches and dates_match(read, other):
            return other
    
    return None


def find_missing_reads(source_reads: list[ReadInstance], target_reads: list[ReadInstance]) -> list[ReadInstance]:
    """Find read instances in source that don't exist in target."""
    missing = []
    for read in source_reads:
        if find_matching_read(read, target_reads) is None:
            missing.append(read)
    return missing


def write_goodreads_import(reads: list[ReadInstance], filepath: Path) -> None:
    """Write a CSV file formatted for Goodreads import."""
    if not reads:
        print(f"No books to write to {filepath}")
        return
    
    fieldnames = [
        'Title', 'Author', 'ISBN', 'ISBN13', 'My Rating', 'Average Rating',
        'Publisher', 'Binding', 'Number of Pages', 'Year Published',
        'Original Publication Year', 'Date Read', 'Date Added', 'Bookshelves',
        'Exclusive Shelf', 'My Review', 'Spoiler', 'Private Notes',
        'Read Count', 'Owned Copies'
    ]
    
    with open(filepath, 'w', encoding='utf-8', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        
        for read in reads:
            # Format date for Goodreads
            date_read = read.read_date.strftime('%Y/%m/%d') if read.read_date else ''
            
            # Format ISBNs in Goodreads style
            isbn10 = f'="{read.isbn10}"' if read.isbn10 else '=""'
            isbn13 = f'="{read.isbn13}"' if read.isbn13 else '=""'
            
            row = {
                'Title': read.title,
                'Author': read.author.replace(',', ' ') if ',' in read.author else read.author,
                'ISBN': isbn10,
                'ISBN13': isbn13,
                'My Rating': '0',
                'Average Rating': '',
                'Publisher': '',
                'Binding': '',
                'Number of Pages': '',
                'Year Published': '',
                'Original Publication Year': '',
                'Date Read': date_read,
                'Date Added': datetime.now().strftime('%Y/%m/%d'),
                'Bookshelves': '',
                'Exclusive Shelf': 'read',
                'My Review': '',
                'Spoiler': '',
                'Private Notes': '',
                'Read Count': '1',
                'Owned Copies': '0'
            }
            writer.writerow(row)
    
    print(f"Wrote {len(reads)} books to {filepath}")


def write_booktracker_import(reads: list[ReadInstance], filepath: Path) -> None:
    """Write a CSV file formatted for Book Tracker import."""
    if not reads:
        print(f"No books to write to {filepath}")
        return
    
    fieldnames = [
        'title', 'authors', 'isbn10', 'isbn13', 'readingStatus',
        'startReading', 'endReading', 'userRating', 'pages'
    ]
    
    with open(filepath, 'w', encoding='utf-8', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, delimiter=';')
        writer.writeheader()
        
        for read in reads:
            # Format date for Book Tracker
            end_reading = read.read_date.strftime('%Y-%m-%d') if read.read_date else ''
            
            # Convert author to Book Tracker format (Lastname,Firstname)
            author = read.author
            if ' ' in author and ',' not in author:
                # Convert "Firstname Lastname" to "Lastname,Firstname"
                parts = author.rsplit(' ', 1)
                if len(parts) == 2:
                    author = f"{parts[1]},{parts[0]}"
            
            row = {
                'title': read.title,
                'authors': author,
                'isbn10': read.isbn10,
                'isbn13': read.isbn13,
                'readingStatus': 'read',
                'startReading': '',
                'endReading': end_reading,
                'userRating': '',
                'pages': ''
            }
            writer.writerow(row)
    
    print(f"Wrote {len(reads)} books to {filepath}")


def main():
    parser = argparse.ArgumentParser(
        description='Sync books between Goodreads and Book Tracker apps.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
Examples:
  uv run sync_books.py "Book Tracker 2026-01-11.csv" goodreads_library_export.csv
  
This will generate:
  - missing_from_goodreads.csv: Books in Book Tracker but not in Goodreads
  - missing_from_booktracker.csv: Books in Goodreads but not in Book Tracker
        '''
    )
    parser.add_argument(
        'booktracker_csv',
        type=Path,
        help='Path to Book Tracker CSV export'
    )
    parser.add_argument(
        'goodreads_csv',
        type=Path,
        help='Path to Goodreads CSV export'
    )
    parser.add_argument(
        '--output-dir',
        type=Path,
        default=Path('.'),
        help='Directory to write output files (default: current directory)'
    )
    parser.add_argument(
        '--tolerance-days',
        type=int,
        default=30,
        help='Date tolerance in days for matching reads (default: 30)'
    )
    
    args = parser.parse_args()
    
    # Validate input files
    if not args.booktracker_csv.exists():
        print(f"Error: Book Tracker file not found: {args.booktracker_csv}", file=sys.stderr)
        sys.exit(1)
    if not args.goodreads_csv.exists():
        print(f"Error: Goodreads file not found: {args.goodreads_csv}", file=sys.stderr)
        sys.exit(1)
    
    # Load data
    print(f"Loading Book Tracker data from: {args.booktracker_csv}")
    booktracker_reads = load_booktracker_csv(args.booktracker_csv)
    print(f"  Found {len(booktracker_reads)} read books")
    
    print(f"Loading Goodreads data from: {args.goodreads_csv}")
    goodreads_reads = load_goodreads_csv(args.goodreads_csv)
    print(f"  Found {len(goodreads_reads)} read books")
    
    # Find missing books
    print(f"\nComparing libraries (using {args.tolerance_days}-day date tolerance)...")
    
    missing_from_goodreads = find_missing_reads(booktracker_reads, goodreads_reads)
    missing_from_booktracker = find_missing_reads(goodreads_reads, booktracker_reads)
    
    print(f"  Books in Book Tracker missing from Goodreads: {len(missing_from_goodreads)}")
    print(f"  Books in Goodreads missing from Book Tracker: {len(missing_from_booktracker)}")
    
    # Write output files
    print("\nWriting output files...")
    
    args.output_dir.mkdir(parents=True, exist_ok=True)
    
    goodreads_output = args.output_dir / 'missing_from_goodreads.csv'
    booktracker_output = args.output_dir / 'missing_from_booktracker.csv'
    
    write_goodreads_import(missing_from_goodreads, goodreads_output)
    write_booktracker_import(missing_from_booktracker, booktracker_output)
    
    print("\nDone!")
    if missing_from_goodreads:
        print(f"  Import '{goodreads_output}' to Goodreads at: https://www.goodreads.com/review/import")
    if missing_from_booktracker:
        print(f"  Import '{booktracker_output}' to Book Tracker via the app's import feature")


if __name__ == '__main__':
    main()
