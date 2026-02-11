import sys
from pathlib import Path

# 프로젝트 루트를 sys.path에 추가하여 src 패키지를 찾을 수 있게 함
BASE_DIR = Path(__file__).parent
if str(BASE_DIR) not in sys.path:
    sys.path.append(str(BASE_DIR))

from src.gui.app import App

if __name__ == "__main__":
    app = App()
    app.mainloop()
