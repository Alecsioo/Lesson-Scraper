import json
import os
import platform
from collections import defaultdict

import requests
import questionary

from pathlib import Path
from dotenv import load_dotenv
from pathvalidate import sanitize_filename
from tqdm import tqdm
from graphql_scraper import extract_chapters_by_level
from v2.classes import Course, Lesson, Level, Chapter

load_dotenv()


# Utility method to assert that the provided response status code matches the expected status code
def assert_response_matches(response, status_code):
    if response.status_code != status_code:
        raise IOError(
            f"Endpoint at {response.url} returned the following status code: {response.status_code}. Expected: {status_code}. Is your access token still valid?")


def assert_response_ok(response):
    return assert_response_matches(response, 200)


# Given some raw level data (a JSON representation) and a list of chapters, this function groups the lessons in the raw
# data into chapters. The type of lesson is used as marker for the boundaries of each chapter. Whenever we encounter a
# checkpoint, we know that it's the last lesson of the chapter
def populate_chapter_lessons(
        raw_level: dict,
        chapters: list[Chapter],
) -> None:
    # ensure lessons lists exist / are empty
    for ch in chapters:
        ch.lessons = []

    chapter_idx = 0

    for raw_item in raw_level.get("structure", []):
        if not isinstance(raw_item, dict):
            continue

        lesson_id = raw_item.get("id")
        lesson_type = raw_item.get("type")
        if not lesson_id:
            continue

        # stop if we run out of chapters
        if chapter_idx >= len(chapters):
            break

        lesson = Lesson(id=lesson_id, type=lesson_type)

        chapters[chapter_idx].lessons.append(lesson)

        # When we encounter a checkpoint, we know that this was the last lesson for the current chapter, so we go to the next one
        if lesson_type == "checkpoint":
            chapter_idx += 1


# We start from a JSON representation of a course pack (aka a collection of different courses/levels like English A1, English A2, English Travel, ...
# and a list of chapters
def map_to_course(course_pack_json: dict, chapters_by_level: list[list[Chapter]]) -> Course:
    course = Course(id=course_pack_json.get("id"))

    raw_levels = course_pack_json.get("structure", [])

    for level_idx, raw_level in enumerate(raw_levels):
        if not isinstance(raw_level, dict):
            continue

        level = Level(id=raw_level.get("id"), level=raw_level.get("level"))

        level.chapters = chapters_by_level[level_idx] if level_idx < len(chapters_by_level) else []

        # At this point we have the raw level data and its chapters, but we still need to group all the lessons in the
        # raw data into chapters
        populate_chapter_lessons(raw_level, level.chapters)

        course.levels.append(level)

    return course


def main() -> int:
    # The access token must be specified in .env
    # It will be used to perform HTTP requests to authenticated endpoints
    access_token = os.getenv("ACCESS_TOKEN")

    session = requests.Session()
    session.cookies.set('access-token', access_token)

    # GET to the courses overview page to retrieve all available languages
    base_course_list = os.getenv("BASE_COURSE_LIST_URL")
    raw_response = session.get(base_course_list)

    assert_response_ok(raw_response)

    raw_json = raw_response.json()

    # The structure of the JSON is fixed, so we can easily navigate down the structure to extract the key-value pairs we need
    overviews = raw_json.get("data", {}).get("overviews", [])  # key, default value
    languages_to_course_packs: dict[str, list[str]] = defaultdict(list)

    # For each course overview (aka a list of all available courses for a given language), extract a language -> list of course
    # ids mapping
    for overview in overviews:
        if not isinstance(overview, dict):
            continue

        lang = overview.get("language")
        if not lang:
            continue

        # The course packs are in overview["structure"]
        structure = overview.get("structure", [])

        for item in structure:
            if not isinstance(item, dict):
                continue

            if item.get("class") == "course_pack":
                pack_id = item.get("id")
                if pack_id:
                    languages_to_course_packs[lang].append(pack_id)

    # Preview of the first two courses for each language
    for lang, packs in languages_to_course_packs.items():
        print(f"{lang}: {len(packs)} course packs - {packs[:2]}")

    # Ask the user to select a language from the keys we just extracted
    selected_language = questionary.select(
        "Select a language:",
        choices=list(languages_to_course_packs.keys()),
    ).ask()

    # One language can have N courses
    # One course is composed of N levels
    # One level is composed of N chapters
    # One chapter can have N lessons
    # One lesson can have N exercises

    # Once the user selected the language, we need to retrieve the course structure with all the lesson IDs, for each course
    course_packs_for_selected_language = languages_to_course_packs[selected_language]

    base_course_pack = os.getenv("BASE_COURSE_PACK_URL")
    base_lesson_url = os.getenv("BASE_LESSON_URL")
    base = Path("00-raw_courses") / selected_language
    base.mkdir(parents=True, exist_ok=True)

    # First pass: resolve the full course structure for each pack so we know the total
    # lesson count upfront. This is required to render a meaningful progress bar with
    # percentage and ETA for each pack.
    course_pack_items: list[tuple[str, Path, list[tuple[Path, object]]]] = []

    for course_pack in course_packs_for_selected_language:
        # Create one subdirectory for each course pack
        course_pack_path = base / course_pack
        course_pack_path.mkdir(parents=True, exist_ok=True)

        # Dynamically build the course URL depending on the course pack we are processing
        course_url = base_course_pack.format(pack=course_pack, source=selected_language, lang=selected_language)

        raw_response = session.get(course_url)
        assert_response_ok(raw_response)
        raw_json = raw_response.json()

        course_structure = (
            raw_json.get("data", {})
            .get("course_pack", {})
        )

        # At this point we have all the lessons associated to the current course. We need to group the lessons by chapter.
        # Chapters are not explicitly defined in the course structure, so we are going to use a GraphQL query to extract
        # a list of all the chapters, and then we are going to group lessons based on some marker types. We know that a chapter
        # always ends with a checkpoint, so we can use lessons of type checkpoint as boundary for each chapter.

        # The chapter information has to be queried from a GraphQL endpoint
        chapters_by_level = extract_chapters_by_level(course_pack, selected_language)

        # From here onwards we work with our classes
        course = map_to_course(course_structure, chapters_by_level)

        lessons_for_pack: list[tuple[Path, object]] = []

        for lvl in course.levels:
            lvl_subdir = course_pack_path / sanitize_filename(lvl.id, platform.system())
            lvl_subdir.mkdir(parents=True, exist_ok=True)
            chapter_index = 0
            for chapter in lvl.chapters:
                chapter_name = chapter.name.replace(" ", "_").lower()
                chapter_indexed_name = f"{chapter_index}-{chapter_name}"
                chapter_subdir = lvl_subdir / sanitize_filename(chapter_indexed_name, platform.system())
                chapter_index += 1
                chapter_subdir.mkdir(parents=True, exist_ok=True)
                for lesson in chapter.lessons:
                    lessons_for_pack.append((chapter_subdir, lesson))

        course_pack_items.append((course_pack, course_pack_path, lessons_for_pack))

    # Create one persistent progress bar per course pack, each pinned to its own terminal
    # row via `position`. `leave=True` keeps finished bars visible so the final state is readable.
    pack_bars = [
        tqdm(
            total=len(lessons),
            desc=f"{pack:<30}",  # left-aligned, fixed width so bars line up
            unit="lesson",
            position=index,
            leave=True,
        )
        for index, (pack, _, lessons) in enumerate(course_pack_items)
    ]

    # Second pass: download every lesson and advance that pack's bar on each completion
    try:
        for (course_pack, course_pack_path, lessons_for_pack), pbar in zip(course_pack_items, pack_bars):
            for chapter_subdir, lesson in lessons_for_pack:
                # Build the lesson URL dynamically and retrieve the associated lesson JSON
                lesson_url = base_lesson_url.format(lesson_id=lesson.id, lang=selected_language)

                raw_response = session.get(lesson_url)
                assert_response_ok(raw_response)
                raw_json = raw_response.json()

                text = json.dumps(raw_json, ensure_ascii=False)
                out_path = chapter_subdir / sanitize_filename(f"{lesson.id}.json", platform.system())
                out_path.write_text(text, encoding="utf-8")

                pbar.update(1)
    finally:
        for pbar in pack_bars:
            pbar.close()

    return 0



main()
