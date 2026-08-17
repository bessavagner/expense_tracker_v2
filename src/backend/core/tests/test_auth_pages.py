"""Every auth page renders, in pt-BR, in the product's shell.

allauth's stock templates are unstyled English. Shipping them is the spec's
named failure condition — these pages are a stranger's first impression of a
financial product, and an unstyled form reads as a phishing page.
"""

import pytest
from django.core import mail
from django.test import Client
from django.urls import reverse
from model_bakery import baker

PAGES = [
    ("account_login", "Entrar"),
    ("account_signup", "Criar conta"),
    ("account_reset_password", "Recuperar senha"),
]


@pytest.mark.django_db
@pytest.mark.parametrize("url_name,expected_copy", PAGES)
def test_page_renders_in_ptbr(url_name, expected_copy):
    response = Client().get(reverse(url_name))
    assert response.status_code == 200
    body = response.content.decode()
    assert expected_copy in body


@pytest.mark.django_db
@pytest.mark.parametrize("url_name,_copy", PAGES)
def test_page_uses_the_product_shell(url_name, _copy):
    """The theme bootstrap lives in base_public.html; its absence means the
    page fell back to allauth's own unstyled base."""
    body = Client().get(reverse(url_name)).content.decode()
    assert 'lang="pt-BR"' in body
    assert "css/tailwind.css" in body


@pytest.mark.django_db
@pytest.mark.parametrize("url_name,_copy", PAGES)
def test_no_template_syntax_leaks_into_the_page(url_name, _copy):
    """Django's `{# #}` comment is single-line only.

    Written across three lines it is not a comment at all — the opener is
    literal text and the whole paragraph renders at the top of the page, above
    the card. Every copy assertion in this module still passed while that was
    happening, because they only ask what the page contains.
    """
    body = Client().get(reverse(url_name)).content.decode()
    for leak in ("{#", "{%", "{{"):
        assert leak not in body, f"unrendered template syntax on {url_name}"


@pytest.mark.django_db
class TestNoEnglishLeaksThrough:
    def test_signup_page_has_no_stock_english(self):
        body = Client().get(reverse("account_signup")).content.decode()
        for stock in ("Sign Up", "Sign In", "Already have an account", "Forgot Password"):
            assert stock not in body

    def test_a_page_this_repo_does_not_override_still_gets_the_shell(self):
        """The MFA screens are stock allauth. They inherit the product's head
        from `allauth/layouts/base.html`, which is the whole reason that file
        is overridden at the top of the chain rather than page by page."""
        staff = baker.make("core.CustomUser", email="operador@example.com", is_staff=True)
        client = Client()
        client.force_login(staff)
        # The MFA index, reached through allauth/layouts/manage.html — a
        # different branch of the chain from the entrance pages, which is what
        # makes it worth asserting. (The TOTP activate page itself 302s to
        # reauthentication first, so it cannot answer this question.)
        body = client.get("/accounts/2fa/").content.decode()
        assert 'lang="pt-BR"' in body
        assert "css/tailwind.css" in body


@pytest.mark.django_db
class TestEmailsAreInPortuguese:
    def test_the_verification_email_is_ptbr(self):
        Client().post(
            reverse("account_signup"),
            {
                "email": "nova@example.com",
                "email2": "nova@example.com",
                "password1": "uma-senha-bem-longa-9",
                "password2": "uma-senha-bem-longa-9",
                # E13: the signup form now carries a required acceptance checkbox.
                "accept_terms": "on",
            },
        )
        assert len(mail.outbox) == 1
        message = mail.outbox[0]
        assert "Confirme" in message.subject
        assert "http" in message.body
        for stock in ("Hello from", "Please confirm", "You're receiving"):
            assert stock not in message.body

    def test_the_password_reset_email_is_ptbr(self):
        baker.make("core.CustomUser", email="volta@example.com")
        Client().post(reverse("account_reset_password"), {"email": "volta@example.com"})
        assert len(mail.outbox) == 1
        assert "senha" in mail.outbox[0].subject.lower()


@pytest.mark.django_db
class TestTheDeadEndsHaveAWayOut:
    """Every terminal page names the next step.

    A page that says "verifique seu e-mail" and nothing else is where a signup
    funnel loses people: the link expired, or went to the wrong address, and
    the page offers no way to say so.
    """

    def test_verification_sent_page_says_how_long_the_link_lasts(self):
        response = Client().post(
            reverse("account_signup"),
            {
                "email": "prazo@example.com",
                "email2": "prazo@example.com",
                "password1": "uma-senha-bem-longa-9",
                "password2": "uma-senha-bem-longa-9",
                # E13: the signup form now carries a required acceptance checkbox.
                "accept_terms": "on",
            },
            follow=True,
        )
        body = response.content.decode()
        assert "3 dias" in body

    def test_password_reset_done_does_not_confirm_the_address_exists(self):
        """ACCOUNT_PREVENT_ENUMERATION is on; the page must not contradict it."""
        body = (
            Client()
            .post(reverse("account_reset_password"), {"email": "ninguem@example.com"}, follow=True)
            .content.decode()
        )
        assert "Se existe uma conta" in body
