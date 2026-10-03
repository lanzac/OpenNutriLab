from collections.abc import Sequence
from typing import Any

from factory.django import DjangoModelFactory
from factory.faker import Faker
from factory.helpers import post_generation

from opennutrilab.users.models import User


class UserFactory(DjangoModelFactory[User]):
    username = Faker("user_name")
    email = Faker("email")
    name = Faker("name")

    @post_generation
    def password(self, create: bool, extracted: Sequence[Any], **kwargs):  # noqa: FBT001
        password = (
            extracted
            if extracted
            else Faker(
                "password",
                length=42,
                special_chars=True,
                digits=True,
                upper_case=True,
                lower_case=True,
            ).evaluate(None, None, extra={"locale": None})
        )
        # factory_boy hands post-generation hooks the built User, not the factory.
        self.set_password(password)  # pyright: ignore[reportAttributeAccessIssue]

    @classmethod
    def _after_postgeneration(cls, instance, create, results=None):
        """Save again the instance if creating and at least one hook ran."""
        if create and results and not cls._meta.skip_postgeneration_save:  # pyright: ignore[reportAttributeAccessIssue]
            # Some post-generation hooks ran, and may have modified us.
            instance.save()

    class Meta:
        model = User
        django_get_or_create = ["username"]
