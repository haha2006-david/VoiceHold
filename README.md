# VoiceHold — Windows 全局按住说话输入

> Hold a mouse button, speak naturally, and see Chinese text appear directly in the focused input box.

**VoiceHold** 是一个本地优先的 Windows 语音输入小工具：在任何可编辑输入框中按住鼠标键说话，识别文字会实时写入光标所在的位置。松开即结束，不弹窗、不需要确认，之后就像普通文字一样修改。

> [!NOTE]
> 项目仍处于早期阶段，欢迎用 Issue 反馈「应用名称、系统版本、触发方式、实际效果」；这会直接帮助改善兼容性与准确率。

默认使用本地流式中文识别模型（sherpa-onnx Zipformer），音频只在本机处理。它会在大约 100–300 ms 的音频块到达时持续解码，而不是等整句话结束后才转写。

## 特性

- 全局触发：不必切换到特定软件，先选中输入框即可使用。
- 直接写入：没有悬浮转写窗，也没有额外确认步骤。
- 实时识别：边说边生成，只替换仍在变化的词尾，减少文字闪动。
- 本地处理：麦克风音频不上传到云端。
- 简体中文输出：内置繁转简；也可在配置中保留原始繁体结果。

## 当前交互

- 短按配置的按钮：照常发送一次点击，不影响普通点击。
- 长按 350 ms：开始录音，当前输入框会持续更新识别文字。
- 松开鼠标：最后结果直接保留在当前输入框，不弹窗、不要求确认。
- 默认触发键为右键。使用右键意味着该按键不能用于拖拽；使用左键也会妨碍拖拽和长按选择，所以建议只选自己不常用于拖拽的按键。
- 密码框、远程桌面、以管理员身份运行的程序和禁止粘贴的应用，可能不会接收文字。这是 Windows 的权限/控件限制。

## 安装与启动

需要 Windows 10/11、Python 3.10+，以及可用麦克风。

```powershell
cd "C:\Users\yangj\Documents\ChatGPT\有意思的小项目"
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe voice_type.py --write-default-config
.\.venv\Scripts\python.exe voice_type.py --download-streaming-model
.\.venv\Scripts\python.exe voice_type.py
```

如果第二步提示 `.venv` 中没有 `pip`（某些 Python 版本在中文路径下会出现），先补一次：

```powershell
py -m pip --python .\.venv\Scripts\python.exe install --upgrade pip
```

然后重新执行安装依赖的那一行即可。

标准模型下载约 160 MB，只需执行一次。看到“已就绪”后，先点击任意输入框，再按住右键说话；文字会直接在该输入框中逐步生成。

要结束程序，回到它所在的终端按 `Ctrl+C`，或直接关闭终端窗口。

## 调整配置

首次执行 `--write-default-config` 会建立被 Git 忽略的 `voice_config.json`：

```json
{
  "trigger_button": "right",
  "hold_to_record_ms": 350,
  "language": "zh",
  "output_chinese": "simplified",
  "streaming_model_dir": "models/sherpa-onnx-streaming-zipformer-zh-int8-2025-06-30",
  "recognizer_threads": 2
}
```

- 将 `trigger_button` 改为 `left`，可改用左键长按。
- `hold_to_record_ms` 建议 250–500，避免普通点击误触发。
- 默认 `output_chinese: "simplified"`，会在粘贴前将繁体转换为简体；如要保留模型原始输出，改为 `"original"`。
- `recognizer_threads` 默认是 2。电脑较慢时设为 1；若 CPU 空闲较多可设为 3–4，以降低实时输入延迟。
- 若更重视准确率，可将 `streaming_model_dir` 改为 `models/sherpa-onnx-streaming-zipformer-zh-xlarge-int8-2025-06-30`，再运行下载命令。该模型约 730 MB，适合网络稳定、磁盘空间充足的电脑。

## 打包成 EXE（可选）

确认能运行后，可执行：

```powershell
.\.venv\Scripts\python.exe -m pip install pyinstaller
.\.venv\Scripts\pyinstaller.exe --onefile --name VoiceType voice_type.py
```

生成文件在 `dist\VoiceType.exe`。`voice_config.json` 放在 EXE 同级目录后，程序会自动读取它；也可以用 `--config` 指向其他位置。

## 后续最值得做的两项

1. 加一个系统托盘图标，显示“聆听/转写/失败”，不必保留终端窗口。
2. 改用鼠标侧键或可自定义组合键。它比左右键更自然，也不会抢占常用的菜单、拖拽和选中文本操作。

## 参与贡献

欢迎提交 Bug 报告、兼容性测试结果、改进建议和 Pull Request。提交问题时，请不要上传录音、密码或其他敏感输入内容。

## 许可证

本项目使用 [MIT License](LICENSE)。语音识别模型及其许可证请以各自上游发布说明为准。
