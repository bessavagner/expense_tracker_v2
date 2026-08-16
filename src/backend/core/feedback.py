"""Somewhere for a beta user to say what the numbers cannot.

S14-5: quantitative data tells you what happened and never why. This is the only
place in E14 that stores user-authored text on purpose, which is exactly why it
has its own model rather than riding in `ProductEvent.metadata`.

The confirmation promises the message will be read. `docs/runbook.md` says who
reads it and when — a promise made in the UI should be one the process keeps.
"""

from django import forms
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpResponse
from django.template.loader import render_to_string
from django.views import View

from core.models import Feedback

#: Matches `Feedback.message`'s `max_length`. A 2 MB paste is not feedback; the
#: cap is a storage bound, not a judgement about what anyone has to say.
MAX_LENGTH = 4000


class FeedbackForm(forms.Form):
    #: No `max_length` on the field on purpose. A length cap here would *reject*
    #: a long paste and lose it; the point is to keep what someone took the
    #: trouble to write, bounded. Emptiness is the only thing worth rejecting.
    message = forms.CharField(
        label="O que você quer nos contar?",
        widget=forms.Textarea(attrs={"rows": 4, "class": "textarea w-full h-24"}),
        strip=True,
    )

    def clean_message(self):
        message = (self.cleaned_data.get("message") or "").strip()
        if not message:
            raise forms.ValidationError("Escreva alguma coisa antes de enviar.")
        return message[:MAX_LENGTH]


class FeedbackView(LoginRequiredMixin, View):
    """Accepts one message, scoped to the sender's household.

    Returns a fragment rather than a redirect: the form lives in a modal, and a
    redirect would close the page the user was looking at when they had
    something to say about it.
    """

    def get(self, request):
        """The empty form, loaded into the modal on open.

        A GET rather than rendering the form into `base.html` on every request:
        the entry modal already works this way, and an unbound form built on
        every page view is work done for a modal almost nobody opens.
        """
        return HttpResponse(
            render_to_string("core/_feedback_form.html", {"form": FeedbackForm()}, request=request)
        )

    def post(self, request):
        form = FeedbackForm(request.POST)
        if not form.is_valid():
            return HttpResponse(
                render_to_string("core/_feedback_form.html", {"form": form}, request=request),
                status=400,
            )
        Feedback.objects.create(
            household=request.household,
            user=request.user,
            message=form.cleaned_data["message"],
            # Where they were, and nothing they typed anywhere else. `context` is
            # for making a report actionable, not for collecting behaviour.
            context={"path": (request.META.get("HTTP_REFERER") or "")[:500]},
        )
        return HttpResponse(render_to_string("core/_feedback_thanks.html", {}, request=request))
