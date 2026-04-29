"""
Unit tests for internationalization module.
"""

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from aider.i18n import (
    I18NManager,
    get_i18n_manager,
    set_language,
    get_language,
    translate,
    _,
)


class TestI18NManager(unittest.TestCase):
    """Test the i18n manager."""

    def setUp(self):
        """Set up test fixtures."""
        with TemporaryDirectory() as temp_dir:
            self.locale_dir = Path(temp_dir)
            self.manager = I18NManager(locale_dir=self.locale_dir)
    
    def test_initialization(self):
        """Test i18n manager initialization."""
        self.assertIsNotNone(self.manager.domain)
        self.assertIsNotNone(self.manager.locale_dir)
        self.assertEqual(self.manager.current_language, "en")
    
    def test_set_language(self):
        """Test setting language."""
        result = self.manager.set_language("en")
        self.assertTrue(result)
        self.assertEqual(self.manager.current_language, "en")
    
    def test_set_invalid_language(self):
        """Test setting invalid language."""
        result = self.manager.set_language("invalid")
        self.assertFalse(result)
    
    def test_get_language(self):
        """Test getting current language."""
        language = self.manager.get_language()
        self.assertEqual(language, "en")
    
    def test_get_available_languages(self):
        """Test getting available languages."""
        languages = self.manager.get_available_languages()
        
        self.assertIn("en", languages)
        self.assertIn("zh", languages)
    
    def test_translate(self):
        """Test translation."""
        message = self.manager.translate("Test message")
        self.assertIsNotNone(message)
    
    def test_create_translation_template(self):
        """Test creating translation template."""
        template_path = self.manager.create_translation_template()
        
        self.assertTrue(template_path.exists())
        content = template_path.read_text()
        self.assertIn("# Translation Template", content)
    
    def test_create_translation_file(self):
        """Test creating translation file."""
        translation_path = self.manager.create_translation_file("zh")
        
        self.assertTrue(translation_path.exists())


class TestGlobalI18NManager(unittest.TestCase):
    """Test global i18n manager instance."""

    def test_get_i18n_manager(self):
        """Test getting global i18n manager."""
        manager = get_i18n_manager()
        self.assertIsNotNone(manager)
        
        # Should return same instance
        manager2 = get_i18n_manager()
        self.assertIs(manager, manager2)


class TestConvenienceFunctions(unittest.TestCase):
    """Test convenience functions."""

    def test_set_language(self):
        """Test set_language convenience function."""
        result = set_language("en")
        self.assertTrue(result)
    
    def test_get_language(self):
        """Test get_language convenience function."""
        language = get_language()
        self.assertIsNotNone(language)
    
    def test_translate(self):
        """Test translate convenience function."""
        message = translate("Test")
        self.assertIsNotNone(message)
    
    def test_shorthand_translate(self):
        """Test shorthand translate function."""
        message = _("Test")
        self.assertIsNotNone(message)


if __name__ == "__main__":
    unittest.main()
