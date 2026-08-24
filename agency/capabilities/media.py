from __future__ import annotations

import json
import logging
import math
import os
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger("agency.media")

_FFMPEG_CANDIDATE_DIRS = [
    str(Path.home() / "AppData" / "Local" / "Microsoft" / "WinGet" / "Links"),
    r"C:\ffmpeg\bin",
    r"C:\Program Files\ffmpeg\bin",
    "/usr/local/bin",
    "/usr/bin",
]


def find_executable(name: str) -> str:
    found = shutil.which(name)
    if found:
        return found
    for directory in _FFMPEG_CANDIDATE_DIRS:
        for candidate in (Path(directory) / f"{name}.exe", Path(directory) / name):
            if candidate.exists():
                return str(candidate)
    winget_packages = Path.home() / "AppData" / "Local" / "Microsoft" / "WinGet" / "Packages"
    if winget_packages.exists():
        matches = sorted(winget_packages.rglob(f"{name}.exe"))
        if matches:
            return str(matches[0])
    return name


FFMPEG_BIN = find_executable("ffmpeg")
FFPROBE_BIN = find_executable("ffprobe")


class MediaError(RuntimeError):
    pass


@dataclass
class ProbeResult:
    duration_s: float
    width: int | None
    height: int | None
    fps: float | None
    video_codec: str | None
    audio_codec: str | None
    sample_rate: int | None
    channels: int | None
    bitrate: int | None
    container: str
    has_audio: bool
    has_video: bool
    raw: dict = field(default_factory=dict)


def run_ffmpeg(args: list[str], timeout: int = 900) -> subprocess.CompletedProcess:
    cmd = [FFMPEG_BIN, "-hide_banner", "-loglevel", "error", "-y", *args]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, shell=False)
    except FileNotFoundError as exc:
        raise MediaError("ffmpeg executable not found on PATH") from exc
    except subprocess.TimeoutExpired as exc:
        raise MediaError(f"ffmpeg timed out after {timeout}s") from exc
    if proc.returncode != 0:
        raise MediaError(f"ffmpeg failed ({proc.returncode}): {proc.stderr[-2000:]}")
    return proc


def run_ffprobe(args: list[str], timeout: int = 120) -> dict:
    cmd = [FFPROBE_BIN, "-hide_banner", "-loglevel", "error", *args]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, shell=False)
    except FileNotFoundError as exc:
        raise MediaError("ffprobe executable not found") from exc
    if proc.returncode != 0:
        raise MediaError(f"ffprobe failed: {proc.stderr[-1000:]}")
    return json.loads(proc.stdout)


def probe(path: Path | str) -> ProbeResult:
    data = run_ffprobe(["-print_format", "json", "-show_format", "-show_streams", str(path)])
    fmt = data.get("format", {})
    streams = data.get("streams", [])
    vstream = next((s for s in streams if s.get("codec_type") == "video"), None)
    astream = next((s for s in streams if s.get("codec_type") == "audio"), None)
    fps = None
    if vstream and vstream.get("avg_frame_rate") not in (None, "0/0"):
        num, den = vstream["avg_frame_rate"].split("/")
        fps = round(float(num) / float(den), 3) if float(den) != 0 else None
    return ProbeResult(
        duration_s=float(fmt.get("duration", 0.0)),
        width=int(vstream["width"]) if vstream else None,
        height=int(vstream["height"]) if vstream else None,
        fps=fps,
        video_codec=vstream.get("codec_name") if vstream else None,
        audio_codec=astream.get("codec_name") if astream else None,
        sample_rate=int(astream["sample_rate"]) if astream and astream.get("sample_rate") else None,
        channels=int(astream["channels"]) if astream and astream.get("channels") else None,
        bitrate=int(fmt.get("bit_rate", 0)) or None,
        container=fmt.get("format_name", ""),
        has_audio=astream is not None,
        has_video=vstream is not None,
        raw=data,
    )


def assert_playable(path: Path | str, timeout: int = 600) -> bool:
    proc = subprocess.run(
        [FFMPEG_BIN, "-hide_banner", "-v", "error", "-i", str(path), "-f", "null", "-"],
        capture_output=True,
        text=True,
        timeout=timeout,
        shell=False,
    )
    fatal_lines = [ln for ln in proc.stderr.splitlines() if ln.startswith("Error") or ln.startswith("Invalid")]
    if proc.returncode != 0 or fatal_lines:
        raise MediaError(f"decode check failed: {proc.stderr[-500:]}")
    return True


def normalize_video(src: Path, dst: Path, width: int, height: int, fps: float) -> Path:
    run_ffmpeg([
        "-i", str(src),
        "-vf", f"scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,fps={fps},setdar={(width / height):.4f}",
        "-c:v", "libx264", "-preset", "medium", "-crf", "20",
        "-an",
        str(dst),
    ])
    return dst


def extract_audio(src: Path, dst: Path, sample_rate: int = 48000, channels: int | None = None) -> Path:
    args = ["-i", str(src), "-vn", "-ar", str(sample_rate)]
    if channels is not None:
        args += ["-ac", str(channels)]
    args += ["-c:a", "pcm_s16le", str(dst)]
    run_ffmpeg(args)
    return dst


def loudness_measure(path: Path) -> dict:
    proc = subprocess.run(
        [FFMPEG_BIN, "-hide_banner", "-nostats", "-i", str(path), "-af", "loudnorm=print_format=json", "-f", "null", "-"],
        capture_output=True,
        text=True,
        timeout=300,
        shell=False,
    )
    start = proc.stderr.rfind("{")
    end = proc.stderr.rfind("}")
    if start == -1 or end == -1:
        raise MediaError("loudness analysis produced no json")
    stats = json.loads(proc.stderr[start : end + 1])
    return {
        "input_i": float(stats["input_i"]),
        "input_tp": float(stats["input_tp"]),
        "input_lra": float(stats.get("input_lra", 0.0)),
        "input_thresh": float(stats.get("input_thresh", -70.0)),
    }


def loudness_normalize(src: Path, dst: Path, target_lufs: float = -16.0, true_peak: float = -1.5) -> dict:
    first = loudness_measure(src)
    args = [
        "-i", str(src),
        "-af",
        (
            f"loudnorm=I={target_lufs}:TP={true_peak}:LRA=11:"
            f"measured_I={first['input_i']}:measured_TP={first['input_tp']}:"
            f"measured_LRA={first['input_lra']}:measured_thresh={first['input_thresh']}:linear=true"
        ),
        "-ar", "48000", "-ac", "2", "-c:a", "aac", "-b:a", "192k",
        str(dst),
    ]
    run_ffmpeg(args)
    second = loudness_measure(dst)
    if abs(second["input_i"] - target_lufs) > 1.5:
        run_ffmpeg([
            "-i", str(dst),
            "-af", f"volume={target_lufs - second['input_i']:.2f}dB,alimiter=limit=0.8913",
            "-ar", "48000", "-ac", "2", "-c:a", "aac", "-b:a", "192k",
            str(dst) + ".tmp.m4a",
        ])
        os.replace(str(dst) + ".tmp.m4a", str(dst))
        second = loudness_measure(dst)
    return {"before": first, "after": second, "target": target_lufs}


def silence_windows(path: Path, noise_db: float = -35.0, min_dur: float = 0.35) -> list[tuple[float, float]]:
    proc = subprocess.run(
        [
            FFMPEG_BIN, "-hide_banner", "-nostats", "-i", str(path),
            "-af", f"silencedetect=noise={noise_db}dB:d={min_dur}", "-f", "null", "-",
        ],
        capture_output=True,
        text=True,
        timeout=300,
        shell=False,
    )
    starts: list[float] = []
    windows: list[tuple[float, float]] = []
    for line in proc.stderr.splitlines():
        if "silence_start" in line:
            starts.append(float(line.strip().rsplit(":", 1)[-1].split()[0]))
        elif "silence_end" in line and starts:
            end = float(line.strip().rsplit(":", 1)[-1].split()[0])
            windows.append((starts.pop(0), end))
    return windows


def cut_segments(src: Path, dst: Path, keep_ranges: list[tuple[float, float]], has_audio: bool | None = None) -> Path:
    n = len(keep_ranges)
    if n == 0:
        raise MediaError("no segments to keep")
    info = probe(src)
    use_video = info.has_video
    use_audio = info.has_audio if has_audio is None else (has_audio and info.has_audio)

    inputs: list[str] = []
    for start, end in keep_ranges:
        inputs += ["-ss", f"{start:.3f}", "-t", f"{max(end - start, 0.05):.3f}", "-i", str(src)]

    if use_video and use_audio:
        streams = "".join(f"[{i}:v][{i}:a]" for i in range(n))
        fc = f"{streams}concat=n={n}:v=1:a=1[vout][aout]"
        maps = ["-map", "[vout]", "-map", "[aout]"]
        codecs = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-c:a", "aac"]
    elif use_video:
        streams = "".join(f"[{i}:v]" for i in range(n))
        fc = f"{streams}concat=n={n}:v=1:a=0[vout]"
        maps = ["-map", "[vout]"]
        codecs = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20"]
    else:
        streams = "".join(f"[{i}:a]" for i in range(n))
        fc = f"{streams}concat=n={n}:v=0:a=1[aout]"
        maps = ["-map", "[aout]"]
        codecs = ["-c:a", "pcm_s16le"] if dst.suffix.lower() == ".wav" else ["-c:a", "aac"]

    run_ffmpeg([*inputs, "-filter_complex", fc, *maps, *codecs, str(dst)])
    return dst


def scene_detect(path: Path, threshold: float = 0.4) -> list[float]:
    proc = subprocess.run(
        [
            FFMPEG_BIN, "-hide_banner", "-nostats", "-i", str(path),
            "-vf", f"select='gt(scene,{threshold})',metadata=print", "-an", "-f", "null", "-",
        ],
        capture_output=True,
        text=True,
        timeout=600,
        shell=False,
    )
    times: list[float] = []
    for line in proc.stderr.splitlines():
        if "pts_time:" in line:
            t = line.split("pts_time:")[-1].strip().split()[0]
            times.append(float(t))
    return times


def make_thumbnail(video: Path, dst: Path, at_s: float = 1.0, width: int = 640) -> Path:
    run_ffmpeg(["-ss", f"{at_s:.3f}", "-i", str(video), "-frames:v", "1", "-vf", f"scale={width}:-2", str(dst)])
    return dst


def audio_peaks(path: Path) -> dict:
    proc = subprocess.run(
        [FFMPEG_BIN, "-hide_banner", "-nostats", "-i", str(path), "-af", "astats=metadata=0:measure_overall=Peak_level+RMS_level:measure_perchannel=None", "-f", "null", "-"],
        capture_output=True,
        text=True,
        timeout=300,
        shell=False,
    )
    peak = rms = None
    for line in proc.stderr.splitlines():
        if "Peak level dB" in line:
            val = line.rsplit(":", 1)[-1].strip()
            if not math.isinf(float(val)):
                peak = float(val)
        elif "RMS level dB" in line:
            val = line.rsplit(":", 1)[-1].strip()
            if not math.isinf(float(val)):
                rms = float(val)
    return {"peak_dbfs": peak, "rms_dbfs": rms, "clipping": (peak is not None and peak > -0.1)}


def mux_av(video: Path, audio: Path, dst: Path, shortest: bool = True) -> Path:
    args = ["-i", str(video), "-i", str(audio), "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k"]
    if shortest:
        args.append("-shortest")
    args += ["-movflags", "+faststart", str(dst)]
    run_ffmpeg(args)
    return dst


def burn_subtitles(video: Path, ass_path: Path, dst: Path) -> Path:
    ass_escaped = str(ass_path).replace("\\", "/").replace(":", "\\:")
    run_ffmpeg([
        "-i", str(video),
        "-vf", f"ass='{ass_escaped}'",
        "-c:v", "libx264", "-preset", "medium", "-crf", "20",
        "-c:a", "copy", "-movflags", "+faststart",
        str(dst),
    ])
    return dst


def color_grade(src: Path, dst: Path, saturation: float = 1.06, contrast: float = 1.04, brightness: float = 0.0, gamma: float = 1.0) -> Path:
    vf = f"eq=saturation={saturation}:contrast={contrast}:brightness={brightness}:gamma={gamma}"
    run_ffmpeg(["-i", str(src), "-vf", vf, "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-c:a", "copy", str(dst)])
    return dst


def render_image_clip(
    image: Path,
    dst: Path,
    duration: float,
    width: int,
    height: int,
    fps: float,
    zoom: float = 1.08,
) -> Path:
    frames = max(int(round(duration * fps)), 1)
    vf = (
        f"scale={int(width * zoom)}:-2,"
        f"zoompan=z='min(zoom+0.0006,{zoom})':d={frames}:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s={width}x{height},"
        f"fps={fps}"
    )
    run_ffmpeg([
        "-loop", "1", "-i", str(image),
        "-vf", vf,
        "-t", f"{duration:.3f}",
        "-r", str(int(fps)),
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
        str(dst),
    ])
    return dst


def concat_videos(clips: list[Path], dst: Path) -> Path:
    if not clips:
        raise MediaError("no clips to concatenate")
    if len(clips) == 1:
        shutil.copyfile(clips[0], dst)
        return dst
    listing = clips[0].parent / "concat_list.txt"
    with open(listing, "w", encoding="utf-8") as fh:
        for clip in clips:
            fh.write(f"file '{str(clip.resolve()).replace(chr(39), chr(39) * 2)}'\n")
    try:
        run_ffmpeg(["-f", "concat", "-safe", "0", "-i", str(listing), "-c", "copy", str(dst)])
    except MediaError:
        inputs: list[str] = []
        for c in clips:
            inputs += ["-i", str(c)]
        fc = "".join(f"[{i}:v]" for i in range(len(clips))) + f"concat=n={len(clips)}:v=1:a=0[outv]"
        run_ffmpeg([*inputs, "-filter_complex", fc, "-map", "[outv]", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-an", str(dst)])
    finally:
        listing.unlink(missing_ok=True)
    return dst


def mix_audio(streams: list[Path], weights: list[float], dst: Path, duck_under_index: int | None = None, total_duration: float | None = None) -> Path:
    if not streams:
        raise MediaError("no audio streams to mix")
    inputs: list[str] = []
    for s in streams:
        inputs += ["-i", str(s)]
    parts = []
    for i, w in enumerate(weights):
        parts.append(f"[{i}:a]volume={w}[a{i}]")
    amix_inputs = "".join(f"[a{i}]" for i in range(len(streams)))
    fc = ";".join(parts) + f";{amix_inputs}amix=inputs={len(streams)}:normalize=0[mixed]"
    if total_duration is not None:
        fc += f";[mixed]apad=whole_dur={total_duration:.3f}[out]"
        out_label = "[out]"
    else:
        out_label = "[mixed]"
    args = [*inputs, "-filter_complex", fc, "-map", out_label, "-ar", "48000", "-ac", "2", "-c:a", "aac", "-b:a", "192k"]
    if total_duration is not None:
        args += ["-t", f"{total_duration:.3f}"]
    args.append(str(dst))
    run_ffmpeg(args)
    return dst

