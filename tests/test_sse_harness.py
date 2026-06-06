from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from test_sse import ServiceController


class ServiceControllerTests(unittest.TestCase):
    def test_cleanup_logs_retries_transient_permission_errors(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            controller = ServiceController(
                app_module="main:app",
                host="127.0.0.1",
                port=8010,
                env={},
                cwd=Path(tmp_dir),
            )
            controller.stdout_path.write_text("stdout", encoding="utf-8")
            controller.stderr_path.write_text("stderr", encoding="utf-8")

            original_unlink = Path.unlink
            call_count = {"stdout": 0}

            def flaky_unlink(path: Path, *args: object, **kwargs: object) -> None:
                if path == controller.stdout_path and call_count["stdout"] == 0:
                    call_count["stdout"] += 1
                    raise PermissionError("still open")
                original_unlink(path, *args, **kwargs)

            with (
                patch.object(Path, "unlink", autospec=True, side_effect=flaky_unlink),
                patch("test_sse.time.sleep"),
            ):
                controller.cleanup_logs()

            self.assertEqual(call_count["stdout"], 1)
            self.assertFalse(controller.stdout_path.exists())
            self.assertFalse(controller.stderr_path.exists())


if __name__ == "__main__":
    unittest.main()
