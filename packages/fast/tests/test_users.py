import tempfile
import unittest
from pathlib import Path

from simplicio_fast.users.repository import JsonUserRepository
from simplicio_fast.users.service import (
    EmailConflictError,
    UserNotFoundError,
    UserService,
)


class UserServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.service = UserService(
            JsonUserRepository(Path(self.temporary.name) / "users.json")
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_complete_crud_and_later_status_change(self) -> None:
        created = self.service.create("Wesley", "WESLEY@example.com")
        self.assertEqual("wesley@example.com", created.email)
        self.assertEqual(created, self.service.get(created.id))

        updated = self.service.update(created.id, name="Wesley Simplicio", active=False)
        self.assertEqual("Wesley Simplicio", updated.name)
        self.assertFalse(updated.active)

        self.service.delete(created.id)
        self.assertEqual([], self.service.list())
        with self.assertRaises(UserNotFoundError):
            self.service.get(created.id)

    def test_rejects_duplicate_email(self) -> None:
        self.service.create("One", "same@example.com")
        with self.assertRaises(EmailConflictError):
            self.service.create("Two", "same@example.com")


if __name__ == "__main__":
    unittest.main()
