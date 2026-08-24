from pathlib import Path

from agency.capabilities.media import assert_playable, loudness_measure, probe

JOB = Path("data/production/jobs/527c4735ae994bdeaaa827b233c1f1ad")
master = JOB / "master.mp4"

info = probe(master)
print(
    f"MASTER: {info.container.split(',')[0].upper()} | {info.video_codec}/{info.audio_codec} | "
    f"{info.width}x{info.height}@{info.fps}fps | {info.duration_s:.2f}s | stereo={info.channels == 2} | "
    f"{master.stat().st_size // 1024} KB"
)

loud = loudness_measure(master)
print(f"LOUDNESS: {loud['input_i']:.1f} LUFS | true peak {loud['input_tp']:.2f} dBTP")

assert_playable(master)
print("DECODE: PASS - fully playable")

for extra in ["deliverables/variant_square.mp4", "deliverables/thumbnail.png", "captions.srt", "deliverables/metadata.json"]:
    p = JOB / extra
    print(f"{'OK ' if p.exists() else 'MISSING'} {extra}" + (f" ({p.stat().st_size // 1024} KB)" if p.exists() else ""))
