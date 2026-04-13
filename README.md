# ayu-flat
Background-first variants of Ayu inspired by flatwhite helix themes

<p align="center">
    <img src="https://github.com/giann/ayu-flat-dark/raw/main/ayu-dark.png" alt="ayu-flat-dark">
</p>

<p align="center">
    <img src="https://github.com/giann/ayu-flat-dark/raw/main/ayu-mirage.png" alt="ayu-flat-dark">
</p>

<p align="center">
    <img src="https://github.com/giann/ayu-flat-dark/raw/main/ayu-light.png" alt="ayu-flat-dark">
</p>

## Generate a Background-First Variant for Any Helix Theme

Use `scripts/background_first_theme.py`:

```sh
python3 scripts/background_first_theme.py ~/.config/helix/runtime/themes/ayu_dark.toml \
  -o ~/.config/helix/runtime/themes/ayu_dark_flat.toml
```

Useful options:

- `--in-place`: overwrite input file
- `--min-saturation`: only convert colors above this saturation (default: `0.18`)
- `--bg-strength`: tint strength for generated `*_bg` colors (default: `0.18`)
- `--min-contrast`: minimum contrast between generated `*_text` and `*_bg` (default: `2.4`)
- `--red-comments`: force `comment*` scopes to use the theme's red accent pair

Note: `function` is always emitted without background to avoid Helix coloring the full function call span.
