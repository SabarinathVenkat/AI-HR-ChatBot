"""Made-up resumes of very different shapes for the layout lab, from nearly empty to far too long."""
from app.rmg.resume.model import Education, Item, Job, Origin, Project, Resume, SkillGroup

LOREM = ("Designed, built and operated production services handling high volumes of traffic, working closely with "
         "product owners and other teams to deliver reliable features on schedule")


def _i(text, n=0):
    return Item(text=text, origin=Origin.ORIGINAL, source=f"s.{n}")


def _groups(count, per, prefix="Tech"):
    return [SkillGroup(category=f"{prefix} area {g + 1}", items=[_i(f"{prefix}{g}-{k}", k) for k in range(per)])
            for g in range(count)]


def _projects(count, bullets, bullet_text=LOREM, description=True):
    return [Project(name=f"Project {n + 1} platform modernisation",
                    description=_i(LOREM + ".") if description else None,
                    bullets=[_i(f"{bullet_text} (item {k + 1}).", k) for k in range(bullets)])
            for n in range(count)]


def _jobs(count):
    return [Job(company=f"Company {n + 1}", title="Software Engineer", start=f"Jan {2000 + n * 2}", end=f"Dec {2001 + n * 2}")
            for n in range(count)]


def _edu(count=1):
    return [Education(degree="B.E. Computer Science and Engineering", institution="Some Institute of Technology", year="2012")
            for _ in range(count)]


RESUMES = {
    "tiny": Resume(name="Tina Tiny", skill_groups=_groups(1, 3), education=_edu()),
    "typical": Resume(
        name="Anil Verma", role_title=_i("Senior Backend Engineer"), summary=_i(LOREM + ". " + LOREM + "."),
        skill_groups=_groups(4, 6), education=_edu(), certifications=["AWS Certified Developer"],
        highlights=[_i(f"Highlight {k}: {LOREM}.", k) for k in range(4)], jobs=_jobs(3), projects=_projects(3, 4)),
    "heavy": Resume(
        name="Hari Heavy", role_title=_i("Principal Data and Platform Engineer, ML and Cloud Architecture"),
        summary=_i((LOREM + ". ") * 6),
        skill_groups=_groups(10, 14), education=_edu(2), certifications=[f"Certification number {k}" for k in range(6)],
        highlights=[_i(f"Highlight {k}: {LOREM}.", k) for k in range(8)], jobs=_jobs(6), projects=_projects(6, 6)),
    "long_bullets": Resume(
        name="Lena Longwinded", skill_groups=_groups(3, 8), education=_edu(),
        highlights=[_i((LOREM + ". ") * 4, 0)], projects=_projects(2, 3, bullet_text=(LOREM + ", ") * 5)),
    "long_tokens": Resume(
        name="Urla Unbreakable", skill_groups=[SkillGroup(category="Links", items=[_i("https://example.com/" + "path/" * 30, 0), _i("A" * 120, 1)])],
        education=_edu(), highlights=[_i("See " + "x" * 150, 0)],
        projects=[Project(name="P" * 90, description=None, bullets=[_i("https://github.com/" + "folder/" * 25, 0)])]),
    "unicode": Resume(
        name="Zoë Müller-Ñandú", role_title=_i("Ingénieur logiciel – données"), skill_groups=[SkillGroup(category="Langues", items=[_i("Français", 0), _i("日本語", 1), _i("Ελληνικά", 2)])],
        education=[Education(degree="Master – Informatique", institution="Université de Strasbourg", year="2014")],
        highlights=[_i("Géré une équipe de 5 personnes — très réussi.", 0)], projects=_projects(1, 2)),
    "no_projects": Resume(name="Nora NoProjects", summary=_i(LOREM + "."), skill_groups=_groups(3, 5), education=_edu(),
                          highlights=[_i(f"Highlight {k}: {LOREM}.", k) for k in range(3)], jobs=_jobs(2)),
    "no_skills": Resume(name="Sam NoSkills", education=_edu(), highlights=[_i(LOREM + ".", 0)], projects=_projects(2, 3)),
    "many_short_projects": Resume(name="Mia Many", skill_groups=_groups(5, 8), education=_edu(),
                                  highlights=[_i(LOREM + ".", 0)], projects=_projects(14, 2, bullet_text="Delivered a feature")),
}
