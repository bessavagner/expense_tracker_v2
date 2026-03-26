from django.contrib.auth import get_user_model
from django.test import TestCase


class AdminSiteTest(TestCase):
    def setUp(self):
        User = get_user_model()
        self.admin_user = User.objects.create_superuser(
            username="admin",
            email="admin@example.com",
            password="adminpass123",
        )
        self.client.force_login(self.admin_user)

    def test_admin_users_list(self):
        response = self.client.get("/admin/core/customuser/")
        self.assertEqual(response.status_code, 200)

    def test_admin_user_detail(self):
        response = self.client.get(f"/admin/core/customuser/{self.admin_user.pk}/change/")
        self.assertEqual(response.status_code, 200)
