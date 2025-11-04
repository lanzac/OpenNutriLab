from crispy_forms.bootstrap import AccordionGroup
from crispy_forms.bootstrap import LayoutObject
from django.utils.safestring import SafeText


class AccordionGroupExtended(AccordionGroup):
    template = "crispy_bootstrap_extend/accordion-group-extended.html"

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
