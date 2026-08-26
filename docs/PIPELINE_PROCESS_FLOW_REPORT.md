# Autonomous AI Video Agency — ব্যাকএন্ড প্রসেস ফ্লো রিপোর্ট

## একটি প্রম্পট দিলে কী কী হয়? — পুরো ট্র্যাকিং

---

## সারসংক্ষেপ

```
ইউজার প্রম্পট (ব্রিফ)
       │
       ▼
  ┌─ API Layer ──────────────────────────────────────┐
  │  POST /v1/projects  →  POST /v1/projects/{id}/jobs │
  │  POST /v1/jobs/{id}/run (inline execution)          │
  └──────────────────────────────────────────────────┘
       │
       ▼
  ┌─ WorkflowEngine.execute_job() ────────────────────┐
  │  20টি স্টেজ ক্রমানুসারে চলে                           │
  │  প্রতিটি স্টেজের আউটপুট পরের স্টেজের ইনপুট হয়          │
  └──────────────────────────────────────────────────┘
       │
       ▼
  Final Video (.mp4) + Thumbnail + Metadata
```

---

## ধাপ ০: প্রম্পট / ব্রিফ তৈরি

ইউজার একটি JSON ব্রিফ পাঠায়:

```json
{
  "name": "Astra AI Launch",
  "brief": {
    "title": "Astra AI Platform Launch",
    "objective": "Convince CTOs that Astra cuts deployment from weeks to hours",
    "audience": "CTOs and ML leaders",
    "platform": "youtube",
    "duration_s": 28,
    "cta": "Start your pilot today",
    "language": "en",
    "key_points": [
      "Governed pipelines deploy in hours",
      "Real-time monitoring catches drift",
      "Enterprise SSO built-in"
    ]
  }
}
```

**API Endpoint:** `POST /v1/projects` → Project ID তৈরি হয়  
**তারপর:** `POST /v1/projects/{id}/jobs` → Job ID তৈরি হয় (state: `queued`)  
**তারপর:** `POST /v1/jobs/{id}/run` → ব্যাকএন্ডে সিঙ্ক্রোনাসভাবে এক্সিকিউট শুরু হয়

---

## ধাপ ১: WorkflowEngine — পুরো পাইপলাইন চালায়

**ফাইল:** `agency/workflow/engine.py:170`

```
WorkflowEngine.__init__(handlers=HANDLERS, max_task_retries=3, repair_budget=2)
```

এন্জিন একটি `plan` তৈরি করে — 20টি `(stage_name, agent_name)` টুপল:

```python
plan = PRODUCTION_STAGES  # 20টি স্টেজ
context = {"payload": job.payload, "artifacts": {}, "state": {}}

for seq, (name, agent) in enumerate(plan):
    task = _run_single_task(db, job, name, agent, seq, context)
    if task.state == "failed":
        repaired = _attempt_repair(db, job, task, context)
        if not repaired:
            _fail_job(db, job)
            return
    seq += 1
_complete_job(db, job, context)
```

**প্রতিটি স্টেজে:**
- `Task` row created (state: `running`)
- Handler function কল হয়
- Output dict context["state"]-তে merge হয় (শুধুমাত্র `ctx_*` prefix কীগুলো)
- Task state → `done` বা `failed`
- সময় ও error logging হয়

---

## ২০টি স্টেজ — বিস্তারিত প্রতিটির কাজ

### স্টেজ ১: `intake` — Intake Agent
**ফাইল:** `agency/agents/stages.py:102`  
**সময়:** ~0ms | **ফলাফল:** ব্রিফ ভ্যালিডেটেড হয়

```
ইনপুট:  brief.json
প্রক্রিয়া:
  1. প্রয়োজনীয় ফিল্ড চেক (title, objective)
  2. platform অনুযায়ী resolution/fps সেট:
     - youtube → 1920×1080 @30fps
     - tiktok/instagram_reels → 1080×1920 @30fps (9:16)
     - instagram_feed → 1080×1080 @30fps (1:1)
  3. duration, width, height limits চেক
  4. width/height even কিনা (H.264 requirement)
  5. Project.status → "in_production"
আউটপুট: ctx_spec = {title, objective, platform, resolution, duration_s, language, ...}
```

### স্টেজ ২: `research` — Research Agent
**ফাইল:** `agency/agents/stages.py:149`  
**সময়:** ~0ms | **ফলাফল:** কী পয়েন্ট + ক্লেইম ট্র্যাকিং

```
ইনপুট:  ctx_spec
প্রক্রিয়া:
  1. key_points থেকে research points বানায়
  2. যদি key_points না থাকে → objective থেকে keywords বের করে
  3. প্রতিটি point-কে claims হিসেবে ট্যাগ করে:
     - সংখ্যা থাকলে → "needs_verification"
     - না থাকলে → "unverified_general"
আউটপুট: ctx_research = {points: [...], claims: [...], sources_required_for_claims: bool}
```

### স্টেজ ৩: `creative_direction` — Creative Director
**ফাইল:** `agency/agents/stages.py:184`  
**সময়:** ~0ms | **ফলাফল:** ক্রিয়েটিভ কনসেপ্ট + প্যালেট

```
ইনপুট:  ctx_spec
প্রক্রিয়া:
  1. brand palette থেকে hex রঙ বের করে
  2. audience অনুযায়ী music mood সিলেক্ট:
     - "enterprise/professional/finance" → calm
     - "alert" → tense
     - অন্য → uplifting
  3. default palette: #101820, #1F6FEB, #F2F7FA (কালো-নীল-সাদা)
আউটপুট: ctx_creative = {concept, tone, palette_hex, music_mood}
```

### স্টেজ ৪: `script_writing` — Script Agent
**ফাইল:** `agency/agents/stages.py:311`  
**সময়:** 0ms–2s | **ফলাফল:** ন্যারেশন স্ক্রিপ্ট

```
ইনপুট:  ctx_spec + ctx_research
প্রক্রিয়া:
  1. LLM চেষ্টা করে (OpenAI available থাকলে):
     - prompt পাঠায়: title, objective, audience, key_points
     - JSON response আশা করে: {hook, beats[], cta}
  2. LLM না থাকলে → template-composer ব্যবহার করে:
     - Hook: "If you work with {audience}, this changes everything: {title}."
     - Beats: key_points থেকে 2-3টি
     - CTA: "Ready? {cta}."
  3. Word budget enforce করে:
     - budget = duration_s × 2.0 words (min 14)
     - beats trim করে যদি বাজেট বেশি হয়
  4. ScriptVersion DB row create করে
আউটপুট: ctx_script = {sections: {hook, beats, cta}, full_text, generator}
```

### স্টেজ ৫: `storyboard` — Storyboard Agent
**ফাইল:** `agency/agents/stages.py:325`  
**সময়:** ~0ms | **ফলাফল:** সিন-ভিত্তিক টাইমিং

```
ইনপুট:  ctx_spec + ctx_script
প্রক্রিয়া:
  1. Script-এর প্রতিটি section (hook, beat1, beat2, cta) একটি scene
  2. Word count-এর উপর ভিত্তি করে duration ওয়েট করে:
     - numpy array: weights = [word_count_per_scene]
     - durations = (weights / total) × total_duration
     - minimum 1.6s per scene
  3. Storyboard DB row create করে
আউটপুট: ctx_scenes = [{id, title, narration, duration_s, style_seed}, ...]
```

### স্টেজ ৬: `asset_acquisition` — Asset Acquisition Agent
**ফাইল:** `agency/agents/stages.py:350`  
**সময়:** ~1-2s | **ফলাফল:** প্রতিটি সিনের ইমেজ

```
ইনপুট:  ctx_spec + ctx_scenes + palette
প্রক্রিয়া:
  1. প্রতিটি scene এর জন্য Pillow (PIL) দিয়ে procedural image তৈরি:
     - render_scene_image() → gradient background + title text
     - palette-অনুযায়ী রঙ
     - scene style_seed অনুযায়ী variation
  2. External assets চেক (যদি payload-তে থাকে):
     - license_state: owned/licensed/cc0/generated → ব্যবহারযোগ্য
     - অন্য → rejected (unknown rights কখনো commercial-safe না)
  3. প্রতিটি image কে Artifact হিসেবে register করে
আউটপুট: ctx_images = [path/to/scene_01.png, ...]
```

### স্টেজ ৭: `narration` — Voice/TTS Agent
**ফাইল:** `agency/agents/stages.py:479`  
**সময়:** 2-10s | **ফলাফল:** ন্যারেশন অডিও + ওয়ার্ড টাইমিং

```
ইনপুট:  ctx_spec + ctx_scenes
প্রক্রিয়া:
  1. TTS Provider সিলেক্ট:
     - edge-tts (network) → en-US-AriaNeural / bn-BD-NabanitaNeural / etc.
     - fallback: synth-local (offline deterministic)
  2. Language mapping: spec.language → voice name
     - "en" → en-US-AriaNeural
     - "bn" → bn-BD-NabanitaNeural (Bangla)
     - "hi" → hi-IN-SwaraNeural (Hindi)
  3. প্রতিটি scene এর narration text synthesize করে:
     - provider.synthesize(text, output_path)
     - edge-tts → .mp3 | synth-local → .wav
  4. .mp3 হলে FFmpeg দিয়ে .wav-তে convert
  5. Word-level timing align করে (440Hz text span)
  6. সব WAV segment মার্জ করে gap=0.28s দিয়ে
  7. Peak normalize to 0.88
  8. Cost record: edge-tts/synth = $0, OpenAI = $0.0002/sec
আউটপুট: ctx_narration = {path, duration, words: [{word, start, end}], provider}
```

### স্টেজ ৮: `autocleanup` — Auto-Cleanup Agent
**ফাইল:** `agency/agents/stages.py:497`  
**সময়:** ~1s | **ফলাফল:** নীরবতা মুছে ফেলা অডিও

```
ইনপুট:  ctx_narration
প্রক্রিয়া:
  1. Silence detection: min_silence=0.42s, keep_pad=0.14s
  2. নীরবতা থাকলে cut_segments() দিয়ে কেটে দেয়
  3. Word timings adjust করে
  4. Duration কমে
আউটপুট: ctx_cleanup = {path: narration_clean.wav, duration, words}
```

### স্টেজ ৯: `editorial_assembly` — Editorial Agent
**ফাইল:** `agency/agents/stages.py:523`  
**সময়:** 5-15s | **ফলাফল:** প্রতিটি সিনের ভিডিও ক্লিপ + EDL

```
ইনপুট:  ctx_spec + ctx_scenes + ctx_images + ctx_cleanup
প্রক্রিয়া:
  1. Scale factor ক্যালকুলেট: actual_audio_duration / planned_scene_duration
  2. প্রতিটি scene image থেকে video clip তৈরি:
     - render_image_clip() → FFmpeg:
       ffmpeg -loop 1 -i scene.png -t {dur} -vf "zoompan=z=1.06"
       -c:v libx264 -pix_fmt yuv420p scene_clip.mp4
     - Ken Burns effect (slight zoom)
  3. TimelineEDL তৈরি:
     - Track(type="video") → Clip list
     - Validate: no gaps, no overlaps
  4. Timeline DB row create
আউটপুট: ctx_scene_clips = [clip1.mp4, clip2.mp4, ...]
          ctx_edl = {fps, width, height, tracks: [{clips: [...]}]}
```

### স্টেজ ১০: `motion_graphics` — Motion Graphics Agent
**ফাইল:** `agency/agents/stages.py:571`  
**সময়:** 1-2s | **ফলাফল:** ওভারলে গ্রাফিক্স

```
ইনপুট:  ctx_spec + ctx_scenes + palette
প্রক্রিয়া:
  1. Title Card (Pillow):
     - render_title_card() → gradient + large title + subtitle
     - 0s → min(scene1_duration × 0.55, 3.0s) পর্যন্ত দেখায়
  2. Lower Third (Pillow):
     - render_lower_third() → title + audience text
     - scene_2 offset + 0.4s → +4.5s পর্যন্ত দেখায়
  3. Logo Watermark (যদি BrandKit থাকে):
     - DB থেকে BrandKit লোড
     - logo_key file path check
     - Full duration (0 → total) overlay, scale 8%
আউটপুট: ctx_overlays = [{path, start, end, mode, anchor_x, anchor_y}, ...]
```

### স্টেজ ১১: `rough_concat` — Render Agent
**ফাইল:** `agency/agents/stages.py:612`  
**সময়:** 3-10s | **ফলাফল:** সব ক্লিপ জয়েন করা ভিডিও

```
ইনপুট:  ctx_scene_clips
প্রক্রিয়া:
  1. FFmpeg concat:
     ffmpeg -f concat -safe 0 -i filelist.txt -c copy rough_cut.mp4
  2. Probe verify
আউটপুট: ctx_rough = {path: rough_cut.mp4, duration}
```

### স্টেজ ১২: `audio_mix` — Sound Design Agent
**ফাইল:** `agency/agents/stages.py:626`  
**সময়:** 2-5s | **ফলাফল:** মিক্সড অডিও + লাউডনেস নরমালাইজ

```
ইনপুট:  ctx_cleanup (narration) + ctx_creative (music_mood)
প্রক্রিয়া:
  1. Procedural music bed তৈরি:
     - generate_music_bed() → নীরবতা-ভিত্তিক wave synthesis
     - mood → frequency profile (calm=low freq, tense=high freq)
  2. Mix: narration (1.0) + music (0.22 weight)
     - FFmpeg amix
  3. Loudness normalize:
     - FFmpeg loudnorm → target -14 LUFS (configurable)
আউটপুট: ctx_audio = {path: audio_final.m4a, duration, loudness_before}
```

### স্টেজ ১৩: `av_mux` — Render Agent
**ফাইল:** `agency/agents/stages.py:646`  
**সময়:** 2-5s | **ফলাফল:** ভিডিও + অডিও একসাথে

```
ইনপুট:  ctx_rough (video) + ctx_audio (audio)
প্রক্রিয়া:
  1. FFmpeg mux:
     ffmpeg -i rough.mp4 -i audio.m4a -c:v copy -c:a aac av_no_captions.mp4
  2. A/V sync check:
     - video duration vs audio duration drift > 1.5s → FAIL
আউটপুট: ctx_av = {path: av_no_captions.mp4, duration}
```

### স্টেজ ১৪: `burn_captions` — Caption Agent
**ফাইল:** `agency/agents/stages.py:665`  
**সময়:** 2-5s | **ফলাফল:** সাবটাইটেল বার্নড ভিডিও

```
ইনপুট:  ctx_spec + ctx_cleanup + ctx_av
প্রক্রিয়া:
  1. ASS subtitle file generate:
     - build_ass() → styled subtitles (font, size, safe zone)
     - Resolution-aware positioning
  2. SRT subtitle file generate:
     - build_srt() → standard format
  3. FFmpeg burn subtitles:
     ffmpeg -i av.mp4 -vf "ass=captions.ass" captioned.mp4
আউটপুট: ctx_captioned = {path: captioned.mp4}
          ctx_caption_files = {ass, srt}
```

### স্টেজ ১৫: `color_grade` — Color Agent
**ফাইল:** `agency/agents/stages.py:685`  
**সময়:** 3-8s | **ফলাফল:** রঙ সম্পাদনা করা master

```
ইনপুট:  ctx_captioned
প্রক্রিয়া:
  1. FFmpeg color grading:
     - saturation=1.05 (5% more vibrant)
     - contrast=1.03 (slight pop)
     - colormatrix + eq filter
আউটপুট: ctx_master = {path: master.mp4, duration, width, height}
```

---

## ৩-স্তর QA (Quality Assurance) — স্টেজ ১৬-১৮

### স্টেজ ১৬: `technical_qa` — Technical QA Agent
**ফাইল:** `agency/agents/stages.py:706`

```
ইনপুট:  ctx_spec + ctx_master
10টি অটোমেটিক চেক:
  ✅ Container → mp4 family
  ✅ Video codec → H.264
  ✅ Audio codec → AAC
  ✅ Resolution → matches spec (e.g., 1920×1080)
  ✅ FPS → matches spec (±0.6 tolerance)
  ✅ Duration → within 65%-145% of target
  ✅ Audio channels → stereo (2ch)
  ✅ Playable → full decode test
  ✅ Loudness → within ±3 LUFS of target (-14)
  ✅ True peak → ≤ -0.3 dBTP
→ সব pass না হলে TaskFailure (repair এর জন্য failure_class সহ)
```

### স্টেজ ১৭: `creative_qa` — Creative QA Agent
**ফাইল:** `agency/agents/stages.py:752`

```
ইনপুট:  ctx_spec + ctx_script + ctx_cleanup + ctx_master
চেক:
  ✅ CTA narration-এ আছে কিনা (50%+ token match)
  ✅ Hook section narration-এ আছে কিনা (60%+ word match)
  ✅ Palette on-brand (frame extraction → dominant colors → palette distance)
     - 3টি frame (15%, 50%, 85%) extract
     - avg palette distance > 160 → FAIL
  ✅ Caption validation (words exist, CPS readable)
```

### স্টেজ ১৮: `multimodal_qa` — Multimodal QA Agent
**ফাইল:** `agency/agents/stages.py:829`

```
ইনপুট:  ctx_spec + ctx_scenes + ctx_master + ctx_script
চেক:
  ✅ Brief→Script concept coverage (45%+ keywords matched for 15s+ video)
  ✅ Scene count matches (storyboard = rendered clips)
  ✅ Aspect ratio matches spec
  ✅ Duration drift ≤ 35% from target
→ সব pass না হলে TaskFailure
```

---

## ধাপ ১৯: `delivery` — Publishing Agent
**ফাইল:** `agency/agents/stages.py:866`

```
ইনপুট:  ctx_spec + ctx_master
প্রক্রিয়া:
  1. যদি approval_required → awaiting_approval state (থামে)
  2. Thumbnail তৈরি:
     - Frame extract (1.5s)
     - render_thumbnail() → title text overlay
  3. Square variant (1:1):
     - FFmpeg: scale+crop → 1080×1080
  4. Deliverable DB rows:
     - master variant → Deliverable(platform="youtube:master")
     - square variant → Deliverable(platform="youtube:square_1x1")
  5. metadata.json write
আউটপুট: ctx_deliverables_list = [{kind, path, duration_s}, ...]
```

## ধাপ ২০: `finalize` — FinOps Agent
**ফাইল:** `agency/agents/stages.py:925`

```
ইনপুট:  all context
প্রক্রিয়া:
  1. CostEntry query → total cost calculate
  2. Budget cap check → emit warning if exceeded
  3. Project.status → "delivered"
  4. Event emit: production.finalized
আউটপুট: total_cost_usd, deliverable_count
```

---

## Repair System (স্বয়ংক্রিয় মেরামত)

```
Task Failed
    │
    ▼
_attempt_repair()
    │
    ├─ Retryable failure class? (transient, render_crash, ffmpeg_error)
    │   └─ Yes → retry_stage (exponential backoff: 0.1s, 0.2s, 0.4s)
    │
    ├─ Repair budget available? (max 2)
    │   └─ Yes → pipeline_repair (reset from seq 0, delete stale tasks)
    │
    └─ Neither → escalate_human (job state → failed)
```

**failure_class categories:**
- `invalid_brief` — brief validation error (no repair)
- `state_missing` — previous stage output missing (no repair)
- `ffmpeg_error` — FFmpeg crash (retryable)
- `render_crash` — render failure (retryable)
- `transient` — network/timeout (retryable)
- `corrupt_media` — decode failure (retryable × 1)
- `qa_sync` — A/V sync drift (pipeline repair)
- `qa_creative` — creative QA fail (pipeline repair)
- `qa_multimodal` — multimodal QA fail (pipeline repair)

---

## FFmpeg Commands যেগুলো চলে

```bash
# Scene clip (Ken Burns zoom)
ffmpeg -loop 1 -i scene.png -t {dur} -vf "zoompan=z='min(zoom+0.0015,1.06)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={dur*fps}" -c:v libx264 -pix_fmt yuv420p clip.mp4

# Concat
ffmpeg -f concat -safe 0 -i list.txt -c copy rough.mp4

# Audio mix
ffmpeg -i narration.wav -i music.wav -filter_complex "amix=inputs=2:weights=1.0 0.22" -t {dur} mixed.m4a

# Loudness normalize
ffmpeg -i mixed.m4a -af "loudnorm=I=-14:TP=-1:LRA=11" final.m4a

# Mux A/V
ffmpeg -i video.mp4 -i audio.m4a -c:v copy -c:a aac merged.mp4

# Burn subtitles
ffmpeg -i merged.mp4 -vf "ass=captions.ass" captioned.mp4

# Color grade
ffmpeg -i captioned.mp4 -vf "colormatrix=..." -c:v libx264 graded.mp4

# Square variant
ffmpeg -i master.mp4 -vf "scale=1080:1080:force_original_aspect_ratio=increase,crop=1080:1080" -c:v libx264 square.mp4
```

---

## DB Models যেগুলো Create/Update হয়

| Stage | Table | Operation |
|-------|-------|-----------|
| intake | Project | UPDATE (spec, status) |
| script_writing | ScriptVersion | INSERT |
| storyboard | Storyboard | INSERT |
| asset_acquisition | Artifact | INSERT (per image) |
| narration | Artifact | INSERT + CostEntry |
| autocleanup | Artifact | INSERT |
| editorial_assembly | Timeline | INSERT |
| audio_mix | Artifact + CostEntry | INSERT |
| technical_qa | QAReport | INSERT |
| creative_qa | QAReport | INSERT |
| multimodal_qa | QAReport | INSERT |
| delivery | Deliverable | INSERT (master + square) |
| finalize | Project | UPDATE (status=delivered) |

---

## সম্পূর্ণ সময়কাল (28s YouTube video)

```
Stage 1-6 (Preparation):     ~2-3s    (brief → images)
Stage 7 (TTS):               2-10s    (narration synthesis)
Stage 8 (Cleanup):           ~1s      (silence removal)
Stage 9 (Assembly):          5-15s    (scene clips)
Stage 10 (Graphics):         ~1-2s    (overlays)
Stage 11 (Concat):           3-10s    (join clips)
Stage 12 (Audio Mix):        2-5s     (music + normalize)
Stage 13 (Mux):              2-5s     (A/V merge)
Stage 14 (Captions):         2-5s     (subtitle burn)
Stage 15 (Color):            3-8s     (grading)
Stage 16-18 (QA):            ~2s      (3-layer verify)
Stage 19 (Delivery):         2-3s     (thumbnail + variants)
Stage 20 (Finalize):         ~0s      (costing + status)
───────────────────────────────────────
Total estimated:             25-70s (no GPU, SQLite, FFmpeg 9.0)
```

---

## Context Flow Diagram

```
ctx_spec ──────────────────────┐
ctx_research ──────────────────┤
ctx_creative ──────────────────┤
ctx_palette ───────────────────┤
ctx_script ────────────────────┤
ctx_scenes ────────────────────┤
ctx_images ────────────────────┤
ctx_narration ─────────────────┤
ctx_cleanup ───────────────────┤  ← context["state"] dict
ctx_scene_clips ───────────────┤     সব key ctx_* prefix এ
ctx_edl ───────────────────────┤     পরের স্টেজ আগের থেকে পড়ে
ctx_overlays ──────────────────┤
ctx_rough ─────────────────────┤
ctx_audio ─────────────────────┤
ctx_av ────────────────────────┤
ctx_captioned ─────────────────┤
ctx_caption_files ─────────────┤
ctx_master ────────────────────┤
qa_summary ────────────────────┤
ctx_deliverables_list ─────────┘
```

---

*রিপোর্ট তৈরি: 2026-08-26 | Tag: v1.2.0 | 20 স্টেজ | 3-স্তর QA | FFmpeg 9.0 | SQLite WAL*
