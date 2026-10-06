import pytest

from opennutrilab.products.models import Additive
from opennutrilab.users.models import User
from opennutrilab.users.tests.factories import UserFactory


@pytest.fixture(scope="session")
def django_db_setup(django_db_setup, django_db_blocker):
    """
    The additives are loaded by a migration (see products/migrations/0013), so the
    test database has the whole list. The tests make the few they need, with codes and
    names of their own, so they start from none: those that want the dataset load it.
    """
    with django_db_blocker.unblock():
        Additive.objects.all().delete()


@pytest.fixture(autouse=True)
def _media_storage(settings, tmpdir) -> None:
    # At the repository root so it covers every app's tests: uploads and
    # downloaded photos must never land in, or overwrite files in, the
    # development MEDIA_ROOT.
    settings.MEDIA_ROOT = tmpdir.strpath


@pytest.fixture
def user(db) -> User:
    return UserFactory()
