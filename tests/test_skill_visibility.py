from app.modules.recruitment.skill_visibility import matches_role_skills


def test_frontend_domain_matches_a_specific_frontend_skill() -> None:
    assert matches_role_skills(["Frontend"], [{"name": "Next.js"}])
    assert matches_role_skills(["Front-end development"], [{"name": "React.js"}])


def test_any_listed_role_skill_can_make_the_role_visible() -> None:
    assert matches_role_skills(["React.js", "Next.js"], [{"name": "Next.js"}])
    assert matches_role_skills(["React.js"], [{"name": "React"}])


def test_unrelated_or_missing_student_skills_do_not_match() -> None:
    assert not matches_role_skills(["Frontend"], [{"name": "Python"}])
    assert not matches_role_skills(["React.js", "Next.js"], [])
    assert not matches_role_skills(["React.js"], [{"name": "Angular"}])


def test_roles_without_listed_skills_remain_visible() -> None:
    assert matches_role_skills([], [])
