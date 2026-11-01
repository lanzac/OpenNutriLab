from crispy_forms.bootstrap import AccordionGroup
from crispy_forms.bootstrap import LayoutObject
from crispy_forms.layout import Div
from django.utils.safestring import SafeText


class AccordionGroupExtended(AccordionGroup):
    template = "crispy_bootstrap_extend/accordion-group-extended-base.html"

    def __init__(  # noqa: PLR0913
        self,
        name: str,
        *fields: str | LayoutObject,
        css_id: str | None = None,
        css_class: str | None = None,
        template: str | None = None,
        active: bool | None = None,
        extra_data: SafeText | None = None,
        **kwargs,  # pyright: ignore[reportUnknownParameterType, reportMissingParameterType]
    ):
        self.extra_data = extra_data  # We keep it as usable attribute in the template
        super().__init__(  # pyright: ignore[reportUnknownMemberType]
            name,
            *fields,
            css_id=css_id,
            css_class=css_class,
            template=template,
            **kwargs,  # pyright: ignore[reportUnknownArgumentType]
        )


class FoldableGroup(Div):
    """
    A group of fields under a head that folds it, with how many of them hold a value
    (see frontend/src/apps/products/form/foldable-groups.js, which keeps that count and
    the person's choice of open and closed groups).
    """

    template = "crispy_bootstrap_extend/foldable-group.html"

    def __init__(  # noqa: PLR0913
        self,
        name: str,
        *fields: str | LayoutObject,
        key: str,
        css_id: str,
        is_open: bool,
        filled: int,
        total: int,
        **kwargs,  # pyright: ignore[reportUnknownParameterType, reportMissingParameterType]
    ):
        self.name = name
        self.key = key
        self.is_open = is_open
        self.filled = filled
        self.total = total
        super().__init__(*fields, css_id=css_id, **kwargs)  # pyright: ignore[reportUnknownArgumentType]
