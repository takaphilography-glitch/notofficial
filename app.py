import os
import json
import subprocess
import uuid
from pathlib import Path

from flask import Flask, jsonify, render_template, request, send_file
from werkzeug.utils import secure_filename


BASE_DIR = Path(__file__).resolve().parent
UPLOAD_DIR = BASE_DIR / "uploads"
OUTPUT_DIR = BASE_DIR / "yokotate"
SUBTITLE_DIR = BASE_DIR / "subtitles"
ALLOWED_EXTENSIONS = {".mp4", ".mov", ".mkv", ".avi", ".webm"}

UPLOAD_DIR.mkdir(exist_ok=True)
OUTPUT_DIR.mkdir(exist_ok=True)
SUBTITLE_DIR.mkdir(exist_ok=True)

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 50 * 1024 * 1024  # 50MB


def is_allowed_file(filename: str) -> bool:
    return Path(filename).suffix.lower() in ALLOWED_EXTENSIONS


def format_srt_timestamp(seconds: float) -> str:
    millis = int(round(seconds * 1000))
    hours = millis // 3_600_000
    millis %= 3_600_000
    minutes = millis // 60_000
    millis %= 60_000
    secs = millis // 1000
    millis %= 1000
    return f"{hours:02}:{minutes:02}:{secs:02},{millis:03}"


def split_japanese_text(text: str, max_chars: int = 18) -> str:
    """日本語テキストを自然な区切り位置で改行する。単語の途中では改行しない。"""
    if len(text) <= max_chars:
        return text

    # 優先度順の区切りパターン（この文字/文字列の後で改行可能）
    # 優先度が高いものから順にグループ化
    break_pattern_groups = [
        # 最優先: 句読点・記号
        ['。', '、', '！', '？', '…', '　', '」', '）'],
        # 高優先: 文末表現
        ['ます', 'です', 'ました', 'でした', 'ません', 'ない', 'った', 'した'],
        # 中優先: 接続表現
        ['って', 'ので', 'から', 'けど', 'ても', 'ては', 'では', 'ければ', 'ながら'],
    ]

    lines = []
    remaining = text

    while len(remaining) > max_chars:
        best_pos = -1

        # 優先度順にパターングループを探す
        for patterns in break_pattern_groups:
            for pattern in patterns:
                search_range = remaining[:max_chars]
                pos = search_range.rfind(pattern)
                if pos != -1:
                    cut_pos = pos + len(pattern)
                    if cut_pos > best_pos and cut_pos < len(remaining):
                        best_pos = cut_pos
            # このグループで見つかったら、より低優先のグループは探さない
            if best_pos > 0:
                break

        if best_pos > 0:
            lines.append(remaining[:best_pos])
            remaining = remaining[best_pos:]
        else:
            # 適切な区切りが見つからない場合は改行せずそのまま
            lines.append(remaining)
            remaining = ""

    if remaining:
        lines.append(remaining)

    return '\n'.join(lines)


def generate_japanese_srt(input_path: Path, srt_path: Path) -> None:
    import requests as http_requests
    import time

    api_key = os.environ.get("ASSEMBLYAI_API_KEY", "")
    if not api_key:
        raise RuntimeError("ASSEMBLYAI_API_KEY が設定されていません。")

    headers = {"authorization": api_key}
    base_url = "https://api.assemblyai.com/v2"

    # 1. Upload audio file
    with open(input_path, "rb") as f:
        upload_resp = http_requests.post(
            f"{base_url}/upload", headers=headers, data=f
        )
    if upload_resp.status_code != 200:
        raise RuntimeError(f"アップロードに失敗しました: {upload_resp.text}")
    audio_url = upload_resp.json()["upload_url"]

    # 2. Request transcription
    transcript_resp = http_requests.post(
        f"{base_url}/transcript",
        headers=headers,
        json={
            "audio_url": audio_url,
            "language_code": "ja",
            "speech_models": ["universal-2"],
        },
    )
    if transcript_resp.status_code != 200:
        raise RuntimeError(f"文字起こしリクエストに失敗: {transcript_resp.text}")
    transcript_id = transcript_resp.json()["id"]

    # 3. Poll until completion
    polling_url = f"{base_url}/transcript/{transcript_id}"
    while True:
        poll_resp = http_requests.get(polling_url, headers=headers)
        data = poll_resp.json()
        status = data.get("status")
        if status == "completed":
            break
        elif status == "error":
            raise RuntimeError(f"文字起こしに失敗: {data.get('error', '不明なエラー')}")
        time.sleep(3)

    # 4. Get sentences
    sentences_resp = http_requests.get(
        f"{base_url}/transcript/{transcript_id}/sentences", headers=headers
    )
    segments = sentences_resp.json().get("sentences", [])

    if not segments:
        raise RuntimeError("音声認識結果が空でした。音声トラックがあるか確認してください。")

    _write_ass_file(srt_path, segments)


def _ass_timestamp(ms: int) -> str:
    """Convert milliseconds to ASS timestamp H:MM:SS.cc"""
    total_cs = ms // 10
    h = total_cs // 360000
    total_cs %= 360000
    m = total_cs // 6000
    total_cs %= 6000
    s = total_cs // 100
    cs = total_cs % 100
    return f"{h}:{m:02}:{s:02}.{cs:02}"


def _write_ass_file(ass_path: Path, segments: list) -> None:
    """Write an ASS subtitle file with embedded font reference."""
    header = """[Script Info]
Title: Generated Subtitles
ScriptType: v4.00+
PlayResX: 540
PlayResY: 960
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Noto Sans CJK JP,28,&H00FFFFFF,&H000000FF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,2,1,2,10,10,120,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    with ass_path.open("w", encoding="utf-8") as f:
        f.write(header)
        for seg in segments:
            start = _ass_timestamp(seg["start"])
            end = _ass_timestamp(seg["end"])
            text = seg["text"].strip()
            if not text:
                continue
            formatted = split_japanese_text(text).replace("\n", "\\N")
            f.write(f"Dialogue: 0,{start},{end},Default,,0,0,0,,{formatted}\n")


def build_output_codec_args(output_ext: str) -> list[str]:
    if output_ext == ".webm":
        return [
            "-c:v",
            "libvpx-vp9",
            "-crf",
            "32",
            "-b:v",
            "0",
            "-c:a",
            "libopus",
            "-b:a",
            "128k",
            "-metadata:s:v:0",
            "rotate=0",
        ]

    codec_args = [
        "-c:v",
        "libx264",
        "-preset",
        "ultrafast",
        "-crf",
        "28",
        "-c:a",
        "aac",
        "-b:a",
        "96k",
        "-threads",
        "1",
        "-metadata:s:v:0",
        "rotate=0",
    ]
    if output_ext in {".mp4", ".mov"}:
        codec_args.extend(["-movflags", "+faststart"])
    return codec_args


def run_ffmpeg(command: list[str]) -> None:
    with open(os.devnull, "w") as devnull:
        completed = subprocess.run(
            command, stdout=devnull, stderr=subprocess.PIPE, text=True,
            timeout=600
        )
    if completed.returncode != 0:
        err = (completed.stderr or "")[-500:]
        raise RuntimeError(err.strip() or "FFmpeg conversion failed")


def get_rotation_degrees(input_path: Path) -> int:
    command = [
        "ffprobe",
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream_side_data=rotation:stream_tags=rotate",
        "-of",
        "json",
        str(input_path),
    ]
    completed = subprocess.run(command, capture_output=True, text=True)
    if completed.returncode != 0 or not completed.stdout.strip():
        return 0

    try:
        data = json.loads(completed.stdout)
    except json.JSONDecodeError:
        return 0

    streams = data.get("streams", [])
    if not streams:
        return 0

    stream = streams[0]
    tags = stream.get("tags", {})
    if "rotate" in tags:
        try:
            return int(float(tags["rotate"])) % 360
        except (TypeError, ValueError):
            pass

    for side_data in stream.get("side_data_list", []):
        if "rotation" in side_data:
            try:
                return int(float(side_data["rotation"])) % 360
            except (TypeError, ValueError):
                return 0

    return 0


def build_rotation_filter(rotation_degrees: int) -> str:
    normalized = rotation_degrees % 360
    if normalized == 90:
        return "transpose=1,"
    if normalized == 180:
        return ""  # 180度の場合は補正不要（メタデータが既に適用済みの場合が多い）
    if normalized == 270:
        return "transpose=2,"
    return ""


def _find_japanese_font(font_dir: str) -> str | None:
    """Return path to first Japanese font found, or None."""
    font_path = Path(font_dir)
    if font_path.is_dir():
        for ext in ("*.otf", "*.ttf"):
            files = list(font_path.glob(ext))
            if files:
                return str(files[0])
    # Also check system fonts
    for sys_path in [
        "/usr/share/fonts/opentype/noto",
        "/usr/share/fonts/truetype/noto",
        "/usr/local/share/fonts",
    ]:
        p = Path(sys_path)
        if p.is_dir():
            for ext in ("*.otf", "*.ttf"):
                files = [f for f in p.glob(ext) if "CJK" in f.name or "JP" in f.name]
                if files:
                    return str(files[0])
    return None


def build_filter_chain(
    mode: str,
    rotation_degrees: int,
    escaped_srt_path: str | None = None,
    beauty_enabled: bool = False,
) -> str:
    rotate_filter = build_rotation_filter(rotation_degrees)
    normalized_rotation = rotation_degrees % 360

    # 180度回転で字幕ありの場合、字幕がdisplaymatrixの影響で反転するため、
    # 前後でhflip,vflipを適用して正しい向きにする
    needs_180_subtitle_fix = (normalized_rotation == 180 and escaped_srt_path)
    pre_flip = "hflip,vflip," if needs_180_subtitle_fix else ""
    post_flip = ",hflip,vflip" if needs_180_subtitle_fix else ""

    if mode == "crop":
        base_chain = (
            f"{pre_flip}{rotate_filter}scale=540:960:force_original_aspect_ratio=increase,"
            "setsar=1,crop=540:960"
        )
    else:
        # Pad with black bars (low memory usage, no split/blur needed)
        base_chain = (
            f"{pre_flip}{rotate_filter}scale=540:960:force_original_aspect_ratio=decrease,"
            "setsar=1,pad=720:1280:(ow-iw)/2:(oh-ih)/2:black"
        )

    # Lightweight beautify pass: soften details and lift skin tone slightly.
    if beauty_enabled:
        base_chain = f"{base_chain},hqdn3d=1.5:1.5:6:6,eq=brightness=0.02:saturation=1.08:gamma=1.02"

    if escaped_srt_path:
        font_dir = str(Path(__file__).resolve().parent / "fonts")
        escaped_font_dir = font_dir.replace("\\", "\\\\").replace("'", "\\'")
        subtitle_filter = (
            f"ass=filename='{escaped_srt_path}':fontsdir='{escaped_font_dir}'"
        )
        return f"{base_chain},{subtitle_filter}{post_flip}"

    return base_chain


def convert_to_vertical_with_subtitles(
    input_path: Path,
    output_path: Path,
    srt_path: Path,
    mode: str,
    beauty_enabled: bool,
    rotation_degrees: int,
) -> None:
    # Step 1: Convert video without subtitles to a temp file
    temp_path = output_path.parent / f"temp_{output_path.name}"
    filter_chain = build_filter_chain(mode, rotation_degrees, beauty_enabled=beauty_enabled)
    cmd1 = [
        "ffmpeg", "-y", "-noautorotate",
        "-i", str(input_path),
        "-filter_complex", filter_chain,
        *build_output_codec_args(output_path.suffix.lower()),
        str(temp_path),
    ]
    run_ffmpeg(cmd1)

    # Delete original input to free memory
    if input_path.exists():
        input_path.unlink()

    # Step 2: Burn subtitles onto the already-small temp file
    escaped_srt = str(srt_path).replace("\\", "\\\\").replace("'", "\\'")
    font_dir = str(Path(__file__).resolve().parent / "fonts")
    escaped_font_dir = font_dir.replace("\\", "\\\\").replace("'", "\\'")
    sub_filter = f"ass=filename='{escaped_srt}':fontsdir='{escaped_font_dir}'"
    cmd2 = [
        "ffmpeg", "-y",
        "-i", str(temp_path),
        "-vf", sub_filter,
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "28",
        "-c:a", "copy", "-threads", "1",
        str(output_path),
    ]
    try:
        run_ffmpeg(cmd2)
    finally:
        if temp_path.exists():
            temp_path.unlink()


def convert_to_vertical_without_subtitles(
    input_path: Path, output_path: Path, mode: str, beauty_enabled: bool, rotation_degrees: int
) -> None:
    filter_chain = build_filter_chain(mode, rotation_degrees, beauty_enabled=beauty_enabled)
    command = [
        "ffmpeg", "-y", "-noautorotate",
        "-i", str(input_path),
        "-filter_complex", filter_chain,
        *build_output_codec_args(output_path.suffix.lower()),
        str(output_path),
    ]
    run_ffmpeg(command)


@app.route("/debug/fonts")
def debug_fonts():
    """Check which fonts are available on the server."""
    font_dir = str(BASE_DIR / "fonts")
    found = _find_japanese_font(font_dir)
    # Get internal font name
    fc_query = ""
    if found:
        try:
            r = subprocess.run(["fc-query", "--format=%{family}\n", found],
                               capture_output=True, text=True, timeout=10)
            fc_query = r.stdout.strip()
        except Exception as e:
            fc_query = str(e)
    fonts_in_dir = []
    if Path(font_dir).is_dir():
        fonts_in_dir = [f.name for f in Path(font_dir).iterdir()]
    # Check fc-list
    try:
        fc = subprocess.run(["fc-list", ":lang=ja"], capture_output=True, text=True, timeout=10)
        fc_output = fc.stdout[:2000]
    except Exception as e:
        fc_output = str(e)
    return jsonify({
        "font_dir": font_dir,
        "fonts_in_dir": fonts_in_dir,
        "found_font": found,
        "font_family_name": fc_query,
        "fc_list_ja": fc_output,
    })


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/convert", methods=["POST"])
def convert():
    if "video" not in request.files:
        return jsonify({"error": "動画ファイルが見つかりません。"}), 400

    video = request.files["video"]
    if not video.filename:
        return jsonify({"error": "ファイルが選択されていません。"}), 400

    if not is_allowed_file(video.filename):
        return jsonify({"error": "対応していない拡張子です。mp4/mov/mkv/avi/webmのみ対応。"}), 400

    subtitle_enabled = request.form.get("subtitle_enabled", "true").lower() == "true"
    beauty_enabled = request.form.get("beauty_enabled", "false").lower() == "true"
    convert_mode = request.form.get("convert_mode", "blur").lower()
    if convert_mode not in {"blur", "crop"}:
        convert_mode = "blur"

    safe_name = secure_filename(video.filename)
    file_id = uuid.uuid4().hex
    output_ext = Path(safe_name).suffix.lower()
    if output_ext not in ALLOWED_EXTENSIONS:
        output_ext = ".mp4"
    input_path = UPLOAD_DIR / f"{file_id}_{safe_name}"
    output_path = OUTPUT_DIR / f"{file_id}_vertical{output_ext}"
    srt_path = SUBTITLE_DIR / f"{file_id}.srt"

    video.save(input_path)

    try:
        rotation_degrees = get_rotation_degrees(input_path)
        if subtitle_enabled:
            generate_japanese_srt(input_path, srt_path)
            convert_to_vertical_with_subtitles(
                input_path, output_path, srt_path, convert_mode, beauty_enabled, rotation_degrees
            )
        else:
            convert_to_vertical_without_subtitles(
                input_path, output_path, convert_mode, beauty_enabled, rotation_degrees
            )
    except Exception as exc:
        if input_path.exists():
            input_path.unlink()
        if srt_path.exists():
            srt_path.unlink()
        return jsonify({"error": f"変換に失敗しました: {exc}"}), 500
    finally:
        if input_path.exists():
            input_path.unlink()
        if srt_path.exists():
            srt_path.unlink()

    return jsonify(
        {
            "message": "変換が完了しました。",
            "download_url": f"/download/{output_path.name}",
            "filename": output_path.name,
        }
    )


@app.route("/download/<path:filename>", methods=["GET"])
def download(filename: str):
    target = OUTPUT_DIR / filename
    if not target.exists():
        return jsonify({"error": "ファイルが見つかりません。"}), 404

    return send_file(target, as_attachment=True, download_name=target.name)


if __name__ == "__main__":
    app.run(debug=True, port=int(os.environ.get("PORT", "8000")))
