from django.test import SimpleTestCase
from django.core.exceptions import ValidationError
from foods.fields import EAN13Field

class EAN13FieldTest(SimpleTestCase):
    def setUp(self):
        self.field = EAN13Field()

    def test_valid_ean13(self):
        valid = "3560071429508"
        self.assertEqual(self.field.clean(valid, None), valid)

    def test_invalid_checksum(self):
        with self.assertRaises(ValidationError):
            self.field.clean("3560071429501", None)

    def test_too_short(self):
        with self.assertRaises(ValidationError):
            self.field.clean("356007142950", None)

    def test_non_numeric(self):
        with self.assertRaises(ValidationError):
            self.field.clean("abcdefghijklm", None)
