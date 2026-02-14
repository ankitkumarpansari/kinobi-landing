"""Generate teaser video with animated 木 prompt icon + keyboard sounds."""

from PIL import Image, ImageDraw, ImageFont
import os
import subprocess
import tempfile
import shutil
import math
import struct
import wave

# ── Config ──
W, H = 3840, 2160  # 4K 16:9
PAD_X = 112
PAD_Y = 80
TITLE_BAR_H = 96
BG = (13, 13, 15)
TITLE_BG = (30, 30, 34)
FG = (230, 230, 230)
WHITE = (255, 255, 255)
DIM = (120, 120, 130)
PRIMARY = (251, 113, 133)   # #fb7185
GREEN = (52, 211, 153)
BLUE = (96, 165, 250)
YELLOW = (250, 204, 21)
CYAN = (103, 232, 249)
PROMPT_COLOR = PRIMARY
COMMENT_COLOR = (180, 180, 195)
CMD_COLOR = PRIMARY
ARG_COLOR = (200, 200, 210)
CURSOR_COLOR = PRIMARY
BAR_BG = (40, 40, 48)
BAR_FG = PRIMARY

# 木 color cycle for spinner
CYCLE_COLORS = [PRIMARY, GREEN, CYAN, YELLOW]

LINE_H = 92
FONT_SIZE = 64
FPS = 24
BLINK_INTERVAL = 12
SCROLL_SPEED = 0.15

PROMPT_ICON = "木"

# ── Audio config ──
SAMPLE_RATE = 44100
CLICK_DURATION = 0.018   # 18ms click
CLICK_FREQ = 1800        # Hz — crisp mechanical sound
CLICK_VOLUME = 0.15      # 0..1
keystroke_frames = []     # track which frames have keystrokes


# ── Font ──
FONT_PATHS = [
    "/usr/local/share/fonts/JetBrainsMono-Regular.ttf",
    "/System/Library/Fonts/Menlo.ttc",
    "/System/Library/Fonts/SFMono-Regular.otf",
    "/Library/Fonts/SF-Mono-Regular.otf",
]

font = None
for fp in FONT_PATHS:
    try:
        font = ImageFont.truetype(fp, FONT_SIZE)
        break
    except (OSError, IOError):
        continue
if font is None:
    font = ImageFont.load_default()

# CJK font for 木 character
CJK_FONT_PATHS = [
    "/System/Library/Fonts/ヒラギノ角ゴシック W8.ttc",
    "/System/Library/Fonts/Hiragino Sans GB.ttc",
    "/System/Library/Fonts/STHeiti Medium.ttc",
]
cjk_font = None
for fp in CJK_FONT_PATHS:
    try:
        cjk_font = ImageFont.truetype(fp, FONT_SIZE)
        break
    except (OSError, IOError):
        continue
if cjk_font is None:
    cjk_font = font

bbox = font.getbbox("M")
CHAR_W = bbox[2] - bbox[0]

small_font = None
for fp in FONT_PATHS:
    try:
        small_font = ImageFont.truetype(fp, FONT_SIZE - 16)
        break
    except (OSError, IOError):
        continue
if small_font is None:
    small_font = font


# ── Color helpers ──
def lerp_color(c1, c2, t):
    return tuple(int(a + (b - a) * t) for a, b in zip(c1, c2))


def breath_color(frame_i, speed=0.18):
    """Pulse between dark bg and full rose — more dramatic than v3."""
    dim_rose = (50, 20, 25)
    t = (math.sin(frame_i * speed) + 1) / 2
    return lerp_color(dim_rose, PRIMARY, t)


# ── Audio generation ──
def generate_click():
    """Generate a single mechanical key click as raw samples."""
    n_samples = int(SAMPLE_RATE * CLICK_DURATION)
    samples = []
    for i in range(n_samples):
        t = i / SAMPLE_RATE
        # Sine wave with fast exponential decay
        envelope = math.exp(-t * 200)
        val = math.sin(2 * math.pi * CLICK_FREQ * t) * envelope * CLICK_VOLUME
        # Add a small noise burst at the start for realism
        if i < int(SAMPLE_RATE * 0.003):
            noise = (((i * 1103515245 + 12345) >> 16) & 0x7FFF) / 32768.0 - 0.5
            val += noise * 0.08 * envelope
        samples.append(val)
    return samples


def generate_audio(total_frames, keystroke_frames, output_path):
    """Generate a WAV file with clicks at keystroke timestamps."""
    total_seconds = total_frames / FPS
    total_samples = int(total_seconds * SAMPLE_RATE)
    audio = [0.0] * total_samples
    click = generate_click()

    for frame_num in keystroke_frames:
        sample_pos = int((frame_num / FPS) * SAMPLE_RATE)
        for i, val in enumerate(click):
            idx = sample_pos + i
            if idx < total_samples:
                audio[idx] += val

    # Clamp and write WAV
    with wave.open(output_path, 'w') as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(SAMPLE_RATE)
        for sample in audio:
            clamped = max(-1.0, min(1.0, sample))
            wf.writeframes(struct.pack('<h', int(clamped * 32767)))


# ── Scrolling viewport ──
scroll_y = 0.0


def content_bottom(lines):
    return len(lines) * LINE_H


def target_scroll(lines):
    content_h = content_bottom(lines)
    viewport_h = H - TITLE_BAR_H - PAD_Y * 2
    target = max(0, content_h - viewport_h + LINE_H * 2)
    return target


def smooth_scroll(current, target):
    diff = target - current
    if abs(diff) < 1:
        return target
    return current + diff * SCROLL_SPEED


def draw_title_bar(draw):
    draw.rectangle([0, 0, W, TITLE_BAR_H], fill=TITLE_BG)
    dot_y = TITLE_BAR_H // 2
    dot_r = 14
    dot_x_start = 48
    dot_gap = 48
    for i, c in enumerate([(255, 95, 86), (255, 189, 46), (39, 201, 63)]):
        cx = dot_x_start + i * dot_gap
        draw.ellipse([cx - dot_r, dot_y - dot_r, cx + dot_r, dot_y + dot_r], fill=c)


def render_frame(lines, scroll_offset, cursor_parts=None, cursor_visible=True,
                 extra_draw=None, prompt_color_override=None):
    img = Image.new("RGB", (W, H), BG)
    draw = ImageDraw.Draw(img)

    base_y = TITLE_BAR_H + PAD_Y - int(scroll_offset)
    for idx, parts in enumerate(lines):
        y = base_y + idx * LINE_H
        if y < TITLE_BAR_H - LINE_H or y > H:
            continue
        x = PAD_X
        for text, color in parts:
            if prompt_color_override and text == PROMPT_ICON + " ":
                color = prompt_color_override
            if PROMPT_ICON in text:
                draw.text((x, y), text, fill=color, font=cjk_font)
            else:
                draw.text((x, y), text, fill=color, font=font)
            x += len(text) * CHAR_W

    if cursor_visible and cursor_parts is not None:
        cursor_line_idx = len(lines)
        if cursor_parts:
            y = base_y + cursor_line_idx * LINE_H
            if TITLE_BAR_H <= y <= H:
                x = PAD_X
                for text, color in cursor_parts:
                    if prompt_color_override and text == PROMPT_ICON + " ":
                        color = prompt_color_override
                    if PROMPT_ICON in text:
                        draw.text((x, y), text, fill=color, font=cjk_font)
                    else:
                        draw.text((x, y), text, fill=color, font=font)
                    x += len(text) * CHAR_W
                draw.rectangle([x, y + 8, x + CHAR_W - 8, y + LINE_H - 16],
                               fill=CURSOR_COLOR)
        else:
            y = base_y + len(lines) * LINE_H
            if TITLE_BAR_H <= y <= H:
                x = PAD_X
                draw.rectangle([x, y + 8, x + CHAR_W - 8, y + LINE_H - 16],
                               fill=CURSOR_COLOR)

    if extra_draw:
        extra_draw(draw, base_y, len(lines))

    draw.rectangle([0, 0, W, TITLE_BAR_H], fill=TITLE_BG)
    draw_title_bar(draw)

    return img


# ── Frame helpers ──
PROMPT = [(PROMPT_ICON + " ", PROMPT_COLOR)]
NO_PROMPT = []  # for opening comment lines

frames = []
current_lines = []


def add_typing(text, color, prompt=True, speed=1, use_prompt=True):
    """Type text char by char. use_prompt=False omits 木 prefix."""
    global scroll_y
    prefix = list(PROMPT) if (prompt and use_prompt) else []
    for i in range(len(text)):
        partial = text[:i+1]
        cursor_parts = prefix + [(partial, color)]
        tgt = target_scroll(current_lines + [cursor_parts])
        scroll_y = smooth_scroll(scroll_y, tgt)
        f = render_frame(current_lines, scroll_y, cursor_parts=cursor_parts)
        if i % speed == 0:
            keystroke_frames.append(len(frames))
            frames.append(f)


def add_pause(n_frames, blink=True):
    global scroll_y
    for i in range(n_frames):
        tgt = target_scroll(current_lines)
        scroll_y = smooth_scroll(scroll_y, tgt)
        vis = (i // BLINK_INTERVAL) % 2 == 0 if blink else True
        cursor = list(PROMPT)
        f = render_frame(current_lines, scroll_y,
                         cursor_parts=cursor, cursor_visible=vis)
        frames.append(f)


def add_pause_no_prompt(n_frames, blink=True):
    """Pause without 木 prompt (for opening section)."""
    global scroll_y
    for i in range(n_frames):
        tgt = target_scroll(current_lines)
        scroll_y = smooth_scroll(scroll_y, tgt)
        vis = (i // BLINK_INTERVAL) % 2 == 0 if blink else True
        f = render_frame(current_lines, scroll_y,
                         cursor_parts=[], cursor_visible=vis)
        frames.append(f)


def add_flash(n_frames=6):
    global scroll_y
    for i in range(n_frames):
        t = i / max(n_frames - 1, 1)
        flash_color = lerp_color(WHITE, PRIMARY, t)
        tgt = target_scroll(current_lines)
        scroll_y = smooth_scroll(scroll_y, tgt)
        f = render_frame(current_lines, scroll_y, prompt_color_override=flash_color)
        frames.append(f)


def add_output_lines(output, delay=3, flash=True):
    global scroll_y
    for line in output:
        current_lines.append(line)
        for _ in range(delay):
            tgt = target_scroll(current_lines)
            scroll_y = smooth_scroll(scroll_y, tgt)
            f = render_frame(current_lines, scroll_y)
            frames.append(f)
    if flash:
        add_flash()


def add_spinner_progress(status_text, n_frames=36,
                          progress_start=0.0, progress_end=1.0):
    global scroll_y
    for i in range(n_frames):
        progress = progress_start + (progress_end - progress_start) * (i / max(n_frames - 1, 1))
        cycle_color = CYCLE_COLORS[i % len(CYCLE_COLORS)]
        pct = int(progress * 100)

        tgt = target_scroll(current_lines)
        scroll_y = smooth_scroll(scroll_y, tgt + LINE_H * 3)

        def draw_extra(draw, base_y, n_lines, p=progress, cc=cycle_color, st=status_text, pc=pct):
            y1 = base_y + n_lines * LINE_H
            if TITLE_BAR_H <= y1 <= H:
                x = PAD_X + 2 * CHAR_W
                draw.text((x, y1), PROMPT_ICON + " ", fill=cc, font=cjk_font)
                draw.text((x + 2 * CHAR_W, y1), st, fill=DIM, font=font)
            y2 = base_y + (n_lines + 1) * LINE_H
            if TITLE_BAR_H <= y2 <= H:
                bar_x = PAD_X + 2 * CHAR_W
                bar_h = 36
                bar_w = 880
                bar_y = y2 + (LINE_H - bar_h) // 2
                draw.rounded_rectangle([bar_x, bar_y, bar_x + bar_w, bar_y + bar_h],
                                        radius=10, fill=BAR_BG)
                fill_w = int(bar_w * p)
                if fill_w > 10:
                    draw.rounded_rectangle([bar_x, bar_y, bar_x + fill_w, bar_y + bar_h],
                                            radius=10, fill=cc)
                draw.text((bar_x + bar_w + 32, y2), f"{pc}%", fill=DIM, font=small_font)

        f = render_frame(current_lines, scroll_y, extra_draw=draw_extra,
                         prompt_color_override=cycle_color)
        frames.append(f)


def add_breathing_pause(n_frames):
    """Pause with 木 breathing — dramatic pulse between near-black and full rose."""
    global scroll_y
    for i in range(n_frames):
        tgt = target_scroll(current_lines)
        scroll_y = smooth_scroll(scroll_y, tgt)
        bc = breath_color(i)
        # Also pulse the standalone 木 signoff line color
        if current_lines and len(current_lines[-1]) == 1 and current_lines[-1][0][0] == PROMPT_ICON:
            current_lines[-1] = [(PROMPT_ICON, bc)]
        f = render_frame(current_lines, scroll_y, prompt_color_override=bc)
        frames.append(f)


# ═══════════════════════════════════════════
# ──── SCRIPT ────
# ═══════════════════════════════════════════

# ─── Opening pause (no 木) ───
add_pause_no_prompt(FPS // 2)

# ─── Comment 1 (no 木 — narrative) ───
add_typing("# what if your AI agent could do sales research?", COMMENT_COLOR, speed=2, use_prompt=False)
current_lines.append([("# what if your AI agent could do sales research?", COMMENT_COLOR)])
add_pause_no_prompt(FPS)

# ─── Comment 2 (no 木 — narrative) ───
add_typing("# let's find warm paths into a target account.", COMMENT_COLOR, speed=2, use_prompt=False)
current_lines.append([("# let's find warm paths into a target account.", COMMENT_COLOR)])
add_pause_no_prompt(FPS)

# ─── Spacing ───
current_lines.append([])

# ─── Search command (木 appears for the first time) ───
cmd = "ki████ search "
arg = '"B+ fintech, hiring CX, Zendesk"'
full = cmd + arg
add_typing(full, CMD_COLOR)
current_lines.append(PROMPT + [(cmd, CMD_COLOR), (arg, ARG_COLOR)])
add_pause(8, blink=False)

# Spinner — 木 color-cycles
add_spinner_progress("indexing 1,095 pipeline companies...", n_frames=30,
                      progress_start=0.0, progress_end=0.65)
add_spinner_progress("scoring warm paths...", n_frames=18,
                      progress_start=0.65, progress_end=1.0)

# Search output — flash 木 white when done
add_output_lines([
    [],
    [("  ✓ ", GREEN), ("1,095 pipeline companies indexed · ", DIM), ("98.7% accuracy", PRIMARY)],
    [("  ✓ ", GREEN), ("12 matched · 47 warm paths", DIM)],
    [],
    [("  [1] ", PRIMARY), ("Ramp    ", FG), ("D · Intercom · Q3  · ", DIM), ("4 paths", GREEN)],
    [("  [2] ", PRIMARY), ("Brex    ", FG), ("D · Zendesk  · up  · ", DIM), ("3 paths", GREEN)],
    [("  [3] ", PRIMARY), ("Chime   ", FG), ("IPO · ZD · migrate · ", DIM), ("7 paths", GREEN)],
    [("  [4] ", PRIMARY), ("Mercury ", FG), ("C · Custom · VP    · ", DIM), ("2 paths", GREEN)],
    [("  ... 8 more", DIM)],
], delay=4)

add_pause(FPS * 2)

# ─── Spacing ───
current_lines.append([])

# ─── Enrich command ───
cmd = "ki████ enrich "
arg = "ramp.com --depth full"
full = cmd + arg
add_typing(full, CMD_COLOR)
current_lines.append(PROMPT + [(cmd, CMD_COLOR), (arg, ARG_COLOR)])
add_pause(8, blink=False)

# Spinner — 木 color-cycles
add_spinner_progress("scraping tech stack...", n_frames=24,
                      progress_start=0.0, progress_end=0.55)
add_spinner_progress("resolving leadership...", n_frames=18,
                      progress_start=0.55, progress_end=1.0)

# Enrich output — flash 木 white when done
add_output_lines([
    [],
    [("  company:   ", DIM), ("Ramp", FG)],
    [("  valuation: ", DIM), ("$32B ", PRIMARY), ("(Nov 2025)", DIM)],
    [("  raised:    ", DIM), ("$2.3B total", FG)],
    [("  employees: ", DIM), ("3,700+ ", FG), ("(3x YoY)", GREEN)],
    [("  revenue:   ", DIM), ("$1B+ ARR", YELLOW)],
    [("  stack:     ", DIM), ("Cohere.io, Snowflake, dbt", CYAN)],
    [("  signal:    ", DIM), ('"CX Ops" posted 5d ago', YELLOW)],
], delay=4)

add_pause(FPS * 2)

# ─── Spacing ───
current_lines.append([])

# ─── Agent command ───
cmd = "ki████ agent "
arg = '"analyze ramp, draft approach"'
full = cmd + arg
add_typing(full, CMD_COLOR)
current_lines.append(PROMPT + [(cmd, CMD_COLOR), (arg, ARG_COLOR)])
add_pause(8, blink=False)

# Spinner — 木 color-cycles (longer for agent)
add_spinner_progress("reasoning over graph...", n_frames=30,
                      progress_start=0.0, progress_end=0.4)
add_spinner_progress("finding warm paths...", n_frames=24,
                      progress_start=0.4, progress_end=0.75)
add_spinner_progress("drafting approach...", n_frames=18,
                      progress_start=0.75, progress_end=1.0)

# Agent reasoning box — flash 木 white when done
add_output_lines([
    [],
    [("  ┌─ ", DIM), ("agent reasoning", PRIMARY), (" ────────────────────────────────┐", DIM)],
    [("  │ → ", DIM), ("CX scaling (+18% YoY)                       ", FG), ("│", DIM)],
    [("  │ → ", DIM), ("Intercom renewal Q3                         ", FG), ("│", DIM)],
    [("  │ → ", DIM), ("Torres → CTO Atiyeh                         ", FG), ("│", DIM)],
    [("  │                                                  │", DIM)],
    [("  │ ", DIM), ("rec: ", PRIMARY), ("intro via Sarah Chen. Timing optimal.  ", FG), ("│", DIM)],
    [("  └──────────────────────────────────────────────────┘", DIM)],
], delay=8)

add_pause(FPS * 2)

# Graph path visualization — flash 木 white when done
add_output_lines([
    [],
    [("  ┌─ ", DIM), ("warm path", GREEN), (" ───────────────────────────────────────┐", DIM)],
    [("  │                                                          │", DIM)],
    [("  │    ", DIM), ("You", PRIMARY), ("  ─────→  ", DIM), ("Sarah Chen", FG), ("  ─────→  ", DIM), ("Eric Atiyeh", FG), ("   │", DIM)],
    [("  │    ", DIM), ("          ", FG), ("ex-Stripe  ", DIM), ("            ", FG), ("CTO, Ramp  ", DIM), ("   │", DIM)],
    [("  │    ", DIM), ("          ", FG), ("2019-2021  ", DIM), ("            ", FG), ("decision   ", DIM), ("   │", DIM)],
    [("  │                                                          │", DIM)],
    [("  │    ", DIM), ("strength: ", DIM), ("████████░░", PRIMARY), ("  82%", FG), ("   hops: ", DIM), ("2", FG), ("   last: ", DIM), ("3w ago", FG), ("   │", DIM)],
    [("  └──────────────────────────────────────────────────────────┘", DIM)],
], delay=8)

add_pause(FPS * 3)

# ─── Coming soon ───
current_lines.append([])
current_lines.append([])

add_typing("# coming soon to Claude Code, Codex, and MCPs near you.", DIM, speed=1)
current_lines.append(PROMPT + [("# coming soon to Claude Code, Codex, and MCPs near you.", DIM)])

add_pause(FPS)

# Type the quote in rose
add_typing("# made for machines ... and humans", PRIMARY, speed=1)
current_lines.append(PROMPT + [("# made for machines ... and humans", PRIMARY)])

# Dramatic pause before wink
add_pause(FPS)

# Animated wink: blink ;) on and off, then hold
wink_line_with = PROMPT + [("# made for machines ... and humans ", PRIMARY), (";)", PRIMARY)]
wink_line_without = PROMPT + [("# made for machines ... and humans", PRIMARY)]

for cycle in range(3):
    current_lines[-1] = wink_line_with
    for _ in range(5):
        tgt = target_scroll(current_lines)
        scroll_y = smooth_scroll(scroll_y, tgt)
        f = render_frame(current_lines, scroll_y)
        frames.append(f)
    current_lines[-1] = wink_line_without
    for _ in range(4):
        tgt = target_scroll(current_lines)
        scroll_y = smooth_scroll(scroll_y, tgt)
        f = render_frame(current_lines, scroll_y)
        frames.append(f)

# Hold with wink on
current_lines[-1] = wink_line_with
add_pause(FPS, blink=False)

# ─── Brand signoff: standalone 木 breathing (dramatic) ───
current_lines.append([])
current_lines.append([(PROMPT_ICON, PRIMARY)])
add_breathing_pause(FPS * 4)


# ═══════════════════════════════════════════
# ──── EXPORT ────
# ═══════════════════════════════════════════

print(f"Rendering {len(frames)} frames...")

frame_dir = tempfile.mkdtemp(prefix="kinobi_frames_")
for i, frame in enumerate(frames):
    frame.save(os.path.join(frame_dir, f"frame_{i:05d}.png"))

# Generate audio track
wav_path = os.path.join(frame_dir, "keystrokes.wav")
print(f"Generating audio ({len(keystroke_frames)} keystrokes)...")
generate_audio(len(frames), keystroke_frames, wav_path)

# Encode silent video first
silent_path = os.path.join(frame_dir, "silent.mp4")
subprocess.run([
    "ffmpeg", "-y",
    "-framerate", str(FPS),
    "-i", os.path.join(frame_dir, "frame_%05d.png"),
    "-c:v", "libx264",
    "-pix_fmt", "yuv420p",
    "-crf", "12",
    "-preset", "slow",
    silent_path,
], capture_output=True)

# Merge video + audio
mp4_path = "/Users/ankitpansari/Desktop/kinobi-landing/teaser_v4.mp4"
subprocess.run([
    "ffmpeg", "-y",
    "-i", silent_path,
    "-i", wav_path,
    "-c:v", "copy",
    "-c:a", "aac",
    "-b:a", "128k",
    "-movflags", "+faststart",
    "-shortest",
    mp4_path,
], capture_output=True)

shutil.rmtree(frame_dir)

print(f"Generated {len(frames)} frames at {FPS}fps = {len(frames)/FPS:.1f}s")
print(f"Keystrokes: {len(keystroke_frames)}")
print(f"MP4: {mp4_path} ({os.path.getsize(mp4_path) / 1024:.0f}KB) — {W}x{H}")
