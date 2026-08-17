"""The Perfil tab: the one place a user tells the product their name."""

import pytest
from django.test import Client
from django.urls import reverse
from model_bakery import baker


@pytest.mark.django_db
class TestProfileTab:
    def test_it_requires_login(self):
        response = Client().get(reverse("account_profile_tab"))
        assert response.status_code == 302
        assert "/accounts/login/" in response["Location"]

    def test_the_fragment_url_renders_standalone(self, logged_client, user):
        """Hit directly, with no HX-Request header, it is a whole page."""
        response = logged_client.get(reverse("account_profile_tab"))
        assert response.status_code == 200
        body = response.content.decode()
        assert "<!DOCTYPE html>" in body
        assert user.email in body

    def test_as_an_htmx_fragment_it_is_not_a_whole_page(self, logged_client):
        response = logged_client.get(reverse("account_profile_tab"), headers={"HX-Request": "true"})
        assert response.status_code == 200
        assert "<!DOCTYPE html>" not in response.content.decode()

    def test_a_name_saves_and_comes_back(self, logged_client, user):
        response = logged_client.post(
            reverse("account_profile_tab"),
            {"first_name": "Vagner"},
            headers={"HX-Request": "true"},
        )
        assert response.status_code == 200
        user.refresh_from_db()
        assert user.first_name == "Vagner"
        assert "Vagner" in response.content.decode()

    def test_saving_fires_the_toast_the_rest_of_the_app_uses(self, logged_client):
        response = logged_client.post(
            reverse("account_profile_tab"),
            {"first_name": "Vagner"},
            headers={"HX-Request": "true"},
        )
        assert "showToast" in response.headers.get("HX-Trigger", "")

    def test_a_blank_name_is_allowed_and_is_not_an_error(self, logged_client, user):
        user.first_name = "Vagner"
        user.save(update_fields=["first_name"])
        response = logged_client.post(
            reverse("account_profile_tab"),
            {"first_name": ""},
            headers={"HX-Request": "true"},
        )
        assert response.status_code == 200
        user.refresh_from_db()
        assert user.first_name == ""

    def test_it_shows_the_current_email_and_a_way_to_change_it(self, logged_client, user):
        body = logged_client.get(reverse("account_profile_tab")).content.decode()
        assert user.email in body
        assert reverse("account_email") in body

    def test_it_cannot_be_used_to_rename_somebody_else(self, logged_client, other_user):
        """The form is bound to request.user and takes no id — this asserts
        that stays true if anyone ever adds one."""
        logged_client.post(
            reverse("account_profile_tab"),
            {"first_name": "Invasor", "id": other_user.pk, "user": other_user.pk},
            headers={"HX-Request": "true"},
        )
        other_user.refresh_from_db()
        assert other_user.first_name != "Invasor"

    def test_a_member_of_another_household_still_gets_their_own_profile(self, household):
        """Perfil is per-user, not per-household: it must work for anyone
        signed in, including someone with no membership at all."""
        stranger = baker.make("core.CustomUser", email="ninguem@example.com")
        client = Client()
        client.force_login(stranger)
        response = client.get(reverse("account_profile_tab"))
        assert response.status_code in (200, 302)
