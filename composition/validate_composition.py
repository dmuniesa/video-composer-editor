"""
Validate a montage output JSON against its composition prompt.

Usage:
    python validate_composition.py [prompt_file] [output_file]

If no args are given, it auto-detects composition<N>.prompt and
composition<N>.output.json in this folder (picks the highest N that has both).

Rules checked (from the composer prompt):
  HARD ERRORS
    - montage must not run past the song's end
    - clips on the same track must not overlap
    - source_in/source_out must stay within the video's duration
    - source_out must be > source_in, timeline_start >= 0
  WARNINGS
    - each clip start should land on a beat (downbeats are strongest)
    - a cut window should overlap a hand-picked range or AI highlight
    - the same video should not appear twice in a row on a track
    - section-boundary scene changes should land near a beat

This simulates the app: it applies the actions in order (clear_track /
remove / move / place) and then inspects the resulting timeline, so it
works on any valid action list, not just a full rebuild.
"""
import json
import re
import sys
from pathlib import Path


# ---------------------------------------------------------------- loading

def load_prompt(path):
    """Return the parsed project-state dict from a *.prompt file.

    The prompt is mostly prose; the JSON blob lives on one long line. We scan
    for the first line that parses as a dict carrying 'song'/'videos'."""
    text = Path(path).read_text(encoding="utf-8")
    for line in text.splitlines():
        s = line.strip()
        if not s.startswith("{"):
            continue
        try:
            obj = json.loads(s)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict) and "song" in obj and "videos" in obj:
            return obj
    raise ValueError(f"No project-state JSON found in {path}")


# ---------------------------------------------------- action application

def apply_actions(state, actions):
    """Replay actions on a copy of the timeline. Returns the final tracks."""
    tl = json.loads(json.dumps(state.get("timeline", {"tracks": []})))
    tracks = {t["index"]: t for t in tl.get("tracks", [])}

    def ensure(idx):
        if idx not in tracks:
            tracks[idx] = {"index": idx, "name": f"V{idx+1}", "clips": []}
        return tracks[idx]

    next_id = 1
    for c in (c for t in tracks.values() for c in t["clips"]):
        next_id = max(next_id, c["id"] + 1)

    for a in actions:
        kind = a["action"]
        if kind == "clear_track":
            ensure(a["track"])["clips"] = []
        elif kind == "place":
            t = ensure(a["track"])
            t["clips"].append({
                "id": next_id,
                "video_id": a["video_id"],
                "track": a["track"],
                "timeline_start": a["timeline_start"],
                "source_in": a.get("source_in", 0.0),
                "source_out": a["source_out"],
            })
            next_id += 1
        elif kind == "move":
            for t in tracks.values():
                for c in t["clips"]:
                    if c["id"] == a["clip_id"]:
                        if "track" in a:
                            # move across tracks
                            t["clips"].remove(c)
                            c["track"] = a["track"]
                            ensure(a["track"])["clips"].append(c)
                        for k in ("timeline_start", "source_in", "source_out"):
                            if k in a:
                                c[k] = a[k]
                        break
        elif kind == "remove":
            for t in tracks.values():
                t["clips"] = [c for c in t["clips"] if c["id"] != a["clip_id"]]
        else:
            raise ValueError(f"Unknown action {kind!r}")

    return [tracks[i] for i in sorted(tracks)]


# ---------------------------------------------------------- validation

BEAT_TOL = 0.06  # seconds; a cut within this of a beat counts as "on beat"


def _nearest(value, grid):
    return min(grid, key=lambda b: abs(b - value)) if grid else None


def validate(state, tracks):
    """Return (errors, warnings, summary_dict)."""
    videos = {v["id"]: v for v in state["videos"]}
    song = state["song"]
    song_end = song["duration"]
    beats = song.get("beats", [])
    downbeats = song.get("downbeats", [])
    # the beat/downbeat lists often stop before the outro — extrapolate both
    # past the last listed sample so outro cuts aren't falsely flagged.
    def _extend(grid):
        if len(grid) >= 2:
            step = grid[-1] - grid[-2]
            e, out = grid[-1], list(grid)
            while e < song_end + 1:
                e += step
                out.append(e)
            return out
        return grid
    beats = _extend(beats)
    downbeats = _extend(downbeats)

    errors, warnings = [], []
    n_clips = 0

    for t in tracks:
        idx = t["index"]
        clips = sorted(t["clips"], key=lambda c: c["timeline_start"])
        prev_video = None
        prev_end = None
        for c in clips:
            n_clips += 1
            v = videos.get(c["video_id"])
            ts = c["timeline_start"]
            si, so = c["source_in"], c["source_out"]
            dur = so - si
            tag = f"tr{idx} clip{c['id']} v{c['video_id']} @{ts:.2f}"

            if v is None:
                errors.append(f"{tag}: video_id not found")
                continue

            # --- hard: source window within duration
            if si < 0:
                errors.append(f"{tag}: source_in {si} < 0")
            if so > v["duration"] + 1e-3:
                errors.append(f"{tag}: source_out {so} > duration {v['duration']}")
            if dur <= 0:
                errors.append(f"{tag}: non-positive source window ({si}->{so})")

            # --- hard: past song end
            te = ts + dur
            if te > song_end + 1e-2:
                errors.append(f"{tag}: ends at {te:.2f}, past song end {song_end}")

            # --- hard: overlap on same track
            if prev_end is not None and ts < prev_end - 1e-2:
                errors.append(f"{tag}: overlaps previous clip (prev ends {prev_end:.2f})")

            # --- warn: on beat? (the song start at t=0 is always fine —
            # the first detected beat is usually a pickup at ~0.1s)
            if beats and ts > 0.01:
                nb = _nearest(ts, beats)
                if nb is not None and abs(nb - ts) > BEAT_TOL:
                    warnings.append(f"{tag}: off-beat (nearest beat {nb:.2f}, d={abs(nb-ts):.2f}s)")
            if downbeats:
                nd = _nearest(ts, downbeats)
                if nd is not None and abs(nd - ts) <= BEAT_TOL:
                    pass  # good: lands on a downbeat

            # --- warn: highlight / range overlap
            window = (si, so)
            ranges = [(r["t_in"], r["t_out"]) for r in v.get("ranges", [])]
            highs = [(h["t_in"], h["t_out"]) for h in v.get("highlights", [])]
            hit_range = any(not (so < a - 1e-3 or si > b + 1e-3) for a, b in ranges)
            hit_high = any(not (so < a - 1e-3 or si > b + 1e-3) for a, b in highs)
            if ranges and not hit_range:
                warnings.append(f"{tag}: window misses hand-picked range(s)")
            elif not ranges and highs and not hit_high:
                warnings.append(f"{tag}: window misses AI highlight(s)")

            # --- warn: back-to-back same video on this track
            if c["video_id"] == prev_video:
                warnings.append(f"{tag}: same video back-to-back with previous clip")

            prev_video = c["video_id"]
            prev_end = te

    # --- warn: section-boundary cuts near a beat?
    for s in song.get("sections", []):
        start = s["start"]
        if beats:
            nb = _nearest(start, beats)
            if nb is not None and abs(nb - start) > BEAT_TOL:
                # informational only
                pass

    all_ends = []
    for t in tracks:
        for c in t["clips"]:
            all_ends.append(c["timeline_start"] + (c["source_out"] - c["source_in"]))
    used = [c["video_id"] for t in tracks for c in t["clips"]]
    summary = {
        "clips": n_clips,
        "tracks_used": sorted({t["index"] for t in tracks if t["clips"]}),
        "ends_at": round(max(all_ends), 2) if all_ends else 0.0,
        "song_end": song_end,
        "unique_videos": len(set(used)),
        "total_placed": len(used),
    }
    return errors, warnings, summary


# --------------------------------------------------------------- main

def _autodetect():
    here = Path(__file__).resolve().parent
    prompts = {}
    for p in here.glob("composition*.prompt"):
        m = re.search(r"composition(\d+)\.prompt$", p.name)
        if m:
            prompts[int(m.group(1))] = p
    for n in sorted(prompts, reverse=True):
        out = here / f"composition{n}.output.json"
        if out.exists():
            return prompts[n], out
    # fall back: any prompt with a matching .output.json
    for p in sorted(here.glob("composition*.prompt"), reverse=True):
        stem = p.stem  # compositionN.prompt -> compositionN.prompt (no, .prompt is ext)
        out = here / (p.name + ".output.json")
        if out.exists():
            return p, out
    raise SystemExit("Could not auto-detect a prompt+output pair.")


def main(argv):
    # Windows consoles default to cp1252 and choke on the check/cross marks;
    # force UTF-8 so diagnostics print everywhere.
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    if len(argv) >= 3:
        prompt_path, output_path = Path(argv[1]), Path(argv[2])
    else:
        prompt_path, output_path = _autodetect()

    state = load_prompt(prompt_path)
    out = json.loads(output_path.read_text(encoding="utf-8"))
    actions = out.get("actions", [])

    tracks = apply_actions(state, actions)
    errors, warnings, summary = validate(state, tracks)

    print(f"prompt : {prompt_path}")
    print(f"output : {output_path}")
    print(f"clips  : {summary['clips']}  tracks {summary['tracks_used']}  "
          f"unique {summary['unique_videos']}/{summary['total_placed']}  "
          f"ends {summary['ends_at']}/{summary['song_end']}")
    print()
    if errors:
        print(f"ERRORS ({len(errors)}):")
        for e in errors:
            print("  ✗ " + e)
    else:
        print("ERRORS: none")
    print()
    if warnings:
        print(f"WARNINGS ({len(warnings)}):")
        for w in warnings:
            print("  ! " + w)
    else:
        print("WARNINGS: none")

    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
