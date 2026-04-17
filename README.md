# Vertical Video Converter

横動画をドラッグ&ドロップするだけで、9:16の縦動画に変換するシンプルなWebアプリです。

## 必要要件

- Python 3.10+
- FFmpeg

### FFmpeg インストール例 (macOS)

```bash
brew install ffmpeg
```

## 起動方法

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python app.py
```

起動後に `http://localhost:8000` を開くと利用できます。

## 使い方

1. 画面中央に横動画をドラッグ&ドロップ
2. 自動で縦動画へ変換
3. 「縦動画をダウンロード」から保存

## 仕様

- 入力対応: `mp4`, `mov`, `mkv`, `avi`, `webm`
- 出力: `mp4` (H.264 / AAC)
- 変換内容: `1080x1920` へ拡大 + 中央クロップ
- 変換後動画の保存先: `yokotate/`
