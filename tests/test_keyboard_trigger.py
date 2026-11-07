import unittest
from unittest.mock import patch

from cardtable.triggers.keyboard_trigger import KeyTrigger


class KeyTriggerTest(unittest.TestCase):
    def test_default_requires_active_window(self):
        trigger = KeyTrigger('<ctrl>+k')
        with patch('cardtable.widgets._runtime.CardRuntime.instance') as instance:
            instance.return_value.is_active.return_value = False
            trigger._on_activate()
            self.assertIsNone(trigger._take_message())
            instance.return_value.is_active.return_value = True
            trigger._on_activate()
            self.assertEqual(trigger._take_message().data, {'hotkey': '<ctrl>+k'})

    def test_global_trigger_works_without_active_window(self):
        trigger = KeyTrigger('<ctrl>+k', global_=True)
        with patch('cardtable.widgets._runtime.CardRuntime.instance') as instance:
            trigger._on_activate()
            instance.assert_not_called()
        self.assertEqual(trigger._take_message().data, {'hotkey': '<ctrl>+k'})

    def test_global_must_be_bool(self):
        with self.assertRaises(TypeError):
            KeyTrigger('<ctrl>+k', global_=1)
