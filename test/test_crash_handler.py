
import unittest
from unittest.mock import MagicMock, patch
import sys
import io
import os

# Ensure src is in path
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

from src.app_logger import install_crash_handler

class TestCrashHandler(unittest.TestCase):
    def setUp(self):
        # Save original hook to restore later
        self.original_hook = sys.excepthook
        
    def tearDown(self):
        # Restore original hook
        sys.excepthook = self.original_hook

    def test_hook_installation(self):
        """Test that install_crash_handler replaces sys.excepthook."""
        install_crash_handler()
        self.assertNotEqual(sys.excepthook, sys.__excepthook__)
        self.assertNotEqual(sys.excepthook, self.original_hook)

    @patch('src.app_logger.QMessageBox')
    @patch('sys.exit')
    def test_crash_handling_flow(self, mock_exit, mock_msgbox):
        """Test the logic inside the exception hook."""
        install_crash_handler()
        crash_hook = sys.excepthook
        
        # Setup mock for QMessageBox instance
        mock_box_instance = MagicMock()
        mock_msgbox.return_value = mock_box_instance
        
        # Capture stderr
        captured_stderr = io.StringIO()
        with patch('sys.stderr', captured_stderr):
            # Trigger 'fake' crash
            # We explicitly call the hook function instead of raising to avoid crashing the test runner
            # excepthook signature: (type, value, traceback)
            try:
                raise ValueError("Test Critical Error")
            except ValueError:
                exc_type, exc_value, exc_tb = sys.exc_info()
                crash_hook(exc_type, exc_value, exc_tb)
        
        # Assertion 1: Check GUI Dialog usage
        mock_msgbox.assert_called() # Constructor called
        mock_box_instance.setText.assert_called()
        # Verify the error message was passed to informative text or detailed text
        args, _ = mock_box_instance.setInformativeText.call_args
        self.assertIn("Test Critical Error", args[0])
        
        mock_box_instance.exec.assert_called_once() # Dialog shown
        
        # Assertion 2: Check System Exit
        mock_exit.assert_called_with(1)
        
        # Assertion 3: Check Logging to stderr
        output = captured_stderr.getvalue()
        self.assertIn("CRITICAL ERROR CAUGHT BY HANDLER", output)
        self.assertIn("ValueError: Test Critical Error", output)

if __name__ == '__main__':
    unittest.main()
