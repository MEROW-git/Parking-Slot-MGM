# Design — SomPark

A locked design system for the SomPark application. Every page uses this file as its visual source of truth.

## Genre

Modern-minimal with a bold utilitarian register inherited from the supplied automotive template.

## Macrostructure family

- Marketing page: Marquee Hero, followed immediately by live city capacity and searchable parking inventory.
- App pages: Workbench, with functional panels, tables, forms, and ticket surfaces carrying the hierarchy.
- Content and error pages: Long Document, using direct copy and one clear route back to the application.

## Theme

- `--color-paper`: `oklch(18% 0.015 255)`
- `--color-paper-2`: `oklch(22% 0.014 255)`
- `--color-paper-3`: `oklch(27% 0.012 255)`
- `--color-ink`: `oklch(97% 0.008 85)`
- `--color-ink-2`: `oklch(79% 0.012 80)`
- `--color-rule`: `oklch(35% 0.014 255)`
- `--color-accent`: `oklch(72% 0.17 55)`
- `--color-focus`: `oklch(82% 0.17 78)`

The orange accent is reserved for primary actions and active navigation. Availability states use green, amber, and red only where status meaning requires them.

## Typography

- Display: Barlow Condensed, weight 700–800, normal style.
- Body: Plus Jakarta Sans with Noto Sans Khmer fallback, weight 400–700.
- Mono: JetBrains Mono, weight 500–700, for ticket codes and live numeric data.
- Display tracking: `-0.035em`.
- Type scale anchor: `--text-display = clamp(4rem, 12vw, 11rem)`.

## Spacing

The project uses a named 4-point scale from `--space-3xs` through `--space-4xl`. Page CSS references tokens instead of raw spacing values where new rules are introduced.

## Motion

- Easings: `--ease-out`, `--ease-in`, and `--ease-in-out` from `tokens.css`.
- Reveal pattern: none; operational information is immediately visible.
- Hover motion: transform and opacity only.
- Reduced motion: spatial motion is removed and remaining transitions are capped at 120ms.

## Microinteractions stance

- Status changes are communicated inline; no celebratory toasts.
- Focus rings appear instantly and visibly.
- Disabled, error, success, loading, hover, focus, and active states share the same component voice.

## CTA voice

- Primary CTA: safety-orange fill, dark ink, compact radius, direct verb-first label.
- Secondary CTA: transparent dark surface with a visible rule and light text.

## Per-page allowances

- Home may use the existing parking-lot photograph as a background enrichment.
- App pages use no decorative imagery; real data and controls carry the page.
- Error pages use typography only.

## What pages MUST share

- SomPark wordmark and Phnom Penh location marker.
- Graphite surfaces, safety-orange primary actions, and restrained status colors.
- Barlow Condensed display, Plus Jakarta Sans/Noto Sans Khmer body, and JetBrains Mono data roles.
- Compact buttons, visible focus treatment, and strong section rules.

## What pages MAY differ on

- Marketing pages may use larger display type and photography.
- Forms, tickets, status pages, and tables may adjust density for their job.
- Print output may switch to black on white while preserving information hierarchy.

## Exports

### tokens.css

The canonical complete CSS export is stored in `tokens.css` at the project root and mirrored at `static/css/tokens.css` for Django static delivery.

```css
:root {
  --color-paper: oklch(18% 0.015 255);
  --color-paper-2: oklch(22% 0.014 255);
  --color-paper-3: oklch(27% 0.012 255);
  --color-ink: oklch(97% 0.008 85);
  --color-ink-2: oklch(79% 0.012 80);
  --color-rule: oklch(35% 0.014 255);
  --color-accent: oklch(72% 0.17 55);
  --color-accent-ink: oklch(18% 0.015 255);
  --color-focus: oklch(82% 0.17 78);
  --font-display: "Barlow Condensed", "Noto Sans Khmer", sans-serif;
  --font-body: "Plus Jakarta Sans", "Noto Sans Khmer", sans-serif;
  --font-outlier: "JetBrains Mono", monospace;
}
```

### Tailwind v4 `@theme`

```css
@theme {
  --color-paper: oklch(18% 0.015 255);
  --color-paper-2: oklch(22% 0.014 255);
  --color-paper-3: oklch(27% 0.012 255);
  --color-ink: oklch(97% 0.008 85);
  --color-ink-2: oklch(79% 0.012 80);
  --color-rule: oklch(35% 0.014 255);
  --color-accent: oklch(72% 0.17 55);
  --color-focus: oklch(82% 0.17 78);
  --font-display: "Barlow Condensed", "Noto Sans Khmer", sans-serif;
  --font-body: "Plus Jakarta Sans", "Noto Sans Khmer", sans-serif;
  --font-outlier: "JetBrains Mono", monospace;
  --spacing-sm: 1rem;
  --spacing-md: 1.5rem;
  --spacing-lg: 2rem;
  --spacing-xl: 3rem;
  --text-md: 1rem;
  --text-xl: 1.563rem;
  --ease-out: cubic-bezier(0.16, 1, 0.3, 1);
}
```

### DTCG `tokens.json`

```json
{
  "$schema": "https://design-tokens.github.io/community-group/format/",
  "color": {
    "paper": { "$value": "oklch(18% 0.015 255)", "$type": "color" },
    "paper-2": { "$value": "oklch(22% 0.014 255)", "$type": "color" },
    "ink": { "$value": "oklch(97% 0.008 85)", "$type": "color" },
    "accent": { "$value": "oklch(72% 0.17 55)", "$type": "color" },
    "focus": { "$value": "oklch(82% 0.17 78)", "$type": "color" }
  },
  "font": {
    "display": { "$value": "Barlow Condensed, Noto Sans Khmer, sans-serif", "$type": "fontFamily" },
    "body": { "$value": "Plus Jakarta Sans, Noto Sans Khmer, sans-serif", "$type": "fontFamily" },
    "outlier": { "$value": "JetBrains Mono, monospace", "$type": "fontFamily" }
  },
  "space": {
    "sm": { "$value": "1rem", "$type": "dimension" },
    "md": { "$value": "1.5rem", "$type": "dimension" },
    "lg": { "$value": "2rem", "$type": "dimension" }
  }
}
```

### shadcn/ui CSS variables

```css
:root {
  --background: 18% 0.015 255;
  --foreground: 97% 0.008 85;
  --card: 22% 0.014 255;
  --card-foreground: 97% 0.008 85;
  --primary: 72% 0.17 55;
  --primary-foreground: 18% 0.015 255;
  --secondary: 27% 0.012 255;
  --secondary-foreground: 97% 0.008 85;
  --muted: 35% 0.014 255;
  --muted-foreground: 76% 0.014 255;
  --border: 35% 0.014 255;
  --input: 35% 0.014 255;
  --ring: 82% 0.17 78;
  --radius: 0.375rem;
}
```
