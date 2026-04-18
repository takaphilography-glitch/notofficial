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
app.config["MAX_CONTENT_LENGTH"] = 500 * 1024 * 1024  # 500MB


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
    import assemblyai as aai

    api_key = os.environ.get("ASSEMBLYAI_API_KEY", "")
    if not api_key:
        raise RuntimeError("ASSEMBLYAI_API_KEY が設定されていません。")

    aai.settings.api_key = api_key
    config = aai.TranscriptionConfig(language_code="ja")
    transcriber = aai.Transcriber()
    transcript = transcriber.transcribe(str(input_path), config=config)

    if transcript.status == aai.TranscriptStatus.error:
        raise RuntimeError(f"文字起こしに失敗しました: {transcript.error}")

    if not transcript.utterances and not transcript.words:
        # Use sentence-level if utterances not available
        segments = transcript.sentences() if transcript.sentences() else []
    else:
        segments = transcript.sentences() if transcript.sentences() else []

    if not segments:
        raise RuntimeError("音声認識結果が空でした。音声トラックがあるか確認してください。")

    with srt_path.open("w", encoding="utf-8") as srt_file:
        for index, seg in enumerate(segments, start=1):
            start = format_srt_timestamp(seg.start / 1000.0)
            end = format_srt_timestamp(seg.end / 1000.0)
            text = seg.text.strip()
            if not text:
                continue
            formatted_text = split_japanese_text(text)
            srt_file.write(f"{index}\n")
            srt_file.write(f"{start} --> {end}\n")
            srt_file.write(f"{formatted_text}\n\n")


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
        "faster",
        "-crf",
        "20",
        "-c:a",
        "aac",
        "-b:a",
        "128k",
        "-threads",
        "0",
        "-metadata:s:v:0",
        "rotate=0",
    ]
    if output_ext in {".mp4", ".mov"}:
        codec_args.extend(["-movflags", "+faststart"])
    return codec_args


def run_ffmpeg(command: list[str]) -> None:
    completed = subprocess.run(command, capture_output=True, text=True)
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.strip() or "FFmpeg conversion failed")


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
            f"{pre_flip}{rotate_filter}scale=1080:1920:force_original_aspect_ratio=increase,"
            "setsar=1,crop=1080:1920"
        )
    else:
        # Blur-fill: enlarged original video + gaussian blur, no brightness shift.
        base_chain = (
            f"[0:v]{pre_flip}{rotate_filter}split=2[bgin][fgin];"
            "[bgin]scale=1080:1920:force_original_aspect_ratio=increase,setsar=1,"
            "crop=1080:1920,gblur=sigma=14:steps=2[bg];"
            "[fgin]scale=1080:1920:force_original_aspect_ratio=decrease,setsar=1[fg];"
            "[bg][fg]overlay=(W-w)/2:(H-h)/2"
        )

    # Lightweight beautify pass: soften details and lift skin tone slightly.
    if beauty_enabled:
        base_chain = f"{base_chain},hqdn3d=1.5:1.5:6:6,eq=brightness=0.02:saturation=1.08:gamma=1.02"

    if escaped_srt_path:
        subtitle_style = (
            f"subtitles=filename='{escaped_srt_path}':force_style='Fontsize=16,Bold=1,PrimaryColour=&H00FFFFFF&,"
            "BorderStyle=1,Outline=0,Shadow=2,BackColour=&H80000000&,MarginV=60'"
        )
        return f"{base_chain},{subtitle_style}{post_flip}"

    return base_chain


def convert_to_vertical_with_subtitles(
    input_path: Path,
    output_path: Path,
    srt_path: Path,
    mode: str,
    beauty_enabled: bool,
    rotation_degrees: int,
) -> None:
    # Inside ffmpeg single-quoted filter values, only \ and ' need escaping (not :)
    escaped_srt = str(srt_path).replace("\\", "\\\\").replace("'", "\\'")
    filter_chain = build_filter_chain(mode, rotation_degrees, escaped_srt, beauty_enabled)
    command = [
        "ffmpeg",
        "-y",
        "-noautorotate",
        "-i",
        str(input_path),
        "-filter_complex",
        filter_chain,
        *build_output_codec_args(output_path.suffix.lower()),
        str(output_path),
    ]
    run_ffmpeg(command)


def convert_to_vertical_without_subtitles(
    input_path: Path, output_path: Path, mode: str, beauty_enabled: bool, rotation_degrees: int
) -> None:
    filter_chain = build_filter_chain(mode, rotation_degrees, beauty_enabled=beauty_enabled)
    command = [
        "ffmpeg",
        "-y",
        "-noautorotate",
        "-i",
        str(input_path),
        "-filter_complex",
        filter_chain,
        *build_output_codec_args(output_path.suffix.lower()),
        str(output_path),
    ]
    run_ffmpeg(command)


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
