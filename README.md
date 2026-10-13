# VoiceHold

> **按住鼠标，说话；文字就出现在你正在输入的地方。**
> *Hold a mouse button, speak naturally, and dictate directly into the focused text field.*

[![Platform](https://img.shields.io/badge/platform-Windows%2010%2F11-0078D4?logo=windows)](#requirements)
[![Python](https://img.shields.io/badge/python-3.10%2B-3776AB?logo=python&logoColor=white)](#quick-start)
[![License](https://img.shields.io/badge/license-MIT-22c55e)](LICENSE)

VoiceHold 是一款本地优先的 Windows 全局语音输入工具。将光标放在任意可编辑文本框中，按住鼠标键说话，中文转写会实时插入到光标位置；松开鼠标后即可像普通文字一样继续编辑。

没有悬浮转写窗、没有确认按钮，也不需要切换到特定软件。

## Why VoiceHold?

- **即时输入**：边说边显示，而非整句话结束后才出现。
- **全局可用**：网页、聊天软件、笔记和编辑器等常规输入框均可使用。
- **本地识别**：语音由本机的流式中文识别模型处理，不上传录音。
- **少闪动更新**：仅替换仍在变化的识别词尾，稳定文字不会反复跳动。
- **中文友好**：默认输出简体中文；也支持保留原始繁体结果。

## Demo

```text
1. 点击一个文本输入框
2. 按住右键并开始说话
3. 文字实时出现 → 松开右键 → 像普通文字一样修改或发送
```

> 正在寻找一段清晰的 GIF 演示。欢迎提交你在不同软件中的使用录屏。

## Requirements

- Windows 10 或 Windows 11
- Python 3.10+
- 一个可用麦克风
- 首次下载模型需要网络；完成下载后，日常识别可离线使用

## Quick start

在 PowerShell 中运行：

```powershell
git clone https://github.com/haha2006-david/VoiceHold.git
cd VoiceHold

py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt

# 创建个人配置并下载默认实时模型（约 160 MB）
.\.venv\Scripts\python.exe voice_type.py --write-default-config
.\.venv\Scripts\python.exe voice_type.py --download-streaming-model

# 启动
.\.venv\Scripts\python.exe voice_type.py
```

看到“已就绪”后，先点击需要输入的文本框，再**按住右键说话**。短按右键仍会正常点击；长按默认 350 ms 后才开始录音。按 `Ctrl+C` 可退出。

如果虚拟环境缺少 pip，可先运行：

```powershell
py -m pip --python .\.venv\Scripts\python.exe install --upgrade pip
```

## Start with Windows

完成上面的安装、配置和模型下载后，在项目目录运行以下命令，即可让 VoiceHold 在当前用户登录 Windows 后静默启动。无需管理员权限。

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\install-autostart.ps1
```

后台启动需要等待模型加载，目前没有托盘图标。程序会定期恢复鼠标监听，并避免新版重复启动。启动状态和错误保存在本机 `logs\voicehold.log`，正常运行日志只记录状态和字数，不记录转写正文。

项目目录移动后，请重新运行安装命令更新路径。取消自启动可运行：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\install-autostart.ps1 -Remove
```

## Configuration

首次启动时创建的 `voice_config.json` 仅存放在你的本机，不会被 Git 跟踪。常用配置如下：

```json
{
  "trigger_button": "right",
  "hold_to_record_ms": 350,
  "output_chinese": "simplified",
  "streaming_model_dir": "models/sherpa-onnx-streaming-zipformer-zh-int8-2025-06-30",
  "recognizer_threads": 2,
  "render_interval_ms": 180
}
```

| 选项 | 作用 | 建议 |
| --- | --- | --- |
| `trigger_button` | 触发键，`right` 或 `left` | 默认 `right`；左右键均会影响原有长按操作 |
| `hold_to_record_ms` | 长按多久后开始录音 | 250–500 ms |
| `output_chinese` | 输出文字形式 | `simplified` 或 `original` |
| `recognizer_threads` | 识别线程数 | 低配电脑用 1；CPU 空闲较多可用 3–4 |
| `render_interval_ms` | 屏幕更新间隔 | 120–220 ms 通常较自然 |

### Accuracy mode

默认模型约 160 MB，启动与下载更轻量。更重视中文准确率时，可把配置中的 `streaming_model_dir` 改为：

```text
models/sherpa-onnx-streaming-zipformer-zh-xlarge-int8-2025-06-30
```

随后再次运行 `--download-streaming-model` 下载 xlarge 模型（约 730 MB）。模型越大，对磁盘、内存和 CPU 的要求也越高。

## Compatibility and limitations

VoiceHold 通过 Windows 的标准输入事件向当前焦点控件写入文字。常规桌面应用与浏览器输入框通常适用，但下列场景可能受系统或应用限制：

- 密码框、安全桌面和远程桌面会话
- 以管理员身份运行的应用（VoiceHold 与目标应用权限不同）
- 明确禁止模拟输入或粘贴的应用
- 游戏、全屏独占程序和某些自绘控件

请勿把它用于输入密码、支付信息或其他敏感内容。VoiceHold 不会主动上传音频，但你仍应了解所使用应用本身的数据政策。

## Build an EXE

确认脚本版运行正常后，可在本机打包：

```powershell
.\.venv\Scripts\python.exe -m pip install pyinstaller
.\.venv\Scripts\pyinstaller.exe --onefile --name VoiceHold voice_type.py
```

生成文件位于 `dist\VoiceHold.exe`。将个人 `voice_config.json` 放在 EXE 同级目录即可使用；模型目录也需要保留在同级的 `models` 文件夹中。

## Roadmap

- [ ] 系统托盘图标与状态提示
- [ ] 鼠标侧键、快捷键等更多触发方式
- [ ] 可下载的签名 EXE 发布包
- [ ] 更多应用的兼容性测试与回归测试

## Contributing

欢迎提交 Issue、兼容性反馈和 Pull Request。报告问题时，请写明 Windows 版本、目标应用、触发方式和复现步骤；请勿附上录音、密码或其他敏感输入内容。

## Acknowledgements

VoiceHold 使用 [sherpa-onnx](https://github.com/k2-fsa/sherpa-onnx) 提供的本地流式语音识别能力，以及其发布的中文模型。

## License

[MIT License](LICENSE) © VoiceHold contributors.
