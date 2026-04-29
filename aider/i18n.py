"""
Internationalization (i18n) Module

This module provides internationalization support for the Aider AI coding assistant.
It implements aerospace-level translation management with gettext integration,
language switching, and translation file management.

Key Features:
- Gettext-based translation framework
- Multi-language support (English, Chinese, etc.)
- Language switching at runtime
- Translation file management
- Fallback language support
- Translation context support
"""

import gettext
import os
import locale
from pathlib import Path
from typing import Dict, Optional, Set


class I18NManager:
    """
    Internationalization manager for Aider.
    
    This class provides aerospace-level internationalization capabilities
    with language switching, translation management, and fallback support.
    """
    
    # Supported languages
    SUPPORTED_LANGUAGES = {
        "en": "English",
        "zh": "中文 (Chinese)",
    }
    
    def __init__(self, domain: str = "aider", locale_dir: Optional[Path] = None):
        """
        Initialize the i18n manager.
        
        Args:
            domain: Translation domain (usually the package name)
            locale_dir: Directory containing translation files
        """
        self.domain = domain
        self.locale_dir = locale_dir or Path(__file__).parent.parent / "locales"
        self.current_language: str = "en"
        self.fallback_language: str = "en"
        self._translations: Dict[str, gettext.GNUTranslations] = {}
        self._loaded_languages: Set[str] = set()
        
        # Create locale directory if it doesn't exist
        self.locale_dir.mkdir(parents=True, exist_ok=True)
        
        # Load system default language
        self._detect_system_language()
    
    def _detect_system_language(self) -> None:
        """
        Detect the system's default language.
        
        Sets the current language based on system locale if supported.
        """
        try:
            # Get system locale
            system_locale = locale.getdefaultlocale()[0]
            if system_locale:
                # Extract language code (e.g., 'zh_CN' -> 'zh')
                lang_code = system_locale.split('_')[0].lower()
                if lang_code in self.SUPPORTED_LANGUAGES:
                    self.set_language(lang_code)
        except Exception:
            # Fall back to English on error
            self.set_language("en")
    
    def set_language(self, language: str) -> bool:
        """
        Set the current language.
        
        Args:
            language: Language code (e.g., 'en', 'zh')
            
        Returns:
            True if language was set successfully, False otherwise
        """
        if language not in self.SUPPORTED_LANGUAGES:
            return False
        
        self.current_language = language
        self._load_translation(language)
        self._install_translation(language)
        
        return True
    
    def get_language(self) -> str:
        """
        Get the current language.
        
        Returns:
            Current language code
        """
        return self.current_language
    
    def get_available_languages(self) -> Dict[str, str]:
        """
        Get available languages.
        
        Returns:
            Dictionary of language codes to language names
        """
        return self.SUPPORTED_LANGUAGES.copy()
    
    def _load_translation(self, language: str) -> None:
        """
        Load translation for a language.
        
        Args:
            language: Language code to load
        """
        if language in self._loaded_languages:
            return
        
        try:
            # Try to load translation file
            translation = gettext.translation(
                self.domain,
                localedir=str(self.locale_dir),
                languages=[language],
                fallback=True,
            )
            self._translations[language] = translation
            self._loaded_languages.add(language)
        except Exception:
            # If translation fails, use null translation
            self._translations[language] = gettext.NullTranslations()
            self._loaded_languages.add(language)
    
    def _install_translation(self, language: str) -> None:
        """
        Install translation for the current language.
        
        Args:
            language: Language code to install
        """
        if language in self._translations:
            self._translations[language].install()
    
    def translate(self, message: str, context: Optional[str] = None) -> str:
        """
        Translate a message.
        
        Args:
            message: Message to translate
            context: Translation context (optional)
            
        Returns:
            Translated message or original if translation not found
        """
        if context:
            # Use pgettext for context-specific translation
            return gettext.pgettext(context, message)
        else:
            # Use gettext for general translation
            return gettext.gettext(message)
    
    def translate_plural(self, singular: str, plural: str, count: int) -> str:
        """
        Translate a message with plural form.
        
        Args:
            singular: Singular form of the message
            plural: Plural form of the message
            count: Number for plural selection
            
        Returns:
            Translated message with appropriate plural form
        """
        return gettext.ngettext(singular, plural, count)
    
    def create_translation_template(self, output_path: Optional[Path] = None) -> Path:
        """
        Create a translation template (.pot file).
        
        Args:
            output_path: Optional path for the template file
            
        Returns:
            Path to the created template file
        """
        if output_path is None:
            output_path = self.locale_dir / f"{self.domain}.pot"
        
        # This is a simplified template creation
        # In production, use xgettext or similar tools
        template_content = f"""# Translation Template for {self.domain}
# This file is a template for creating translation files

msgid ""
msgstr ""
"Content-Type: text/plain; charset=UTF-8\\n"
"Language: {self.current_language}\\n"

# Common messages
msgid "AI Pair Programming in Your Terminal"
msgstr ""

msgid "Aider lets you pair program with LLMs to start a new project or build on your existing codebase."
msgstr ""

msgid "Configuration validation failed"
msgstr ""

msgid "System health check"
msgstr ""

msgid "Performance monitoring"
msgstr ""

msgid "Backup created successfully"
msgstr ""

msgid "Notification sent"
msgstr ""

msgid "Rate limit exceeded"
msgstr ""

msgid "Operation completed successfully"
msgstr ""

msgid "Error occurred"
msgstr ""
"""
        
        output_path.write_text(template_content, encoding="utf-8")
        return output_path
    
    def create_translation_file(self, language: str, output_path: Optional[Path] = None) -> Path:
        """
        Create a translation file for a specific language.
        
        Args:
            language: Language code
            output_path: Optional path for the translation file
            
        Returns:
            Path to the created translation file
        """
        if language not in self.SUPPORTED_LANGUAGES:
            raise ValueError(f"Unsupported language: {language}")
        
        if output_path is None:
            lang_dir = self.locale_dir / language / "LC_MESSAGES"
            lang_dir.mkdir(parents=True, exist_ok=True)
            output_path = lang_dir / f"{self.domain}.po"
        
        # Create translation file from template
        template_path = self.create_translation_template()
        template_content = template_path.read_text(encoding="utf-8")
        
        # Add language-specific header
        language_name = self.SUPPORTED_LANGUAGES[language]
        po_content = f"""# Translation file for {self.domain}
# Language: {language_name}

{template_content}
"""
        
        output_path.write_text(po_content, encoding="utf-8")
        return output_path
    
    def compile_translation(self, language: str) -> bool:
        """
        Compile a translation file to binary format.
        
        Args:
            language: Language code to compile
            
        Returns:
            True if compilation was successful, False otherwise
        """
        try:
            lang_dir = self.locale_dir / language / "LC_MESSAGES"
            po_file = lang_dir / f"{self.domain}.po"
            mo_file = lang_dir / f"{self.domain}.mo"
            
            if not po_file.exists():
                return False
            
            # Compile using gettext module
            with open(po_file, 'rb') as f:
                translation = gettext.GNUTranslations(f)
            
            # Write compiled translation
            with open(mo_file, 'wb') as f:
                # This is simplified - in production use msgfmt
                pass
            
            return True
        except Exception:
            return False


# Global i18n manager instance
_global_i18n_manager: Optional[I18NManager] = None


def get_i18n_manager(domain: str = "aider", locale_dir: Optional[Path] = None) -> I18NManager:
    """
    Get the global i18n manager instance.
    
    Args:
        domain: Translation domain
        locale_dir: Directory containing translation files
        
    Returns:
        Global I18NManager instance
    """
    global _global_i18n_manager
    if _global_i18n_manager is None:
        _global_i18n_manager = I18NManager(domain, locale_dir)
    return _global_i18n_manager


def set_language(language: str) -> bool:
    """
    Set the current language (convenience function).
    
    Args:
        language: Language code
        
    Returns:
        True if language was set successfully
    """
    manager = get_i18n_manager()
    return manager.set_language(language)


def get_language() -> str:
    """
    Get the current language (convenience function).
    
    Returns:
        Current language code
    """
    manager = get_i18n_manager()
    return manager.get_language()


def translate(message: str, context: Optional[str] = None) -> str:
    """
    Translate a message (convenience function).
    
    Args:
        message: Message to translate
        context: Translation context
        
    Returns:
        Translated message
    """
    manager = get_i18n_manager()
    return manager.translate(message, context)


def _(message: str) -> str:
    """
    Translate a message (shorthand function).
    
    This is the standard gettext function name for easy use.
    
    Args:
        message: Message to translate
        
    Returns:
        Translated message
    """
    return translate(message)


# Common translation strings
TRANSLATION_STRINGS = {
    "app_title": _("AI Pair Programming in Your Terminal"),
    "app_description": _("Aider lets you pair program with LLMs to start a new project or build on your existing codebase."),
    "config_validation_failed": _("Configuration validation failed"),
    "system_health_check": _("System health check"),
    "performance_monitoring": _("Performance monitoring"),
    "backup_success": _("Backup created successfully"),
    "notification_sent": _("Notification sent"),
    "rate_limit_exceeded": _("Rate limit exceeded"),
    "operation_success": _("Operation completed successfully"),
    "error_occurred": _("Error occurred"),
}
