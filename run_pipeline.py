from database.database import close_driver
from v2.lesson_scraper import main as scrape_main
from v2.cleaning import main as clean_main
from database.pair_mapper import run_import as pair_main
from database.group_mapper import run_import as group_main
from database.gap_fill_mapper import run_import as gap_main
from database.list_mapper import run_import as list_main
from database.question_mapper import run_import as question_main


def run_step(name: str, fn):
    print(f"\n--- Running: {name} ---")
    result = fn()
    if result not in (0, None):
        raise RuntimeError(f"{name} failed with exit code {result}")
    print(f"--- Done: {name} ---")


def main() -> int:
    selected_language = scrape_main()
    path = "01-cleaned_courses"

    run_step("clean", clean_main)
    run_step("pair mapping",     lambda: pair_main(path))
    run_step("group mapping",    lambda: group_main(path))
    run_step("list mapping",     lambda: list_main(path))
    run_step("question mapping", lambda: question_main(path))
    run_step("gap fill mapping", lambda: gap_main(path))
    close_driver()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())