# VRC-Translator

VRChat 实时语音翻译工具，支持正向翻译（你说的话翻译给外国人）和反向翻译（外国人说的话翻译给你看）。

## 功能

- **正向翻译**：麦克风采集你的语音 → ASR识别 → 翻译 → 发送到VRChat聊天框
- **反向翻译**：桌面音频回环捕获游戏内声音 → ASR识别 → 翻译 → 本地显示
- **实时翻译**：边说边翻译，不用等话说完（每5个字就开始翻译）
- **自动降级**：DashScope配额用完时自动切换到Google翻译，5分钟后重试
- **语音活动检测**：Silero VAD / Energy VAD 自动检测语音
- **Web UI**：浏览器控制面板，设置、状态监控
- **VRChat检测**：自动检测VRChat是否运行，未运行时禁用启动按钮

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

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 配置 API Key

复制 `config/.env.example` 为 `config/.env`，填入你的 DashScope API Key：

```
DASHSCOPE_API_KEY=sk-xxxxxxxx
```

> API Key 获取方式：登录 [阿里云百炼平台](https://bailian.console.aliyun.com/) → API Key 管理

### 3. 启动

```bash
python main.py
```

或双击 `run.bat`

### 4. 使用

1. 浏览器自动打开控制面板（默认 http://localhost:5001）
2. 启动 VRChat（必须先运行，否则启动按钮禁用）
3. 点击 **"启动翻译"**
4. 对着麦克风说话，翻译会自动发送到 VRChat 聊天框

## 详细使用教程

### 正向翻译（你说的话翻译给外国人听）

1. 启动翻译后，对着麦克风说中文
2. ASR 实时识别你说的话（边说边识别，不用等说完）
3. 识别结果自动翻译成英文（默认），发送到 VRChat 聊天框
4. 翻译结果会显示在网页控制面板上

### 反向翻译（外国人说的话翻译给你看）

1. 在设置中开启"反向翻译"
2. 程序会自动捕获桌面音频（VRChat 游戏内声音）
3. 识别并翻译其他玩家说的话，显示在控制面板上

### 设置说明

在网页控制面板的设置中可以调整：

- **目标语言**：翻译成什么语言（默认英文）
- **ASR语言**：你说什么语言（默认中文）
- **反向翻译**：是否开启桌面音频翻译
- **OSC设置**：VRChat 聊天框发送参数

## 系统要求

- Windows 10/11
- Python 3.10+
- VRChat（OSC功能需要）
- 麦克风

## 目录结构

```
VRC-trans/
├── main.py              # 入口
├── run.bat              # Windows 启动脚本
├── config/
│   ├── settings.json    # 配置文件（自动生成）
│   └── .env             # API Key
├── src/
│   ├── ui/              # Web UI
│   ├── audio/           # 音频采集
│   ├── asr/             # 语音识别
│   ├── translators/     # 翻译引擎
│   └── osc/             # VRChat OSC 通信
└── hot_words/           # 热词文件（提高识别准确率）
```

## 热词

在 `hot_words/` 目录下创建 `.txt` 文件，每行一个热词，可以提高 ASR 识别准确率。例如：

```
VRChat
Avatar
Quest
PC
```

## 常见问题

**Q: 翻译没反应？**
A: 检查 VRChat 是否在运行，API Key 是否正确配置。

**Q: 翻译很慢？**
A: DashScope 配额用完会自动降级到 Google 翻译。充值后5分钟自动恢复。

**Q: 识别不准？**
A: 在 `hot_words/` 目录添加热词，或切换 ASR 引擎。
