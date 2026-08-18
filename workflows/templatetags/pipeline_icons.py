from django import template

register = template.Library()

ICONS = {
    'webhook': '⇄',
    'condition': '◇',
    'http': '↗',
    'telegram': '✉',
}


@register.filter
def pipe_icon(node_type):
    return ICONS.get(node_type, '●')