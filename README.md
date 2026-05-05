# VRC-Translator

VRChat 实时语音翻译工具，结合 Yakutan（正向翻译）和 MioVRC_Translator（反向翻译）的功能。

## 功能

- **正向翻译**：麦克风采集你的语音 → ASR识别 → 翻译 → 发送到VRChat聊天框
- **反向翻译**：桌面音频回环捕获游戏内声音 → ASR识别 → 翻译 → 本地显示
- **自动降级**：DashScope配额用完时自动切换到Google翻译，5分钟后重试
- **语音活动检测**：Silero VAD / Energy VAD 自动检测语音
- **Web UI**：浏览器控制面板，设置、状态监控

## 翻译后端

| 后端 | 说明 |
|------|------|
| DashScope Qwen-MT | 推荐，需要API Key |
| DeepL | 可选，需要API Key |
| OpenRouter | 可选，LLM翻译 |
| Google Translate | 免费，无需Key |
| CTranslate2 | 本地离线 |

## ASR 引擎

| 引擎 | 说明 |
|------|------|
| DashScope paraformer-realtime-v2 | 云端流式，推荐 |
| SenseVoice | 本地离线 |
| Faster Whisper | 本地离线 |

## 安装

```bash
pip install -r requirements.txt
```

## 配置

1. 复制 `config/.env.example` 为 `config/.env`
2. 填入你的 API Key：
   ```
   DASHSCOPE_API_KEY=sk-xxxxxxxx
   ```
3. 运行 `run.bat` 启动

## 使用

1. 双击 `run.bat`
2. 浏览器自动打开控制面板
3. 点击"启动翻译"
4. 打开VRChat开始说话

## 系统要求

- Windows 10/11
- Python 3.10+
- VRChat（OSC功能需要）
