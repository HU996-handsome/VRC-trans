"""
VRC-Translator 启动脚本 (带实时显示)
双击 run.cmd 或运行: python run.py
"""
import os
import sys
import time
import threading

os.environ.setdefault('NO_PROXY', '*')
os.environ.setdefault('no_proxy', '*')
os.chdir(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.getcwd())

import logging
logging.basicConfig(level=logging.CRITICAL)
logging.getLogger("asyncio").setLevel(logging.CRITICAL)

# Suppress asyncio event loop cleanup errors
import warnings
warnings.filterwarnings("ignore", category=RuntimeError, message="Event loop is closed")

def _suppress_unraisable(args):
    if args.exc_type is RuntimeError:
        return
    sys.__unraisablehook__(args)

sys.unraisablehook = _suppress_unraisable


def main():
    # ── 依赖检查 ──
    missing = []
    for pkg in ["flask", "flask_cors", "numpy", "pyaudio", "dashscope", "pythonosc"]:
        try:
            __import__(pkg)
        except ImportError:
            missing.append(pkg)
    if missing:
        print(f"[!] 缺少依赖: {', '.join(missing)}")
        print(f"    请运行: pip install {' '.join(missing)}")
        input("按回车退出...")
        return

    # ── 初始化 ──
    from src.config.settings import get_settings
    from src.app_state import get_state
    from src.text.dictionary import DictionaryCorrector
    from src.text.processor import TextProcessor
    from src.translators.factory import TranslatorFactory
    from src.ui.app import create_app

    settings = get_settings()
    state = get_state()

    state.dictionary = DictionaryCorrector()
    state.dictionary.load()

    try:
        state.translator = TranslatorFactory.create(settings.translation.primary_backend, settings)
        tr_name = settings.translation.primary_backend
    except Exception as e:
        print(f"[!] 翻译器初始化失败: {e}, 使用 Google 备用")
        settings.translation.primary_backend = "google"
        state.translator = TranslatorFactory.create("google", settings)
        tr_name = "google"

    state.text_processor = TextProcessor(max_length=settings.osc.max_text_length)
    state.is_running = True

    # ── 打印横幅 ──
    print()
    print("=" * 56)
    print("    VRC-Translator v1.0.0")
    print("=" * 56)
    print(f"  翻译后端: {tr_name}")
    print(f"  目标语言: {settings.translation.target_language}")
    print(f"  闭麦控制: {'开启' if settings.osc.mic_control_enabled else '关闭'}")
    print(f"  OSC 端口: 发送={settings.osc.send_port} 监听={settings.osc.listen_port}")
    print()
    print(f"  >>> 浏览器打开: http://127.0.0.1:{settings.ui.web_port} <<<")
    print()
    print("  按 Ctrl+C 停止")
    print("=" * 56)
    print()

    # ── 启动 Web UI ──
    app = create_app(settings, state)

    # Suppress Flask request logs
    import logging as _logging
    _logging.getLogger("werkzeug").setLevel(_logging.WARNING)

    def run_web():
        app.run(host="127.0.0.1", port=settings.ui.web_port, debug=False, use_reloader=False)

    web_thread = threading.Thread(target=run_web, daemon=True)
    web_thread.start()

    # ── Keep alive loop ──
    try:
        while True:
            time.sleep(1)

    except KeyboardInterrupt:
        print("\n正在停止...")
        state.is_running = False
        for name in ["mic_recorder", "desktop_recorder", "asr", "reverse_asr", "osc_sender", "osc_listener"]:
            comp = getattr(state, name, None)
            if comp:
                try:
                    comp.stop()
                except Exception:
                    pass
        print("已停止.")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"\n[严重错误] {e}")
        import traceback
        traceback.print_exc()
        input("\n按回车退出...")
