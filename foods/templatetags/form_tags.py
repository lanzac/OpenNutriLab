from django import template

register = template.Library()

@register.filter
def get_field(form, field_name):
    """Récupère un champ spécifique du formulaire"""
    return form[field_name]

@register.filter
def field_help_text(field):
    """Récupère le help_text d'un champ"""
    return field.help_text or ""