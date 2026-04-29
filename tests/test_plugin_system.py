"""
Unit tests for plugin system module.
"""

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from aider.plugin_system import (
    BasePlugin,
    Plugin,
    PluginHook,
    PluginManager,
    PluginMetadata,
    PluginStatus,
    get_plugin_manager,
)


class TestPluginMetadata(unittest.TestCase):
    """Test plugin metadata dataclass."""

    def test_plugin_metadata_creation(self):
        """Test creating plugin metadata."""
        metadata = PluginMetadata(
            name="test_plugin",
            version="1.0.0",
            author="Test Author",
            description="Test plugin",
        )
        
        self.assertEqual(metadata.name, "test_plugin")
        self.assertEqual(metadata.version, "1.0.0")


class TestPlugin(unittest.TestCase):
    """Test plugin dataclass."""

    def test_plugin_creation(self):
        """Test creating a plugin."""
        metadata = PluginMetadata(
            name="test_plugin",
            version="1.0.0",
            author="Test Author",
            description="Test plugin",
        )
        plugin = Plugin(metadata=metadata)
        
        self.assertEqual(plugin.metadata.name, "test_plugin")
        self.assertEqual(plugin.status, PluginStatus.UNLOADED)


class TestBasePlugin(unittest.TestCase):
    """Test base plugin class."""

    def test_base_plugin_initialization(self):
        """Test base plugin initialization."""
        config = {"key": "value"}
        plugin = BasePlugin(config)
        
        self.assertEqual(plugin.config, config)


class TestPluginManager(unittest.TestCase):
    """Test plugin manager functionality."""

    def setUp(self):
        """Set up test fixtures."""
        with TemporaryDirectory() as temp_dir:
            self.manager = PluginManager(plugin_dir=Path(temp_dir))
    
    def test_initialization(self):
        """Test plugin manager initialization."""
        self.assertIsNotNone(self.manager.plugin_dir)
        self.assertIsInstance(self.manager._plugins, dict)
    
    def test_get_plugin(self):
        """Test getting a plugin."""
        plugin = self.manager.get_plugin("nonexistent")
        self.assertIsNone(plugin)
    
    def test_list_plugins(self):
        """Test listing plugins."""
        plugins = self.manager.list_plugins()
        self.assertIsInstance(plugins, list)
    
    def test_register_command(self):
        """Test registering a command."""
        def test_command():
            return 42
        
        self.manager.register_command("test", test_command)
        
        retrieved = self.manager.get_command("test")
        self.assertIsNotNone(retrieved)
    
    def test_register_hook(self):
        """Test registering a hook."""
        def test_hook(plugin):
            pass
        
        self.manager.register_hook(PluginHook.ON_LOAD, test_hook)
        
        self.assertIn(test_hook, self.manager._hooks[PluginHook.ON_LOAD])
    
    def test_get_plugin_stats(self):
        """Test getting plugin statistics."""
        stats = self.manager.get_plugin_stats()
        
        self.assertIn("total_plugins", stats)
        self.assertIn("loaded_plugins", stats)
        self.assertIn("registered_commands", stats)


class TestGlobalPluginManager(unittest.TestCase):
    """Test global plugin manager instance."""

    def test_get_plugin_manager(self):
        """Test getting global plugin manager."""
        manager = get_plugin_manager()
        self.assertIsNotNone(manager)
        
        # Should return same instance
        manager2 = get_plugin_manager()
        self.assertIs(manager, manager2)


if __name__ == "__main__":
    unittest.main()
