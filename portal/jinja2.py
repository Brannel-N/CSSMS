from datetime import date

from django.contrib.auth import get_user_model
from django.contrib.messages import get_messages
from django.templatetags.static import static
from django.urls import reverse
from jinja2 import Environment, pass_context


def url_for(endpoint, **values):
    if endpoint == "static":
        return static(values["filename"])
    return reverse(endpoint, kwargs=values or None)


@pass_context
def get_flashed_messages(context, with_categories=False):
    request = context.get("request")
    if request is None:
        return []
    messages = list(get_messages(request))
    if with_categories:
        return [(message.tags, str(message)) for message in messages]
    return [str(message) for message in messages]


def environment(**options):
    options.setdefault("autoescape", True)
    env = Environment(**options)
    env.globals.update(
        url_for=url_for,
        get_flashed_messages=get_flashed_messages,
    )
    return env
