from datetime import date

from django.test import TestCase
from model_bakery import baker

from core.models import CustomUser
from finances.models import Category, Entry
from finances.models.entry import EntryType


class TestCategoryDetailEntryTypeFilter(TestCase):
    def setUp(self):
        self.user = baker.make(CustomUser)
        self.client.force_login(self.user)
        self.cat = baker.make(Category, user=self.user, name="Casa")
        self.regular = baker.make(
            Entry, user=self.user, category=self.cat, amount="10.00",
            description="Alcir - estorno do vizinho", date=date(2026, 2, 20),
            billing_month=date(2026, 2, 1), entry_type=EntryType.REGULAR,
        )
        self.systemic = baker.make(
            Entry, user=self.user, category=self.cat, amount="50.00",
            description="Aluguel", date=date(2026, 2, 1),
            billing_month=date(2026, 2, 1), entry_type=EntryType.SYSTEMIC,
        )

    def test_systemic_detail_excludes_diverse(self):
        resp = self.client.get(
            f"/consolidated/detail/{self.cat.id}/2026/2/?type=systemic"
        )
        body = resp.content.decode()
        self.assertIn("Aluguel", body)
        self.assertNotIn("estorno do vizinho", body)

    def test_diverse_detail_excludes_systemic(self):
        resp = self.client.get(f"/consolidated/detail/{self.cat.id}/2026/2/")
        body = resp.content.decode()
        self.assertIn("estorno do vizinho", body)
        self.assertNotIn("Aluguel", body)
