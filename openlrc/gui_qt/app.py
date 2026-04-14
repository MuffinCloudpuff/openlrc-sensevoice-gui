from __future__ import annotations

import sys


def main() -> int:
    try:
        from PySide6.QtWidgets import QApplication
    except ImportError as exc:  # pragma: no cover
        raise SystemExit(
            "PySide6 未安装。请先在当前环境中执行：pip install PySide6，或安装 openlrc[desktop]。"
        ) from exc

    from .main_window_v2 import MainWindowV2

    app = QApplication(sys.argv)
    window = MainWindowV2()
    window.show()
    return app.exec()


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
