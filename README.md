# Lesson Scraper (v2)

Scrapes course content and saves raw lesson JSON files to disk, organized as:

`language → course_pack → level → chapter → lessons`

---

## Requirements

- Python 3.10+ recommended (works with newer versions too).
- An `.env` file containing the required URLs and an access token cookie (see below).

### Python dependencies

This script uses:

- `requests` (HTTP client)
- `python-dotenv` (loads `.env` into environment variables)
- `questionary` (interactive CLI selection prompt)
- `pathvalidate` (sanitize filenames/dirnames for Windows/macOS/Linux compatibility)

Install:

```bash
pip install requests python-dotenv questionary pathvalidate
```

## Configuration (.env)

Create a file named .env in your project root:

```
# Auth cookie used for authenticated endpoints
ACCESS_TOKEN=...

# Endpoint that returns the course overview list (languages and available course packs)
BASE_COURSE_LIST_URL=...

# Endpoint to fetch a course pack JSON by id (must contain "{pack}" placeholder)
BASE_COURSE_PACK_URL=...{pack}...

# Endpoint to fetch a lesson JSON by id (must contain "{lesson_id}" placeholder)
BASE_LESSON_URL=...{lesson_id}...
```

## Output layout

Example:

```
00-raw_courses/
  en/
    course_pack_en_complete/
      pack_level_en_a1/
        0-introductions/
          <lesson_id>.json
          ...
        1-greetings/
          <lesson_id>.json
          ...
      pack_level_en_a2/
        ...

```

# Running the script

From the v2 directory:

```
python lesson_scraper.py
```

You will be prompted to select a language, and the script will download all course packs for that language.

