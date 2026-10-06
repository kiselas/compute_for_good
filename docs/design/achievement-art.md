# Achievement art and copy

Six original collectible illustrations accompany the existing accepted-outcomes-v1 achievements. Only presentation changes: IDs, thresholds, server progress and eligibility are unchanged. Movie/game references live in localized UI copy; illustrations have no embedded text, logos or character likenesses.

Generated on 2026-10-06 using the built-in `image_gen` tool with `transparent_background: true` (not the CLI fallback). Final delivery assets are 320×320 transparent WebP in `frontend/public/images/achievements/`, rendered at 128px on desktop and 96px on mobile with explicit dimensions, lazy loading and asynchronous decoding. Delivery conversion preserves composition and alpha. Original PNG outputs remain in the generator's output directory; the website uses only repository-local WebP files.

The decorative illustrations are hidden from assistive technology. Every card exposes a localized title, a playful line, an exact unlock condition, explicit earned/locked status and a labelled native progress bar. Partial and zero progress use different quest labels. Unknown future achievement IDs retain a generic icon instead of constructing arbitrary image paths.

## Prompt set

Shared prompt, followed by the subject below for each individual built-in call:

```text
Use case: stylized-concept. Asset type: one original collectible achievement illustration for a polished open-source contributor website, not a UI mockup. Style: premium playful 3D enamel pin / sculpted game inventory collectible, crisp rounded silhouette, brushed midnight-blue metal edges, luminous jewel tones, softly bevelled glossy details, tiny tasteful highlights, warm studio lighting, slight three-quarter view. Centered isolated object, square composition, large readable silhouette occupying 75 percent of image with 12 percent clear padding on every edge. Same unified style for a six-piece collection. Truly transparent background and subtle contained shadow. No letters, no numbers, no text, no logos, no characters, no faces, no surrounding scenery. Original imagery with a subtle cinema / game Easter egg.
```

### first_contribution

File: `frontend/public/images/achievements/first_contribution-v1.webp`

```text
Subject: a cyan glowing energy blade with a small golden circular branching-code emblem integrated into its polished dark-blue hilt, a tiny green spark at the tip. Celebrates the first accepted code contribution. Palette cyan, pale teal, warm gold.
```

### five_contributions

File: `frontend/public/images/achievements/five_contributions-v1.webp`

```text
Subject: exactly five floating faceted elemental crystals forming a compact circular crown above a small brushed dark-blue pedestal: emerald, sapphire, amber, ruby, amethyst. A luminous center links all five. Evokes a fifth-element adventure and five accepted contributions. Very clearly five crystals. Palette jewel tones with warm amber.
```

### ten_contributions

File: `frontend/public/images/achievements/ten_contributions-v1.webp`

```text
Subject: a compact retro arcade joystick trophy, dark blue and gold base, glossy magenta joystick and two small amber buttons, one energetic lightning bolt behind it. Evokes a satisfying fighting-game combo and ten useful changes. Palette vivid coral, magenta, electric purple and warm gold. No numbers.
```

### cross_project

File: `frontend/public/images/achievements/cross_project-v1.webp`

```text
Subject: two luminous oval portal rings, one cyan and one amber, with a tiny third violet branching-code world between them and a small metallic paper airplane passing through. Compact emblem, portals clearly readable. Evokes a portal puzzle adventure and helping three repositories. Palette cyan, amber, violet.
```

### first_review

File: `frontend/public/images/achievements/first_review-v1.webp`

```text
Subject: a refined detective magnifying glass, bronze-gold and dark-blue handle, the lens revealing a small stylized emerald bug with a tiny gold checkmark beside it. Compact elegant collectible, glass refraction. Evokes Sherlock and spotting details in independent code review. Palette emerald, teal, warm brass.
```

### five_reviews

File: `frontend/public/images/achievements/five_reviews-v1.webp`

```text
Subject: five small polished protective shields assembled in a compact heroic fan, each midnight-blue with different jewel colored inlay, joined by one central golden magnifying lens with a green check mark. Evokes a team of review heroes assembling, protecting accepted work. Clearly five shields. Palette royal blue, sapphire, emerald, violet, warm gold.
```

## UI copy and verification

English, Russian and Simplified Chinese share the same image assets. Humor is localized, while unlock conditions stay literal and separate. No progress is awarded for viewing images, logins or unfinished PRs.

Render regressions cover earned/locked states, all six original IDs with zero progress, decorative lazy images and Russian/Chinese conditions. The production build validates locale parity and TypeScript. Browser QA covers all three languages, mobile/desktop widths, real image decoding and the production account's single earned achievement.
