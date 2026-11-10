"""RMG roles, the Competency Lead mapping and the demo people for the resume builder."""
import pytest

from app.db.seed import email_for
from app.rmg.resume.demo import DEMO_PEOPLE, seed_resume_demo
from app.rmg.resume.people import PeopleError, assign_role, lead_of, list_assignments, roles_of, set_lead


def employee_id(conn, name):
    return conn.execute("SELECT id FROM employees WHERE email = ?", (email_for(name),)).fetchone()["id"]


def test_an_employee_has_no_rmg_roles_until_given_one(db):
    assert roles_of(db, 4) == frozenset()

    assign_role(db, 4, "rmg_staff")
    assign_role(db, 4, "rmg_staff")  # twice is harmless

    assert roles_of(db, 4) == {"rmg_staff"}


def test_an_unknown_role_is_refused(db):
    with pytest.raises(PeopleError) as e:
        assign_role(db, 4, "superuser")
    assert e.value.code == "unknown_role"


def test_only_a_competency_lead_can_be_chosen_as_a_lead(db):
    with pytest.raises(PeopleError) as e:
        set_lead(db, associate_id=4, lead_id=5)
    assert e.value.code == "not_a_lead"


def test_a_lead_cannot_be_their_own_lead(db):
    assign_role(db, 5, "competency_lead")

    with pytest.raises(PeopleError) as e:
        set_lead(db, associate_id=5, lead_id=5)
    assert e.value.code == "self_lead"


def test_a_lead_is_assigned_and_can_be_replaced(db):
    assign_role(db, 5, "competency_lead")
    assign_role(db, 7, "competency_lead")

    set_lead(db, 4, 5)
    assert lead_of(db, 4) == 5
    set_lead(db, 4, 7)

    assert lead_of(db, 4) == 7 and len(list_assignments(db)) == 1


def test_an_associate_without_a_lead_has_none(db):
    assert lead_of(db, 4) is None


def test_the_demo_adds_one_account_per_role_and_maps_leads(db):
    seed_resume_demo(db, hash_password=lambda p: "h")

    assert roles_of(db, employee_id(db, "Sam Joseph")) == {"rmg_staff"}
    assert roles_of(db, employee_id(db, "Rhea Kapoor")) == {"rmg_head"}
    lead = employee_id(db, "Lakshmi Narayan")
    assert roles_of(db, lead) == {"competency_lead"}
    assert lead_of(db, 4) == lead and lead_of(db, 6) is None  # Sanjay has no lead on purpose: the "no lead" case
    assert db.execute("SELECT count(*) FROM job_descriptions").fetchone()[0] == 1


def test_the_demo_seed_can_run_again_without_duplicating_anything(db):
    tables = ("employees", "rmg_roles", "lead_assignments", "job_descriptions")
    seed_resume_demo(db, hash_password=lambda p: "h")
    counts = [db.execute(f"SELECT count(*) FROM {t}").fetchone()[0] for t in tables]

    seed_resume_demo(db, hash_password=lambda p: "h")

    assert counts == [db.execute(f"SELECT count(*) FROM {t}").fetchone()[0] for t in tables]
    assert len(DEMO_PEOPLE) == 3
