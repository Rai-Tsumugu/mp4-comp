import argparse
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

DEFAULT_TARGET_SIZE_MB = 200
DEFAULT_AUDIO_BITRATE_KBPS = 128
DEFAULT_QUALITY_KEY = "standard"
EVENT_PREFIX = "__MP4_COMP_EVENT__"
StatusCallback = Callable[[str], None]


@dataclass(frozen=True)
class QualityProfile:
    key: str
    label: str
    description: str
    crf: int
    max_height: int | None


QUALITY_PROFILES = (
    QualityProfile(
        key="near_source",
        label="かなり高画質",
        description="できるだけ元の見た目を保ちたいとき向けです。",
        crf=20,
        max_height=None,
    ),
    QualityProfile(
        key="high",
        label="高画質",
        description="見栄えを保ちながら容量も抑える、扱いやすい設定です。",
        crf=23,
        max_height=1080,
    ),
    QualityProfile(
        key="standard",
        label="標準画質",
        description="普段使い向けの見やすさと容量のバランスを取ります。",
        crf=26,
        max_height=720,
    ),
    QualityProfile(
        key="compact",
        label="容量重視の画質",
        description="視聴しやすさを残しつつ、軽さを優先して圧縮します。",
        crf=30,
        max_height=540,
    ),
)
QUALITY_PROFILES_BY_KEY = {profile.key: profile for profile in QUALITY_PROFILES}


@dataclass(frozen=True)
class VideoInfo:
    duration: float
    width: int
    height: int
    video_bitrate_kbps: float | None
    audio_bitrate_kbps: float | None
    fps: float | None
    source_size_bytes: int
    has_audio: bool


@dataclass(frozen=True)
class QualityAssessment:
    label: str
    description: str


@dataclass(frozen=True)
class CompressionResult:
    output_file: str
    final_size_mb: float
    mode: str
    target_description: str
    remove_audio: bool


def _notify(status_callback: StatusCallback | None, message: str) -> None:
    if status_callback:
        status_callback(message)


def _emit_event(event_type: str, **payload: object) -> None:
    if os.getenv("MP4_COMP_EVENT_MODE") != "1":
        return
    print(
        f"{EVENT_PREFIX}{json.dumps({'type': event_type, **payload}, ensure_ascii=False)}",
        flush=True,
    )


def _emit_progress(
    percent: float,
    label: str,
    current_seconds: float | None = None,
    total_seconds: float | None = None,
) -> None:
    clamped = max(0.0, min(percent, 100.0))
    payload: dict[str, object] = {
        "percent": round(clamped, 1),
        "label": label,
    }
    if current_seconds is not None:
        payload["current_seconds"] = round(max(current_seconds, 0.0), 2)
        payload["current_text"] = format_duration(current_seconds)
    if total_seconds is not None:
        payload["total_seconds"] = round(max(total_seconds, 0.0), 2)
        payload["total_text"] = format_duration(total_seconds)
    _emit_event("progress", **payload)


def _decode_output(raw_output: bytes | None) -> str:
    if not raw_output:
        return ""
    return raw_output.decode("utf-8", errors="ignore")


def _safe_float(value: object) -> float | None:
    if value in (None, "", "N/A"):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_ratio(value: str | None) -> float | None:
    if not value or value in {"0/0", "N/A"}:
        return None
    if "/" in value:
        numerator, denominator = value.split("/", 1)
        numerator_value = _safe_float(numerator)
        denominator_value = _safe_float(denominator)
        if numerator_value is None or denominator_value in (None, 0):
            return None
        return numerator_value / denominator_value
    return _safe_float(value)


def _parse_ffmpeg_time(value: str) -> float:
    if not value or value == "N/A":
        return 0.0
    parts = value.split(":")
    if len(parts) != 3:
        return 0.0
    hours = _safe_float(parts[0]) or 0.0
    minutes = _safe_float(parts[1]) or 0.0
    seconds = _safe_float(parts[2]) or 0.0
    return (hours * 3600) + (minutes * 60) + seconds


def _format_size_mb(size_mb: float) -> float:
    return round(size_mb, 2)


def _run_subprocess(command: list[str], error_prefix: str) -> bytes:
    try:
        completed = subprocess.run(command, capture_output=True, check=True)
        return completed.stdout
    except FileNotFoundError as exc:
        raise RuntimeError(
            f"'{command[0]}' が見つかりません。FFmpeg がインストールされ、PATH に含まれていることを確認してください。"
        ) from exc
    except subprocess.CalledProcessError as exc:
        details = _decode_output(exc.stderr or exc.stdout).strip()
        if details:
            details = details[-2000:]
            raise RuntimeError(f"{error_prefix}\n{details}") from exc
        raise RuntimeError(error_prefix) from exc


def probe_video(input_file: str) -> VideoInfo:
    input_path = Path(input_file)
    if not input_path.exists():
        raise FileNotFoundError(f"ファイル '{input_file}' が見つかりません。")

    command = [
        "ffprobe",
        "-v",
        "quiet",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        str(input_path),
    ]
    output = _run_subprocess(command, "ffprobe の実行に失敗しました。")
    data = json.loads(_decode_output(output))

    video_stream = next(
        (stream for stream in data.get("streams", []) if stream.get("codec_type") == "video"),
        None,
    )
    audio_stream = next(
        (stream for stream in data.get("streams", []) if stream.get("codec_type") == "audio"),
        None,
    )
    if not video_stream:
        raise RuntimeError("動画ストリームが見つかりませんでした。")

    width = int(video_stream.get("width") or 0)
    height = int(video_stream.get("height") or 0)

    duration = _safe_float(data.get("format", {}).get("duration"))
    if duration is None:
        duration = _safe_float(video_stream.get("duration"))
    if duration is None or duration <= 0:
        raise RuntimeError("動画の長さを取得できませんでした。")

    audio_bitrate_kbps = None
    if audio_stream:
        audio_bitrate = _safe_float(audio_stream.get("bit_rate"))
        if audio_bitrate:
            audio_bitrate_kbps = audio_bitrate / 1000

    source_size_bytes = input_path.stat().st_size
    source_total_bitrate_kbps = (source_size_bytes * 8) / duration / 1000

    video_bitrate_kbps = None
    video_bitrate = _safe_float(video_stream.get("bit_rate"))
    if video_bitrate:
        video_bitrate_kbps = video_bitrate / 1000

    format_bitrate = _safe_float(data.get("format", {}).get("bit_rate"))
    if video_bitrate_kbps is None and format_bitrate:
        if audio_bitrate_kbps:
            estimated_video_bitrate = format_bitrate - (audio_bitrate_kbps * 1000)
            if estimated_video_bitrate > 0:
                video_bitrate_kbps = estimated_video_bitrate / 1000
        else:
            video_bitrate_kbps = format_bitrate / 1000

    if video_bitrate_kbps is None:
        fallback_audio = audio_bitrate_kbps or 0
        estimated_video_bitrate_kbps = source_total_bitrate_kbps - fallback_audio
        if estimated_video_bitrate_kbps > 0:
            video_bitrate_kbps = estimated_video_bitrate_kbps

    fps = _parse_ratio(video_stream.get("avg_frame_rate")) or _parse_ratio(
        video_stream.get("r_frame_rate")
    )

    return VideoInfo(
        duration=duration,
        width=width,
        height=height,
        video_bitrate_kbps=video_bitrate_kbps,
        audio_bitrate_kbps=audio_bitrate_kbps,
        fps=fps,
        source_size_bytes=source_size_bytes,
        has_audio=audio_stream is not None,
    )


def assess_video_quality(video_info: VideoInfo) -> QualityAssessment:
    height = video_info.height
    bitrate = video_info.video_bitrate_kbps or 0

    if bitrate <= 0:
        if height >= 1080:
            return QualityAssessment("高画質", "高解像度で、見栄えを保ちやすい動画です。")
        if height >= 720:
            return QualityAssessment("標準画質", "普段使いでは見やすいバランスの動画です。")
        if height >= 480:
            return QualityAssessment("容量重視の画質", "軽さを優先した圧縮寄りの動画です。")
        return QualityAssessment("かなり圧縮された画質", "細部がつぶれやすい軽量寄りの動画です。")

    if height >= 1440:
        if bitrate >= 12000:
            return QualityAssessment("かなり高画質", "高精細で、細部まで残りやすい動画です。")
        if bitrate >= 7000:
            return QualityAssessment("高画質", "高解像度で見栄えを保ちやすい動画です。")
        if bitrate >= 3500:
            return QualityAssessment("標準画質", "解像感はありますが、圧縮もそれなりに入っています。")
        return QualityAssessment("容量重視の画質", "高解像度ですが、軽さ優先の圧縮傾向です。")

    if height >= 1080:
        if bitrate >= 8000:
            return QualityAssessment("かなり高画質", "フルHDで細部の情報量に余裕がある動画です。")
        if bitrate >= 4500:
            return QualityAssessment("高画質", "フルHDで見やすく、崩れにくい動画です。")
        if bitrate >= 2200:
            return QualityAssessment("標準画質", "フルHDとしては標準的な見やすさです。")
        if bitrate >= 1000:
            return QualityAssessment("容量重視の画質", "フルHDですが、軽量化を優先した動画です。")
        return QualityAssessment("かなり圧縮された画質", "フルHDでも細部のつぶれが出やすい状態です。")

    if height >= 720:
        if bitrate >= 4500:
            return QualityAssessment("高画質", "HD画質としては余裕があり、見栄えを保ちやすい動画です。")
        if bitrate >= 2000:
            return QualityAssessment("標準画質", "HD画質で普段使いしやすい動画です。")
        if bitrate >= 900:
            return QualityAssessment("容量重視の画質", "HD画質で軽さを優先した動画です。")
        return QualityAssessment("かなり圧縮された画質", "HDでも細部の粗さが出やすい軽量寄りの動画です。")

    if height >= 480:
        if bitrate >= 1800:
            return QualityAssessment("標準画質", "見やすさと軽さのバランスが取れた動画です。")
        if bitrate >= 900:
            return QualityAssessment("容量重視の画質", "軽めにまとめた標準的な動画です。")
        return QualityAssessment("かなり圧縮された画質", "粗さが見えやすい軽量寄りの動画です。")

    if bitrate >= 1000:
        return QualityAssessment("容量重視の画質", "小さめの解像度で軽さ優先の動画です。")
    return QualityAssessment("かなり圧縮された画質", "かなり軽量化された低解像度の動画です。")


def format_duration(seconds: float) -> str:
    total_seconds = max(0, int(round(seconds)))
    hours, remainder = divmod(total_seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours:02}:{minutes:02}:{secs:02}"
    return f"{minutes:02}:{secs:02}"


def describe_video(video_info: VideoInfo) -> str:
    parts = [f"長さ: {format_duration(video_info.duration)}"]
    if video_info.width and video_info.height:
        parts.append(f"解像度: {video_info.width}x{video_info.height}")
    if video_info.fps:
        parts.append(f"フレームレート: {video_info.fps:.1f}fps")
    return " / ".join(parts)


def _estimated_total_bitrate_kbps(video_info: VideoInfo) -> float:
    return (video_info.source_size_bytes * 8) / video_info.duration / 1000


def _source_video_bitrate_kbps(video_info: VideoInfo) -> float:
    if video_info.video_bitrate_kbps and video_info.video_bitrate_kbps > 0:
        return video_info.video_bitrate_kbps

    fallback_audio = video_info.audio_bitrate_kbps or 0
    estimated_video = _estimated_total_bitrate_kbps(video_info) - fallback_audio
    return max(estimated_video, 300.0)


def _audio_bitrate_for_output(video_info: VideoInfo, remove_audio: bool) -> float:
    if remove_audio or not video_info.has_audio:
        return 0.0
    return min(video_info.audio_bitrate_kbps or DEFAULT_AUDIO_BITRATE_KBPS, DEFAULT_AUDIO_BITRATE_KBPS)


def _quality_factor_for_profile(quality_key: str) -> float:
    return {
        "near_source": 0.95,
        "high": 0.72,
        "standard": 0.48,
        "compact": 0.30,
    }[quality_key]


def _minimum_video_bitrate_kbps(quality_key: str, target_height: int) -> float:
    scaled_height = max(target_height, 360)
    scale = scaled_height / 1080
    base = {
        "near_source": 3200,
        "high": 2200,
        "standard": 1400,
        "compact": 800,
    }[quality_key]
    return max(base * scale, 250.0)


def estimate_quality_output_size_mb(
    video_info: VideoInfo, quality_key: str, remove_audio: bool = False
) -> float:
    profile = QUALITY_PROFILES_BY_KEY[quality_key]
    target_dimensions = _calculate_scaled_dimensions(
        video_info.width, video_info.height, profile.max_height
    )

    area_ratio = 1.0
    target_height = video_info.height
    if target_dimensions:
        target_width, target_height = target_dimensions
        if video_info.width > 0 and video_info.height > 0:
            area_ratio = (target_width * target_height) / (video_info.width * video_info.height)

    source_video_bitrate = _source_video_bitrate_kbps(video_info)
    scaled_video_bitrate = source_video_bitrate * area_ratio * _quality_factor_for_profile(quality_key)
    target_video_bitrate = max(
        scaled_video_bitrate, _minimum_video_bitrate_kbps(quality_key, target_height)
    )
    audio_bitrate = _audio_bitrate_for_output(video_info, remove_audio)

    total_bitrate = target_video_bitrate + audio_bitrate
    estimated_size_mb = (total_bitrate * 1000 * video_info.duration) / 8 / (1024 * 1024)
    return _format_size_mb(estimated_size_mb)


def build_quality_estimates(video_info: VideoInfo) -> dict[str, dict[str, object]]:
    estimates: dict[str, dict[str, object]] = {}
    for profile in QUALITY_PROFILES:
        estimates[profile.key] = {
            "label": profile.label,
            "description": profile.description,
            "with_audio_mb": estimate_quality_output_size_mb(video_info, profile.key, False),
            "without_audio_mb": estimate_quality_output_size_mb(video_info, profile.key, True),
        }
    return estimates


def video_info_to_dict(video_info: VideoInfo) -> dict[str, float | int | bool | None]:
    return {
        "duration": video_info.duration,
        "width": video_info.width,
        "height": video_info.height,
        "video_bitrate_kbps": video_info.video_bitrate_kbps,
        "audio_bitrate_kbps": video_info.audio_bitrate_kbps,
        "fps": video_info.fps,
        "source_size_bytes": video_info.source_size_bytes,
        "source_size_mb": _format_size_mb(video_info.source_size_bytes / (1024 * 1024)),
        "has_audio": video_info.has_audio,
    }


def quality_profile_to_dict(profile: QualityProfile) -> dict[str, str | int | None]:
    return {
        "key": profile.key,
        "label": profile.label,
        "description": profile.description,
        "crf": profile.crf,
        "max_height": profile.max_height,
    }


def build_probe_payload(input_file: str) -> dict[str, object]:
    video_info = probe_video(input_file)
    quality = assess_video_quality(video_info)
    return {
        "video_info": video_info_to_dict(video_info),
        "video_summary": describe_video(video_info),
        "current_quality": {
            "label": quality.label,
            "description": quality.description,
        },
        "estimated_sizes_mb": build_quality_estimates(video_info),
    }


def _build_output_path(input_file: str, suffix: str, remove_audio: bool) -> Path:
    input_path = Path(input_file)
    extra_suffix = "_noaudio" if remove_audio else ""
    return input_path.with_name(f"{input_path.stem}{suffix}{extra_suffix}{input_path.suffix}")


def _cleanup_pass_logs(passlog_base: Path) -> None:
    for candidate in passlog_base.parent.glob(f"{passlog_base.name}*"):
        if candidate.is_file():
            try:
                candidate.unlink()
            except OSError:
                pass


def _calculate_scaled_dimensions(
    width: int, height: int, max_height: int | None
) -> tuple[int, int] | None:
    if not max_height or width <= 0 or height <= 0 or height <= max_height:
        return None

    ratio = max_height / height
    new_width = max(2, int(round(width * ratio)))
    new_height = max(2, int(round(height * ratio)))

    if new_width % 2:
        new_width -= 1
    if new_height % 2:
        new_height -= 1

    return new_width, new_height


def _validate_input_file(input_file: str) -> None:
    if not Path(input_file).exists():
        raise FileNotFoundError(f"ファイル '{input_file}' が見つかりません。")


def _run_ffmpeg_with_progress(
    command: list[str],
    error_prefix: str,
    duration: float,
    progress_from: float,
    progress_to: float,
    progress_label: str,
) -> None:
    ffmpeg_command = command[:1] + ["-nostats", "-progress", "pipe:1"] + command[1:]

    try:
        process = subprocess.Popen(
            ffmpeg_command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="ignore",
        )
    except FileNotFoundError as exc:
        raise RuntimeError(
            f"'{command[0]}' が見つかりません。FFmpeg がインストールされ、PATH に含まれていることを確認してください。"
        ) from exc

    latest_seconds = 0.0
    last_percent = None

    while True:
        line = process.stdout.readline() if process.stdout else ""
        if line == "" and process.poll() is not None:
            break
        if not line:
            continue

        line = line.strip()
        if not line or "=" not in line:
            continue

        key, value = line.split("=", 1)
        if key == "out_time":
            latest_seconds = _parse_ffmpeg_time(value)
        elif key in {"out_time_us", "out_time_ms"}:
            raw_value = _safe_float(value) or 0.0
            latest_seconds = raw_value / 1_000_000
        elif key == "progress":
            normalized = 0.0
            if duration > 0:
                normalized = max(0.0, min(latest_seconds / duration, 1.0))
            current_percent = progress_from + ((progress_to - progress_from) * normalized)
            if value == "end":
                current_percent = progress_to
            if last_percent is None or abs(current_percent - last_percent) >= 0.5 or value == "end":
                display_seconds = duration if value == "end" else latest_seconds
                _emit_progress(
                    current_percent,
                    progress_label,
                    current_seconds=display_seconds,
                    total_seconds=duration,
                )
                last_percent = current_percent

    stderr = process.stderr.read() if process.stderr else ""
    return_code = process.wait()
    if return_code != 0:
        details = stderr.strip()
        if details:
            details = details[-2000:]
            raise RuntimeError(f"{error_prefix}\n{details}")
        raise RuntimeError(error_prefix)

    _emit_progress(
        progress_to,
        progress_label,
        current_seconds=duration,
        total_seconds=duration,
    )


def compress_video_to_size(
    input_file: str,
    target_size_mb: int = DEFAULT_TARGET_SIZE_MB,
    remove_audio: bool = False,
    status_callback: StatusCallback | None = print,
) -> CompressionResult:
    if target_size_mb <= 0:
        raise ValueError("目標ファイルサイズは 1MB 以上で指定してください。")

    _validate_input_file(input_file)
    video_info = probe_video(input_file)
    quality = assess_video_quality(video_info)
    audio_enabled = video_info.has_audio and not remove_audio

    _notify(status_callback, f"動画情報: {describe_video(video_info)}")
    _notify(status_callback, f"現在の画質: {quality.label} - {quality.description}")
    _notify(
        status_callback,
        f"元ファイルサイズ: {video_info.source_size_bytes / (1024 * 1024):.2f} MB",
    )
    _notify(
        status_callback,
        f"音声: {'削除して出力' if not audio_enabled else '残して出力'}",
    )

    target_size_bits = target_size_mb * 1024 * 1024 * 8 * 0.95
    total_bitrate_bits = target_size_bits / video_info.duration
    audio_bitrate_bits = _audio_bitrate_for_output(video_info, remove_audio) * 1000
    video_bitrate_kbps = (total_bitrate_bits - audio_bitrate_bits) / 1000
    video_bitrate_kbps = max(video_bitrate_kbps, 50)

    if video_bitrate_kbps < 100:
        _notify(
            status_callback,
            "警告: かなり低いビットレートになるため、画質が大きく落ちる可能性があります。",
        )

    output_file = _build_output_path(input_file, "_compressed", remove_audio)
    passlog_base = output_file.with_suffix("")
    passlog_base = passlog_base.parent / f"{passlog_base.name}_passlog"
    null_device = "NUL" if os.name == "nt" else "/dev/null"

    pass1_command = [
        "ffmpeg",
        "-loglevel",
        "error",
        "-y",
        "-i",
        str(input_file),
        "-c:v",
        "libx264",
        "-preset",
        "medium",
        "-b:v",
        f"{int(video_bitrate_kbps)}k",
        "-pass",
        "1",
        "-passlogfile",
        str(passlog_base),
        "-an",
        "-f",
        "mp4",
        null_device,
    ]
    pass2_command = [
        "ffmpeg",
        "-loglevel",
        "error",
        "-y",
        "-i",
        str(input_file),
        "-c:v",
        "libx264",
        "-preset",
        "medium",
        "-b:v",
        f"{int(video_bitrate_kbps)}k",
        "-pass",
        "2",
        "-passlogfile",
        str(passlog_base),
    ]
    if audio_enabled:
        pass2_command.extend(
            [
                "-c:a",
                "aac",
                "-b:a",
                f"{int(_audio_bitrate_for_output(video_info, remove_audio))}k",
            ]
        )
    else:
        pass2_command.append("-an")
    pass2_command.extend(["-movflags", "+faststart", str(output_file)])

    try:
        _notify(status_callback, "エンコード中 (Pass 1/2)...")
        _emit_progress(0, "Pass 1/2")
        _run_ffmpeg_with_progress(
            pass1_command,
            "Pass 1 のエンコードに失敗しました。",
            video_info.duration,
            progress_from=0,
            progress_to=50,
            progress_label="Pass 1/2",
        )
        _notify(status_callback, "エンコード中 (Pass 2/2)...")
        _run_ffmpeg_with_progress(
            pass2_command,
            "Pass 2 のエンコードに失敗しました。",
            video_info.duration,
            progress_from=50,
            progress_to=100,
            progress_label="Pass 2/2",
        )
    finally:
        _cleanup_pass_logs(passlog_base)

    final_size_mb = output_file.stat().st_size / (1024 * 1024)
    _notify(status_callback, f"圧縮完了: {output_file}")
    _notify(status_callback, f"出力サイズ: {final_size_mb:.2f} MB")

    if final_size_mb > target_size_mb:
        _notify(status_callback, f"警告: 目標サイズ ({target_size_mb}MB) を超過しました。")
    else:
        _notify(status_callback, "目標サイズ内に収まりました。")

    result = CompressionResult(
        output_file=str(output_file),
        final_size_mb=final_size_mb,
        mode="size",
        target_description=f"{target_size_mb}MB 以下",
        remove_audio=remove_audio,
    )
    _emit_event(
        "result",
        output_file=result.output_file,
        final_size_mb=_format_size_mb(result.final_size_mb),
        mode=result.mode,
    )
    return result


def compress_video_to_quality(
    input_file: str,
    quality_key: str,
    remove_audio: bool = False,
    status_callback: StatusCallback | None = print,
) -> CompressionResult:
    _validate_input_file(input_file)
    profile = QUALITY_PROFILES_BY_KEY.get(quality_key)
    if profile is None:
        raise ValueError(f"未知の画質プリセットです: {quality_key}")

    video_info = probe_video(input_file)
    current_quality = assess_video_quality(video_info)
    audio_enabled = video_info.has_audio and not remove_audio

    _notify(status_callback, f"動画情報: {describe_video(video_info)}")
    _notify(status_callback, f"現在の画質: {current_quality.label} - {current_quality.description}")
    _notify(status_callback, f"目標画質: {profile.label} - {profile.description}")
    _notify(
        status_callback,
        f"元ファイルサイズ: {video_info.source_size_bytes / (1024 * 1024):.2f} MB",
    )
    _notify(
        status_callback,
        f"目安ファイルサイズ: 約 {estimate_quality_output_size_mb(video_info, quality_key, remove_audio):.2f} MB",
    )
    _notify(
        status_callback,
        f"音声: {'削除して出力' if not audio_enabled else '残して出力'}",
    )

    output_file = _build_output_path(input_file, f"_quality_{profile.key}", remove_audio)
    command = [
        "ffmpeg",
        "-loglevel",
        "error",
        "-y",
        "-i",
        str(input_file),
        "-c:v",
        "libx264",
        "-preset",
        "medium",
        "-crf",
        str(profile.crf),
    ]

    scaled_dimensions = _calculate_scaled_dimensions(
        video_info.width, video_info.height, profile.max_height
    )
    if scaled_dimensions:
        width, height = scaled_dimensions
        command.extend(["-vf", f"scale={width}:{height}"])
        _notify(status_callback, f"解像度を {width}x{height} に調整しながら圧縮します。")

    if audio_enabled:
        command.extend(
            [
                "-c:a",
                "aac",
                "-b:a",
                f"{int(_audio_bitrate_for_output(video_info, remove_audio))}k",
            ]
        )
    else:
        command.append("-an")

    command.extend(["-movflags", "+faststart", str(output_file)])

    _notify(status_callback, "エンコード中...")
    _emit_progress(0, "エンコード")
    _run_ffmpeg_with_progress(
        command,
        "画質指定のエンコードに失敗しました。",
        video_info.duration,
        progress_from=0,
        progress_to=100,
        progress_label="エンコード",
    )

    final_size_mb = output_file.stat().st_size / (1024 * 1024)
    _notify(status_callback, f"圧縮完了: {output_file}")
    _notify(status_callback, f"出力サイズ: {final_size_mb:.2f} MB")

    result = CompressionResult(
        output_file=str(output_file),
        final_size_mb=final_size_mb,
        mode="quality",
        target_description=profile.label,
        remove_audio=remove_audio,
    )
    _emit_event(
        "result",
        output_file=result.output_file,
        final_size_mb=_format_size_mb(result.final_size_mb),
        mode=result.mode,
    )
    return result


def convert_mov_to_mp4(
    input_file: str,
    status_callback: StatusCallback | None = print,
) -> CompressionResult:
    _validate_input_file(input_file)
    video_info = probe_video(input_file)

    input_path = Path(input_file)
    output_file = input_path.with_suffix(".mp4")
    if input_path.suffix.lower() == ".mp4":
        output_file = input_path.with_name(f"{input_path.stem}_converted.mp4")

    _notify(status_callback, f"動画情報: {describe_video(video_info)}")
    _notify(status_callback, f"元ファイルサイズ: {video_info.source_size_bytes / (1024 * 1024):.2f} MB")
    _notify(status_callback, f"出力先: {output_file}")

    command = [
        "ffmpeg",
        "-loglevel", "error",
        "-y",
        "-i", str(input_path),
        "-c:v", "libx264",
        "-preset", "medium",
        "-crf", "18",
    ]
    if video_info.has_audio:
        command.extend(["-c:a", "aac", "-b:a", "128k"])
    else:
        command.append("-an")
    command.extend(["-movflags", "+faststart", str(output_file)])

    _notify(status_callback, "変換中...")
    _emit_progress(0, "変換")
    _run_ffmpeg_with_progress(
        command,
        "MOV→MP4 変換に失敗しました。",
        video_info.duration,
        progress_from=0,
        progress_to=100,
        progress_label="変換",
    )

    final_size_mb = output_file.stat().st_size / (1024 * 1024)
    _notify(status_callback, f"変換完了: {output_file}")
    _notify(status_callback, f"出力サイズ: {final_size_mb:.2f} MB")

    result = CompressionResult(
        output_file=str(output_file),
        final_size_mb=final_size_mb,
        mode="convert",
        target_description="MOV→MP4変換",
        remove_audio=not video_info.has_audio,
    )
    _emit_event(
        "result",
        output_file=result.output_file,
        final_size_mb=_format_size_mb(result.final_size_mb),
        mode=result.mode,
    )
    return result


def _print_quality_profiles() -> None:
    print("利用できる画質プリセット:")
    for profile in QUALITY_PROFILES:
        print(f"- {profile.key}: {profile.label} / {profile.description}")


def _prompt_for_mode() -> str:
    print("圧縮モードを選んでください [1: 目標ファイルサイズ / 2: 目標画質] (Enterで1):")
    selected = input().strip()
    if selected == "2":
        return "quality"
    return "size"


def _prompt_for_target_size() -> int:
    print(f"ターゲットサイズを入力してください（MB）[デフォルト: {DEFAULT_TARGET_SIZE_MB}]:")
    size_input = input().strip()
    if not size_input:
        return DEFAULT_TARGET_SIZE_MB
    try:
        target_size = int(size_input)
    except ValueError as exc:
        raise ValueError("ターゲットサイズは整数で入力してください。") from exc
    if target_size <= 0:
        raise ValueError("ターゲットサイズは 1 以上で入力してください。")
    return target_size


def _prompt_for_quality() -> str:
    print("目標画質を選んでください:")
    for index, profile in enumerate(QUALITY_PROFILES, start=1):
        print(f"{index}. {profile.label} - {profile.description}")

    selected = input().strip()
    if not selected:
        return DEFAULT_QUALITY_KEY

    try:
        profile_index = int(selected) - 1
    except ValueError as exc:
        raise ValueError("画質は番号で選択してください。") from exc

    if not 0 <= profile_index < len(QUALITY_PROFILES):
        raise ValueError("存在しない画質番号です。")
    return QUALITY_PROFILES[profile_index].key


def _prompt_remove_audio() -> bool:
    print("音声を削除しますか？ [y/N]:")
    selected = input().strip().lower()
    return selected in {"y", "yes"}


def run_interactive_cli() -> None:
    print("圧縮したいMP4ファイルをドラッグ＆ドロップするか、パスを入力してください:")
    input_path = input().strip().strip('"')
    if not input_path:
        print("ファイルが指定されませんでした。")
        return

    try:
        payload = build_probe_payload(input_path)
        print(f"動画情報: {payload['video_summary']}")
        current_quality = payload["current_quality"]
        print(f"現在の画質: {current_quality['label']} - {current_quality['description']}")
        print(f"元ファイルサイズ: {payload['video_info']['source_size_mb']:.2f} MB")

        mode = _prompt_for_mode()
        remove_audio = _prompt_remove_audio()
        if mode == "size":
            target_size = _prompt_for_target_size()
            compress_video_to_size(input_path, target_size, remove_audio=remove_audio)
        else:
            quality_key = _prompt_for_quality()
            compress_video_to_quality(input_path, quality_key, remove_audio=remove_audio)
    except Exception as exc:
        print(f"エラー: {exc}")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="MP4を目標サイズまたは言葉で選ぶ目標画質で圧縮します。"
    )
    parser.add_argument("input_path", nargs="?", help="圧縮するMP4ファイル")
    parser.add_argument(
        "legacy_target_size",
        nargs="?",
        type=int,
        help="旧形式のサイズ指定 (MB)。従来通り `python compress.py file.mp4 100` で使えます。",
    )
    parser.add_argument(
        "--mode",
        choices=["size", "quality"],
        help="圧縮モード。未指定時は `--quality` があれば quality、それ以外は size です。",
    )
    parser.add_argument("--target-size", type=int, help="目標ファイルサイズ (MB)")
    parser.add_argument(
        "--quality",
        choices=list(QUALITY_PROFILES_BY_KEY.keys()),
        help="目標画質プリセット。`--mode quality` と一緒に使います。",
    )
    parser.add_argument(
        "--no-audio",
        action="store_true",
        help="音声を削除して出力します。",
    )
    parser.add_argument(
        "--list-qualities",
        action="store_true",
        help="利用できる画質プリセットを表示します。",
    )
    parser.add_argument(
        "--list-qualities-json",
        action="store_true",
        help="利用できる画質プリセットを JSON で表示します。",
    )
    parser.add_argument(
        "--probe-json",
        action="store_true",
        help="入力動画の解析結果を JSON で表示します。",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.list_qualities_json:
        print(
            json.dumps(
                [quality_profile_to_dict(profile) for profile in QUALITY_PROFILES],
                ensure_ascii=False,
            )
        )
        return 0

    if args.list_qualities:
        _print_quality_profiles()
        return 0

    if args.probe_json:
        if not args.input_path:
            parser.error("`--probe-json` を使う場合は入力ファイルを指定してください。")
        try:
            print(json.dumps(build_probe_payload(args.input_path), ensure_ascii=False))
            return 0
        except Exception as exc:
            print(f"エラー: {exc}")
            return 1

    if not args.input_path:
        run_interactive_cli()
        return 0

    mode = args.mode or ("quality" if args.quality else "size")

    try:
        if mode == "quality":
            if not args.quality:
                parser.error("`--mode quality` を使う場合は `--quality` を指定してください。")
            compress_video_to_quality(
                args.input_path,
                args.quality,
                remove_audio=args.no_audio,
            )
            return 0

        target_size = args.target_size
        if target_size is None:
            target_size = args.legacy_target_size or DEFAULT_TARGET_SIZE_MB
        compress_video_to_size(
            args.input_path,
            target_size,
            remove_audio=args.no_audio,
        )
        return 0
    except Exception as exc:
        print(f"エラー: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
