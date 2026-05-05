"""
VRC-Translator 启动脚本
双击运行或在终端中执行: python start.py
"""
import os
import sys

# Fix proxy issues for API calls
os.environ.setdefault('NO_PROXY', '*')
os.environ.setdefault('no_proxy', '*')

# 切换到脚本所在目录
os.chdir(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.getcwd())

print("=" * 50)
print("  VRC-Translator v1.0.0")
print("=" * 50)
print()

# 检查依赖
missing = []
for pkg in ["flask", "flask_cors", "numpy"]:
    try:
        __import__(pkg)
    except ImportError:
        missing.append(pkg)

if missing:
    print(f"[!] 缺少依赖: {', '.join(missing)}")
    print(f"    请运行: pip install {' '.join(missing)}")
    input("按回车退出...")
    sys.exit(1)

# 加载配置和组件
from src.config.settings import get_settings
from src.app_state import get_state
from src.text.dictionary import DictionaryCorrector
from src.text.processor import TextProcessor
from src.translators.factory import TranslatorFactory
from src.ui.app import create_app

settings = get_settings()
state = get_state()

# 初始化字典
state.dictionary = DictionaryCorrector()
state.dictionary.load()
print(f"[OK] 字典已加载")

# 初始化翻译器
try:
    state.translator = TranslatorFactory.create(
        settings.translation.primary_backend, settings
    )
    print(f"[OK] 翻译器: {settings.translation.primary_backend}")
except Exception as e:
    print(f"[!] 翻译器初始化失败: {e}")
    print("    将使用 Google Translate 作为备用")
    settings.translation.primary_backend = "google"
    state.translator = TranslatorFactory.create("google", settings)

# 初始化文本处理器
state.text_processor = TextProcessor(max_length=settings.osc.max_text_length)
state.is_running = True

# 创建 Flask 应用
app = create_app(settings, state)

port = settings.ui.web_port
print()
print(f"[OK] Web UI 启动中...")
print(f"")
print(f"  >>> 请在浏览器打开: http://127.0.0.1:{port} <<<")
print(f"")
print(f"  如果打不开，请尝试: http://localhost:{port}")
print(f"  按 Ctrl+C 停止服务")
print()

try:
    app.run(host="127.0.0.1", port=port, debug=False, use_reloader=False)
except KeyboardInterrupt:
    print("\n正在停止...")
    state.is_running = False
except Exception as e:
    print(f"\n[!] 启动失败: {e}")
    print("    可能是端口被占用，请关闭其他程序后重试")
    input("按回车退出...")
