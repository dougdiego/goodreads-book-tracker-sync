# Goodreads / Book Tracker Sync

A Python script to sync your reading history between [Goodreads](https://www.goodreads.com) and [Book Tracker](https://booktrack.app).

## Features

- Compares CSV exports from both platforms
- Identifies books marked as "read" that are missing from each platform
- Supports multiple reads of the same book (e.g., read in 2010 and again in 2025)
- Uses 30-day date tolerance to account for minor tracking differences
- Generates properly formatted import files for each platform

## Prerequisites

- Python 3.10+
- [UV](https://docs.astral.sh/uv/) package manager

## Exporting Your Data

### From Goodreads

1. Go to [My Books](https://www.goodreads.com/review/list) on Goodreads
2. Click "Import and export" in the left sidebar
3. Click "Export Library"
4. Download the CSV file (usually named `goodreads_library_export.csv`)

### From Book Tracker

1. Open Book Tracker on your device
2. Go to Settings > Export
3. Export as CSV
4. Transfer the file to your computer

## Usage

```bash
# Run the sync script
uv run sync_books.py "Book Tracker 2026-01-11.csv" goodreads_library_export.csv

# Specify a custom output directory
uv run sync_books.py "Book Tracker.csv" goodreads.csv --output-dir ./output

# Adjust date tolerance (default is 30 days)
uv run sync_books.py "Book Tracker.csv" goodreads.csv --tolerance-days 60
```

## Output Files

The script generates two CSV files:

1. **`missing_from_goodreads.csv`** - Books in Book Tracker that aren't in Goodreads

   - Import at: https://www.goodreads.com/review/import

2. **`missing_from_booktracker.csv`** - Books in Goodreads that aren't in Book Tracker
   - Import via the Book Tracker app's import feature

## How Matching Works

Books are matched using these identifiers (in order of priority):

1. **ISBN-13** - Most reliable unique identifier
2. **ISBN-10** - Fallback if ISBN-13 is unavailable
3. **Title + Author** - Final fallback for books without ISBNs

### A Note on Book Editions

Matching books across platforms is inherently challenging because the same book can have multiple **editions** (hardcover, paperback, Kindle, anniversary editions, etc.), and each edition has a different ISBN. For example:

- "Morning Star" (paperback): ISBN 9780345539854
- "Morning Star" (hardcover): ISBN 9780345539847

Additionally, titles can vary between editions and platforms:

- `The Alchemist 25th Anniversary LP`
- `The Alchemist: A Fable About Following Your Dream`

This script does its best to match books by:

- Normalizing titles (stripping subtitles after colons, removing series info in parentheses)
- Using prefix matching (so "Gironimo!" matches "Gironimo! Riding the Very Terrible 1914 Tour of Italy")
- Falling back to title + author when ISBNs don't match

However, some books may still appear in the output files even if you have them in both apps. Review the output before importing to avoid duplicates.

### Multiple Reads

If you've read the same book multiple times, each read is tracked separately based on the completion date. A 30-day tolerance is used when comparing dates to account for minor differences between how the two apps track dates.

**Example:**

- Book Tracker: "Dune" read on 2010-05-15 and 2025-01-10
- Goodreads: "Dune" read on 2010-05-12
- Result: The 2025 read of "Dune" will be added to `missing_from_goodreads.csv`

## License

MIT
