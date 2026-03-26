from django import template

register = template.Library()


@register.filter
def get_item(dictionary, key):
    """Access dict value by key in templates: {{ dict|get_item:key }}"""
    if isinstance(dictionary, dict):
        return dictionary.get(key, "")
    return ""
