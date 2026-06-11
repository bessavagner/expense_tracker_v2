# src/backend/finances/tests/test_entries_page_sections.py
from datetime import date
from django.test import TestCase
from model_bakery import baker
from core.models import CustomUser


class TestEntriesPageSections(TestCase):
    def setUp(self):
        self.user = baker.make(CustomUser)
        self.client.force_login(self.user)

    def test_entries_page_includes_income_section_loader(self):
        resp = self.client.get("/entries/2026/10/")
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode()
        # The page should lazy-load the income section for this month via htmx.
        self.assertIn("/cockpit/2026/10/income/", body)
