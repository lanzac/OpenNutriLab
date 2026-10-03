import pytest

from opennutrilab.users.models import User
from opennutrilab.users.tests.factories import UserFactory


@pytest.fixture(autouse=True)
def _media_storage(settings, tmpdir) -> None:
    # At the repository root so it covers every app's tests: uploads and
    # downloaded photos must never land in, or overwrite files in, the
    # development MEDIA_ROOT.
    settings.MEDIA_ROOT = tmpdir.strpath


@pytest.fixture
def user(db) -> User:
    return UserFactory()
