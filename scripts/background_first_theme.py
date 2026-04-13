#!/usr/bin/env python3
"""Convert a Helix theme into a background-first variant.

The script applies a Flatwhite-style strategy to syntax scopes:
- high-saturation foreground colors become paired foreground/background colors
- generated colors are added to the palette as `<name>_text` and `<name>_bg`
- UI/diagnostic/diff scopes are preserved by default
- `function` is always foreground-only (no background)
- optional `--red-comments` forces `comment*` scopes to use red accent colors

Formatting and comments from the input TOML are not preserved.
"""

from __future__ import annotations

import argparse
import colorsys
import copy
import re
from pathlib import Path
from typing import Any

try:
    import tomllib  # Python 3.11+
except ModuleNotFoundError:  # pragma: no cover - runtime fallback
    import tomli as tomllib


HEX_RE = re.compile(r"^#([0-9a-fA-F]{6})$")
BARE_KEY_RE = re.compile(r"^[A-Za-z0-9_-]+$")
SKIP_PREFIXES = ("ui.", "diagnostic", "diff.")
SKIP_EXACT = {"warning", "error", "info", "hint"}
NEUTRAL_NAME_PARTS = (
    "foreground",
    "background",
    "gray",
    "grey",
    "white",
    "black",
    "base",
)

ANSI_FALLBACK_PALETTE: dict[str, str] = {
    "black": "#1f1f1f",
    "red": "#d75f5f",
    "green": "#5f875f",
    "yellow": "#af875f",
    "blue": "#5f87af",
    "magenta": "#875f87",
    "cyan": "#5f8787",
    "gray": "#5f5f5f",
    "white": "#d7d7d7",
    "light-red": "#ff8787",
    "light-green": "#87af87",
    "light-yellow": "#ffd787",
    "light-blue": "#87afd7",
    "light-magenta": "#af87af",
    "light-cyan": "#87d7d7",
    "light-gray": "#bcbcbc",
}


def parse_hex(value: str) -> tuple[int, int, int] | None:
    match = HEX_RE.match(value.strip())
    if not match:
        return None
    packed = match.group(1)
    return (int(packed[0:2], 16), int(packed[2:4], 16), int(packed[4:6], 16))


def to_hex(rgb: tuple[int, int, int]) -> str:
    return "#{:02x}{:02x}{:02x}".format(*rgb)


def clamp_channel(value: float) -> int:
    return max(0, min(255, int(round(value))))


def blend(base: tuple[int, int, int], tint: tuple[int, int, int], amount: float) -> tuple[int, int, int]:
    return (
        clamp_channel(base[0] * (1.0 - amount) + tint[0] * amount),
        clamp_channel(base[1] * (1.0 - amount) + tint[1] * amount),
        clamp_channel(base[2] * (1.0 - amount) + tint[2] * amount),
    )


def relative_luminance(rgb: tuple[int, int, int]) -> float:
    def _channel(c: int) -> float:
        value = c / 255.0
        if value <= 0.04045:
            return value / 12.92
        return ((value + 0.055) / 1.055) ** 2.4

    r, g, b = (_channel(c) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast_ratio(a: tuple[int, int, int], b: tuple[int, int, int]) -> float:
    la = relative_luminance(a)
    lb = relative_luminance(b)
    lighter = max(la, lb)
    darker = min(la, lb)
    return (lighter + 0.05) / (darker + 0.05)


def saturation(rgb: tuple[int, int, int]) -> float:
    h, l, s = colorsys.rgb_to_hls(*(c / 255.0 for c in rgb))
    _ = (h, l)
    return s


def key_name_for_palette(name: str) -> str:
    if BARE_KEY_RE.match(name):
        return name
    escaped = name.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def key_name_for_scope(name: str) -> str:
    escaped = name.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def dump_value(value: Any) -> str:
    if isinstance(value, str):
        escaped = value.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, list):
        return "[" + ", ".join(dump_value(item) for item in value) + "]"
    if isinstance(value, dict):
        pairs = ", ".join(f"{key_name_for_palette(k)} = {dump_value(v)}" for k, v in value.items())
        return "{ " + pairs + " }"
    raise TypeError(f"Unsupported TOML value type: {type(value)}")


def dump_theme(data: dict[str, Any]) -> str:
    lines: list[str] = []
    for key, value in data.items():
        if key == "palette":
            continue
        lines.append(f"{key_name_for_scope(key)} = {dump_value(value)}")

    palette = data.get("palette", {})
    if isinstance(palette, dict):
        if lines:
            lines.append("")
        lines.append("[palette]")
        for key, value in palette.items():
            lines.append(f"{key_name_for_palette(key)} = {dump_value(value)}")

    return "\n".join(lines) + "\n"


def merge_themes(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = copy.deepcopy(base)
    for key, value in override.items():
        if key == "inherits":
            continue
        if key == "palette" and isinstance(value, dict):
            base_palette = merged.get("palette")
            if not isinstance(base_palette, dict):
                base_palette = {}
            new_palette = dict(base_palette)
            new_palette.update(value)
            merged["palette"] = new_palette
            continue
        merged[key] = copy.deepcopy(value)
    return merged


def load_theme(path: Path, visited: set[Path] | None = None) -> dict[str, Any]:
    resolved = path.resolve()
    visited = visited or set()

    if resolved in visited:
        raise ValueError(f"Cyclic theme inheritance involving: {resolved}")
    visited.add(resolved)

    with resolved.open("rb") as f:
        data = tomllib.load(f)
    if not isinstance(data, dict):
        raise ValueError(f"Theme TOML root must be a table: {resolved}")

    inherits = data.get("inherits")
    if isinstance(inherits, str):
        parent_name = inherits if inherits.endswith(".toml") else f"{inherits}.toml"
        parent_path = resolved.parent / parent_name
        if not parent_path.exists():
            raise ValueError(f'Inherited theme "{inherits}" not found for {resolved}')
        parent = load_theme(parent_path, visited=visited)
        data = merge_themes(parent, data)

    visited.remove(resolved)
    return data


class Transformer:
    def __init__(
        self,
        palette: dict[str, Any],
        background_rgb: tuple[int, int, int],
        dark_theme: bool,
        min_saturation: float,
        bg_strength: float,
        min_contrast: float,
        red_comments: bool,
    ) -> None:
        self.palette = palette
        self.background_rgb = background_rgb
        self.dark_theme = dark_theme
        self.min_saturation = min_saturation
        self.bg_strength = bg_strength
        self.min_contrast = min_contrast
        self.red_comments = red_comments
        self._derived_for_ref: dict[str, tuple[str, str] | None] = {}
        self._auto_counter = 0
        self._comment_red_ref = self._pick_comment_red_ref() if red_comments else None

    def should_skip_scope(self, scope: str) -> bool:
        if scope in SKIP_EXACT:
            return True
        return scope.startswith(SKIP_PREFIXES)

    def resolve_ref(self, ref: str) -> tuple[int, int, int] | None:
        direct = parse_hex(ref)
        if direct is not None:
            return direct
        from_palette = self.palette.get(ref)
        if isinstance(from_palette, str):
            return parse_hex(from_palette)
        fallback = ANSI_FALLBACK_PALETTE.get(ref)
        if fallback is not None:
            return parse_hex(fallback)
        return None

    def is_accent_ref(self, ref: str, rgb: tuple[int, int, int]) -> bool:
        lowered = ref.lower()
        if lowered.endswith("_bg"):
            return False
        if any(part in lowered for part in NEUTRAL_NAME_PARTS):
            return False
        return saturation(rgb) >= self.min_saturation

    def base_name_for_ref(self, ref: str, rgb: tuple[int, int, int]) -> str:
        if ref in self.palette and BARE_KEY_RE.match(ref):
            return ref

        color_key = "".join(f"{channel:02x}" for channel in rgb)
        candidate = f"auto_{color_key}"
        while f"{candidate}_text" in self.palette or f"{candidate}_bg" in self.palette:
            self._auto_counter += 1
            candidate = f"auto_{color_key}_{self._auto_counter}"
        return candidate

    def adjusted_bg(self, rgb: tuple[int, int, int]) -> tuple[int, int, int]:
        return blend(self.background_rgb, rgb, self.bg_strength)

    def adjusted_text(self, rgb: tuple[int, int, int], bg_rgb: tuple[int, int, int]) -> tuple[int, int, int]:
        if self.dark_theme:
            candidate = blend(rgb, (255, 255, 255), 0.10)
            nudger = (255, 255, 255)
            step = 0.08
        else:
            candidate = blend(rgb, (0, 0, 0), 0.30)
            nudger = (0, 0, 0)
            step = 0.08

        for _ in range(20):
            if contrast_ratio(candidate, bg_rgb) >= self.min_contrast:
                break
            candidate = blend(candidate, nudger, step)
        return candidate

    def derive_pair(self, ref: str) -> tuple[str, str] | None:
        if ref in self._derived_for_ref:
            return self._derived_for_ref[ref]

        rgb = self.resolve_ref(ref)
        if rgb is None or not self.is_accent_ref(ref, rgb):
            self._derived_for_ref[ref] = None  # type: ignore[assignment]
            return None

        base_name = self.base_name_for_ref(ref, rgb)
        text_key = f"{base_name}_text"
        bg_key = f"{base_name}_bg"

        if text_key not in self.palette:
            bg_rgb = self.adjusted_bg(rgb)
            text_rgb = self.adjusted_text(rgb, bg_rgb)
            self.palette[text_key] = to_hex(text_rgb)
        if bg_key not in self.palette:
            self.palette[bg_key] = to_hex(self.adjusted_bg(rgb))

        pair = (text_key, bg_key)
        self._derived_for_ref[ref] = pair
        return pair

    def _pick_comment_red_ref(self) -> str | None:
        preferred = ("red", "light-red", "diff_delete")
        for ref in preferred:
            if self.resolve_ref(ref) is not None:
                return ref

        for ref in self.palette:
            lowered = ref.lower()
            if lowered.endswith("_bg") or "red" not in lowered:
                continue
            if self.resolve_ref(ref) is not None:
                return ref
        return None

    def _pair_to_bg_style(self, original_style: Any, pair: tuple[str, str]) -> Any:
        text_key, bg_key = pair
        if isinstance(original_style, dict):
            updated = dict(original_style)
            updated["fg"] = text_key
            updated["bg"] = bg_key
            return updated
        return {"fg": text_key, "bg": bg_key}

    def _pair_to_fg_only_style(self, original_style: Any, pair: tuple[str, str]) -> Any:
        text_key, _ = pair
        if isinstance(original_style, dict):
            updated = dict(original_style)
            updated["fg"] = text_key
            updated.pop("bg", None)
            return updated
        return text_key

    def transform_style(self, scope: str, style: Any) -> Any:
        if self.should_skip_scope(scope):
            return style

        if scope.startswith("comment") and self._comment_red_ref is not None:
            pair = self.derive_pair(self._comment_red_ref)
            if pair is not None:
                return self._pair_to_bg_style(style, pair)

        if scope == "function":
            if isinstance(style, str):
                pair = self.derive_pair(style)
                if pair is None:
                    return style
                return self._pair_to_fg_only_style(style, pair)
            if isinstance(style, dict):
                fg = style.get("fg")
                if not isinstance(fg, str):
                    return style
                pair = self.derive_pair(fg)
                if pair is None:
                    updated = dict(style)
                    updated.pop("bg", None)
                    return updated
                return self._pair_to_fg_only_style(style, pair)
            return style

        if isinstance(style, str):
            pair = self.derive_pair(style)
            if pair is None:
                return style
            return self._pair_to_bg_style(style, pair)

        if isinstance(style, dict):
            fg = style.get("fg")
            if not isinstance(fg, str):
                return style
            if "bg" in style:
                return style

            pair = self.derive_pair(fg)
            if pair is None:
                return style
            return self._pair_to_bg_style(style, pair)

        return style


def background_from_theme(theme: dict[str, Any], palette: dict[str, Any]) -> tuple[int, int, int]:
    for candidate in ("background", "bg", "base7", "base6"):
        value = palette.get(candidate)
        if isinstance(value, str):
            parsed = parse_hex(value)
            if parsed is not None:
                return parsed

    ui_bg = theme.get("ui.background")
    if isinstance(ui_bg, dict):
        ref = ui_bg.get("bg")
        if isinstance(ref, str):
            parsed = parse_hex(ref) or parse_hex(str(palette.get(ref, "")))
            if parsed is not None:
                return parsed

    return (15, 20, 25)


def transform_theme(
    theme: dict[str, Any],
    min_saturation: float,
    bg_strength: float,
    min_contrast: float,
    red_comments: bool,
) -> dict[str, Any]:
    palette = theme.get("palette")
    if not isinstance(palette, dict):
        palette = {}

    output = dict(theme)
    output_palette = dict(palette)
    for key, value in ANSI_FALLBACK_PALETTE.items():
        output_palette.setdefault(key, value)
    output["palette"] = output_palette

    bg_rgb = background_from_theme(theme, output_palette)
    dark_theme = relative_luminance(bg_rgb) < 0.45

    transformer = Transformer(
        palette=output_palette,
        background_rgb=bg_rgb,
        dark_theme=dark_theme,
        min_saturation=min_saturation,
        bg_strength=bg_strength,
        min_contrast=min_contrast,
        red_comments=red_comments,
    )

    for scope, style in list(output.items()):
        if scope == "palette":
            continue
        output[scope] = transformer.transform_style(scope, style)

    return output


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="Input Helix theme TOML file")
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        help="Output path (default: <input_stem>_flat.toml in the same directory)",
    )
    parser.add_argument(
        "--in-place",
        action="store_true",
        help="Overwrite the input file",
    )
    parser.add_argument(
        "--min-saturation",
        type=float,
        default=0.18,
        help="Minimum color saturation to qualify for background-first conversion",
    )
    parser.add_argument(
        "--bg-strength",
        type=float,
        default=0.18,
        help="Amount of source hue mixed into generated *_bg colors",
    )
    parser.add_argument(
        "--min-contrast",
        type=float,
        default=2.4,
        help="Minimum contrast ratio between generated *_text and *_bg",
    )
    parser.add_argument(
        "--red-comments",
        action="store_true",
        help="Force all comment scopes to use the theme's red accent pair",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    input_path = args.input.expanduser().resolve()

    if args.in_place and args.output is not None:
        raise SystemExit("Use either --in-place or --output, not both.")

    if not input_path.exists():
        raise SystemExit(f"Input file not found: {input_path}")

    output_path: Path
    if args.in_place:
        output_path = input_path
    elif args.output:
        output_path = args.output.expanduser().resolve()
    else:
        output_path = input_path.with_name(f"{input_path.stem}_flat.toml")

    theme_data = load_theme(input_path)

    transformed = transform_theme(
        theme=theme_data,
        min_saturation=args.min_saturation,
        bg_strength=args.bg_strength,
        min_contrast=args.min_contrast,
        red_comments=args.red_comments,
    )
    rendered = dump_theme(transformed)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(rendered, encoding="utf-8")
    print(f"Wrote background-first theme: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
