"""Facts about a resume that code computes, so no model ever does arithmetic or guesses a date.

"Today" is always passed in, so every test is deterministic.
"""
from datetime import date

import pytest

from app.rmg.resume.facts import dedupe_skills, experience, parse_month
from app.rmg.resume.model import Item, Job, Origin, Resume, SkillGroup

TODAY = date(2026, 11, 5)


def job(start, end, company="Acme"):
    return Job(company=company, title="Engineer", start=start, end=end)


def skill(text, n=0):
    return Item(text=text, origin=Origin.ORIGINAL, source=f"skills.{n}")


# --- reading a date -----------------------------------------------------------------------------

@pytest.mark.parametrize("text,expected", [
    ("Mar 2020", (2020, 3)), ("March 2020", (2020, 3)), ("sept 2019", (2019, 9)), ("03/2020", (2020, 3)),
    ("2020-03", (2020, 3)), ("  MAR  2020 ", (2020, 3)), ("Mar'20", (2020, 3)),
])
def test_common_month_formats_are_read(text, expected):
    assert parse_month(text, TODAY) == expected


@pytest.mark.parametrize("text", ["Present", "current", "Till date", "Now", "ongoing", "to date"])
def test_words_meaning_still_working_mean_today(text):
    assert parse_month(text, TODAY) == (2026, 11)


def test_a_bare_year_is_the_start_or_end_of_that_year_depending_on_which_it_is():
    assert parse_month("2020", TODAY) == (2020, 1)
    assert parse_month("2020", TODAY, as_end=True) == (2020, 12)


@pytest.mark.parametrize("text", ["", "   ", None, "soon", "13/2020", "Foo 2020", "1850", "Mar 3020"])
def test_anything_unreadable_is_none_and_never_a_guess(text):
    assert parse_month(text, TODAY) is None


# --- experience ---------------------------------------------------------------------------------

def test_a_single_job_counts_both_end_months():
    result = experience([job("Jan 2020", "Dec 2020")], TODAY)

    assert result.months == 12 and (result.years, result.extra_months) == (1, 0)


def test_a_current_job_runs_up_to_today():
    assert experience([job("Mar 2020", "Present")], TODAY).months == 6 * 12 + 9  # Mar 2020 .. Nov 2026


def test_overlapping_jobs_count_the_overlap_once():
    jobs = [job("Jan 2020", "Dec 2021"), job("Jun 2021", "Jun 2022", "Beta")]

    assert experience(jobs, TODAY).months == 30  # Jan 2020 .. Jun 2022


def test_a_gap_between_jobs_is_not_counted():
    jobs = [job("Jan 2018", "Dec 2018"), job("Jan 2020", "Dec 2020", "Beta")]

    assert experience(jobs, TODAY).months == 24


def test_a_missing_end_date_means_the_job_is_current():
    assert experience([job("Jan 2026", None)], TODAY).months == 11


def test_jobs_that_cannot_be_dated_are_skipped_and_reported_not_guessed():
    jobs = [job("Jan 2020", "Dec 2020"), job("sometime", "later", "Mystery Co"), job(None, "2019", "No Start")]

    result = experience(jobs, TODAY)

    assert result.months == 12 and result.skipped == ("Mystery Co", "No Start")


def test_an_end_before_the_start_is_skipped():
    result = experience([job("Dec 2021", "Jan 2020", "Backwards")], TODAY)

    assert result.months == 0 and result.skipped == ("Backwards",)


def test_a_future_start_is_skipped_and_a_future_end_stops_at_today():
    result = experience([job("Jan 2027", "Dec 2027", "Future"), job("Jan 2026", "Dec 2030")], TODAY)

    assert result.months == 11 and result.skipped == ("Future",)


def test_no_jobs_is_zero_experience():
    result = experience([], TODAY)

    assert result.months == 0 and result.describe() == "less than a month"


@pytest.mark.parametrize("months,text", [(1, "1 month"), (12, "1 year"), (15, "1 year 3 months"), (97, "8 years 1 month"), (96, "8 years")])
def test_experience_is_described_in_plain_words(months, text):
    jobs = [job("Jan 2000", "Dec 2000")]
    result = experience(jobs, TODAY)
    assert result.describe() == "1 year"

    from app.rmg.resume.facts import Experience
    assert Experience(months=months, skipped=()).describe() == text


# --- skills -------------------------------------------------------------------------------------

def resume_with_groups(*groups):
    return Resume(name="A", skill_groups=[SkillGroup(category=c, items=items) for c, items in groups])


def test_a_repeated_skill_is_kept_once_ignoring_case_and_spacing():
    resume = resume_with_groups(("Backend", [skill("Spring Boot", 0), skill("spring  boot", 1), skill("Java", 2)]))

    result = dedupe_skills(resume)

    assert result.skills_flat() == ["Spring Boot", "Java"]


def test_a_skill_repeated_in_another_group_stays_in_the_first_and_empty_groups_go():
    resume = resume_with_groups(("Backend", [skill("Java")]), ("Languages", [skill("java"), skill("Python", 1)]),
                                ("Dupes", [skill("JAVA"), skill("Python")]))

    result = dedupe_skills(resume)

    assert [(g.category, [i.text for i in g.items]) for g in result.skill_groups] == [
        ("Backend", ["Java"]), ("Languages", ["Python"])]


def test_deduplication_keeps_provenance_and_does_not_change_the_original():
    resume = resume_with_groups(("Backend", [skill("Java", 3), skill("java", 4)]))

    result = dedupe_skills(resume)

    assert result.skill_groups[0].items[0].source == "skills.3"
    assert len(resume.skill_groups[0].items) == 2


def test_a_job_without_a_company_still_counts_and_a_skipped_one_is_named_by_its_title():
    jobs = [Job(title="Freelance developer", start="Jan 2020", end="Dec 2020"), Job(title="Consultant", start="sometime", end="later")]

    result = experience(jobs, TODAY)

    assert result.months == 12 and result.skipped == ("Consultant",)
