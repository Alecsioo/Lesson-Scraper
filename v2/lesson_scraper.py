import json
import os
from pathlib import Path

import requests
import questionary

from dotenv import load_dotenv

load_dotenv()

def assert_response_matches(response, status_code):
    if response.status_code != status_code:
        raise IOError(
            f"Endpoint at {response.url} returned the following status code: {raw_response.status_code}. Expected: {status_code}. Is your access token still valid?")


def assert_response_ok(response):
    return assert_response_matches(response, 200)

# The access token must be specified in .env
# It will be used to perform HTTP requests to authenticated endpoints
ACCESS_TOKEN = os.getenv("ACCESS_TOKEN")

session = requests.Session()
session.cookies.set('access-token', ACCESS_TOKEN)

# GET to the courses overview page to retrieve all available languages
BASE_COURSE_LIST = os.getenv("BASE_COURSE_LIST_URL")
raw_response = session.get(BASE_COURSE_LIST)

assert_response_ok(raw_response)

raw_json = raw_response.json()

# The structure of the JSON is fixed, so we can easily navigate down the structure to extract the key-value pairs we need
overviews = raw_json.get("data", {}).get("overviews", [])  # key, default value
languages = [o.get("language") for o in overviews if isinstance(o, dict) and o.get("language")]
languages = list(dict.fromkeys(languages))

# Ask the user to select a language
selected = questionary.select(
    "Select a language:",
    choices=languages
).ask()

# Once the user selected the language, we need to retrieve the course structure with all the lesson IDs
BASE_COURSE_STRUCTURE_URL = os.getenv("BASE_COURSE_STRUCTURE_URL")
course_url_for_selected_language = BASE_COURSE_STRUCTURE_URL.format(lang=selected)

raw_response = session.get(course_url_for_selected_language)

assert_response_ok(raw_response)

raw_json = raw_response.json()

# Same here, the structure of the JSON is fixed
course_structure = (
    raw_json.get("data", {})
            .get("course_pack", {})
            .get("structure", [])
)

level_to_lessons: dict[str, list[str]] = {}

for level in course_structure:
    if not isinstance(level, dict):
        continue

    level_id = level.get("id")
    if not level_id:
        continue

    lessons = []
    for item in level.get("structure", []):
        if isinstance(item, dict) and item.get("id"):
            lessons.append(item["id"])

    level_to_lessons[level_id] = lessons

for level_id, lessons in level_to_lessons.items():
    print(f"{level_id}: {len(lessons)} lessons")

# For some reason the endpoints to retrieve the lesson data are not authenticated, so no need to use our auth token.
session.cookies.clear()
base = Path("00-raw_courses") / selected
base.mkdir(parents=True, exist_ok=True)

BASE_LESSON_URL = os.getenv("BASE_LESSON_URL")

for level_id, lessons in level_to_lessons.items():
    level_dir = base / level_id
    level_dir.mkdir(parents=True, exist_ok=True)

    for lesson_id in lessons:

        lesson_url = BASE_LESSON_URL.format(lesson_id=lesson_id)
        raw_response = session.get(lesson_url)
        assert_response_ok(raw_response)

        raw_json = raw_response.json()
        out_path = level_dir / lesson_id
        text = json.dumps(raw_json, ensure_ascii=False)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(text, encoding="utf-8")
