# Achievement art and copy

Six original collectible illustrations accompany the existing accepted-outcomes-v1 achievements. Only presentation changes: IDs, thresholds, server progress and eligibility are unchanged. Movie/game references live in localized UI copy; illustrations have no embedded text, logos or character likenesses.

The initial v1 set was generated on 2026-10-06 using the built-in `image_gen` tool with `transparent_background: true` (not the CLI fallback), delivered as 320×320 transparent WebP and rendered at 128px desktop / 96px mobile. The current minimal v2 revision is documented below. Both sets live in `frontend/public/images/achievements/` with explicit dimensions, lazy loading and asynchronous decoding. Delivery conversion preserves composition and alpha. Original PNG outputs remain in the generator's output directory; the website uses only repository-local WebP files.

The decorative illustrations are hidden from assistive technology. Every card exposes a localized title, a playful line, an exact unlock condition, explicit status and a labelled native progress bar. Earned, partial and zero progress use distinct labels. Unknown future achievement IDs retain a generic icon instead of constructing arbitrary image paths.

## Initial v1 prompt set

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


## Minimal v2 revision — 2026-10-06

User feedback requested simpler icons and more natural captions. The current UI uses `*-v2.webp`: flat geometric silhouettes, navy outlines and fewer details; 96px desktop / 80px mobile. The v1 files remain available for older cached bundles. Decorative images, labelled progress and eligibility rules remain unchanged. Long jokes and quest labels are replaced by short titles, one-line Easter eggs and ordinary earned/partial/pending labels in all three languages.

Edited with the built-in `image_gen` tool, using each corresponding v1 WebP as the edit target and `transparent_background: true`. Shared edit prompt:

```text
Edit target: the attached achievement icon. Preserve its core subject and recognizable idea, but redesign it as a MUCH simpler flat editorial app icon for a clean contributor profile. A coordinated six-icon collection: front-facing geometric silhouettes, rounded dark navy outlines, consistent bold stroke, just 2 or 3 flat muted colors, generous negative space. No realistic materials, no metal shine, no facets, no lighting, no bevels, no glows, no textures, no shadows, no elaborate ornaments. Keep only the few essential shapes. Like a premium small playful vector illustration, but deliver a raster image with genuine transparent background. Centered square canvas, object within central 65 percent, clear padding. Readable at 64 pixels. No text, no numbers, no logos.
```

### first_contribution v2

Current file: `frontend/public/images/achievements/first_contribution-v2.webp`

```text
Keep a simple small cyan sword and one tiny branching-code mark in its plain hilt. One clean blade, very simple handle, no gold ornamentation.
```

### five_contributions v2

Current file: `frontend/public/images/achievements/five_contributions-v2.webp`

```text
Keep exactly five smooth colored elemental stones in a simple compact ring. No pedestal, no gold frame, no facets, no center glow. Five rounded diamonds, each a single flat fill; coordinate muted blue/teal/amber/purple/coral.
```

### ten_contributions v2

Current file: `frontend/public/images/achievements/ten_contributions-v2.webp`

```text
Keep a compact navy arcade joystick with one coral stick and two amber buttons. Plain rectangular base; remove the lightning, rays and additional base layers.
```

### cross_project v2

Current file: `frontend/public/images/achievements/cross_project-v2.webp`

```text
Keep two simple oval portals, cyan and amber, joined by a small paper airplane. Remove floating cubes, mechanical detail and glows. Just two clean outlined rings and the tiny plane.
```

### first_review v2

Current file: `frontend/public/images/achievements/first_review-v2.webp`

```text
Keep a simple teal-and-navy magnifying glass with a tiny stylized bug in the lens and one small checkmark. Plain short handle; no gemstone, brass, glass reflections or ornament.
```

### five_reviews v2

Current file: `frontend/public/images/achievements/five_reviews-v2.webp`

```text
Keep exactly five simple small navy shield outlines in a compact fan, one teal checkmark on the central shield. Remove jewel inlays, emblems, lens, stars and gold. Strong simple shield silhouettes.

Final focused edit, using the intermediate v2 as the edit target:
Edit target: this flat achievement icon. Simplify ONLY the shield arrangement: remove every surrounding shield, retain ONE centered large shield with the existing teal checkmark. One shield total. Keep the exact dark navy bold rounded outline, off-white flat fill, teal checkmark and friendly editorial flat style. No additional shapes, no ornaments, no letters, no numbers, no shadows, no glow, no realistic texture. Preserve transparent background and generous padding. Square icon readable at 64 px. It represents guarding code through review; review count is shown separately in the UI.
```
