# PyREUser3 Branding

This branch only hosts the generated "Powered by PyREUser3" repository cards and the small generator that keeps them fresh.

## Recommended README Usage

Use the responsive light/dark card in another GitHub repository README:

```html
<a href="https://github.com/dzxrly/PyREUser3">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/dzxrly/PyREUser3/branding/powered-by-pyreuser3-dark.svg">
    <img alt="Powered by PyREUser3" src="https://raw.githubusercontent.com/dzxrly/PyREUser3/branding/powered-by-pyreuser3-light.svg">
  </picture>
</a>
```

## Simple Version

Use the compact badge when the README section is tight:

```html
<a href="https://github.com/dzxrly/PyREUser3">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/dzxrly/PyREUser3/branding/powered-by-pyreuser3-simple-dark.svg">
    <img alt="Powered by PyREUser3" src="https://raw.githubusercontent.com/dzxrly/PyREUser3/branding/powered-by-pyreuser3-simple-light.svg">
  </picture>
</a>
```

## Backward-Compatible Markdown

The original dark card path remains available:

```md
[![Powered by PyREUser3](https://raw.githubusercontent.com/dzxrly/PyREUser3/branding/powered-by-pyreuser3.svg)](https://github.com/dzxrly/PyREUser3)
```

## Generated Files

- `powered-by-pyreuser3.svg` is the backward-compatible dark repository card.
- `powered-by-pyreuser3-dark.svg` is the full dark repository card.
- `powered-by-pyreuser3-light.svg` is the full light repository card.
- `powered-by-pyreuser3-simple.svg` is the backward-compatible dark compact badge.
- `powered-by-pyreuser3-simple-dark.svg` is the compact dark badge.
- `powered-by-pyreuser3-simple-light.svg` is the compact light badge.
- `scripts/generate_powered_by_card.py` fetches GitHub repository metadata and regenerates all SVGs.

The cards embed the GitHub owner avatar during generation, so README consumers do not need to load the avatar as a separate external asset.

The scheduled workflow should live on the repository default branch. It checks out this `branding` branch, runs the generator, and pushes updated SVG output back here.