"""The release notes used when a commit has no pull request: the commit subjects since the previous release."""
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parent.parent / ".github" / "scripts" / "commit-notes.sh"

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="a bash script, used on the Linux release runner")


class Repo:
    def __init__(self, path: Path):
        self.path = path
        self.git("init", "-q", "-b", "master")
        self.git("config", "user.name", "t")
        self.git("config", "user.email", "t@example.com")
        self.count = 0

    def git(self, *args: str) -> str:
        return subprocess.run(["git", *args], cwd=self.path, check=True, capture_output=True, text=True).stdout.strip()

    def commit(self, subject: str, file: str = "f") -> str:
        self.count += 1
        (self.path / file).write_text(str(self.count))
        self.git("add", file)
        self.git("commit", "-q", "-m", subject)
        return self.git("rev-parse", "--short", "HEAD")

    def tag(self, name: str) -> None:
        self.git("tag", name)

    def notes(self, stable: bool, sha: str = "HEAD") -> str:
        full = self.git("rev-parse", sha)
        result = subprocess.run(["bash", str(SCRIPT), full, "true" if stable else "false"],
                                cwd=self.path, check=True, capture_output=True, text=True)
        return result.stdout


@pytest.fixture
def repo(tmp_path):
    return Repo(tmp_path)


def test_lists_the_commit_subjects_since_the_previous_release_newest_first(repo):
    repo.commit("old")
    repo.tag("v0.1.1")
    first = repo.commit(":sparkles: add a thing")
    second = repo.commit(":bug: fix the thing")

    assert repo.notes(stable=True) == (
        "### Changes since v0.1.1\n\n"
        f"- :bug: fix the thing ({second})\n"
        f"- :sparkles: add a thing ({first})\n")


def test_a_stable_release_looks_past_beta_releases_to_the_previous_stable_one(repo):
    repo.commit("old")
    repo.tag("v0.1.1")
    a = repo.commit("a")
    repo.tag("v0.1.2-beta")
    b = repo.commit("b")

    notes = repo.notes(stable=True)

    assert notes.startswith("### Changes since v0.1.1\n")
    assert f"- a ({a})" in notes and f"- b ({b})" in notes


def test_a_beta_release_lists_only_what_is_new_since_the_nearest_release_of_any_kind(repo):
    repo.commit("old")
    repo.tag("v0.1.1")
    repo.commit("a")
    repo.tag("v0.1.2-beta")
    b = repo.commit("b")

    assert repo.notes(stable=False) == f"### Changes since v0.1.2-beta\n\n- b ({b})\n"


def test_with_no_earlier_release_every_commit_is_listed(repo):
    a = repo.commit("a")
    b = repo.commit("b")

    assert repo.notes(stable=True) == f"### Changes\n\n- b ({b})\n- a ({a})\n"


def test_merge_commits_are_left_out(repo):
    repo.commit("base")
    repo.tag("v0.1.1")
    repo.git("checkout", "-q", "-b", "feature")
    work = repo.commit("feature work")
    repo.git("checkout", "-q", "master")
    other = repo.commit("master work", file="g")
    repo.git("merge", "-q", "--no-ff", "-m", "Merge branch 'feature'", "feature")

    notes = repo.notes(stable=True)

    assert "Merge branch" not in notes
    assert f"- feature work ({work})" in notes and f"- master work ({other})" in notes


def test_a_commit_that_is_itself_tagged_is_compared_with_the_release_before_it(repo):
    repo.commit("old")
    repo.tag("v0.1.1")
    a = repo.commit("a")
    repo.tag("v0.1.2")  # a re-run of the job for a release that already exists

    assert repo.notes(stable=True) == f"### Changes since v0.1.1\n\n- a ({a})\n"


def test_tags_that_are_not_releases_are_ignored(repo):
    repo.commit("old")
    repo.tag("v0.1.1")
    repo.commit("a")
    repo.tag("wip")

    assert repo.notes(stable=True).startswith("### Changes since v0.1.1\n")


def test_a_very_long_history_is_capped(repo):
    for n in range(105):
        repo.commit(f"c{n}")

    notes = repo.notes(stable=True)

    assert notes.count("\n- ") == 100
    assert "c104" in notes and "c4 " not in notes
