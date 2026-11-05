# Reiya (レイヤ): character specification

> **Rights notice:** Reiya and her design belong to her creator; this model is a drawing reference made from the creator's design sheet; the character is not part of this project's authorized distribution (the GPL-3.0 licence covers the castplane software only).

This is the design spec written **before modelling**, from the creator's design sheet and six other reference images.
It fixes the numbers the part builders in this directory are written against. Where this document and `rig.py` or a
builder disagree later, **the code wins**: it is what `examples/reiya.json` is generated from. Deviations are marked
in the comments of `rig.py` and the builders ("spec ..."), and `rig.SPEC_ONLY_FIELDS` lists the spec values that no
builder reads. Read this file for the intent and the likeness checklist (§I); read `rig.py` for the numbers in force.
`README.md` in this directory is the maintainer guide.

The section letters A-I are cited from the code (for example `SPEC.md §C.4` in `hair.py`). In this repository a bare
"spec §N" means `docs/spec/spec-v0.1.md`, the castplane spec, so cite this document as `SPEC.md §X`.

All lengths are in **metres**, in castplane's world frame:
- Z is up and the soles sit on z = 0.
- She faces **-Y**, and her left is **+x**.
- "hw" means half-width in x. `yf` / `yb` are the front (most negative y) and back (most positive y) extents at the
  midline unless stated otherwise.
- A horizontal **section** `(hw, yf, yb)` is the closed curve whose front half is the superellipse with semi-axes
  `(hw, c - yf)` and whose back half has `(hw, yb - c)`, with `c = (yf + yb) / 2` unless a row gives `c` (the head).
  `Rig.section_point` / `Rig.section_ring` evaluate it.
- An **azimuth** φ (degrees) runs round the vertical axis from the front (-Y, 0) through her left (+x, 90) to the back
  (+Y, 180).
- Points are given for her left (`x >= 0`) and mirrored, except the parts marked **TRUE x** (asymmetric).
- Every number is binding for the builders unless marked *(guide)*.

**Sources** (none of the images is in the repository; they are not needed to use this spec):
- **The design sheet** (三面図, 4093 × 2894 px), the authority for everything. A near-orthographic turnaround: three
  bust shots (smile, laugh, hair down), then four full figures: cardigan off (カーディガンOFF), front (正面), back
  (後ろ) and side (よこ), a 7-swatch palette and a 70 px background grid. Measured at one scale, 0.615 mm per pixel
  (the sheet scale; Decision 1). The measurement table is the appendix.
- Six other images: a full-figure screenshot (cardigan crossover, button line), a 3D render of the upper body (the
  bob, the ear tufts, the braids, the puffed sleeves and ribbed edges, the lettuce-edge mock neck; the underside of the
  hair is lavender), two illustrations without / with the cardigan worn differently, a bust shot with another girl
  (front face, heterochromia), and a variant with a cap and glasses (not modelled).
- **No official height exists** in the images (a search found no public source). The user gave it later, on
  2026-10-21: "Her height is 152cm", her barefoot height. The model is built at the sheet scale and scaled to it
  (Decision 1, the note at the top of §A).

Corrections to the first reading of the sheet in the task brief (each re-checked on a zoomed crop):
- The side view (よこ) is her **left** profile: she faces the viewer's left and the visible eye is the blue one, her
  left eye.
- The cardigan crossover: **her right front (-x) laps over her left**, and the round button sits on the centre line
  (x ≈ -0.001), on the over-lap's band (the sheet and the full-figure image agree; Decision 18).
- The fringe is swept **to her left** from a parting on her right. Her right brow and a triangle of forehead show at
  the parting; her left brow is under the fringe.
- The ear tufts' tips are only 8 mm above the hair crown (z 1.614); the lobe is about 3 cm tall and 3 cm deep, a rounded
  fin whose point is its top-inner corner (no outward hook: the sheet's front and back views are mirror outlines).
- The sock cuff is 5.3 cm tall (0.202-0.255) and the loafer's block heel is 3.4 cm (Decision 2).

---

## A. Overall proportions

> **Scale.** The tables of §A-§E (and every length in `rig.py` and the builders) are at the **design sheet's scale**:
> 0.615 mm per pixel, skin height 1.555 m. Her height is **1.52 m barefoot** (the user, 2026-10-21), so the assembled
> model is scaled uniformly about the origin by **`rig.figure_scale` = `stated_height / skin_height` = 1.52 / 1.555 =
> 0.97749** (`assemble.CHARACTER.scale`, applied by `charmodel.assembly.build_parts` before the rounding; the soles stay
> on z = 0). Every final length is the sheet value times 0.97749; ratios (the head count, the face fractions) do not
> change. The scene camera and the preview framing are scaled by the same factor, so every view frames her as before.
> Decision 1 has the final key heights; the table below lists them next to the sheet values.

| quantity | sheet scale (`rig.py`, §A-§E) | final model (× 0.97749) |
| --- | --- | --- |
| skin height (sole of the foot to skull top, barefoot; `rig.stated_height`) | 1.555 | **1.520** (the user) |
| heel lift in the loafers | 0.035 | 0.0342 |
| skull top, standing in her shoes (`rig.final_height`) | 1.590 | **1.5542** |
| hair crown (`rig.final_hair_top_z`) | 1.606 | **1.5699** |
| ear-tuft tips (`rig.final_figure_top_z`; the model's highest point) | 1.614 | **1.5777** |
| eye centre | 1.459 | 1.4262 |
| chin | 1.388 | 1.3568 |
| head height (chin to skull top) | 0.202 | 0.1975 |
| high-waist seam | 1.108 | 1.0831 |
| skirt hem (flute crests) | 0.390 | 0.3812 |
| heads tall (crown height / head unit) | 7.37 | 7.37 |

Measured on the built model (`examples/reiya.json`): the highest vertex is a tuft tip at z 1.57767, the hair dome's top
1.56985, the head's 1.55421.

The rest of this document is at the sheet scale.

| quantity | value |
| --- | --- |
| skin height (sole of the foot to skull top, barefoot) | **1.555 m** (Decision 1: 1.520 m on the final model) |
| heel lift in the loafers | 0.035 (block heel 0.034 + insole) |
| skull top, standing in her shoes (`rig.height`) | **1.590** |
| hair crown | **1.606** (16 mm of hair on the crown); this row sets the sheet scale |
| ear-tuft tips (`rig.figure_top_z`) | 1.614 (8 mm over the crown) |
| chin | 1.388 |
| head height (chin to skull top) | **0.202** |
| head unit (chin to hair crown) | 0.218 |
| **heads tall** (crown height / head unit) | **7.37** (skin: 1.555 / 0.202 = 7.70) |
| skull (skin) at the brow line | hw 0.074, y -0.114 ... +0.078 (0.192 deep) |
| hair mass at the eyes | hw **0.120**, y -0.130 ... +0.105 (sheet) |
| hair mass widest (the bob's bell, at the nose) | hw **0.1235** at z 1.425-1.436 |
| shoulder point (white sleeve outside) | hw 0.113: the bob is about 1 cm wider than the shoulders |

**Face proportions.** Let E be the distance from the chin to the eye centre: E = 1.459 - 1.388 = 0.071, which is 0.35 of
the head height (the eyes sit low in a big cranium, the anime "baby schema").

| feature | z | height above the chin |
| --- | --- | --- |
| mouth (closed smile, middle) | 1.4127 | 0.35 E |
| nose tip | 1.4355 | 0.67 E |
| eye centre | 1.459 | 1.00 E |
| upper lash band: lower edge / top at the middle (x 0.041) | 1.4712 / 1.4762 | 1.17 E / 1.24 E |
| fringe lower edge (over her left eye) | 1.470-1.475 | 1.20 E |
| brow (her right, inner .. outer) | 1.4963-1.5024 | 1.53 E |
| skull top | 1.590 | 2.85 E |

### Landmark table

The body column is the outermost surface at that level (hair, skin or clothing, see the note). y values are at the
midline unless noted. `rig.landmarks` holds this table; the derived heights (`rig.chin_z`, `eye_z`, `seam_z`, ...) are
read from it.

| landmark | z | hw (x) | yf | yb | surface / note |
| --- | --- | --- | --- | --- | --- |
| ear-tuft tip | 1.614 | 0.064 (tip x) | -0.001 | 0.028 | tuft (yf / yb: the lobe's front / back edge); 8 mm over the crown (sheet front and back views; the side view's 1.620 is drawing noise) |
| hair crown | 1.606 | 0 | -0.015 | -0.015 | hair top |
| skull top | 1.590 | 0 | -0.012 | -0.012 | skin |
| brow | 1.499 | 0.074 (skin) | -0.114 | 0.078 | widest skull; brows 1.4963 inner .. 1.5024 outer |
| bang line | 1.475 | 0.115 (hair) | -0.131 (sheet fringe front) | 0.1046 (hair) | fringe tips 1.4705-1.4740 (centre lock B 1.4705); lock D's lower edge on the lash band |
| eye centre | 1.459 | 0.068 (skin) | -0.102 | 0.077 | eye centres x ±0.0395 (sheet ±0.041); hair hw 0.1203 |
| nose tip | 1.4355 | 0.058 | -0.1125 (bump) | 0.071 | face plane -0.105 |
| mouth | 1.416 | 0.0495 | -0.1025 | 0.061 | smile corners 1.4176, middle 1.4127 |
| chin | 1.388 | 0 | -0.077 | -0.040 | yb = neck front, where the jaw underside meets it |
| neck | 1.375 | 0.022 | -0.038 | 0.018 | visible from 1.366 to 1.387 |
| mock-neck rim | 1.364 | 0.029 | -0.0475 | 0.0285 | white top; lettuce waves ±1.5 mm (±1.1 at the sides) |
| neck base | 1.338 | 0.050 | -0.051 | 0.032 | the mock neck flares into the shoulders |
| shoulder | 1.300 | 0.113 | -0.083 | 0.050 | shoulder point (white sleeve outer); top hw 0.104 |
| neckline | 1.2765 | 0.0935 | -0.110 | 0.053 | square neckline of the bodice; straps x 0.0555-0.0885 |
| bust | 1.225 | 0.0925 | -0.1245 | 0.050 | bodice; apex x ±0.045 |
| high-waist seam | 1.108 | 0.0724 | -0.1103 | 0.0376 | the bodice's lower edge, 1 mm over the skirt; the narrowest is hw 0.0705 at z 1.116 |
| natural waist | 1.000 | 0.0955 | -0.1245 | 0.048 | skirt (body under it: body_rows, Decision 13) |
| hip | 0.860 | 0.1257 | -0.149 | 0.076 | skirt (body hip 0.100 / -0.080 / 0.060) |
| crotch | 0.775 | 0.1414 | -0.162 | 0.097 | skirt; the legs start at 0.730 |
| skirt hem | 0.390 | 0.2125 | -0.2215 | 0.179 | flute crests; level (Decision 9) |
| calf | 0.340 | 0.0985 | -0.0388 | 0.0412 | legs: centre x ±0.0595, r 0.039 |
| sock-cuff top | 0.255 | 0.0967 | -0.036 | 0.042 | turned-down cuff, leg + 6.2 mm (sheet edge 0.253-0.256) |
| sock-cuff bottom | 0.202 | 0.088 | -0.031 | 0.037 | drawn edge (sheet fold 0.201-0.205) |
| ankle | 0.085 | 0.0825 | -0.026 | 0.028 | ankle centre (±0.056, 0.000); sock r 0.026 |
| heel top | 0.034 | 0.083 | -0.012 | 0.035 | block heel (y range of the block) |
| sole | 0 | 0.0915 | -0.1525 | 0.035 | shoe outer x / toe / heel back; the feet parallel |

### Section models

All body sections are superellipses with `body_exponent` 2.4 (both halves) unless stated; interpolate rows linearly
in z.

**Body under the clothes** (`body_rows`, *(guide)*: hidden, the legs' top and what the skirt hangs over):

| z | hw | yf | yb |
| --- | --- | --- | --- |
| 1.108 | 0.066 | -0.103 | 0.031 |
| 1.000 | 0.074 | -0.090 | 0.035 |
| 0.900 | 0.095 | -0.082 | 0.056 |
| 0.860 | 0.100 | -0.080 | 0.060 |
| 0.775 | 0.096 | -0.070 | 0.052 |

**White top's torso** (`top_rows`, outer surface; the shoulders are the cardigan-off view's slope, about 27° from the
neck to the shoulder point; the white sleeve tube adds the upper arm outside):

| z | hw | yf | yb | note |
| --- | --- | --- | --- | --- |
| 1.349 | 0.0318 | -0.0488 | 0.0298 | the mock neck flares into the shoulders: a smooth concave flare (review r2-L11) |
| 1.346 | 0.036 | -0.0495 | 0.0305 | (sheet OFF outline hw 0.0356) |
| 1.342 | 0.042 | -0.050 | 0.031 | the fold (`top_fold_z`), where the flare meets the shoulders (sheet ~0.041) |
| 1.336 | 0.060 | -0.054 | 0.034 | |
| 1.330 | 0.072 | -0.058 | 0.038 | |
| 1.322 | 0.087 | -0.064 | 0.043 | |
| 1.312 | 0.099 | -0.072 | 0.047 | |
| 1.300 | 0.104 | -0.083 | 0.050 | shoulder point level |
| 1.276 | 0.091 | -0.106 | 0.0505 | neckline level |
| 1.258 | 0.090 | -0.114 | 0.049 | armpit |
| 1.225 | 0.0885 | -0.1185 | 0.0465 | bust (inside the bodice) |
| 1.190 | 0.0815 | -0.1155 | 0.0425 | ends here, buried in the bodice |

**Dress bodice** (`bodice_rows`, outer; front half exponent 2.2, back half 2.5) and **skirt** (`skirt_rows`, outer at
the flute crests, exponent 2.1): see §D.3 and §D.4.

**Cardigan** (`cardigan_rows`, the panels' inner reference surface; the panels are 6 mm thick outward): see §D.6.

---

## B. Head and face

### B.1 Skin head profile

One closed shell for skull and face (object `head`). The hair covers the skull above the hairline and behind the face
opening. `rig.head_profile` (z, hw, yf, yb):

| z | hw | yf (face plane, midline) | yb | note |
| --- | --- | --- | --- | --- |
| 1.590 | 0 | -0.0120 | -0.0120 | skull top |
| 1.582 | 0.034 | -0.0460 | 0.0200 | |
| 1.570 | 0.050 | -0.0700 | 0.0400 | |
| 1.555 | 0.060 | -0.0880 | 0.0560 | |
| 1.540 | 0.067 | -0.1000 | 0.0650 | |
| 1.522 | 0.072 | -0.1080 | 0.0720 | |
| 1.505 | 0.074 | -0.1125 | 0.0765 | forehead |
| 1.495 | 0.074 | -0.1140 | 0.0780 | brow line: widest skull, forehead front (sheet -0.1138) |
| 1.482 | 0.073 | -0.1110 | 0.0785 | |
| 1.470 | 0.071 | -0.1060 | 0.0780 | upper lid |
| 1.459 | 0.068 | -0.1020 | 0.0770 | eyes, the bridge (sheet -0.1021); 4 mm wider than the visible skin |
| 1.447 | 0.064 | -0.1030 | 0.0745 | lower lid (sheet visible skin hw 0.060) |
| 1.436 | 0.058 | -0.1050 | 0.0710 | nose (the bump is separate) |
| 1.426 | 0.0535 | -0.1055 | 0.0665 | |
| 1.416 | 0.0495 | -0.1025 | 0.0610 | mouth |
| 1.410 | 0.0455 | -0.0985 | 0.0560 | |
| 1.404 | 0.0385 | -0.0925 | 0.0490 | the jaw narrows fast (a small V chin) |
| 1.400 | 0.0310 | -0.0880 | 0.0440 | last back row |
| 1.396 | 0.0235 | -0.0845 | (neck) | |
| 1.392 | 0.0145 | -0.0810 | (neck) | |
| 1.389 | 0.0075 | -0.0785 | (neck) | |
| 1.388 | 0 | -0.0770 | (neck) | chin bottom |

- **Cross-section at height z:** front half `|x/hw|^3.6 + |(y-c)/(c-yf)|^3.6 = 1` (`face_front_exponent`), back half
  the ellipse with semi-axes `(hw, yb - c)`. The widest-point offset c is -0.012 for z ≥ 1.47, -0.008 for z ≤ 1.41,
  linear between (`face_center_offset`). The flat front keeps the eyes from wrapping round the face (they wrap 2.0 cm in
  depth across their 3.95 cm, Decision 4). `rig.head_surface_y(x, z)` and `rig.head_normal(x, z)` evaluate it.
- **Jaw underside** (y, z): (-0.077, 1.388) → (-0.065, 1.3885) → (-0.052, 1.3895) → (-0.040, 1.392), nearly level
  (sheet side view), meeting the neck front. Several jaw rings must turn under into the neck (no flat shelf: the
  Miki lesson). The back of the head curves into the nape at (y 0.030, z 1.392).
- **Nose:** a small bump in the skin mesh only (`rig.nose_bump`): tip (0, -0.1125, 1.4355), 7.5 mm proud of the face
  plane (sheet profile ~10 mm, Decision 5), half-width 6 mm, from the bridge at z 1.452 to the upper lip at 1.4285
  (cosine falloff). No nostrils and no mark: in the line drawing it shows only as a silhouette in profile.
- **Face-surface y** at the feature points (place the features with these; `rig.face_y` includes the nose):

  | point (x, z) | y |
  | --- | --- |
  | eye centre (±0.0395, 1.459) | -0.0982 |
  | eye inner corner (±0.0195) | -0.1017 |
  | eye outer corner (±0.059) | -0.0816 |
  | brow inner (±0.028, 1.4963) | -0.1129 |
  | brow outer (±0.054, 1.5024) | -0.1026 |
  | mouth middle (0, 1.415) | -0.1018 |

- **Cheek bulge** (`cheek_bulge`, review r2-L3): behind the bob's front edge the head mesh's last front column (y ≈
  -0.037) moves out 2.6-3.2 mm over z 1.408-1.500, hidden under the curtain, so in the front views the skin's outline
  lies behind the curtain and the cheek line is the curtain's edge (head_front margin 0.45-2 mm).
- **Ears: not modelled** (Decision 22). The bob hides them in every view of the sheet.

### B.2 Eyes

The eyes are big, set low and wide, **gently drooping outward** (tare-me), with a thick dark upper lash band and no
lower lid line. **Heterochromia: her right
eye (x < 0) is red, her left eye (x > 0) is blue.** Each eye is a stack of thin closed slabs conforming to the face
(objects `eye_l` / `eye_r`); their back faces sit 0.3 mm below the skin.

| item | value |
| --- | --- |
| eye centre | (±0.0395, 1.459), surface y -0.0982 (sheet x ±0.041) |
| opening (chord) | inner corner x 0.0195 to outer corner x 0.059 (3.95 cm; the sheet's lash line spans 0.023-0.067, the lash flick reaches 0.066) |
| inner-corner gap | 0.039 (about one eye width) |
| upper boundary (lid line) | (0.0195, 1.4708), (0.0295, 1.4716), (0.041, 1.4712), (0.0525, 1.4688), (0.059, 1.4661): highest at the inner-middle (x 0.03-0.04), falling 5.5 mm to the outer corner; it droops ~10° outward (sheet 9.5-11°). It is the sheet's lash lower edge (both eyes averaged) about 0.5 mm lower, so the band covers the top of the sclera |
| lower boundary (sclera) | (0.0195, 1.4698) → (0.023, 1.4560) → (0.0305, 1.4485) → bottom (0.0395, 1.4458) → (0.049, 1.4475) → (0.0555, 1.4540) → (0.059, 1.4651) (each end 1 mm under the lid line) |
| iris | ellipse 0.025 × 0.030, centre (±0.0395, 1.459): its top 2.7 mm above the lid line (inside the lash band, 2.2 mm under its top), its bottom clipped by the lower boundary (the sheet's iris fills the opening's height) |
| pupil | the iris's dark upper part: ellipse 0.016 × 0.012, centre z 1.468; its top tucks under the lash band (2.2 mm under the band's top), so only its lower arc draws: a dark cap under the lash with the big highlight in it (review r2-L2: a closed circle 1.4 mm under the lash read as looking up) |
| highlights | one per eye, the same on both eyes (light from the upper left): Ø 4.5 mm at (cx - 0.003, 1.466) (review r4-L3: a second one, Ø 2 mm at (cx + 0.0055, 1.4515), printed as a black dot at the scene camera's scale and read as a low pupil looking down-right) |

The sheet's iris is a gradient (dark top, middle tone, light bottom: red `#9f2a29` / `#d25754` / `#ffc1b3`, blue
`#2a3944` / `#6387a6` / `#c4e3e6`). The model keeps two tones (iris + pupil): a third slab would draw a line across the
iris (Decision 24).

**Layer stack** (front face above the skin; slabs never coplanar; the walls undercut 2.2 mm):

| layer | object | material | above the skin |
| --- | --- | --- | --- |
| sclera | `eye_l` / `eye_r` | `eye_white` | 0.6 mm |
| iris | `eye_l` / `eye_r` | `iris_red` / `iris_blue` | 1.0 mm |
| pupil | `eye_l` / `eye_r` | `pupil_red` / `pupil_blue` | 1.3 mm |
| highlight | `eye_l` / `eye_r` | `eye_white` | 1.6 mm |
| upper lash band | `face_marks_l` / `face_marks_r` | `lashes` | 1.4 mm, overlapping the top of sclera and iris |

**Upper lash band:** thick, flat and dark (the sheet's line is 7 mm tall at its thickest). Its lower edge runs from
(±0.0205, 1.4714) along the lid line to (±0.060, 1.4660), drooping outward with it (5.4 mm lower at the outer end); its
height is 1.0 / 3.6 / 5.0 / 5.2 / 4.5 mm at x 0.0205 / 0.0295 / 0.041 / 0.0525 / 0.060 (`lash_height` plus
`lash_height_quarters`): a smooth arc with no peak in the middle (review r2-L6: three stations made a pointed roof, a 22° turn at the middle), a
tapering point at the inner end (review r1-L11: 2.8 mm ended square), measured on her right eye, which the fringe does
not cover (on her left eye the fringe hides the band's top). The band rises 0.5 mm over the pupil, moved column by
column so it never folds. At the outer end a **flick** 2 mm wide runs out and down to (±0.0665, 1.4640). No lower lash
mark (the sheet has none).

### B.3 Brows

Thin, high (2.5 cm above the lash band's lower edge, 2.1 cm above its top), **the inner end lower** (her right brow on
the sheet slopes down 13° towards the centre). Inner end (±0.028, 1.4963), middle (±0.041, 1.5005), outer end (±0.054,
1.5024); width 1.6 mm tapering to 1.0 mm; raised 0.8 mm (material `face_marks`). Her left brow lies under the fringe:
modelled, normally hidden.

### B.4 Mouth and blush

- **Mouth:** a closed gentle smile, a U from the corners (±0.0165, 1.4176) to the middle (0, 1.4127): 3.3 cm wide,
  4.9 mm of sag, band 0.6 mm, raised 0.8 mm (review r3-L4: at 1.2 mm both borders drew a closed double line in
  close-ups; at 0.6 mm it reads as one stroke, as on the sheet). Mouth to chin 2.5 cm, nose tip to the corners 1.8 cm.
- **Blush (Decision 6):** the sheet's three short hatch strokes under each eye are modelled as decals: 3 strokes per
  cheek, 6 mm × 0.5 mm (review r2-L7: at 0.9 mm they drew as outlined boxes; at 0.5 mm the two long borders merge
  into one hatch stroke), 3.5 mm apart, tilted 70° from horizontal (the same lean on both cheeks, as drawn), centred at
  (±0.050, 1.4375), raised 0.72 mm (0.70 mm on the final model, Decision 1). The blush colour ovals are not modelled (a
  decal always draws its outline).

---

## C. Hair (the most important part for likeness)

**Colour:** salmon pink `#f2b5a7` (palette swatch 1). The underside is lavender `#e1d7ef` (the sheet's jaw gaps and the
3D render).

**Parts** (all closed shells):

| id | part | object |
| --- | --- | --- |
| H1 | dome | `hair` |
| H2 | fringe (swept lock SL + 4 wide locks A-D) | `fringe` |
| H3 | bob: side curtains + back bell with layered locks, cut into three shells (§C.3) | `bob_l`, `bob`, `bob_r` |
| H4 | lavender under-layer: a lining strip per side + one V-shaped under-lock per side (Decision 7) | `hair_under` |
| H5 | ear tufts ×2 with their inner faces | `tufts` |
| H6 | braids ×2 (lobes, tie, end tuft) | `braid_l`, `braid_r` |

**Outer silhouette of the hair mass** (`rig.hair_rows`, from the sheet's front and side views; section exponent 2.3
front, 2.2 back). The crown is **flat and wide**: the top rows' hw fit the front and back views' drop below their own
crown (2.3 / 5.2 / 9.8 / 13.2 / 31.9 / 39.9 mm at x 0.025 / 0.037 / 0.049 / 0.057 / 0.075 / 0.081; sheet 2.5 / 5.5 /
9.2 / 12.8 / 32.0 / 39.2), so the tufts stand on a high dome:

| z | hw | yf | yb | note |
| --- | --- | --- | --- | --- |
| 1.606 | 0 | -0.0150 | -0.0150 | crown |
| 1.604 | 0.0240 | -0.0247 | -0.0017 | (yf / yb on the line to the next row) |
| 1.600 | 0.0400 | -0.0440 | 0.0250 | |
| 1.592 | 0.0590 | -0.0710 | 0.0410 | |
| 1.582 | 0.0680 | -0.0890 | 0.0550 | the tufts sit here |
| 1.573 | 0.0760 | -0.1020 | 0.0650 | |
| 1.563 | 0.0835 | -0.1100 | 0.0720 | |
| 1.548 | 0.0900 | -0.1185 | 0.0805 | |
| 1.533 | 0.0950 | -0.1255 | 0.0873 | |
| 1.518 | 0.1005 | -0.1298 | 0.0935 | |
| 1.504 | 0.1058 | -0.1322 | 0.0984 | |
| 1.489 | 0.1105 | -0.1328 | 0.1021 | |
| 1.474 | 0.1150 | -0.1310 | 0.1046 | |
| 1.459 | 0.1203 | -0.1298 | 0.1052 | eyes (= `bob_rows`; the bob widens further, to hw 0.1235 at z 1.43) |

Below z 1.50 the yf column is the sheet's fringe front; the model's fringe lies closer to the face (C.2).

**Hair thickness over the scalp** (`hair_thickness`, the minimum): crown 0.016, front hairline 0.014, sides 0.026,
back 0.020. The silhouette gives 0.026-0.050 at the sides above the ears (the bob's volume: the side curtain stands
out) and 0.020-0.028 at the back.

### C.1 Dome (H1)

The top hair: one smooth shell from the crown down to the bob, lofted through `hair_rows` (the sheet's silhouette),
closed by a cap buried in the skull at about z 1.50. Its front boundary is the hairline: hidden under the fringe on
her left, and on her right it follows `hairline_right` (TRUE x) from the parting down to the temple: (-0.028, 1.569),
(-0.038, 1.545), (-0.047, 1.520), (-0.055, 1.492), (-0.062, 1.470). Below that line on her right the forehead skin
shows (C.2); the swept lock SL lies along it on its outer side. The dome carries the parting as a shallow groove from
(-0.028, 1.569) back towards the crown *(guide; not built, §F)*.

*(Review round 1.)* The dome's bottom ring is level all round at z 1.488 (`hair.DOME_FRONT_BOTTOM_Z` = `dome_bottom_z` −
`hair.DOME_SIDE_DROP`; it was 1.470 at the front), so the curtain's top corner no longer leaves the dome's lower rim as
a dash beside the eye (r1-L5). The crown's first ring is the second ring scaled towards the pole
(`hair.DOME_CROWN_SCALE` 0.6, lifted `DOME_CROWN_LIFT` 0.8 mm): a convex crown without the valley folds that dashed the
head-top outline in 3/4 views (r1-T4). The dome's constant-z rings (`hair.DOME_RING_Z`) are the hair rows plus z 1.596
and 1.587 between them, so the crown's facets stay small and the head-top outline is whole from every azimuth (review
r2-T1: 22 missing columns at az 060 / 300 → 0).

*(Finishing pass, the seam with the new bob.)* With 13 bob columns per side against the dome's 5 the two shells lay
within ±2 mm of each other over 15 mm of height and crossed back and forth (a crenellated seam in the shaded views).
Behind φ 52° (`hair.DOME_SEAM_FRONT_PHI`) the dome's three lowest rings take the bob's own contour columns at the bob's
rows 1.517 / 1.495 / 1.481 (`hair.DOME_SEAM_MATCH`), 0 / 3 / 5 mm inside the bob's unshrunk outer surface
(`DOME_SEAM_TUCK`, tied to `BOB_BELL_ROWS[1:4]`): the facets are parallel, so the seam is a straight level line at
about z 1.506 in every column; the rings above zip onto them by angle. The dome keeps its own facets above (M10 / M11,
P2, fail: 32.5° / 33.6°); the switch `hair.DOME_SMOOTH` (every ring on the bob's columns plus a ring at 1.5775 over the
temples) passes both (27.0° / 24.8°) for +161 polygons / +358 triangles and is off (§G, Decision 32).

### C.2 Fringe (H2): swept to her left from a parting on her right

- **Parting** (TRUE x): (-0.028, 1.569), the apex of a tall triangle of **exposed forehead on her right**, bounded by
  the hairline (`hairline_right`, with the swept lock SL outside it) and lock A; her right brow shows in it.
- **Locks** (`fringe_locks`, TRUE x, her right → left): the sheet draws a narrow **swept lock** plus **four wide locks**
  whose bottom is nearly level at the upper lash, split by strand lines (not a comb of pointed locks). Each lock is its
  own shell, rooted under the dome along the hairline; it keeps its width down to `fringe_taper` (30 %) of its length
  above the tip and only then tapers, so the notches between locks are at most 10 mm deep; neighbours overlap about
  2 mm and alternate ±0.6 mm in depth so their surfaces never coincide.

| # | root (x, z) | tip (x, z) | root width | tip | note |
| --- | --- | --- | --- | --- | --- |
| SL | (-0.026, 1.569) | (-0.063, 1.4717) | 0.012 | pointed | the swept lock from the parting along the hairline on her right (its inner edge is `hairline_right`); its tip over her right lash's outer end |
| A | (-0.022, 1.565) | (-0.009, 1.4717) | 0.020 | pointed | its edge bounds the exposed forehead |
| B | (-0.006, 1.563) | (+0.003, 1.4705) | 0.022 | blunt, 12 mm wide | the centre lock between the eyes (sheet flat bottom x -0.007 ... +0.008) |
| C | (+0.004, 1.560) | (+0.014, 1.4729) | 0.022 | pointed | a notch 9 mm deep between B and C; leans 6.5° to her left (review r2-L13) |
| D | (+0.028, 1.554) | (+0.048, 1.4740) | 0.030 | pointed | leans 14° to her left (a root further in makes `_hairline` pick up `hairline_left`'s (0.028, 1.569) and spikes the dome's hairline); over her left eye: its lower edge (`fringe_lower_edge`) (0.018, 1.4745) → (0.034, 1.4752) → tip → (0.062, 1.4700) runs along the top of the lash band (from its lower-inner corner just outside lock C's tip: the sheet's lock rests on the lash from x 0.015; a start at x 0.034 left a 20 mm V of forehead between C and D), 0.5 mm over it, and merges into her left curtain's front edge |

- **Thickness** 0.004. The inner surface lies 3 mm off the skin at the roots and 5 mm at the tips (`fringe_gap`), so
  the tips' front surface is 4.5-12 mm (true distance) from the skin and the far eye shows in 3/4 views (review
  r1-L2: 9 mm thick and 4-9 mm off, the locks stood 18-27 mm off the face as a visor over the far eye). The sheet's
  profile shows the fringe 2-3 cm in front of the face, a drawing convention (Decision 8).
- Over her left eye lock D rests on the lash band (its lower edge overlaps the band's top 0.5 mm in the front view, so
  no skin shows between, as on the sheet, where the fringe hides the top of that band).
- Each lock's surface is one smooth group: its outline draws as the strand lines of the sheet. They lean 6-14° to her
  left (A 13°, B 7°, C 6.5°, D 4-14°; the sheet's strand lines 10-15°).

### C.3 Bob (H3): side curtains and back

One closed shell from z 1.54 (inside the dome) down to the locks' tips: a **crescent** that opens towards the face,
built in two zones, the **bell** above z 1.452 and the **lock zone** below it (finishing pass, 2026-10-31: the user's
review called the earlier bob "a faceted helmet" with a sawtooth lower edge). Its outer profile is `bob_rows` (z,
outer hw, outer back y, front edge x, front edge y, thickness). The bob is a **bell**: it keeps widening below the eyes
to hw **0.1235 at the nose** (z 1.425-1.436) and then curves in to long tapered locks (no flip); the back curls in
under to the nape. For the hidden-line pass the shell is cut into three (the last bullet).

| z | hw | yb | front edge (x, y) | t | note |
| --- | --- | --- | --- | --- | --- |
| 1.520 | 0.1015 | 0.0950 | (0.0750, -0.090) | 0.018 | starts under the dome / fringe at the temple |
| 1.495 | 0.1085 | 0.1010 | (0.0715, -0.070) | 0.020 | the curtain's top corner kept off the dome's lower rim (no temple dash) |
| 1.474 | 0.1150 | 0.1046 | (0.0716, -0.0635) | 0.021 | a mesh row (`hair.BOB_ROW_Z`): the edge follows the wide temple |
| 1.459 | 0.1203 | 0.1052 | (0.0667, -0.053) | 0.022 | eyes; 1.459 and 1.445 are sampled together at z 1.452 (a mesh row): the front edge 2.6 cm behind the eye's outer corner |
| 1.445 | 0.1227 | 0.1040 | (0.0667, -0.053) | 0.022 | (see 1.459) |
| 1.430 | 0.1235 | 0.1010 | (0.0556, -0.058) | 0.021 | **widest** (sheet front / back hw 0.1233 at z 1.422-1.437); a mesh row |
| 1.415 | 0.1217 | 0.0960 | (0.0478, -0.064) | 0.019 | |
| 1.408 | 0.1180 | 0.0920 | (0.0425, -0.072) | 0.017 | the side tips start at 1.405 |
| 1.403 | 0.1140 | 0.0900 | (0.0430, -0.0715) | 0.016 | back curl (only the back columns reach below z 1.405) |
| 1.398 | 0.1080 | 0.0640 | (0.0400, -0.071) | 0.015 | |
| 1.385 | 0.0900 | 0.0500 | (0.0400, -0.071) | 0.012 | at the nape (the back centre ends at 1.378) |

Sheet: front-view hw 0.1196 / 0.1221 / 0.1233 / 0.1215 / 0.1175 at z 1.459 / 1.445 / 1.422-1.437 / 1.415 / 1.408, the
back view the same; the side view's back edge 0.1046 / 0.1021 / 0.0984 / 0.0947 / 0.0904 / 0.065 / 0.058 / 0.049 at z
1.445 / 1.430 / 1.415 / 1.408 / 1.403 / 1.400 / 1.390 / 1.386. The front edges of the rows below 1.403 only matter for
the front tips at z 1.399. *(Review round 1 moved the front edges of the rows 1.495-1.408 in and forward: r1-L3,
r1-L5. Review round 2 moved the rows 1.474-1.415 back again, with the hidden `cheek_bulge` (§B.1): r2-L3. The mesh rows
were `hair.BOB_ROW_Z` (1.540, 1.495, 1.474, 1.452, 1.430) until the finishing pass; a sixth row gave the bob 66-69
rays, over the cap. The finishing pass reads the table through a monotone cubic, see the bell below.)*

- **Section geometry.** The outer contour of a row is the hair mass's section at that height (`rig.hair_section` above
  z 1.459, whose hw / yb the rows repeat; the rows' hw / yb below it). The outer contour at `front_y` lies 3-5 cm
  outside `front_x`, more than the thickness t, so the crescent cannot simply end in a blunt face there: towards the
  face it **turns inward along a front face** (the curtain's front, facing -y) from the outer contour at `front_y` to
  the inner edge (`front_x`, `front_y`). The inner surface runs from there round the inside at t inside the outer
  contour and follows the face and the skull at ≥ 3 mm. The inner edge (`front_x`, `front_y`) is the drawn
  face-window line; the front face's border with the outer surface draws as the curtain's outer edge.
- **Front edge** (the face opening): the edge stands 1-2 mm off the faceted skin (0.94-2.15 mm at z 1.415-1.482,
  0.6-0.7 mm at the temple, z 1.488-1.495). The hidden cheek bulge (§B.1, `cheek_bulge`) puts the skin's outline behind
  the curtain, so in the front views only the curtain's edge draws as the cheek line (head_front margin 0.45-2 mm; the
  sheet's curtains: inner edges x 0.060 / 0.052-0.055 / 0.049-0.052 at z 1.445 / 1.430 / 1.415; review r1-L3: a second
  cheek line). In profile it sweeps back from y -0.070 at the temple to -0.056 at the eye line and -0.053 at z 1.452
  (2.6 cm behind the eye's outer corner, 4.6-4.9 cm of cheek), then forward to the A-line tips beside the jaw (a '('
  sweep; review r2-L3: at 1.2 cm behind the eye only 3.2 cm of cheek showed, the sheet has 7-8 cm). The curtain's inner
  rim leans 8 mm outward (`hair.BOB_EDGE_UNDERCUT`), clearing the bulge by ≥ 3 mm. *Known limit:* far-cheek views 5-15°
  off the front show the edge as a parallel stroke about 1 mm outside the face outline.
- **Innermost front tips** (`bob_front_tip`): (±0.039, -0.070, 1.399), φ ~30° from the origin: the curtains' lowest
  locks curve in under the cheeks. The sheet draws them on the jaw outline at z ≈ 1.408; the tip sits lower to keep ≥ 3
  mm of skin clearance (6.7 mm in 3D at 1.399; 3.7 mm at 1.404, 1.4 mm at 1.407): **never above z 1.404**.
- **The bell** (above `bob_slit_top_z` 1.452): rows 1.540 / 1.517 / 1.495 / 1.481 / 1.466 (`hair.BOB_BELL_ROWS`, the
  inner surface the same); the rows above 1.495 (`BOB_BELL_SURFACE_Z`) shrink into the dome by the height fraction
  squared (`BOB_BELL_INSET_POWER`; the top row 8 mm inside it, `BOB_TOP_INSET`), so no crease shows where the bell
  leaves the dome; above the table's top row the hair silhouette's rows. Columns: each curtain's inner edge (the
  face-window line), one column across its flat front face (`BOB_BELL_FACE`), the outer corner, **13 contour columns
  per side** (`BOB_BELL_CONTOUR`, was 5) and the back centre. The contour columns sit at even turning of the section's
  tangent (`BOB_BELL_TURN`; the back superellipse turns twice as fast at its diagonals, azimuth 130-160°, as at the
  side), about 9° per column. `bob_rows` are read through a monotone cubic (no kink at the table's rows); the front
  face's depth is averaged over 30 mm (`BOB_FRONT_SMOOTH`: the table's '(' sweep turned 35° in 2 cm at the eye line)
  and its lean above the dome's edge is halved (`BOB_FACE_TOP_LEAN`: the curtain's front-top tab folded 27°, now 16°).
  The strip joining the bell's last row to the lock zone's top row zips by the shorter diagonal (`hair._zip_param`, V4
  pass: advancing the row whose next point came first put a fan triangle's apex outside its base wherever two lock
  columns fell between two bell columns; the skewed facet stood 2-4° steeper than the bell: 23.6° at the back centre,
  13.2° beside the back slit). Measured (the overlay check, Decision 31; V4 pass): the largest visible dihedral inside
  one smooth group 19.7° (M3, ≤ 25°; 23.6° before), 95 % ≤ 11.8° (M4, ≤ 12°; 11.93° before); the bell's visible
  outline turns ≤ 12.0° in the 3/4 and low views (M1, ≤ 20°).
- **The lock zone** (`bob_lock_columns`, 21 columns her left, mirrored, from the face-window edge round to the nape):
  the curtain's front locks (the edge column, four front-face columns, the front slit's inner side), a slit, the side
  lock (its front edge, three columns at φ 84 / 90 / 102°, its back edge), a slit, the back locks (the back slit's
  inner side, six back columns) and the nape (the back centre). The locks are **layered**: each tip sits at the lock's
  inner end (face side in front, nape side at the back) and each lower edge rises outward; a **step** ends a lock on its
  neighbour's column above that column's own tip (the sheet's front view: tips at |x| 0.069 / 0.092 and the side strand
  0.115, notches 0.0687 / 0.0915; back view: tips 0.092 / 0.070 / 0.030, the nape 1.374). Rows about every 18 mm
  (`hair.BOB_LOCK_ROW_STEP`, 2-5 strips per lock, `BOB_LOCK_STRIPS`), the front columns every 8 mm
  (`BOB_FRONT_ROW_STEP`). Each lock thins to 20 % of the bob's thickness below z 1.428 (`BOB_TIP_THIN`,
  `BOB_LOCK_MID_Z`; the back locks thin by 20 % already above it, `BOB_LOCK_PRE_THIN`) and curls in 1 mm at its edge
  (`BOB_TIP_CURL`). Against the sheet (Decision 31): the lowest tip per side within 0.6 mm in height (H2), the lower
  edge at the sides 4.9 mm off per column on average and 10.8 mm at the 95th percentile (H3, H4; the old row of 20 mm
  teeth: 11.0 / 40.5 mm; before the leaf pass 5.2 mm), the nape within 0.6 mm (H5). `bob_hem_z`, `bob_tips`,
  `bob_tip_depth` and `bob_tip_depth_back` describe the old tip line: only the mannequin reads `bob_hem_z`, the others
  are spec only.
- **Leaf-shaped lock ends** (leaf pass, 2026-11-01: the user's "add leaf-shaped tips"; criterion M2). Seen
  obliquely, a layered lock end with straight edges projected to corners of 20-58° (M2 45.1°). Four changes, all in
  the lock zone, the table's columns and their indices unchanged:
  - **Inserted columns** (`bob_leaf_columns`, `(after, frac, kind, a, z_bottom)` for kind "back" and
    `(after, frac, "backc", a, z_bottom, phi_top)` for kind "backc", 5 per side): `after + frac` (0 < frac < 1, each
    used once; checked, `ValueError`) is only the column's stable index, its place in the order and its label, between
    the table's columns (the strand / split indices 15 and 18 stay valid); it moves no point. A "back" column lies on
    the surface between its two neighbours (their points blended at the fraction that puts its tip's x at `a`, at the
    same fraction of their height: the bell's facets stay), only its lower end moved onto its lock's leaf curve over
    its last 12 mm (`hair.BOB_LEAF_PLAN_H`); its inner points blend the neighbours' the same way. A "backc" column (V4
    pass, 2026-11-01: the two beside the back slit) lies on the contour itself like the table's back columns, its
    azimuth running from `phi_top` at the top row to that of x = `a` at its tip, its rows a table column's (the middle
    row kept down to a 2 mm lock end, `BOB_LEAF_ROW_GAP`, so the zips pair it with its neighbours), its inner points
    the blend above lowered in proportion to the height, and its eased rows moved along the normal into the plane of
    the strip towards the slit (the quad between columns 14 and 14.51 was twisted 0.2 mm by the two columns' different
    drift with the depth, and the 40° presets and three_quarter_back see that strip edge-on: a 6 px loop). The back
    lock (tip at column 15) now
    curves up from its tip at 28° to the back slit's end (columns 13.66 at (0.1055, 1.4214) and 14.51 at (0.096,
    1.4092), column 14 at 1.4128: three 11° turns of the curve in x-z from the slit's end to the tip), the next lock
    (from the step at column 15) falls at 47° from its notch and flattens towards column 17 (columns 15.48, 16.23,
    16.57; column 16 at 1.4062), as the sheet's back view draws them (convex flanks, 35 -> 59 -> 81° and 47 -> 25°).
  - **A closed tip** (`hair.BOB_CLOSED_TIPS = (15,)`): the back lock's inner surface meets its outer one at the tip
    (one vertex), so the lock thins into a point and the outline no longer runs across a 2-3 px rim beside it (the
    48-53° corner); the point now ends the outline's chain in the three review views.
  - **The side lock's front corner** is its shoulder: the front edge's rows below z 1.428 are a circular arc
    (`bob_side_corner_radius[0]` 19 mm, `hair.BOB_SIDE_CORNER_SEGMENTS` 7, the angle steps `BOB_SIDE_CORNER_STEPS`
    0.10 / 0.23 / 0.24 / 0.14 / 0.10 / 0.10 / 0.10 of the arc's angle) tangent to the edge and to the lower edge
    (before: 36° + 30° in two vertices; the leaf pass: 16 mm, steps by the power `BOB_SIDE_CORNER_EASE` 0.8). V4 pass:
    the 3/4 views foreshorten the arc's end along the lower edge to 0.57 and see its start on the edge nearly full
    size, the low view the reverse, so the steps are small at the start, largest in the arc's upper half and 9-10°
    over its last three: the last two chords stay 1.3 px long (the metric drops segments under 1 px and merges their
    turns) and their turns 11.0 / 13.7°. The next side column moved from φ 78° to 84° (its tip at z 1.4075, 14 mm
    behind the arc's end): at 78° the lower edge's 2 mm step in x from the edge strip to the lock's body folded 15°
    from below. The 90° column's tip is at z 1.4070 (1.4058 before: between the 84° and 102° tips at 1.4075 it drew a
    13.5° turn in the 3/4 views). The 84° column's middle row, z 1.4155, comes in onto the line between its rows above
    and below, in x only (bulging out past the arc it made the low view's outline run down the arc and back, a 3 px
    spur); the 90° column's eased row, z 1.4152, is not tucked and ends a short chain of outline in the low view
    (tucking it too costs H3 / H4).
  - **The side lock's back corner** is its point (`bob_side_corner_radius[1]` 0): the back edge runs straight from
    z 1.428 to a tip 6 mm towards the lock from and 2 mm below the corner of the two edges' lines
    (`bob_side_back_tip` (-0.006, 0.0020); 2.5 mm until the V4 pass: with the 90° tip raised the 3/4 views read the
    drop at the next column as a 12° turn), so the lower edge falls into a point at the lock's back and the back edge
    leans down and forward, as the sheet's profile strokes there do; from below it reads over 60° (a designed tip;
    before: 58° + 20°). The lower edge's last stretch is the side lock's 0.6 mm edge strip, 17.5 mm long; with the tip
    6 mm behind the corner it was 29 mm, leaning back against the sheet's strokes, and read as a long thin blade from
    below. The tip itself carries no counted turn (its strip projects under 1 px in the three review views and merges
    into its neighbours' turns).
  Measured (Decision 31; the V4 pass, 2026-11-01): the bob's visible outline turns ≤ 13.7° in the 3/4 views and
  ≤ 13.4° in the low view, 95 % ≤ 11.3 / 11.8 / 11.8° (M2, ≤ 15°; the leaf pass: 14.8 / 14.4°, 13.8 / 13.7 / 13.3°),
  the smallest counted segment 1.3 px (the arc's last chords) in the 3/4 views and 2.3 px in the low view; M1, M3, M4
  and H1-H14 hold (H3 5.2 -> 4.9 mm). The leaf ends cost +148 polygons / +196 triangles (§G; the budget, Decision 32).
  **The back slit's end** (V4 pass): the leaf pass left one fold loop per 3/4 view, on the near side, where the outline
  traced a back-facing sliver triangle between the back slit's end (column 13, tip at z 1.437) and the chord column
  13.66, a 5 px loop. The 3/4 cameras graze the back lock's surface along a nearly vertical line just behind the slit
  (x 0.104-0.107 at z 1.418-1.452), and the chord column lay 1.5-3 mm inside the surface across that line, so the
  facets' azimuths were not monotone across the columns (28-38° | 24-33° | 37-43°): an island. Column 13.66 is now a
  "backc" column on the contour along that line (`phi_top` 123°, tip (0.1055, 1.4214); the surface's normal 1.5°
  beyond the grazing azimuth, so the strips on both sides face the cameras by 2.5-3°), the slit's wall (column 13)
  keeps its three rows (two rows made the wall one quad joined to the inner group, M3 58°), and columns 13.66 / 14 /
  14.51 do not curl in at the tip (`hair.BOB_LEAF_NO_CURL`: a curled tip 3-9 mm below the row above tilted the facet 6°
  towards the cameras, which look up, and the outline zigzagged along that lip in sub-pixel steps). The silhouette now
  runs down column 13.66 to its tip and on to column 14's: no fold or tip vertex in the lock zone in the three views,
  none in the 40° / top presets (three_quarter_back: a 6 px loop on column 14, removed by the planar eased row above;
  back: the nape's six, unchanged). The inner surface keeps one 18° dihedral pair at the slit end's inner tip (the
  blend's thick-to-thin step over 3 rows; M4 holds).
- **Two slits per side** (`bob_slit_x` 0.1130 / 0.1146, from the tips up to z 1.452): the curtain's front locks and
  the back locks end at x 0.1130, the side lock's inner face is flat at 0.1146, so the front and back views see
  background through the slits: the sheet's standing-off outer strand (its back view: a gap at x 0.1116-0.1165 up to
  z 1.44-1.46; without it the lower edge's 95th percentile is 25-40 mm, H4). Each slit narrows over its top 8 mm
  (`hair.BOB_SLIT_V`) to a closed V (its two top points 0.2 mm apart, `BOB_SLIT_TOP_GAP`; a 1.3 mm flat top read as a
  blunt 47° corner from below), and the back slit's lock end has its lower corner 1.2 mm in (`BOB_SLIT_END_FLARE`).
  The front slit's V closes on one vertex (V4 review): the face lock's slit-side top point, 0.2 mm past the side
  lock's flat face, is also the flat face's front corner on the top row. As two points the lock zone's top row ran
  back on itself by 0.2 mm there, so the joining strip's triangle over them and the ceiling's were flipped slivers
  (180° against their neighbours) that drew a double stroke from the bell's corner (a spur on the outline of the
  three review views); the flat face's corner moved 0.2 mm out, and the shell lost one vertex and two triangles per
  side.
  A strip of triangles joins the bell's last row to the lock zone's top row; under the bell's side, behind the side
  lock, a flat ceiling closes the shell.
- **Strand lines:** 2 per side on the back, group boundaries from the bell's top to the notches of the back locks at
  |x| 0.092 (z 1.415) and 0.030 (z 1.392) (`hair.BOB_STRANDS`, lock columns 15 and 18). With the curtain's front-face
  borders, the slits' walls and the lock ends they are the bob's designed lines (before: 2 + 2 + 4 V-grooves). The rims
  and walls take the neighbouring group whose lit side differs, then settle by a deterministic descent that weighs
  castplane's rays against folds inside a group (`hair._settle_rim_groups`, `RIM_FOLD_WEIGHT` 1.2): no rim fold over
  25° inside a group.
- **Lavender under-layer (H4, Decision 7; mandatory):** material `hair_inner` (`#e1d7ef`), never on the outer surface.
  - The **lining**: one short straight strip per side on the inner face of the curtain's long front lock, by the jaw
    (between lock columns 1 and 2, `hair.LINING_STATIONS`), from 2 mm above the lock's lower edge (`LINING_LOW`) up to
    `bob_under_depth` (4 mm), its visible face 1.5 mm off the inner face (`LINING_OFF`), its ends tapered to 12 %
    points (`LINING_END_TAPER`). It lies behind the front lock in the 3/4 and low views (M5 has no visible outline to
    measure; before the finishing pass it ran round the curtain's inside, azimuth 78-100°, and drew a 31-40° kink from
    below).
  - The **under-locks** (`under_lock_tips`): **one flat lock per side**, 2 mm thick (`hair.UNDER_LOCK_THICKNESS`),
    hanging from under the bob behind the jaw (the sheet's lavender spikes between the jaw and the braids, x
    0.022-0.036, z 1.387-1.398); its root edge is buried in the head's lower back at z 1.410 (`under_lock_root_z`);
    its lower edge is a **V** down to one point midway between the two `under_lock_tips`, its sides 6 mm above the
    point at the tips' x (`hair.UNDER_LOCK_NOTCH`), flaring to 8 mm (`under_lock_width`) at the root. (Review r3-T6:
    three teeth drew a W under the chin from knee height; the finishing pass: two blunt teeth still drew a zigzag.)
- **Three shells** (finishing pass, merge; Decision 32): after it is built the shell is cut along the **outer back
  strand line** on each side (`hair.BOB_SPLIT_STRAND`, lock column 15) into her left side (object `bob_l`: the curtain,
  the side lock and the back locks out to the strand), the back between the two cuts with the nape (`bob`) and her right
  side (`bob_r`). Each cut runs from the bell's top (inside the dome) down the strand line to the lock's notch and is
  closed by a cap, a strip between the outer and the inner surface in the rim faces' group, inside the hair. The shells
  share no vertex and no face: the back shell's own copies of the cut's outer and inner column are tucked
  `hair.BOB_CUT_TUCK` (0.107 mm on the final model) past the cut into the side shell and as far into the hair, so its
  cap lies inside the side shell and the side shell's cap inside it (with coinciding caps, the OBJ imported as one
  castplane mesh had 44 edges with three or more faces). castplane's hidden-line pass tests a sample only against the
  objects whose image rectangle contains it and that reach nearer than it, and the one-shell bob (1292 triangles) was
  tested by every line of the face, the head, the dome and the braids: the cut takes the web still frame's cost model
  from 23.7 to 19.3 M ray-triangle tests. The strand line draws as before (the side shell's cut edge; the back shell's
  is tucked inside the side shell); the scene camera's and the 3/4 views' object lines are pixel-identical. Added to the
  drawing: the cut's inner edge, a line on the bob's underside behind the side lock seen from below (`low_angle`,
  `head_low`; 14-31 mm of stroke on the 24 × 36 mm frame) and 2 mm of it under the bob in the front views, and a few
  strokes inside the head's ground shadow (cast per object). The inner strand (column 18) was tried first: its inner
  edge runs beside the neck and drew a stroke in the scene camera and the 3/4 views. Counts: 836 polygons / 1348
  triangles (456 / 436 / 456 per shell, the caps 56 triangles), rays 25 / 29 / 36 (≤ 64 each; the one shell had 58).
  Since the leaf pass (leaf-shaped lock ends, above): 984 polygons / 1544 triangles (506 / 532 / 506 per shell, the
  caps still 56 triangles: the one shell would have 956 / 1488), rays 25 / 28 / 37 (the one shell 57).

### C.4 Ear tufts (H5): the first thing people recognise

Two ear-shaped hair tufts ("horns", like rounded bear / hamster ears) on the upper-outer slope of the dome, one each
side of the crown. Object `tufts`, `objects[0]`.

| item | value |
| --- | --- |
| base centre | (±0.066, 0.012, 1.582), on the dome's slope (the dome surface is at z 1.5795 there, 2.5 mm under it); the base sinks 4 mm into the dome |
| base footprint | 0.030 along the slope (in the x-z plane, from the inner notch (±0.0566, 1.5930) to the outer junction (±0.0755, 1.5736), both on the dome silhouette) × 0.031 deep (y -0.0035 ... +0.0275) |
| tip | (±0.064, 0.006, 1.614): 3.2 cm above the base centre, **8 mm above the hair crown** (sheet front 7.4-8.0 mm, back 8.0-8.6 mm) |
| shape (front view) | a **rounded fin, no hook**: the point is its **top-inner corner**; the inner edge runs straight from the tip to the notch, leaning ~19° outward going up (sheet 15-18°); the outer contour is convex (`tuft_front_outline`): tip (0.064, 1.614) → (0.0738, 1.6085) → (0.0787, 1.6005) → widest (0.080, 1.5915) → (0.078, 1.581) → junction (0.0755, 1.5736), bulging 10 mm from the tip-junction chord (`tuft_outer_bulge`). The lobe axis (base centre → tip) is near vertical, ~4° inward; the outer top edge leaves the tip almost horizontally, so the point's own bisector aims ~20° inward. Do not make the point aim straight up or out |
| shape (side view) | a round lobe **3 cm deep** behind the top of the crown: the front edge vertical at y -0.001 up to 3.5 mm under the top, the round top at y 0.006, the convex back edge out to y 0.028 at z 1.593 and straight down to the base (sheet: 23 mm deep near the top, 28-30 mm over the lower half, 31-33 mm at the base). *(Review r5-L2: `tuft_side_outline` holds the plate's section ends, not the silhouette. `hair._tuft_section` puts the cup face 2t·n off the front end and the back face 2t·n off the back end (n_y ≈ -0.57), about 4 mm each, so the outline as drawn built a 36-37 mm deep, low hump. The rig's outline is therefore the drawn profile moved inward by that inset, less over the tapered top: (y, z) (0.003, 1.580), (0.003, 1.605), (0.0016, 1.609), (0.0012, 1.612), (0.006, 1.614), (0.013, 1.612), (0.0172, 1.6085), (0.0219, 1.6005), (0.024, 1.593), (0.024, 1.583). Built: the front edge at y -0.0015 ... -0.0021, the back at 0.029; 30.3 / 31.0 / 29.8 / 28.7 / 24.7 mm deep at z 1.585 / 1.590 / 1.595 / 1.600 / 1.605. The front view is unchanged.)* |
| shape (back view) | the same outline mirrored (an orthographic back view): the tip at its inner top, the outer side rounded |
| thickness | 7 mm at the rim, tapering together with the cup's sag to 15 % at the point (`hair.TUFT_TAPER`, `TUFT_TAPER_MIN`): a sharp point, 2.2 / 4.3 / 6.5 mm wide 1 / 2 / 3 mm under the tip (review r1-L4: the even 7 mm plate ended in a flat 14 mm roof). The section's ends are inset, so the straight inner edge and the convex outer contour are exactly the front view's outlines (nothing overhangs inward past the notch-tip line); the shell is one smooth group |
| cup | the concave (inner) face opens towards the front, turned 35° outward; 3.5 mm deep *(build: the tuft's section runs from the front view's inner edge to the side view's back outline, so the built cup faces about 51° outward; `tuft_cup_azimuth_deg` is read only by the mannequin's stand-in, `rig.MANNEQUIN_ONLY_FIELDS`)* |
| inner face | a lighter decal slab (material `tuft_inner`, `#ffdfd2`) on the cup's **outer half**, from cup station 0.5 to 0.9 (`hair.TUFT_FACE_U`): 0.63 mm proud along its inner border (0.62 mm on the final model, Decision 1; the rig value was 0.62 mm before review r5-L2 re-laid the cup) and sunk 0.315 mm under the cup along its outer border (`hair.TUFT_FACE_PROUD`), so its outer border draws no second contour; its inner border and top are their own smooth group, the one **inner-ear line** of the sheet, from near the tip to the base. From the front and 3/4 it shows on the outer half; from the side it shows across the middle of the lobe (the built cup faces about 51° outward); from the back not at all. *(`tuft_inner_inset` is not read: `rig.SPEC_ONLY_FIELDS`.)* |

`rig.tuft_frame(side)` gives (base, tip, cup normal).

### C.5 Braids (H6)

Two short, thin **three-strand braids** that come out from under the side hair behind the jaw and hang beside the
neck. Objects `braid_l` and `braid_r`.

- **Centreline** (`braid_path`, her left, mirrored): root (0.050, 0.005, 1.420) hidden inside the curtain → out under
  the side hair at (0.052, 0.008, 1.398) → (0.054, 0.015, 1.384) → (0.058, 0.022, 1.370) → **tie** (0.062, 0.028,
  1.356). It bows outward (13°) and slants back (25°; the sheet's lobe centres lean 23-27°); it comes out at y +0.008
  (sheet side view +0.009, -0.003 ... +0.0215) and the tie is at y +0.028 (sheet +0.022 ... +0.031).
  `rig.braid_point(side, u)` walks it.
- **Three-strand look:** 5 lobes along the path at u 0.12 / 0.31 / 0.50 / 0.69 / 0.88 (`hair.BRAID_LOBE_AT`; the top
  one tucked under the hair, 4 visible), each a slender pointed lobe 24 × 11 mm, 12 mm thick
  (`hair.BRAID_LOBE_HALF_LENGTH` 0.012, `hair.BRAID_LOBE_HALF_WIDTH` 0.0055, a superellipsoid with
  `hair.BRAID_LOBE_POINT` 1.6), leaning 40° alternately left and right (`braid_lobe_tilt_deg`) and pitched 22°
  (`hair.BRAID_LOBE_PITCH_DEG`: the upper end back, the lower end forward), so each lobe comes out from under the one
  above and the lobe edges draw a chevron down the braid (review r4-L1: four round 17 mm ellipsoid lobes at 35° buried
  each other's edges and read as a string of beads). `braid_width` (0.017) is now read only by the mannequin's
  stand-in tube (`rig.MANNEQUIN_ONLY_FIELDS`).
- **Tie:** a small ring, radius 4.5 mm (a 9 mm band, sheet ~14 px), 4 mm long, at the last path point (z 1.356, just
  beside the mock-neck rim).
- **End tuft:** 3 pointed sub-locks from the tie, 10 mm wide × 10 mm thick at the tie (round strands), kicking **outward and back**:
  tips (0.0919, 0.0448, 1.3530), (0.0849, 0.0518, 1.3398), (0.0790, 0.0382, 1.3407). Each lock is a 4-station path
  (`hair.BRAID_TUFT_STATIONS`) that sags 4 mm below its chord (`hair.BRAID_TUFT_CURL`, a parabola): a crescent brush
  whose ends curl up, the upper lock longest and level with the tie (review r2-L5: three straight spikes read as a
  claw; review r1-L9: the tips pulled 15 % towards the tie; 10 × 5 mm locks 23-33 mm long read as three needles;
  review r4-L2: 14 mm blades sagging 7 mm read as a claw; review r5-L1: 10 × 6 mm blades sagging 10 mm read as a claw
  from the front and back and, seen edge-on, as two V-shaped hooks in profile; now a crescent from the front and back
  and a soft brush sweeping back in profile).
- Clearances (self-consistency, merged model): ≥ 25 mm from the neck; the end tufts ≥ 13.0 mm from the straps,
  ≥ 19.1 mm from the top and ≥ 17.2 mm from the cardigan (review round 5: the 4 mm sag; round 4's 10 mm sag left
  8.4 / 14 / 12.8 mm).

---

## D. Body and outfit

### D.1 Neck (object `neck`, skin)

An elliptic cylinder: hw 0.022 (sheet 0.0221), y from -0.038 (sheet front -0.0375) to +0.018 (back: Decision 26), from
z 1.330 (inside the mock neck) to 1.400 (inside the head). About 2 cm of neck shows between the chin (1.388) and the
mock-neck rim (1.364).

### D.2 Mock-neck top (object `top`, material `top`, white)

- **Mock neck:** a high turtleneck tube (`mock_neck_rows`, ellipse): (1.364, hw 0.0290, -0.0475, 0.0285), (1.352,
  0.0293, -0.0480, 0.0290), (1.342, 0.0330, -0.0490, 0.0300) *(the last row is a guide, not sampled: below 1.352 the
  flare is `top_rows`', see Flare)*. It stands loose round the neck (4.5 mm at the sides, 7-8 mm front and back).
- **Lettuce-edge rim:** the top edge at z 1.364 is wavy: 20 scalloped waves round the rim (5-6 small humps across the
  front, each 9-10 mm wide, as drawn: a rounded hump between cusp troughs, 4 points per wave on the profile
  2|sin| − 1, `body.RIM_SAMPLES_PER_WAVE`; review r1-L13: 3 points drew V troughs with flat tops), ±1.5 mm in z at
  the centre front and back, × (0.75 + 0.25 cos² φ), so ±1.1 mm at her sides (`lettuce_side_amplitude`); turning out
  2 mm; the rim's top face is 1 mm wide (`lettuce_rim_width`), and the inner wall flares to it from 2.5 mm
  (`mock_neck_thickness`) at the dent's floor. The rim's top face is its own smooth group so the wavy line draws.
  *(Review round 4, r4-T1 / round 1's R1-08: with a 4.5 mm face, the views that see the rim edge-on drew its radial
  edges as 3-4 nested boxes at each side, and the steeper side waves doubled the tube's side outline. Now each side
  shows one short curl and the front one wavy line.)*
- **Torso:** `top_rows` (§A): the shoulders slope about 27° from the neck base to the shoulder point; the top is visible
  above the bodice's square neckline, beside the straps and on the shoulders inside the cardigan's edge; it ends at z
  1.190 inside the bodice.
- **White sleeves:** tubes along the arm axis, radius 0.0235 at the shoulder joint, 0.0225 at mid upper arm, ending at
  arm position 0.40 inside the cardigan sleeve (they show only on the shoulders between the strap and the cardigan's
  edge). They overlap the torso at the shoulder. *(Merge: they lie ≥ 7.9 mm inside the balloon and show in no preset
  or close-up view; each is in the object of its arm, `arm_l` / `arm_r`, see §G.)* *(Finishing pass: not built,
  `body.TOP_SLEEVE_TUBES` off, −60 triangles; no camera of an 864-camera scan saw them, and the white the shoulders
  show is the torso's. Each arm's ground shadow loses the tube's loop, 10 strokes inside the sleeve's own shadow. The
  mannequin keeps its tubes, so `top_sleeve_end` / `top_sleeve_radii` are mannequin only and `top_sleeve_start` spec
  only.)*
- **Fold** *(build)*: the mock neck's base, where it meets the shoulders, is a group boundary (the sheet draws this fold
  in its front, side and back views). It dips `top_fold_dip` 3.5 mm at the centre front and back (cos² of the azimuth,
  level at her sides), sliding down the top's surface: a soft U in the front view (sheet z 1.341 at the ends, 1.335 at
  the centre; review r1-L14: a level fold drew a ruler-straight line). The fold lies on the `top_rows` row at
  `top_fold_z` 1.342.
- **Flare** (review r2-L11): the mock neck flares smoothly into the shoulders, from the straight tube at 1.352 over rows
  1.349 / 1.346 to the fold at `top_fold_z` 1.342 (hw 0.0318 / 0.036 / 0.042, the sheet's OFF outline; it was a
  straight tube to 1.35 and then a flat 56° ledge, a lampshade). The flare rows dip with the fold in proportion and
  blend their section exponent from the mock neck's 2.0 to the torso's 2.4 (`body._flare_point`); the fold's kink is
  16° (was 26°). 1.342 hw 0.044 broke the far strap's crest line in head_three_quarter, so it is 0.042. Below the fold
  a 72° band runs to 1.336, mostly under the straps in the front view: flattening it means re-laying the straps (it
  broke strap lines in 8 views), so it is left.
- **Hidden back** *(finishing pass, build)*: the two `top_rows` rows below the shoulder-point row leave out their
  points at azimuths 108-234° (`top_back_cut`: round the back, under the cardigan's back panel and in the bodice); a
  22-triangle fan from the back shoulder-row point (`body.TOP_FILL_APEX`) closes the shell. Every fill face is unlit,
  like the faces it replaces, and the range stops one column short of her right back side, where the top's light
  silhouette runs down: the object lines and the ground shadow are unchanged (−32 triangles; an id z-buffer of 864
  cameras sees the new faces in 0 pixels). The mock neck's dent floor has one point per lettuce wave
  (`body.TOP_FLOOR_POINTS_PER_WAVE` 1, option F of the body agent, taken at the merge: −120 triangles, +20 polygons):
  the dent's inner wall shows beside the neck from about 10° above, so two short strokes inside the mock neck move by
  2-3 mm in the head close-ups; at the scene camera no pixel changes by more than 40 grey levels (2400 px). The top
  has 465 polygons / 724 triangles (was 442 / 876).

### D.3 Jumper bodice and straps (object `bodice`, material `dress`, navy)

- **Bodice** (`bodice_rows`, outer surface; front half exponent 2.2, back half 2.5):

| z | hw | yf | yb | note |
| --- | --- | --- | --- | --- |
| 1.2765 | 0.0935 | -0.1100 | 0.0530 | square neckline (front top edge between the straps) |
| 1.258 | 0.0940 | -0.1180 | 0.0520 | the top edge at the sides (armpit) |
| 1.225 | 0.0925 | -0.1245 | 0.0500 | bust; apex x ±0.045 |
| 1.185 | 0.0835 | -0.1215 | 0.0460 | |
| 1.147 | 0.0760 | -0.1145 | 0.0410 | |
| 1.116 | 0.0705 | -0.1090 | 0.0365 | the narrowest (sheet) |
| 1.108 | 0.0724 | -0.1103 | 0.0376 | high-waist seam: the lower edge, 1 mm over the skirt |

- **Top edge:** straight across at z 1.2765 between the straps (x ±0.0555, the square neckline); outside the straps
  it drops to z 1.258 at the sides (the armpit); at the back (hidden under the cardigan) z 1.250 *(guide)*. The top edge
  is a rim with its own group (the neckline line draws). The bodice's inner face lies 2 mm above the top. *(Build: the
  bodice is a solid; its top is a level ledge that runs in from the edge to `bodice_tuck` inside the top, not a slab
  2 mm over the top.)* *(Review round 1, r1-L15, open: the sheet's edge runs as one arch from the centre over the straps
  to under the arms (inventory XC-4), about 18 mm lower at the strap's outer edge; this section keeps it level between
  the straps and the strap ends level. An arch needs the neckline and the straps' front ends sloped together; it is
  left for a later round.)*
- **Straps:** 0.033 wide (x 0.0555-0.0885 at the front; sheet 0.0547-0.089), 2.5 mm thick, 1.2 mm above the top;
  centreline `strap_path` (x 0.072) from the bodice's top edge (y -0.085, z 1.2765) over the shoulder (top z 1.333, sheet
  1.334) down the back to z 1.250 under the cardigan. The strap is its own shell (its edges draw).
- **High-waist seam:** at z 1.108, just under the bust: the bodice's lower edge laps 1 mm over the skirt (the skirt's
  top edge at z 1.116 tucks 1.2 mm inside the bodice), so the seam draws as the bodice's lower rim.
- **Placket lines** (Decision 17): two lines at x ±0.0165 (`placket_x`; the sheet's ink lines 33 mm apart framing the
  button line) from the neckline (z 1.2765) down the bodice to the seam and on down the skirt to the hem (§D.4): group
  boundaries with a crease of ≥ 1° (so the coplanar merge keeps them).
- No shirring tucks and no plaid (Decision 17).
- **Hidden back** *(finishing pass, build)*: under the cardigan's back panel the bodice's ledge ring leaves out the
  section angles t 30-150°, the 1.225 row t 30-135° and the 1.185 row t 45-135° (`bodice_back_cut`; 90° = the back
  centre; the 1.225 row keeps her right back side's column, where the light silhouette turns down the back); fans close
  it, lit and unlit as the faces they replace, so the lines and the shadow are unchanged (−48 triangles). Each strap
  drops its last two stations at its back end under the cardigan (`body.STRAP_HIDDEN_BACK_STATIONS` 2, option B,
  taken at the merge: −24 triangles per strap); the object lines are unchanged, the strap's ground-shadow outline loses
  its end. The bodice object has 337 polygons / 660 triangles (was 350 / 756).

### D.4 Skirt (object `skirt`, material `dress`)

A long **A-line** skirt to **mid-calf**, softly fluted. One closed shell: the outer surface, a hem rim, an inner
facing 4 mm inside rising from the hem to a **ceiling** at z 0.720 (the legs start inside it; low views see the legs
and the ceiling, not a hole).

| z | hw | yf | yb |
| --- | --- | --- | --- |
| 1.116 | 0.0693 | -0.1078 | 0.0357 |
| 1.108 | 0.0714 | -0.1093 | 0.0366 |
| 1.100 | 0.0730 | -0.1110 | 0.0375 |
| 1.060 | 0.0820 | -0.1170 | 0.0410 |
| 1.012 | 0.0929 | -0.1230 | 0.0460 |
| 0.950 | 0.1064 | -0.1341 | 0.0523 |
| 0.889 | 0.1196 | -0.1439 | 0.0689 |
| 0.827 | 0.1325 | -0.1550 | 0.0836 |
| 0.766 | 0.1439 | -0.1642 | 0.1002 |
| 0.704 | 0.1565 | -0.1734 | 0.1168 |
| 0.643 | 0.1694 | -0.1839 | 0.1298 |
| 0.581 | 0.1827 | -0.1956 | 0.1451 |
| 0.520 | 0.1950 | -0.2060 | 0.1581 |
| 0.458 | 0.2057 | -0.2146 | 0.1710 |
| 0.434 | 0.2097 | -0.2183 | 0.1759 |
| 0.390 | 0.2125 | -0.2215 | 0.1790 |

- Rows are the sheet's front and side silhouettes (the cardigan-off and front views draw the same skirt); the back
  above z 0.97 is hidden on the sheet and extrapolated. Cross-section exponent 2.1. The skirt is deep in profile: its
  centre runs from y -0.041 at z 0.95 to -0.021 at the hem.
- **Flutes (Decision 10):** 8 soft flutes (godets), a crest at the centre front so the button line runs down a crest
  (the sheet: 6-8 soft lobes, about 3 valleys across the front, hem steps 7-25 mm). The crest-to-valley depth is 0
  above z 0.860 (they fade by the hip) and grows linearly to 20 mm at the hem, never more (`rig.flute_depth_at`,
  `rig.flute_offset`, `rig.skirt_point(z, φ)`). *(Build, review round 3 r3-T3: the outer surface's 192 quads are
  written as their two fan triangles, `body._Shell.mesh(triangles=...)`. On these twisted quads (0.2-9.7°)
  castplane's Newell facing and the fan triangles disagreed near the flank outline, and the flank line broke for
  9-13 mm in back and side 3/4 views and 5 mm at the front hip; +192 polygons, 0 triangles. Review round 4 (r4-L4):
  those triangles are fanned on the quad's ridge diagonal (`meshkit.fan_fold`). On the valley diagonal each strip of
  the convex hip and crests had a concave crease, so at a grazing angle its two triangles faced opposite ways and both
  long edges drew: a doubled flank stroke 1-2 mm apart (4 strips in the scene camera, 187 over 72 azimuths), now 0. As
  separate triangles a ridge cannot hide an edge; 0 polygons.)*
- **Hem:** level at **z 0.390** at the crests (Decision 9), 10 mm higher at the valleys (`rig.skirt_hem_at`), so the
  hem line waves and reads in the drawing. The hem rim is its own group; the 8 valleys draw as lines from the hem up to
  z 0.620 *(build: thin single-group ridge stripes lying in the valleys, `valley_stripe`: a group boundary cannot end
  in the middle of a smooth surface)*.
- **Placket lines** (§D.3): the two lines at x ±0.0165 continue from the seam down the centre-front crest to the hem
  (creases ≥ 1°, their own group boundaries).

### D.5 Dress buttons (object `buttons`, material `buttons`, gold)

17 small **teardrops, pointed end up**, on the centre front (Decision 11; `rig.button_positions()`): **three on the
bodice** at z 1.236, 1.190, 1.138 (`button_bodice_z`), a 6 cm gap across the high-waist seam, then **14 on the skirt**
evenly spaced 0.0495 apart from 1.076 to 0.432 (`button_skirt_z`, `button_skirt_count`; the bottom one 4.2 cm above
the hem). 0.0068 wide × 0.0123 tall (sheet 11 × 20 px), domed 2.5 mm on the bodice (`button_relief`) and 1.5 mm on
the skirt (`button_skirt_relief`): the skirt's front crest is the side views' outline, where 2.5 mm still drew 14
teeth and 3.5 mm big ones; the sheet shows none (review r1-L16) *(build: on the faceted centre
column of the bodice / skirt, the flat back `button_float` over it)*.
Buttons 3 and 4 (z 1.138, 1.076) lie under the cardigan's crossover and its hem band (kept: low views see them). Each
is one smooth group.

### D.6 Cardigan (object `cardigan`, material `cardigan`, rust brown)

A **cropped** knit cardigan worn **wide off the shoulders**, with a deep V and a crossover fastened by one button.

- **Body panels:** back and two fronts, 6 mm thick, on the inner reference surface `cardigan_rows` (exponent 2.4). The
  panels hang from the bust and the shoulder blades and do not follow the under-bust in.

| z | hw | yf | yb | note |
| --- | --- | --- | --- | --- |
| 1.322 | 0.0980 | -0.0680 | 0.0500 | |
| 1.300 | 0.1080 | -0.0930 | 0.0560 | |
| 1.258 | 0.1040 | -0.1240 | 0.0600 | |
| 1.225 | 0.1010 | -0.1285 | 0.0600 | 4 mm off the bust apex |
| 1.185 | 0.0990 | -0.1285 | 0.0580 | |
| 1.150 | 0.0980 | -0.1280 | 0.0560 | |
| 1.109 | 0.0980 | -0.1270 | 0.0550 | |
| 1.060 | 0.0980 | -0.1265 | 0.0540 | |
| 0.996 | 0.0990 | -0.1295 | 0.0540 | back hem level |

- **Neckline** (`cardigan_neckline`, her left half, on the reference surface): the back is a straight wide **boat
  line** at z 1.313 (centre) - 1.319, crossing the shoulders at their points (0.0905, 0.020, 1.321) and (0.099, -0.020,
  1.318), so the white shoulders and the straps show inside it; the front edge falls from the shoulder point to
  (0.097, -0.0696, 1.272) and then runs as a **deep V** through (0.080, 1.245), (0.060, 1.221), (0.041, 1.196),
  (0.022, 1.172) to the **crossing** at (0.007, -0.1279, 1.150) (sheet: V edges at x ±0.080 at z 1.245, ±0.042 at 1.196,
  crossing at x +0.007, z 1.150).
- **Crossover (Decision 18):** **her right front laps over her left** (the women's wrap). The over-lap's front edge
  (TRUE x, `overlap_edge`, y = its inner face) continues past the crossing to x +0.020 and down to its lower corner at
  (0.014, 1.072); the under-lap's edge (`underlap_edge`) runs on underneath to x -0.030. The over-lap lies 4.0 mm in
  front of the under-lap (`overlap_gap`; review r3-L3: at 2.5 mm the over-lap bands' undercut edge lay exactly on the
  under-lap's hem band top, which hid the over-lap hem band's lower border, and the edge line ended in mid-air). The
  over-lap's lift is applied on her right front only (azimuth > 270), so the back is symmetric (review r3-T2: the lift
  by x bulged her right back 5 mm beside the centre back and hid the back's outline at az 270). The hem band's end at
  the over-lap's corner runs up along the over-lap's front edge (mitred), so the two bands meet with no panel edge
  between them (review r3-L3: a 6 mm wedge of the panel's edge showed as a tab under the button).
- **Button:** one round gold button (material `buttons`), Ø 0.013, 3.5 mm proud, at **(x -0.001, z 1.109)** TRUE
  coordinates, on the over-lap's front band near its inner border (its front at y ≈ -0.1475; sheet side view -0.142).
- **Ribbed bands:** front bands 0.022 wide along both V edges and the over-lap's edge, a neck band of the same width
  round the back boat line, and a **hem band 0.032 tall**. They are separate shells 7.5 mm thick (1.5 mm proud of the
  panels), so their inner borders draw. No rib lines (Decision 12): the hem band is a plain band
  (`hem_band_ribs` 0) with stations about 1.9 cm apart along the hem (38, `cardigan.HEM_STATION_STEP`), so it
  follows the rounded front corners; its two borders draw. Each band's edge-face quads (the garment-edge face) twisted
  more than 1° (`cardigan.BAND_EDGE_SPLIT_DEG`) are split into their two fan triangles, so the garment-edge outline
  stays unbroken where that face turns edge-on (review r2-T5: castplane's Newell facing and the fan triangles of a
  twisted quad disagreed, and the outline broke 1-1.5 mm in the scene camera); +45 polygons, 0 triangles.
- **Hem:** the back is level at **z 0.996**; the fronts have **rounded front corners** (`cardigan_front_hem`, |x|, z):
  (0, 1.072), (0.040, 1.061), (0.081, 1.036), (0.094, 1.012), (0.099, 1.000). `rig.cardigan_hem_z(x, front)`.
- **Back:** plain, no seams (Decision 19).

### D.7 Balloon sleeves and long ribbed cuffs (objects `arm_l`, `arm_r`, material `cardigan`)

- **Dropped shoulder:** the sleeve is sewn on at an armhole seam round the shoulder point: centre (±0.104, -0.004,
  1.262), half-axes 0.058 (y) × 0.060 (z), its plane leaning out 12° at the bottom. The sleeve may overlap the panels at
  the armhole and under the arm (the two are sewn together); everything else must stay outside the dress.
- **Balloon** *(finishing pass, the user's review: "the hair and sleeves stay low-poly"; Decision 15)*: very full,
  hanging from the shoulder and widest low, at z 0.90, then rounding in over the cuff. Five elliptic rings along the arm
  axis (`sleeve_rings`: position 0 shoulder joint, 1 elbow, 2 wrist; lateral radius, depth radius, offset out and back,
  and how far the ring's plane is turned towards level), each perpendicular to the sleeve's centre line:

| position | lateral r | depth r | out | back | level |
| --- | --- | --- | --- | --- | --- |
| 0.000 | 0.0320 | 0.0340 | 0.0030 | 0.0000 | 0.00 |
| 0.600 | 0.0348 | 0.0389 | 0.0015 | 0.0120 | 0.00 |
| 1.250 | 0.0415 | 0.0518 | 0.0067 | 0.0200 | 0.00 |
| 1.680 | 0.0440 | 0.0581 | 0.0082 | 0.0180 | 0.30 |
| 1.970 | 0.0451 | 0.0505 | 0.0124 | 0.0080 | 0.40 |

  Fitted ring by ring to the sheet's balloon (front and back views, both sides averaged): outer half-width 0.130 at z
  1.20, 0.150 at 1.10, 0.174 at 1.00, widest 0.215 at 0.90, rounding in to 0.209 over the cuff; the inner side stays
  where it clears the skirt. Every ring is sampled at equal steps of its normal's angle (15 points, 24°,
  `cardigan.SLEEVE_POINTS`), so neighbouring facets meet at about 24° all round, the deep sides included. The last
  ring closes in a **rounded bottom** 30 mm deep (`sleeve_bag_depth`; `cardigan.SLEEVE_BAG_RINGS` 5 rings at equal
  normal steps, the pole inside the cuff) whose rings converge 30 % onto the cuff's axis (`sleeve_bag_converge`), so
  they hug the cuff all round. The bottom's rings below the second (`sleeve_gather_ring` 2) are a second smooth group:
  the boundary, 4-22 mm outside the cuff, draws the **gather** (the cuff's top) wherever it is seen (the bottom faces
  the camera down to the cuff, so without it no line drew the cuff's top). Quads of the body bands twisted by more than
  0.25° are written as their fan triangles (`cardigan.SLEEVE_SPLIT_DEG`: their Newell facing and one fan triangle
  disagreed edge-on, and a 72-azimuth scan found 3-4 cm outline gaps on the upper sleeve). Against the sheet and the
  smoothness criteria (Decision 31): half-width error ≤ 5.4 mm (S1), the cuff's ≤ 4.9 mm (S2), widest 8.7 mm from the
  sheet's height (S3); visible outline turns ≤ 24.1°, 95 % ≤ 18.8° (M6, M7), visible in-group dihedrals 95 % ≤ 24.7°,
  the largest 25.5° (M8, M9). The sleeve is 285 polygons / 450 triangles (was 141 / 278, a straight cone widest at the
  cuff's end). `sleeve_radii`, `sleeve_depth_ratio` and `balloon_offset` (`rig.sleeve_center`,
  `rig.sleeve_radii_at`) now shape only the mannequin's sleeve; `balloon_drop` is spec only. In profile the drape
  reaches y +0.09 (sheet +0.105, Decision 15).
- **Cap** (review r3-L1): a shoulder ring above the joint's ring (`sleeve_shoulder_ring` (0.001, 0.016, 0.031,
  0.033): its centre moved out / up from the first ring's centre, and its lateral / depth radii) closed by a dome
  `sleeve_cap_depth` 0.012 of 4 rings at equal normal steps (`cardigan.SLEEVE_CAP_RINGS`). One round dropped shoulder:
  front outline 0.118 / 0.122 / 0.123 at z 1.310 / 1.305 / 1.300 (sheet 0.115-0.121 / 0.117-0.123 / 0.118-0.126).
  *Known limit:* in close-ups from an elevated side-front angle (az 60, el 15) the cap rises 7-8 mm through the front
  band's outer lower border, and the cap's upper boundary against the band is not inked there (castplane draws no
  intersection lines).
- **Cuff:** a long ribbed **cone** from the gather to a wide mouth just short of the knuckles, **46 mm** along its axis
  (`cuff_length`; its outer side 58 mm, its inner side 35 mm, because the mouth is **level**, `cuff_mouth_level` 1, as
  the sheet draws it: its outer edge 0.209 → 0.221 from z 0.87 to 0.84, its inner edge 0.136 → 0.139). The gather lies
  7 mm below the wrist (`cuff_gather_offset` −0.007, `rig.cuff_start`) and the cuff's axis 6 mm outward of the
  forearm's (`cuff_offset`: the sheet's cuffs hang outside the wrist). It flares from radius 0.032 at the gather (dia
  64 mm, `cuff_radius`) to **0.0405 at the mouth** (dia 81 mm, `cuff_end_radius`; `rig.cuff_radius_at(s)`); 8 rib
  creases. The mouth turns straight into one recess cone 15 mm deep (`cuff_recess`; the palm passes through it): the
  old 4 mm rim, recess ring and flat cap are gone (−62 triangles per cuff; `cuff_opening_radius` is spec only). The
  cuff's quads are fanned on their valley diagonals (`meshkit.inscribed_fan`: the level mouth makes them non-planar).
  48 polygons / 64 triangles. **The palm comes out of its mouth, not through its side.** Sheet: the four drawn cuffs
  flare from dia 56-76 mm just below the sleeve bag to 73-86 mm at the mouth (front right 65 → 73, back right 65 → 76,
  front left 76 → 86, back left 76 → 85, perpendicular to the cuff axis) and run 54-65 mm from the gather to the mouth;
  the model takes about the mean of both sides. `rig.cuff_start(side)`, `rig.cuff_end(side)`.

### D.8 Hands (objects `arm_l`, `arm_r`, material `skin`)

Open and **relaxed** in the sheet's A-pose *(finishing pass, the user's review: "the stiff, splayed five-finger hands
... look like a mannequin")*: **palms forward** (turned 15° towards the body), the four fingers close together and
curled a little at both joints, the thumb beside the index (palm direction A, the lateral digit is the thumb; Decision
3: fingers, not a mitten; 105 polygons per hand: palm 10, fingers 95).

- **Palm axis:** wrist → `fingertip_pos` (±0.2091, -0.0100, 0.7843), 0.1127 long (`rig.hand_dir`, `rig.hand_length`),
  **26° out** from vertical (`hand_out_deg`, was 24.4°) and 10° off the forearm: the palm leaves through the middle of
  the cuff's mouth, which hangs outside the wrist (§D.7).
- **Palm:** 0.068 from the wrist to the knuckle line along the palm axis, **0.050 wide** (narrowing to 88 % at its
  end, `limbs.PALM_WIDTH_END`, so its corners stay inside the thumb's and the little finger's roots), 0.020 thick; it
  starts behind the cuff's recess (`limbs.PALM_STATIONS` (0.45, 0.92); the hidden ring inside the cuff and
  `palm_start` are gone, −16 triangles) and the back of the hand shows for about 14 mm below the mouth, as on the
  sheet.
- **Fingers** (`rig.fingers`: across the palm, along it, length, base thickness, fan angle in the palm plane, curl per
  joint): each a closed tube of 34 triangles, a straight tube to its first joint (half its length,
  `limbs.FINGER_SEGMENT`), a ring just past the second joint and a rounded tip (`limbs.FINGER_TIP_RING`); both joints
  curl by the row's curl towards the palm (the old layout, one straight step to a curled last ring, never showed the
  curl). The tube tapers to 80 % (`finger_taper`).

| finger | across | along | length | thickness | fan | curl per joint | straight tip (front view) |
| --- | --- | --- | --- | --- | --- | --- | --- |
| thumb | +0.014 | 0.80 | 0.046 | 0.0145 | +30° | 18° | 47° out, 101 mm from the wrist |
| index | +0.010 | 1.00 | 0.050 | 0.0125 | +15° | 16° | 37°, 119 mm |
| middle | 0 | 1.00 | 0.052 | 0.0125 | +10° | 18° | 30°, 120 mm |
| ring | -0.010 | 1.00 | 0.042 | 0.0118 | +2° | 22° | 22°, 110 mm |
| little | -0.016 | 0.90 | 0.032 | 0.0108 | -9° | 26° | 14°, 95 mm |

  (Before the finishing pass: fan 46 / 28 / 10 / −24 / −38°, curl 6-12°, the thumb 56 mm long at 0.95 along: the
  sheet's drawn digits, 51 / 40 / 28 / 12 / 6° out, splayed.) The curl grows towards the little finger, as a hanging
  hand curls; the thumb is shorter and thicker, rooted further back and curled forward, so it reads as a thumb. The
  middle tip is the lowest point, where the sheet draws the lowest fingertip (A4: 5.1 mm); the curl at the joints is
  16-26° (A2, 10-30°).
- **Checks** (cardigan / limbs agent): no finger vertex passes the cuff's wall (margin 1.5 mm); adjacent fingers touch
  at their sides (the deepest overlap 2.3 mm, the little finger at its first joint: fingers held together, not
  crossing); every tube's outer edge (|across| + 0.575 × thickness) stays ≥ 2 mm inside `palm_width` / 2, so no tube's
  flat start shows past the palm block's side.
- `rig.hand_frame(side)` gives (wrist, palm axis, palm normal, thumb direction); `rig.finger_base(side, name)` and
  `rig.fingertip(side, name)` place each finger (every digit is its base + length along its fanned direction, before
  the curl; the middle one's straight tip is (±0.2197, -0.0130, 0.7825)). The wrist sits inside the cuff.

### D.9 Legs, socks, shoes

- **Legs** (object `legs`, skin): from z 0.730 (inside the skirt ceiling) to the ankle. Axis hip joint (±0.068,
  -0.004, 0.860) → knee (±0.062, -0.003, 0.475) → ankle (±0.056, 0.000, 0.085). Circular radius by z (`leg_radii`):
  0.800: 0.058, 0.700: 0.053, 0.600: 0.048, 0.520: 0.043, 0.475: 0.0405, 0.420: 0.0405, 0.360: 0.040, 0.340: 0.039
  (calf, sheet), 0.290: 0.036, 0.250: 0.032, 0.200: 0.0285, 0.150: 0.0265, 0.110: 0.025, 0.085: 0.0245. About 13.5 cm
  of bare calf shows between the hem and the sock cuff; the calves are 4.2 cm apart.
- **Socks** (objects `sock_l` / `sock_r`, material `socks`, white): the leg + 1.5 mm from inside the shoe up to the
  **turned-down cuff** (z 0.202-0.255; sheet edges 0.253-0.256 and 0.201-0.205), whose outer radius is the leg + 6.2 mm
  (sheet r 0.0372): a separate fold shell 4 mm thick at the bottom, its inside sloping up to a sharp rim (the top draws
  as its outline), its bottom edge a drawn line. A **navy 5-point star** (material `star`, outer radius 6.8 mm, inner
  2.9 mm, 0.8 mm proud) on the outer side of each cuff at z 0.225, 65° from the front.
- **Shoes** (objects `shoe_l` / `shoe_r`, material `shoes`): brown **penny loafers** with a **block heel**.
  - Sole outline 0.188 long from the heel back (±0.055, 0.035, 0) straight forward: **the feet are parallel** (the
    sheet's apron centrelines are vertical; `shoe_toe_out_deg` 0; `rig.foot_dir`, `rig.heel_point`, `rig.toe_point`);
    0.073 wide at the ball (70 % of the length), 0.060 at the heel.
  - Forefoot sole **0.0135 thick** (sheet 13.5-15 mm), its own smooth group (the sole line draws); **block heel** 0.034
    tall, **0.050 long** from the back (sheet 48 mm at the ground, 54 mm at its top); the sole line rises from the
    forefoot to the heel.
  - Upper: the topline (opening rim) at z 0.098 at the heel back and 0.090 along the sides (the sock shows above it,
    and the inside of the heel counter shows above the lower side topline, as on the sheet's front view); the instep at
    z 0.080 at the strap; the moc toe **0.052 high** at the ball (sheet 0.051-0.055). The toe box is **blunt** (review
    r4-L5; r2-T6's domed toe had become a 2 cm sloping wedge, a doorstop in profile): in front of the ball its top edge
    slopes gently to `shoe_toe_tip_height` 0.045 at the tip and comes forward over the sole's toe
    (`limbs.SHOE_TOE_INSET` −0.04, quadratic), so its front rises almost vertically from the sole line to 0.045, as on
    the sheet's side view (a vertical front up to 0.043-0.045 under the apron's lip). The raised **apron seam** (piping
    1.2 mm) is a rounded moc-toe U of 11 stations (`limbs.APRON_STATIONS`; 4 made a flat trapezoid lid). It is laid on
    the upper as drawn (the valley fan diagonals), and its quads twisted more than 1° are split into their fan
    triangles (`limbs.APRON_SPLIT_DEG`; r4-L5: where it crosses from the vamp's steep sides onto the flat toe top, a
    29° twist dropped a piece of its inner border).
  - **Saddle strap** across the instep at 58 % of the length from the heel, 16 mm wide, **2.8 mm proud**
    (`shoe_strap_relief`, a visible leather band), with the **penny slot**, a 20 × 4 mm outline sunk 0.52 mm into the
    strap's top (0.51 mm on the final model, Decision 1; Decision 14).
  - Soles exactly on z = 0, no vertex below.

---

## E. Pose (relaxed A-pose of the sheet)

| item | value |
| --- | --- |
| head | straight, facing -Y, no tilt |
| shoulder joints | (±0.088, 0.000, 1.285) (the upper arm's outer edge at x 0.111, as on the sheet) |
| upper arm | 0.191 long, nearly vertical (abducted 3.6°), hanging a little behind the torso's mid-depth |
| elbow | (±0.100, 0.022, 1.095), at the high-waist seam (sheet ~1.10-1.12), bent 17° (A3, 10-25°) |
| forearm | 0.222 long, 15.9° out from vertical (sheet ~16°) |
| wrist | (±0.160, 0.002, 0.885): the sheet's (±0.159, 0.886) (finishing pass: was 0.170, 11 mm out for the sleeve-skirt clearance; the shoulder-to-wrist angle is now 0.1° over the sheet's 10.1°, A1) |
| hand | palm axis wrist → `fingertip_pos` (±0.2091, -0.010, 0.7843), 26° out, 10° off the forearm; the middle tip lowest (A4: within 5.1 mm of the sheet's lowest fingertip); palm forward, fingers together and curled 16-26° per joint (§D.8) |
| legs | straight, hip joints (±0.068, -0.004, 0.860), ankles (±0.056, 0.000, 0.085) |
| feet | heel backs at (±0.055, 0.035), the feet parallel (toes straight forward, as on the sheet), soles flat on z = 0 |
| sun | `SUN_TOWARDS = (-0.45, -0.55, 1.14)`: the viewer's upper left of the 3/4 front-left scene camera, 58° high; the ground shadow (about 1.0 m) recedes to her left-back inside the portrait frame |

The arms hang a little behind the torso's mid-depth (y 0 ... +0.022, Decision 16): the torso is narrower there, so the
upper arm fits beside it while the front view shows the arm overlapping the torso's side, as the sheet draws it. The
sleeves clear the skirt by 10.95 mm (A5, ≥ 8 mm; mesh distance of sleeve, cuff and hand to the skirt): the bag's shape
gives the clearance now, not a wrist moved out. The
pose is symmetric except the fringe, the hairline on her right, the cardigan crossover and its button, and the iris
colours.

---

## F. Lines plan

castplane always draws a **feature edge** (between different smooth groups, or a group-0 crease above
`smooth_angle_deg`) and draws **smooth edges** only on the silhouette. Give every smooth patch its own non-zero group,
make each designed line a group boundary, and never let a tessellation edge inside a patch become a feature.

| part | feature lines (group boundaries / creases) | smooth (silhouette only) |
| --- | --- | --- |
| head skin | none on the face (no jaw line, no nose line) | skull, face and nose in one group |
| neck | none | one group |
| eyes | sclera, iris, pupil and highlight outlines (each slab: top face one group, walls another) | slab tops |
| face_marks | the outline of every mark: lash bands with flicks, brows, mouth, blush strokes | — |
| dome H1 | none (silhouettes only; the parting reads from the forehead triangle and lock SL's inner edge: a groove line on one closed smooth shell would need a visible return line) | the whole dome |
| fringe H2 | none inside a lock; each lock is its own shell, so its edges draw as strand lines | each lock |
| bob H3 | the front face's borders (the face-window line at the inner edge and the curtain's outer edge); the slits' walls and the locks' ends and steps (rims settled to the fewest rays, no fold over 25° inside a group); 2 strand lines per side on the back (group boundaries; the cut between the three shells runs on the outer one, §C.3) | the bell and each strip between the strand lines (finishing pass: 13 contour columns per side, about 9° per column); the inner surface |
| under-layer H4 | none inside a shell: the two lining strips (on the inner face of the curtains' long front locks, 2 mm above their edge) and the two V-shaped under-lock plates draw only as silhouettes | one group per shell |
| tufts H5 | the inner-face decal's inner border and top (the inner-ear line, on the cup's outer half; its outer border sinks under the cup) | the whole tuft shell (one group) |
| braids H6 | none; every lobe, the tie and each tuft lock is its own shell (silhouettes give the three-strand look: the pitched lobes' edges draw a chevron, review r4-L1) | each shell |
| top | the lettuce rim's top face (the wavy line); the fold where the mock neck's flare meets the shoulders (`top_fold_z`) | mock neck and its flare, shoulders (the white sleeve tubes are off, §D.2) |
| bodice | the square neckline / top-edge rim; the lower edge (the high-waist seam); the two placket lines (x ±0.0165) | bodice |
| straps | none (separate shells: their edges draw) | strap |
| buttons | none (silhouette outlines) | each button |
| skirt | the hem rim (wavy); the 8 flute valleys as thin ridge stripes (single group) from the hem up to z 0.62; the two placket lines (x ±0.0165) from the seam to the hem | flute faces; the smooth yoke above 0.86 |
| cardigan | the panels' edges are covered by the bands; the bands' borders (separate shells; their twisted edge-face quads split into triangles, r2-T5); no rib creases (`hem_band_ribs` 0; Decision 12) | panels, bands |
| sleeves | the gather (finishing pass: the boundary between the balloon and its rounded bottom's lower rings, 4-22 mm outside the cuff), the cuff's lower rim, 8 cuff rib creases | balloon, its rounded bottom, cuff |
| hands | none (palm and fingers are separate shells) | each shell |
| legs | none | legs |
| socks | cuff fold (separate shell: its top and bottom draw); star outline (decal) | sock, cuff |
| shoes | sole / upper boundary, heel-block edges, topline rim, saddle strap band, penny-slot outline, apron piping | upper |

**Colour borders that need separate shells** (castplane cannot draw a colour border on one surface):

| border | how | object |
| --- | --- | --- |
| tuft inner face (pink on pink) | decal slab 0.63 mm proud | `tufts` |
| eye layers, lash bands, brows, mouth, blush strokes | decal slabs 0.6-1.6 mm proud | `eye_l` / `eye_r`, `face_marks_l` / `face_marks_r` |
| straps (navy on white) | strap shells 1.2 mm above the top | `bodice` |
| dress buttons, cardigan button (gold) | domed shells | `buttons` |
| cardigan bands (knit edge lines) | band shells 1.5 mm proud | `cardigan` |
| sock star (navy on white) | decal slab 0.8 mm proud | `sock_l`, `sock_r` |
| hair underside (lavender) | a lining strip per side inside the curtain's long front lock's lowest 4 mm and one V-shaped under-lock per side (mandatory) | `hair_under` |

The plaid of the dress is colour only and not modelled (Decision 17).

*(Build, review round 1: the top, the bodice and the skirt and the cardigan's panel, front band and hem band are fanned
on their valley diagonals (`charmodel.meshkit.inscribed_fan`), so no non-planar quad's diagonal folds out over the
outline (r1-T1 / r1-T2: outlines dropped out in 7 of 16 views); the straps use `fan_fold` (the outer face and rims on
the valley diagonal, the inner face on the ridge diagonal), so their two faces fold the same way and never cross. Review
round 3 (r3-T1): the balloon sleeves, palms, fingers, legs, socks, sock cuffs, shoe bodies and heels take their valley
fan diagonal too (`meshkit.inscribed_fan`; the shoe's strap and apron keep `fan_fold`): ridge diagonals hid pieces of
their own outline (gaps of 9-18 mm at az 130, 165, 195, 230). Review round 3 (r3-T3): the skirt's outer quads are also
split into their fan triangles (§D.4), so the facing and the occluders agree and the flank outline is unbroken from
every azimuth. A 72-azimuth outline scan (the shaded silhouette's boundary against the ink, 1200 px) went from 3320
missing pixels, 19 azimuths with a gap over 9 mm, to 266, the longest gap 26 px (4 mm, az 310). Review round 4
(r4-L4): the skirt's triangles take the ridge diagonal instead, the convex fold, so a strip seen at a grazing angle no
longer draws both of its long edges. Finishing pass: the balloon sleeves' twisted body-band quads are written as
triangles (§D.7), and the cuff, whose level mouth makes its quads non-planar, is fanned on its valley diagonals.)*

---

## G. Polygon budget and objects plan

**Budget:** ≤ **4 400 polygons** (≤ 8 300 triangles), the same as Miki (4 469 / 8 154), so the web still frame is no
slower (BRIEF §4; hard limits 6 000 / 10 000, scene ≤ 700 KiB). Spend polygons on the silhouettes (hair, face, skirt,
cardigan, sleeves), not on flat areas. *(Finishing pass: the user's review moved the detail budget to the bob and the
sleeves, and the merged model was over the old hard limits; `assemble.BUDGET` was provisionally 6 500 polygons /
10 500 triangles, pending the user's decision, on a fresh measurement of the web still frame (Decision 32). The 64
feature-silhouette vertices per object and the 700 KiB stay hard limits. Leaf pass: the user kept the raise on
2026-11-01; with the leaf-shaped lock ends `assemble.BUDGET` is **6 500 polygons / 10 600 triangles**, Decision 32.)*

**Objects plan** (the fixed order of `assemble.OBJECTS`; spatially compact, each ≤ 64 feature-silhouette vertices).
*(Merge: the plan below had 18 objects in region order; the built model has 27, outer layers first. castplane's
hidden-line pass tests a sample only against the objects whose image rectangle contains it and stops at the first
object that hides it, so the order and the split cut the web still frame from about 5 % slower than Miki's to about
10 % faster: the fringe, the lavender under-layer and each foot's shoe and sock are objects of their own, the white
sleeve tubes joined their arms and the cardigan's button the dress buttons. Review round 1's merge split the eyes, the
face marks and the braids by side (their left and right ground shadows do not overlap, so the drawing, the shadow
included, is pixel-identical) to win back the hidden-line time that round's finer meshes cost (cost model 21.2 → 20.1 M
ray-triangle tests, Miki 21.7 M). The finishing pass's merge cut the bob into three shells along its outer back strand
lines (§C.3): the smooth bob alone had taken the cost model from 21.0 to 24.6 M (23.7 M with the body's options B and
F); with the cut it is 19.3 M (Decision 32). The polygons are the built counts.)*

| # | object | holds | dominant material | polygons | triangles | feature-silhouette vertices |
| --- | --- | --- | --- | --- | --- | --- |
| 0 | `tufts` | the two ear tufts with their inner-face decals (152 vertices: the observer's sight rays show their perspective) | `hair` | 204 | 288 | 17 |
| 1 | `cardigan` | back + 2 fronts, front / neck bands, plain hem band | `cardigan` | 447 | 800 | 0 |
| 2 | `arm_l` | her left balloon sleeve with its rounded bottom, ribbed cuff (8 ribs), hand + 5 fingers | `cardigan` | 438 | 712 | 19 |
| 3 | `arm_r` | the same for her right | `cardigan` | 438 | 712 | 15 |
| 4 | `face_marks_l` | her left lash band with its flick, brow, 3 blush strokes, and the mouth | `lashes` | 75 | 138 | 0 |
| 5 | `face_marks_r` | her right lash band with its flick, brow, 3 blush strokes | `lashes` | 55 | 100 | 0 |
| 6 | `eye_l` | her left eye: sclera, blue iris, pupil, 1 highlight | `eye_white` | 114 | 208 | 0 |
| 7 | `eye_r` | her right eye: sclera, red iris, pupil, 1 highlight | `eye_white` | 114 | 208 | 0 |
| 8 | `fringe` | fringe H2 (swept lock SL, locks A-C, lock D as two plates) | `hair` | 153 | 300 | 0 |
| 9 | `neck` | neck | `skin` | 18 | 60 | 0 |
| 10 | `bob_l` | the bob H3's left side: her left curtain, side lock and back locks out to the outer back strand | `hair` | 323 | 498 | 22 |
| 11 | `bob_r` | the same for her right | `hair` | 323 | 498 | 34 |
| 12 | `bob` | the bob H3's back between the two outer back strands, down to the nape | `hair` | 328 | 532 | 28 |
| 13 | `hair` | dome H1 | `hair` | 490 | 734 | 0 |
| 14 | `head` | skin head with the nose bump | `skin` | 498 | 888 | 0 |
| 15 | `braid_l` | her left braid (5 pointed lobes, tie, 3-lock crescent end tuft) | `hair` | 161 | 254 | 0 |
| 16 | `braid_r` | her right braid | `hair` | 161 | 254 | 0 |
| 17 | `hair_under` | lavender under-layer H4 (2 lining strips + 2 V-shaped under-lock plates) | `hair_inner` | 40 | 80 | 0 |
| 18 | `top` | mock neck with the lettuce rim, its flare and base fold, shoulders / upper chest | `top` | 465 | 724 | 51 |
| 19 | `bodice` | bodice (neckline rim, seam edge, placket creases), 2 straps | `dress` | 337 | 660 | 37 |
| 20 | `buttons` | 17 teardrop buttons, the cardigan's round button | `buttons` | 144 | 216 | 0 |
| 21 | `skirt` | fluted skirt (8 flutes), placket lines, hem rim, inner facing, ceiling, 8 valley stripes | `dress` | 538 | 732 | 17 |
| 22 | `shoe_l` | her left loafer (sole, heel block, blunt-toed upper, strap with its slot, apron) | `shoes` | 141 | 266 | 14 |
| 23 | `shoe_r` | her right loafer | `shoes` | 141 | 266 | 14 |
| 24 | `sock_l` | her left sock, cuff fold, star | `socks` | 70 | 148 | 10 |
| 25 | `sock_r` | her right sock, cuff fold, star | `socks` | 70 | 148 | 10 |
| 26 | `legs` | the two legs | `skin` | 68 | 152 | 0 |
| | **total** | 115 parts, 123 shells | | **6 354** | **10 576** | |

The plan was 4 360 polygons; the merge spent 4 752 (head and hair +262, body +249, cardigan / limbs −119) and review
round 1 5 051 (head and hair +99: the tufts' tapered point, rounder irises, the bob's cheek row and tips; body +80:
the scalloped lettuce rim; cardigan / limbs +120: broader fingers with rounded tips, the hem band's 38 stations),
within the hard limits; review round 2 5 310 (head and hair +92: two more crown rings +55, the lash arc, the bob's
1.474 row, the braids' 4-station tuft locks, minus the under-lock plates −6; body +40: the mock neck's flare rows;
cardigan / limbs +127: the bands' split edge faces +45, the sleeve lip rings +40, the domed loafers +42); review round
3 5 480 (head and hair −62: the lining ends in front of the braid roots −58, two under-lock teeth instead of
three −4; body +192: the skirt's outer quads written as triangles, 0 triangles; cardigan / limbs +40: the sleeves'
shoulder ring and 3-ring cap), 9 776 triangles; review round 4 5 528 (head and hair +16: a fifth, slender pitched
braid lobe per side +48, one highlight per eye instead of two −32; body 0: the lettuce rim's narrow top face and the
skirt's ridge diagonals; cardigan / limbs +32: the apron's twisted quads written as triangles, 0 triangles), 9 816
triangles; review round 5 5 540 (head and hair +12: the tufts' compensated side outline, r5-L2, twists 12 more quads,
which are written as triangles, 0 triangles; the braid end tufts' round strands, r5-L1, 0), 9 816
triangles of the 10 000 (184 to spare). The web still frame stays at parity with Miki's because of the objects above.
**Finishing pass** (2026-10-31, the user's review; Decisions 31, 32): 6 216 polygons / 10 396 triangles. Head and hair
+462 polygons / +700 triangles (the bob's bell and lock zone +386 / +616, its three-shell cut +28 / +56, the dome's
seam band +74 / +84; the hidden back of the skull −10 / −24, the lining and the V under-locks −16 / −32); body −24
polygons / −308 triangles (the hidden backs of the top and the bodice +14 / −80, the white sleeve tubes off −34 / −60,
the straps' hidden back ends −24 / −48, the mock neck's dent floor +20 / −120); cardigan / limbs +238 / +188 (the
balloon sleeves +288 / +344, the cuffs' recess cone −34 / −124, the palms −16 / −32). Over the old limits of 6 000 /
10 000, so the limits were provisional (6 500 / 10 500, `assemble.BUDGET`) until the user decided (Decision 32).
**Leaf tips** (2026-11-01, the user's "keep the raised cap and the split, add leaf-shaped tips"; §C.3 "Leaf-shaped lock
ends"): **6 364 polygons / 10 592 triangles**, 5 538 vertices. The bob +148 polygons / +196 triangles (the side
shells `bob_l` / `bob_r` +41 / +50 each, the back shell `bob` +66 / +96); nothing else changed. The
budget is now 6 500 / 10 600 (Decision 32; 8 triangles to spare). **V4 pass** (2026-11-01, the user's "remove the
fold sliver and widen the M2 margin"; §C.3 "The back slit's end"): **6 354 polygons / 10 576 triangles**, 5 530
vertices. The side shells `bob_l` / `bob_r` −5 polygons / −8 triangles / −4 vertices each (column 13.66 on the
contour, the front slit's V closed on one vertex, the joining strip zipped by the shorter diagonal), the back shell
`bob` unchanged; nothing else changed. 24 triangles to spare.

If the budget is tight, cut in this order: shoes, socks, hands (fewer finger segments), braids' end tufts, cuff ribs.
Never cut the tufts, the face, the eyes, the fringe, the lavender under-layer, the bob's bell and locks (its smoothness
is the finishing pass's criterion M3 / M4), the sleeves' rings (M6-M9) or the cardigan's V. The body agent's option S
(the straps' inner face on two columns, −64 triangles) changes strap and top edge lines in 13 views and is not taken.

**Module → regions mapping** (builders are split by these files; `REGIONS` per module):

| module | regions | default object of each region |
| --- | --- | --- |
| `head.py` | `head`, `eyes`, `face_marks` | `head`; eyes none (`eye_l` / `eye_r`); face marks none (`face_marks_l`, with the mouth, / `face_marks_r`) |
| `hair.py` | `hair`, `tufts`, `braids` | `hair` (the fringe sets `obj="fringe"`, the bob's three shells `obj="bob_l"` / `"bob"` / `"bob_r"`, the under-layer `obj="hair_under"`), `tufts`, braids none (`braid_l` / `braid_r`) |
| `body.py` | `neck`, `top`, `dress`, `buttons` | `neck`, `top` (the white sleeve tubes, off since the finishing pass, set `obj="arm_l"` / `"arm_r"`), `bodice` (the skirt sets `obj="skirt"`), `buttons` |
| `cardigan.py` | `cardigan`, `sleeves` | `cardigan` (the button sets `obj="buttons"`); sleeves have none (each part sets `obj="arm_l"` / `"arm_r"`) |
| `limbs.py` | `hands`, `legs`, `socks`, `shoes` | hands none (`arm_l` / `arm_r`), `legs`, socks none (`sock_l` / `sock_r`), shoes none (`shoe_l` / `shoe_r`) |

Objects that receive parts from several modules: `arm_l` / `arm_r` (sleeve and cuff from `cardigan.py`, hand from
`limbs.py`; the white sleeve tube from `body.py` when `body.TOP_SLEEVE_TUBES` builds it) and `buttons` (the dress
buttons from `body.py`, the cardigan's button from `cardigan.py`).

---

## H. Colours (sRGB, for the MTL, the GLB and the shaded previews)

Sampled on the sheet (the palette swatches exactly; the rest as the dominant colour of the area).

| material | colour | source |
| --- | --- | --- |
| `hair` | `#f2b5a7` | swatch 1 (hair pink) |
| `hair_inner` | `#e1d7ef` | lavender under the side hair (front view jaw gaps) |
| `tuft_inner` | `#ffdfd2` | the tufts' inner faces |
| `skin` | `#fad8cd` | rosier than the finishing pass's `#fae3d8`, the warm mid-tone between the sheet's flat skin `#fff8f1` and its skin shadow `#f6cebf` (Decision 30): the hue 4.7° towards pink, more saturation, the same value (Decision 33) |
| `eye_white` | `#ffffff` | sclera and highlights |
| `iris_red` | `#d25754` | her right iris (middle tone) |
| `pupil_red` | `#9f2a29` | its dark top |
| `iris_blue` | `#6387a6` | her left iris (= swatch 6, steel blue) |
| `pupil_blue` | `#2a3944` | its dark top |
| `lashes` | `#3f2924` | upper lash bands |
| `face_marks` | `#8d5946` | brows `#9f6456`, mouth `#8d5946`, blush strokes |
| `top` | `#f2f2f2` | white mock-neck top |
| `dress` | `#184059` | swatch 5 (dress navy) |
| `buttons` | `#d99559` | swatch 3 (button gold), both button kinds |
| `cardigan` | `#a66b63` | swatch 2 (cardigan brown) |
| `socks` | `#f2f2f2` | socks |
| `star` | `#173449` | the sock star |
| `shoes` | `#91643c` | swatch 4 (loafer brown) |

Swatch 7 (`#ffc1b3`, light pink) is the lower iris of the red eye and the blush; it is not a material (Decisions 6, 24).
Display material (dominant, `display_color`) per object: `tufts`, `fringe`, `bob`, `hair`, `braid_l`, `braid_r` →
`hair`; `hair_under` → `hair_inner`; `head`, `neck`, `legs` → `skin`; `eye_l`, `eye_r` → `eye_white`; `face_marks_l`,
`face_marks_r` → `lashes`; `top` → `top`; `bodice`, `skirt` → `dress`; `buttons` → `buttons`; `cardigan`, `arm_l`,
`arm_r` → `cardigan`; `sock_l`, `sock_r` → `socks`; `shoe_l`, `shoe_r` → `shoes`.

---

## I. Likeness checklist (ranked)

Each item is verifiable on a render from the named view.

1. **Ear tufts** (front, 3/4, back, side): two rounded fins on the upper-outer slope of a flat, wide crown, bases at x
   ±0.066, tips at x ±0.064, z 1.614 (8 mm over the crown); each a lobe about 3 cm tall, its point the top-inner corner
   aiming nearly straight up (axis ~4° inward), the inner edge straight and leaning ~19° outward going up, the outer
   contour convex (bulging 1 cm), **no hook**, tapering to a sharp point (2-4 mm wide 1-2 mm under the tip); one
   inner-ear stroke (the lighter cupped inner face's inner border) on the outer half in front and 3/4; in profile a
   round ear 3 cm deep just behind the top of the crown; the back view the mirrored outline.
2. **Round mushroom bob, a bell** (front, back, 3/4, low angle): hw 0.120 at the eyes, widening to **0.1235 at the
   nose** (z 1.425-1.436), about 1 cm wider than the shoulders, then curving in to long layered locks (no flip); a
   smooth bell, no flat panels in the 3/4 and low views (finishing pass: 13 contour columns per side; visible in-group
   dihedrals ≤ 19.7°, 95 % ≤ 11.8°); the curtains cover the face's edge (one cheek line), their innermost tips curving
   in under the cheeks to x ±0.039; the outermost strand stands off the curtain with background seen through a slit in
   front and behind; the back curls in to the nape (1.374) with layered tapered locks of uneven length, each tip at its
   lock's inner end (not a regular saw: the lower edge within 5.2 mm of the sheet's on average); lavender locks under
   the jaw between the jaw and the braids. In profile the front edge sweeps back to 2.6 cm behind the eye's outer
   corner: 4.6-4.9 cm of cheek shows.
3. **Fringe swept to her left** (head close-up front, front): the parting on her right with a tall triangle of forehead
   and her right brow showing; a narrow swept lock along the hairline on her right to the lash's outer end, then four
   wide locks with a nearly level bottom at the upper lash (a blunt centre lock to z 1.4705, notches ≤ 1 cm deep), the
   last one resting on the lash band over her left eye; the locks lie close to the face (the far eye shows in 3/4).
4. **Heterochromia** (head close-up front, 3/4, shaded / 3D): her right eye red, her left eye blue.
5. **Big low eyes with a thick lash band** (head close-up front): eye centres at 35 % of the head height above the chin,
   3.95 cm wide and one eye width apart, **drooping outward** (tare-me: the lid line highest at the inner-middle and
   5.5 mm lower at the outer corner, ~10°); a dark band with an outer flick; the iris filling the opening from the lash
   band to the lower boundary; the pupil a dark cap hanging from the lash band with the big highlight in it (she looks
   forward, not up); the lash band's top a smooth arc; no lower lid line.
6. **Two short braids** (front, side, back): three-strand, from under the side hair behind the jaw (y +0.008) to a
   small tie (9 mm) at z 1.356 beside the mock neck, leaning 25° back, ending in a 3-lock crescent brush kicking outward
   and back, its locks sagging with the ends curling up, the upper lock longest; the lobes lean 40° alternately, their
   edges a chevron (not a string of beads).
7. **Lettuce-edge mock neck** (front, 3/4, head close-up): a white high neck with a wavy rim at z 1.364 (5-6 small humps
   across the front), 2 cm of neck between it and the chin; the mock neck flares smoothly into the shoulders (hw 0.032
   / 0.036 / 0.042 at z 1.349 / 1.346 / 1.342).
8. **Cardigan V and crossover** (front, 3/4): a deep V from the shoulder points to the crossing at z 1.150, her right
   front over her left, one round gold button on the centre line at z 1.109, the over-lap's edge curving down to the hem
   at 1.072.
9. **Cropped length with a ribbed hem band** (front, back, side): the cardigan ends at about the high-waist seam in
   front (1.072 at the centre, rounded corners down to 1.00) and at 0.996 at the back, with a plain 3.2 cm band whose
   borders draw (no ribs, Decision 12).
10. **Wide off-shoulder neckline** (front, back): the white shoulders and the straps show inside the cardigan's edge in
    front; a straight boat line at z 1.313-1.321 across the back with the straps and the mock neck above it; the band
    ends on one round dropped shoulder (the sleeve's cap), no notch: front outline 0.118 / 0.122 / 0.123 at z 1.310 /
    1.305 / 1.300 (sheet 0.115-0.121 / 0.117-0.123 / 0.118-0.126; review r3-L1).
11. **Balloon sleeves into long ribbed cuffs** (front, back, 3/4): very full, smooth sleeves widest low (outer x 0.215
    at z 0.90), the bag rounding in over the cuff's top (0.209), the gather drawn all round; ribbed cones 46 mm long
    (58 mm on the outer side: a level mouth) flaring from dia ≈ 64 to ≈ 81 mm (sweater paws), hanging 6 mm outside the
    wrist, that cover the wrists and palms; the back of the hand shows for about 1.4 cm below the mouth, then the
    digits part.
12. **Relaxed open hands** (front, 3/4): palms forward, the four fingers close together and curled 16-26° at each
    joint, the thumb beside the index, curled forward (finishing pass: the sheet's splayed fan, 51° / 40° / 28° / 12° /
    6° out, read as a mannequin's), broad digits with rounded tips, beside the skirt at about crotch height (the middle
    tip the lowest, at z 0.78); the arms within 0.1° of the sheet's shoulder-to-wrist angle, the elbow bent 17°.
13. **Jumper bodice** (front): square neckline at z 1.2765 with straps 3.3 cm wide, a fitted bodice narrowing to hw
    0.0705 just above the high-waist seam at 1.108.
14. **Teardrop gold buttons** (front, low angle): 17 drops, point up, down the centre front: three on the bodice (1.236
    to 1.138), a 6 cm gap across the seam, then 14 evenly spaced from 1.076 to 0.432; two placket lines 33 mm apart
    frame the button line from the neckline to the hem.
15. **Long A-line skirt to mid-calf** (front, side): straight sides from hw 0.0714 at the seam to 0.2125 at the hem (z
    0.390); deep in profile (y -0.2215 ... +0.179); 8 soft flutes fading out by the hip, a wavy hem line, valley lines
    rising from the hem.
16. **Slim calves in calf socks** (front, side): about 13.5 cm of bare calf (r 0.039) between the hem and the cuff, the
    legs 4.2 cm apart.
17. **Turned-down sock cuff with the navy star** (front, side): cuff 0.202-0.255, wider than the sock, a star on the
    outer side.
18. **Penny loafers with a block heel** (side, low angle): 18.8 cm long, a 3.4 cm block heel 5 cm long, a 13.5 mm
    forefoot sole, the saddle strap (2.8 mm proud) with the slot, the rounded moc-toe U seam on a blunt toe 5.2 cm high
    at the ball falling to 4.5 cm at its almost vertical front; the heel counter shows beside the ankle as on the
    sheet; the feet parallel.
19. **Proportions** (front, full figure): 7.4 heads (crown to chin 0.218 of 1.606 m; final 0.213 of 1.570 m); narrow
    sloping shoulders; the hair (the bob's bell) a little wider than the shoulders.
20. **Soft round face, small V chin** (front, 3/4, head low): the face widest under the eyes, narrowing fast to a small
    chin; a 3.3 cm closed smile 2.5 cm above the chin, drawn as one stroke; the nose only in profile; in profile 4.6 cm
    of cheek at the eye line in front of the bob's edge (sheet 7-8 cm, Decision 8).
21. **Clean drawing in the scene camera** (scene camera): silhouettes plus the §F lines only, no wireframe noise,
    `warnings: []`, the ground shadow inside the frame.

Known differences from the sheet, by Decision: the eyes sit about 2 cm further forward in profile than the sheet's
drawn eye (4), the fringe and the bob's front edge lie closer to the face than the sheet's profile (8), the side view
shows the arm (the sheet's side view omits it; 15), the hem is level (9), and the bodice's top
edge is level across the straps (the sheet's arch, §D.3).

---

## Self-consistency checks (verified on the numbers)

Evaluated on the rig's surface models by a check script (`check.py` in the spec agents' scratch work, not in the
repository; positive = clear, metres; "3D" distances are to a sampled skin: face, back of the head, the underside behind
the jaw and the neck). **The distances and clearances below are at the sheet scale**; on the final model (Decision 1)
each is 0.97749 times as large (2.25 % less), except the decal standoffs of the last bullet, which are measured on the
final model.

- **Hair outside the scalp:** the hair silhouette stands 16 mm over the crown, 20-28 mm over the back of the skull and
  26-52 mm over its sides (z 1.46-1.57). The crown is flat: the front silhouette drops 2.3 / 5.3 / 9.8 / 13.2 / 31.9 /
  39.9 mm below it at x 0.025 / 0.037 / 0.049 / 0.057 / 0.075 / 0.081 (sheet 2.5 / 5.5 / 9.2 / 12.8 / 32.0 / 39.2).
- **Bob:** its inner surface clears the skull by ≥ 11 mm at the sides and ≥ 3 mm at the back (min 3.0 mm at z 1.495);
  the back curl stays ≥ 8.5 mm off the nape (z 1.398) and 20 mm off the neck (z 1.385). The front edge's vertices clear
  the faceted skin by 0.94-2.15 mm at z 1.415-1.482 and 0.61-0.74 mm at z 1.490-1.495 (the closest bob vertex 0.58 mm
  from the skin at the temple corner, z 1.495); 0 skin vertices lie inside the curtain (the closest 0.80 mm from the
  bob; review round 2, with the hidden `cheek_bulge`); in head_front the skin's outline lies 0.45-1.99 mm behind the
  curtain's edge at every z from 1.415 to 1.495. The innermost front tip (±0.039, -0.070, 1.399) is 6.7 mm off the skin
  and 1.9 mm off the front edge at its height. In profile the eye's outer corner (y -0.0816) is 26 mm in front of the
  bob's front edge at z 1.452 (4.6-4.9 cm of cheek), so the eye and the cheek show. The lavender lining's visible face
  is 1.5 mm off the bob's inner face (0.51 mm at its tapered end) and ≥ 41 mm from the braids. *(Finishing pass, final
  model: the bob's vertices clear the skin by ≥ 0.99 mm, the mock neck and the cardigan by ≥ 18.6 mm; the lining
  stands 1.7 mm off the front lock's inner face, its front faces ≥ 0.63 mm from the bob's surface.)*
- **Lavender under-locks** (one V-shaped plate per side since the finishing pass): ≥ 8.8 mm off the neck, ≥ 14.2 mm
  off the braids' lobes and ≥ 33.3 mm off the bob's outer surface (final model, vertex to surface).
- **Fringe:** every lock tip's front surface is ≤ 12 mm from the skin (true distance, 4.5-12 mm); the far eye is ≥ 80 %
  visible at az ±35 el 15 and ≥ 85 % at the in-light camera; lock D's lower edge overlaps the top of her left lash band
  by 0.5 mm in the front view (no skin between, as on the sheet).
- **Ear tufts:** the base centre is 2.5 mm above the dome surface (1.5795; the base sinks 4 mm into it); the tip is
  8 mm above the crown and 32.6 mm from the base centre, the lobe axis 3.6° inward; the outer bulge is 10.4 mm from the
  tip-junction chord; the inner edge leans 19.4° outward going up; the notch and the outer junction lie on the dome's
  front silhouette (27 mm apart); the built side silhouette is 29-31 mm deep at z 1.585-1.600 (review r5-L2: the
  rig's `tuft_side_outline`, 21 mm, is that profile less the plate's inset; before, 35-37 mm). The built tuft's outer
  silhouette stays within
  0.63 mm of `tuft_front_outline` (maximum x 0.0800); its point is 2.2 / 4.3 / 6.5 / 10.7 mm wide 1 / 2 / 3 / 5 mm
  under the tip.
- **Braids:** ≥ 25 mm from the neck along the visible part (25.2 mm, review round 4's merged model; the finishing
  pass's bob keeps ≥ 14.6 mm between the braids and the bob and its under-locks, and the braid tufts stay ≥ 12.7 mm off
  the straps, the top, the cardigan and the neck); the lobes
  ≥ 20 mm from the straps and the top; the tie 28.5 mm outside the mock-neck rim; the end tufts ≥ 13.0 mm from the
  straps, ≥ 19.1 mm from the top and ≥ 17.2 mm from the cardigan (review round 5: round strands sagging 4 mm; review
  round 4's 10 mm sag left 8.4 / 14.1 / 12.8 mm; review round 2's crescent tufts' upper lock is longer and level with
  the tie); ≥ 28.4 mm from the sleeves' raised caps.
- **Neck and mock neck:** the mock neck's inner surface clears the neck by 4.5 mm at the sides, 7 mm in front, 8 mm at
  the back; its rim (with the waves) is 22.5 mm under the chin and 26.5 mm under the jaw at the neck front. The flare
  rows (review round 2) re-lay the straps by ≤ 0.3 mm: the straps' vertices stay ≥ 1.83 mm above the top.
- **Bodice over the top:** 1.5-2.9 mm radially (z 1.19-1.27); the top's sides at z 1.27 lie outside the strap region,
  where the bodice has no side panel. The bodice's lower edge laps 0.8-1.0 mm over the skirt (z 1.108-1.116).
- **Cardigan off the dress:** the panels' inner surface clears the top / bodice / skirt by 3.4-17 mm radially (min 3.4
  mm at z 1.0, the hem band over the skirt; 4 mm at the bust); the front hangs 4-17 mm in front of the dress (17 mm at
  the button level); the hidden buttons 3 and 4 (z 1.138, 1.076) have 11.3 and 8.6 mm under the crossover; the
  neckline points are 6-13 mm off the top and the straps lie 2-6 mm over the top.
- **Sleeves in the A-pose** (finishing pass, final model): the sleeve, the cuff and the hand stay ≥ 10.95 mm off the
  skirt and the buttons (vertex to surface, the cuff's lower outer corner; the skirt's vertices ≥ 12.2 mm off the
  sleeve), the A5 criterion's mesh distance 10.95 mm (≥ 8 mm); the balloon's rounded bottom ends 4-22 mm outside the
  cuff at the gather ring; the sleeves stay ≥ 30 mm off the braids and the bob. (The white sleeve tubes are off since
  the finishing pass, §D.2.)
- **Hand in the cuff** (finishing pass): the palm starts behind the cuff's recess cone and leaves through the middle
  of its mouth; no finger vertex passes the cuff's wall (margin 1.5 mm); the finger tubes start inside the palm block;
  the straight tips lie 47 / 37 / 30 / 22 / 14° out from vertical at 101 / 119 / 120 / 110 / 95 mm from the wrist
  (before the curl; §D.8).
- **Legs inside the skirt:** ≥ 21 mm to the skirt's inner surface (at the ceiling, x; the flute valleys counted), ≥ 52
  mm front / back; the legs start 10 mm inside the ceiling; the inner thighs are 24 mm apart at the ceiling and the
  calves 42 mm; the hem is 13.5 cm above the sock cuff.
- **Ground:** heel and toe points at z = 0 on both feet; the ankle centre 51 mm above the heel block; the ankle lies over
  the shoe axis (1.0 mm off); the shoe's heel (0.060 wide) holds the sock (r 0.028 at the topline) with 2 mm walls.
- **Face:** eye wrap 20 mm; the lid line falls 5.5 mm from its highest point to the outer corner; the lash band covers
  the sclera's top everywhere (its lower edge 0-0.5 mm over the lid line) and its top is z 1.4762 at the middle; the
  iris top 2.7 mm above the lid line (inside the band, 2.2 mm under its top), its bottom clipped 1.8 mm by the lower
  boundary; brow 21 mm over the band's top; nose 7.5 mm proud; mouth to chin 24.7 mm; 7.37 heads; eye centre at 0.35 of
  the head height. The pupil's top (z 1.474) is 2.2 mm under the lash band's top; the band rises 0.5 mm over it,
  moved column by column (0 back-face pixels in the eye close-ups; review round 2).
- **Decals on the final model (rule 5; the 152 cm scale).** Minimum standoff of each layer over the surface it sits on
  (the skin, or the front faces of the layers under it), measured on the rounded final meshes from the decal's exposed
  front-face vertices and edge midpoints: along +y (the metric of `head.py`'s clearance pass) for the face decals,
  the nearest distance for the rest; in mm, sheet-scale model → final model: sclera 0.641 → 0.628 (y); iris 0.500 →
  0.506 and pupil 0.500 → 0.505 (y; `decal_layer_step`); lash bands 0.497 → 0.506 (y); highlights 0.369 → 0.381 (y,
  where a highlight's border passes over the pupil's chord facets); brows 0.739 → 0.726 (y); mouth 0.718 → 0.704 (y);
  blush strokes 0.473 → 0.478; tuft inner faces 0.472 → 0.481 (the faceted cup); lavender lining 0.530 → 0.515; dress
  buttons 0.593 → 0.580; cardigan button 1.35 → 1.32; sock stars 0.794 → 0.774; shoe straps 0.927 → 0.918; penny slot
  depth 0.443 → 0.448 (from the strap top's facet); and the silhouette floats under 0.5 mm by design: valley stripes
  0.290 → 0.295, the cardigan's front band 0.299 → 0.309, the apron piping 0.350 → 0.359. Without the raised fields
  (scale only) the iris, pupil and lash bands fell to 0.485-0.490 mm. **Review round 4** (final model): the skirt's
  ridge-fanned triangles (r4-L4) bulge between the valley columns, so the valley stripes fell to 0.288 and their float
  `valley_stripe[2]` went 0.31 → 0.32 mm: 0.299; the blunt toe (r4-L5) re-lays the strap and the apron: shoe straps
  0.694 (the toe faces now run back under the strap's inner lower corner), the apron piping 0.385, and the penny slot
  is still sunk `penny_slot_depth` (0.508 mm) under its step's corners, but the re-laid step is twisted, so the
  facet measure reads 0.413-0.507 (its outline draws as before in the close-ups); one highlight per eye (r4-L3), the
  remaining one unchanged at 0.381. **Review round 5** (final model): the ear tufts' compensated side outline (r5-L2)
  re-lays the faceted cup, which would leave the inner faces 0.474 mm proud, so `tuft_inner_relief` went 0.62 →
  0.63 mm: tuft inner faces 0.483; every other row unchanged. **Finishing pass** (final model): every row unchanged
  except the lavender lining, rebuilt on the curtain's long front lock: at 1.5 mm off the inner face its front faces
  came within 0.445 mm of the lock's curled lower edge, so `hair.LINING_OFF` went 1.5 → 1.7 mm: 0.632.

---

## Decisions (not shown on the sheet, or chosen)

1. **Height: 1.52 m barefoot**, from the user (2026-10-21: "Her height is 152cm"; sole of the foot to the skull top).
   It replaces the first choice (no source then: skin height 1.555 m, a typical Japanese high-school girl), which stays
   as the **sheet scale**: `rig.py`, §A-§E and the builders keep the lengths measured on the sheet at 0.615 mm/px (skin
   height 1.555, skull top 1.590 in the loafers, hair crown 1.606, which sets the scale, tuft tips 1.614), and the
   assembled model is scaled uniformly about the origin by `rig.figure_scale = rig.stated_height / rig.skin_height =
   1.52 / 1.555 = 0.97749` (`assemble.CHARACTER.scale`, the optional scale of `charmodel.assembly.Character`, applied to
   every part, the mannequin's too, before the rounding). The soles stay on z = 0. The scene camera's position and target
   (`export.SHEET_CAMERA`) and the preview framing are scaled by the same factor, so the scene camera's drawing is the
   same picture as before the scale (rasterised at 1200 / 2400 / 4800 px: no ink pixel farther than 1 px from the other
   drawing) and every preset frames her as before. Rescaling keeps every count (then 115 parts, 5 540 polygons, 9 816
   triangles; after the leaf pass 6 364 polygons, 10 592 triangles; since the V4 pass 115 parts, 6 354 polygons,
   10 576 triangles in 27 objects) and the
   feature-silhouette vertices of every object. **Final key heights:** skull top in
   her loafers **1.554**, hair crown **1.570**, ear-tuft tips **1.578** (the highest point), eye centres 1.426, chin
   1.357, head height 0.1975, high-waist seam 1.083, skirt hem 0.381 (flute crests), heel lift 0.034. Measured head
   count: **7.37 heads** (crown height / crown-to-chin, a ratio the scale keeps); 7.70 skin heads.
   **Rule 5 on the final model:** the scale makes every relief 2.25 % thinner, so the standoff fields at or under 0.5 mm
   were raised: `decal_layer_step` and `penny_slot_depth` 0.5 → 0.52 mm (0.508 mm final); the floors and floats that are
   under 0.5 mm by design (borders that draw as silhouettes) were divided by the scale, so they keep their verified
   values on the final model: `decal_skin_clearance`, `head.RELIEF_TAPER_END` and `shoe_decal_float` 0.4 → 0.41 mm,
   `band_float` and the valley stripes' float (`valley_stripe[2]`) 0.3 → 0.31 mm (0.32 since review round 4); and
   `tuft_inner_relief` 0.6 → 0.62 (0.63 since review round 5, r5-L2's re-laid cup) and `blush_relief` 0.7 → 0.72 mm,
   whose faceted standoffs were under 0.5 mm. Every
   decal layer stands at least 0.5 mm proud on the final model, or, where it stood less on the sheet-scale model (the
   silhouette floats, the highlights over the pupil's facets, the faceted cup and cheek), at least as proud as there
   (the self-consistency checks list the measured minimums; the penny slot's facet measure is the exception since
   review round 4, see there).
2. **Heel:** the sheet's block heel is 3.4 cm (57 px) and lifts her heel 3.5 cm (the brief guessed 2.5 cm); the sheet
   wins.
3. **Hands:** five separate fingers (the open hand is on every full figure of the sheet), not a mitten; 105 polygons
   and no construction rays per hand (single-group shells). Palm direction A (palms forward, the lateral digit is the
   thumb). The back of the hand shows for about 1.4 cm below the cuff's mouth, and the digits are broad with rounded
   tips (§D.7, §D.8; review r1-L6: thin digits from one point read as a rake). **Relaxed, not splayed** (finishing
   pass, the user's review: the stiff, splayed five-finger hands read as a mannequin's): the sheet draws the digits
   fanned 51 / 40 / 28 / 12 / 6° out; the model keeps the four fingers close together (fanned 15 / 10 / 2 / −9° about
   the hand axis) and curls each joint 16-26°, more towards the little finger, with the thumb beside the index, curled
   forward; the palm axis is 26° out and 10° off the forearm, so the palm leaves through the middle of the cuff's mouth
   (the cuff hangs 6 mm outside the wrist).
4. **Flat face:** front exponent 3.6 and a face 4 mm wider than the sheet's visible skin at the eyes (the hair covers the
   sheet's face edge), with the eye opening 0.0195-0.059 (the sheet's lash line reaches 0.067; the lash flick reaches
   0.066). The eyes wrap 2 cm; in profile they sit about 2 cm further forward than the sheet's drawn eye.
5. **Nose:** a bump 7.5 mm proud (the sheet's profile ~10 mm), no nose mark in the front view (the sheet's tiny dot is
   shading).
6. **Blush:** the three hatch strokes per cheek are modelled as decals; the blush colour ovals are not (an outline
   would draw). The strokes lean the same way on both cheeks, as drawn.
7. **Hair underside (mandatory):** lavender `#e1d7ef` (`hair_inner`): a short straight lining strip with pointed ends
   on the inner face of each curtain's long front lock, over its lowest 4 mm, by the jaw, and one flat under-lock per
   side, its lower edge a V down to one point, hanging from under the bob behind the jaw, where the sheet draws
   lavender spikes between the jaw and the braids (the 3D render shows them on both sides of the neck); never on the
   outer surface. A model without lavender misses a design feature. (Review round 2: 8 mm of lining and three
   separate wedges per side drew a bar and 3-4 parallel lines under the bob in low views. Review round 3: the lining
   round the back drew a strap across the neck from below, and three teeth a W under the chin from knee height. The
   finishing pass: the lining round the curtain's inside drew a 31-40° kink from below, and two blunt teeth still drew
   a zigzag; the strip now lies behind the front lock in the 3/4 and low views.)
8. **Hair depth:** the fringe lies 3-5 mm off the skin (4 mm thick) and the bob's front edge runs 2.6 cm behind the
   eye's outer corner (4.6-4.9 cm of cheek in profile, sheet 7-8 cm) and forward to the A-line tips beside the jaw
   (y -0.070): the sheet's profile draws the fringe 2-3 cm and the front tips 2 cm further forward (a 2D convention that
   would float hair in front of the face in 3/4 views). A hidden bulge of the head's side under the curtain
   (`cheek_bulge`, 2.6-3.2 mm) keeps one cheek line in the front views: the skin's outline lies behind the curtain and
   only the curtain's edge draws, as on the sheet's curtains (review r1-L2 / r1-L3: a fringe 18-27 mm off the face hid
   the far eye, and an edge 3-7 mm outside the skin drew the cheek twice; review r2-L3: an edge 1.2 cm behind the eye
   left only 3.2 cm of cheek in profile).
9. **Level hem at z 0.390** (flute crests): the sheet's curved hem is its look-down convention (front sides 0.375, side
   view front / back 0.41, the front centre 0.343 drawn low); the 17th button's position (4.3 cm above the drawn hem)
   agrees.
10. **Flutes:** 8 soft flutes (the sheet shows 6-8 soft lobes, hem steps 7-25 mm), 20 mm deep at the hem (never
    more), from z 0.86 (they fade by the hip); the hem 10 mm higher at the valleys; the valleys draw as lines up to z
    0.62.
11. **Buttons:** 17 teardrops as the sheet places them: three on the bodice (z 1.236, 1.190, 1.138), a 6 cm gap across
    the high-waist seam, then 14 evenly spaced 0.0495 from 1.076 to 0.432; the two under the crossover are kept.
12. **Ribs:** no rib creases on the cardigan's bands, 8 on each cuff. 16 creases 4 cm apart cut the 32 mm hem band into
    boxes that read as a segmented belt with a buckle at the centre front (review r1-L7), and the sheet's ~32 cost
    about 110 ms of the web still frame; the sheet's short rib strokes on the front and neck bands are cut too (lines
    and rays).
13. **Hidden body:** natural waist 1.000, hip 0.860, crotch 0.775 (anime-long legs); the legs start at 0.730 inside the
    skirt ceiling at 0.720; the body rows are a guide only.
14. **Shoes:** penny loafers 0.188 long (sheet 0.185: small anime feet, kept), the feet parallel (the sheet's front
    view: the apron centrelines are vertical), a 13.5 mm forefoot sole, a blunt moc toe 5.2 cm high at the ball
    falling to 4.5 cm at its almost vertical front (review r4-L5: the domed toe falling to 4.2 cm read as a wedge in
    profile), with a rounded moc-toe U apron, a 5 cm block heel, a saddle strap 2.8 mm proud, the penny slot as an
    outline sunk in the strap (no shell of its own). The sole's top and bottom lines stay 13.5 mm apart (as on the
    sheet) and the heel counter shows above the lower side topline (as on the sheet's front view); a rounding ring
    between the sole line and the toe top was tried and dropped (+72 triangles for a barely visible change).
15. **Balloon sleeves** deeper than wide and hanging back (the sheet's side view shows a big drape to y +0.105 and no
    forearm or hand; the model's profile shows the arm).
16. **Arms** hang a little behind the torso's mid-depth (y 0 ... +0.022) so the upper arm fits beside the narrow torso
    while overlapping its side in the front view. Until the finishing pass the wrist was 11 mm further out than the
    sheet's for the sleeve-skirt clearance (a wrist at x 0.165 left 4.8 mm with the old straight-coned sleeve); the
    finishing pass puts it at the sheet's x 0.160 (the shoulder-to-wrist angle 0.1° over the sheet's 10.1°, the elbow
    bent 17°): the balloon's bag, widest at z 0.90 and rounding in onto the cuff, keeps the inner side where it clears
    the skirt, 10.95 mm (A5, ≥ 8 mm), and the arm no longer reads as held out in a rigging pose (the user's review).
17. **No plaid, no shirring:** the dress is plain navy (the plaid is colour only); the bodice's vertical tucks are not
    modelled. The **two placket lines** the sheet draws 33 mm apart from the neckline to the hem, framing the button
    line, are modelled as creases (x ±0.0165; they cost almost no construction rays on the lit front).
18. **Crossover:** her **right** front laps over her left (the sheet and the full-figure image; the brief said her left),
    the button on the centre line at x -0.001 (the brief said -0.03), on the over-lap's band.
19. **Cardigan back:** plain, no seams; the back neckline is a straight boat line at z 1.313-1.321 (just under the neck
    base, through the shoulder points); the hem level at 0.996 with a 3.2 cm band.
20. **The side view is her left profile** (the blue eye; she faces the viewer's left), not her right as the brief said.
21. **Not modelled:** the cardigan-off and hair-down variants, the newsboy cap and glasses, the clover pendant, the fangs
    (other images; the sheet's face has a closed smile).
22. **No ears:** the bob hides them in every view.
23. **Fringe asymmetry:** swept to her left from a parting on her right (a swept lock along the hairline on her right,
    then four wide locks with a nearly level bottom); her right forehead and brow show; her left brow is modelled under
    the fringe.
24. **Eyes:** two tones per iris (iris + its dark top as the pupil); the sheet's lighter lower iris is not modelled (it
    would draw a line across the iris); one highlight per eye, the same on both (review r4-L3: a second, 2 mm one
    printed as a black dot at the scene camera's scale).
25. **Sock star:** a 5-point navy star at 65° from the front on the outer side of each cuff, z 0.225 (the front and side
    views place it between 49° and 90°).
26. **Neck back:** y +0.018 (hidden by the hair on the sheet).
27. **Symmetry:** the sheet's eyes and tuft tips differ by 1-3 mm left to right; the model is symmetric except the
    fringe, the hairline on her right, the crossover and the iris colours.
28. **Mock-neck rim:** 20 scalloped lettuce waves of ±1.5 mm (±1.1 mm at her sides; 5-6 small rounded humps between
    cusp troughs across the front, as drawn), on a 1 mm wide top face (review r4-T1).
29. **Open after review round 4** (minor, recorded so later rounds do not rediscover them): the cardigan's back boat
    band reads as a rectangular shelf behind the shoulder in side and 3/4-back views (r2-T4: filling the balloon's back
    pokes it through the panel's back at the shoulder blades, and a boxier panel back folds the faceted panel; a fix
    needs more panel columns at the back corners); the far ear tuft is seen edge-on as a post from the scene and
    in-light cameras (r2-L9: bowing its section widens the front view's straight inner edge, the defining feature); the
    fringe locks' roots step out of the dome in shaded views (r2-L8: needs an extra station and per-lock root heights);
    no chin line in low views (r2-T7: castplane draws no inter-object line, and a keel group draws a lens); the
    far-temple double stroke and the dashed jaw outline in head_three_quarter (r2-T3) and the shaded bite at the
    curtain's top-front corner (r2-L10). Added in review round 3: the cardigan's front hem corners drop steeply and
    read as a hook in 3/4 and low views (r3-L2: the proposed higher corners put the side view's lower edge 1.3-2 cm
    above the sheet's behind the corner, so the hem was not changed); the sleeve cap's boundary under the front band's
    outer edge is not inked in elevated side-front close-ups (§D.7, castplane draws no intersection lines); from below,
    the bob's own back edges still draw single lines behind the neck, and from knee height the two lavender teeth float
    under the chin because the jaw's underside draws no line (r2-T7). Added in review round 4: from the front the bob's
    side tips read as a row of straight isosceles teeth (r4-L6: pulling each tip 5 mm inward still reads as teeth;
    curved locks need a mid-station per tip, which costs polygons and bob rays, 57 of 64, and the budget went to the
    braids: 184 triangles are left). **Resolved in the finishing pass:** the side tips (r4-L6) and the helmet look:
    the bob is a smooth bell with the sheet's layered locks and slits (§C.3; criteria H2-H6, M1, M3, M4 pass).
    **Still open after the finishing pass** (Decision 31): seen obliquely, each layered lock end with straight edges
    projected to corners of 20-58°, so 95 % of the bob's outline turns were 45° against 15° (M2; **resolved in the leaf
    pass**, §C.3 "Leaf-shaped lock ends": 13.8°; 11.8° after the V4 pass); the dome's
    crown keeps its facets (M10 / M11, P2: `hair.DOME_SMOOTH` passes both for +358 triangles); the sleeve's inner edge
    beside the skirt in the back view is 23.5 mm off on her right (S4, P2: the sheet draws the two sides 22 mm apart,
    Decision 27); the front hair IoU is 0.795 against 0.80 (H11, P2: the sheet's fringe and strand interior).
30. **Skin colour `#fae3d8`** (the user's review, 2026-10-31): the sheet paints skin as a flat near-white `#fff8f1` with
    warm cel shadows `#f6cebf` (face, calves; `#fbc6b1` under the fringe). Used as a 3D albedo the flat near-white
    shades to a neutral grey (RGB 143, 139, 136 on the lit side of the face), which reads like the grey mannequin.
    The material is the warm mid-tone between the two sheet tones, close to Miki's `#fbe3d6`. Amended by Decision 33
    (2026-11-01): the colour is now `#fad8cd`.
31. **Pass criteria and the overlay check** (the finishing pass, 2026-10-31; the user's review borrowed both from
    mesh-avatar-studio). Every finishing check closes with a number and a limit. The **overlay check**
    (`python3 tools/make_reiya_model.py --overlay SHEET.png DIR`, with `--out-dir` to keep `examples/` untouched; the
    character-free code is `tools/charmodel/overlay.py`, Reiya's data `tools/reiya_model/overlay.py`, its test
    `tests/test_charmodel_overlay.py`) renders the front, the left profile (よこ) and the back orthographically into
    the design sheet's pixel grid (the appendix mapping; the model divided by `rig.figure_scale`, so 1 sheet pixel is
    0.601 mm on her), lays each over the sheet at 50 % and reports, in mm on the final model: the silhouette per row
    (and the half-width error, which cancels the sheet's left-right asymmetry, Decision 27), per-class IoU, class
    outlines (the bob, the tufts, the sleeve balloon, the cuff, the skirt), lower edges per column (the bob's locks, the
    fringe, the nape), about 90 landmarks, the smoothness of the bob, the dome, the lining and the sleeves (the largest
    and the 95th-percentile dihedral inside one smooth group, and the turns of the outline in the 3/4 views at ±35° and
    `low_angle`; since the correction of 2026-10-31 only what the whole model shows counts: faces visible from one of
    16 review cameras, outline edges where the part is front-most), the skin's warmth in the shaded head close-up, the
    arm angles, the finger curl and the sleeves' clearance from the skirt. DIR must lie outside the repository (the
    images contain the sheet); the command exits 1 while a criterion fails. The 41 criteria (`overlay.CRITERIA`; P1 must
    pass, P2 should): H1-H14 the hair against the sheet, S1-S4 the sleeves, K1 the skirt's flare, F1-F5 the figure, the
    legs, the shoes and the shoulders, A1-A5 the pose, the fingers and the clearance, C1 the skin, M1-M11 the
    smoothness. No overlay limit is under 3 mm (1.5 ink widths) except the fringe's, which sat at 0-2.6 mm. Exempt by
    Decision, reported only: 8 (the hair's depth in profile), 9 (the level hem), 4 (the eye wrap), 15 (the profile's
    sleeve drape) and the cardigan-off view. **Rule:** at most three fix rounds against the criteria; after the third,
    stop and report every criterion that still fails, with its value; never loosen a limit to pass. **Result of the
    finishing pass** (baseline 19 of 41): 35 pass, M5 has nothing to measure (the lining has no visible outline in the
    three views: it lies behind the front lock), 5 fail: M2 45.1° (≤ 15°, P1: the lock ends' corners seen obliquely,
    Decision 29), H11 0.795 (≥ 0.80, P2), S4 23.5 mm (≤ 8 mm, P2), M10 32.5° (≤ 30°, P2) and M11 33.6° (≤ 25°, P2).
    **Result of the leaf pass** (2026-11-01, §C.3 "Leaf-shaped lock ends"): **36 of 41 pass**, M5 n/a, 4 fail, all P2:
    H11 0.796 (≥ 0.80), S4 23.5 mm (≤ 8 mm), M10 32.5° (≤ 30°) and M11 33.6° (≤ 25°). M2 passes at 13.75° (95 % of
    the turns ≤ 13.8 / 13.7 / 13.3° in the two 3/4 views and the low view; the largest 14.8°); every P1 passes.
    **Result of the V4 pass** (2026-11-01, §C.3 "The back slit's end", Decision 33): 36 of 41 pass, M5 n/a, the same
    4 fail, all P2: H11 0.796, S4 23.47 mm, M10 32.49° and M11 33.60°. M2 passes at 11.83° (95 % of the turns ≤ 11.3
    / 11.8 / 11.8°; the largest 13.7 / 13.7 / 13.4°), M3 at 19.72° (23.56° before), M4 at 11.84° (11.93°), H3 at
    4.86 mm (4.88 mm) and C1 at 27 (21, the rosier skin); no fold vertex is left in the lock zone in the three views
    (the bell rim's two per view remain).
32. **Budget: 6 500 polygons / 10 600 triangles** (`assemble.BUDGET`; decided by the user on 2026-11-01, "keep the
    raised cap and the split, add leaf-shaped tips"; provisionally 6 500 / 10 500 from the finishing pass 2026-10-31
    until then). The user: the detail budget should move to the bob and the sleeves, and Reiya's web still frame
    measured slightly faster than Miki's "supports a small raise of the cap later, but only after a fresh measurement".
    The merged finishing pass had 6 216 polygons / 10 396 triangles (§G), over the old 6 000 / 10 000; the limits were
    the smallest round numbers that fit. **Decided:** the user kept the raise and the bob's three-shell cut and asked
    for leaf-shaped lock ends (criterion M2). Those add +148 polygons / +196 triangles (the inserted lock columns, the
    side lock's front arc and back point; §C.3, §G), so the model has 6 364 / 10 592 and the triangle limit went up to
    the smallest multiple of 100 that fits, 10 600 (8 to spare); the polygons stay 6 500. The scene file is 256 KiB.
    The V4 pass (§C.3 "The back slit's end") took −10 polygons / −16 triangles from the side shells: 6 354 / 10 576,
    24 to spare, and a scene file of 255.7 KiB. After it, four alternating rounds on an idle container (2026-11-01,
    Miki first in each round, medians of the per-round medians) gave the still frame 2783 ms against Miki's 3060 ms
    (9.0 % faster, faster in 4 of 4 rounds), the drag frame 101 ms against 71 ms (the 120 ms limit holds on the
    median; the slowest round 108 ms) and stage A 267 ms against 197 ms. The container is noisy: Miki's unchanged file
    moved +6 % (still frame) and +17 % (stage A) against the leaf pass's rounds, and three more alternating rounds of
    the file before the V4 pass against the new one gave a drag frame of 94.6 against 96.9 ms and a still frame of
    2779 against 2807 ms (medians; one round of the new file 124 ms), no difference beyond the noise. The figures
    below are the finishing pass's. The 64 feature-silhouette vertices per object and the scene's 700 KiB stay
    hard limits (the file is 255.7 KiB now). **Measured** (this container, `node tools/web_frame_bench.mjs SCENE 5`, the scenes
    alternating, 6 rounds per session, medians of the per-run medians): first session, Miki 3532 ms (3145-3828), the
    model before the pass 3386 ms (3050-3678), the merged model before the merger's changes 4091 ms (3614-4397; +16.5 %
    against Miki per round, slower in 6 of 6), the same with the body's options B and F 3753 ms (+8.9 %); second
    session, Miki 3396 ms (3283-3554), before the pass 3172 ms (3054-3383), the merged model before the changes 3590 ms
    (3501-3861; +6.7 %), **the final model 2937 ms (2736-3168; −14.0 % against Miki per round, faster in 6 of 6)**; a
    third session with the final bytes (the lining 0.2 mm further off its lock, nothing else changed) against Miki: 2778
    ms (2472-3064) against 2938 ms (2777-3268), −7.7 % per round, faster in 5 of 6. Drag frame medians of the sessions:
    Miki 78-91 ms, before the pass 99-121 ms, merged 104-114 ms, final 106 / 114 ms (84-138 ms per run; the limit 120
    ms); in one process with a warm JIT (40 interleaved frames each): Miki 42, before the pass 55, merged 56, final 60
    ms. The deterministic cost model of the still frame's hidden-line pass (ray-triangle tests in the scene camera,
    objects in their order): Miki 21.65 M, before the pass 20.98 M, merged 24.60 M (the bob alone, 1292 triangles in one
    object, was tested by every line of the face, the head, the dome and the braids: 6.34 M against it), with the
    options B and F 23.69 M, **final 19.26 M** after the bob's three-shell cut (§C.3). Not taken: the dome step
    `hair.DOME_SMOOTH` (+161 polygons / +358 triangles; M10 / M11 would pass), which needs a larger raise.
33. **Skin colour `#fad8cd`** (the user's request, 2026-11-01: "skin still looks a bit dull, please give her a natural
    rosy glow"; it amends Decision 30 by reference). Decision 30's `#fae3d8` (HSV 19.4° / 13.6 % / 98 %) is dull for
    its saturation and for what the lights make of it, not for its hue: the reference's lit skin is a warm near-white
    (the sheet's flat `#fff8f1`, hue 30°) and only the artist's blush is pink (hue 11-13°). `#fad8cd` (HSV 14.7° /
    18 % / 98 %) moves the hue 4.7° towards pink with more saturation and the same value. It was chosen against four
    other candidates, `#fad0c6`, `#f7c6bc`, `#f5ccbf` and `#fed6cb`, in the shaded close-up, a three.js PBR viewer
    (the GLB, NeutralToneMapping) and the web UI: it is the largest warm step that keeps the face apart from the
    salmon hair (`#f2b5a7`, hue 11°; Lab ΔE between skin and hair where they touch in the GLB view, forehead / fringe
    and cheek / side lock, 11.9 / 9.5, the other candidates 5.8-9.7 / 6.4-7.7, pink on pink) and keeps the lit side's
    lightness (L* 75.9 on the lit cheek in the web UI, the others 71.3-75.6; 78.4 before). The lit cheek's R − B in
    the web UI goes from 29 to 39, criterion C1 from 21 to 27 (its limit, 15, unchanged). No blush decal and no vertex
    colour (Decision 6: a blush oval would draw an outline). Only the `display_color` of `head`, `neck` and `legs`, the
    MTL's `skin` Kd and the GLB's `skin` baseColorFactor change (metallic 0 and roughness 0.85 as before); the OBJ's
    geometry and the line drawing do not depend on the colour. The web UI's shaded side stays dull with any colour (it
    gets the ambient light only, about 0.57 of the colour); more would need the lights or a blush, both out of scope.
    Miki's `#fbe3d6` is unchanged.

---

## Appendix: measurements on the design sheet

**Scale and mappings.** One scale for all views, **s = 0.000615 m/px**, chosen so that the hair crown (rows 131 front,
135 side, 136 back; mean 133) is z 1.606 with the ground at **row 2745** (the side view's sole). The background is a
neutral grey 249 with grid lines of 214 every 70 px (4.3 cm). Pixel → world:

| view | x / y | z |
| --- | --- | --- |
| front (正面) | X = (px - 1940) s | Z = (2745 - py) s |
| cardigan off | X = (px - 1044) s | same |
| back (後ろ) | X = -(px - 2839) s (image right = her right) | same |
| side (よこ, her left profile) | Y = (px - 3655) s (image left = her front) | same |

Method: a flood fill of the background gave the silhouettes; a nearest-colour classification (hair, skin, white, navy,
cardigan, gold, shoe, outline) gave the per-row extents of each part; every landmark was confirmed on a zoomed crop.
The views are near-orthographic, but the lower body is drawn as if seen from slightly above (the hem and the shoes
curve; Decision 9). The cardigan-off and front figures share the same skirt drawing.

| item | view | pixels | metres | note |
| --- | --- | --- | --- | --- |
| ear-tuft tip | front / back | y 119 / 123, x 1837 / 2043 (back 2736.5 / 2942.5, the same) | z 1.6150 / 1.6125, x -0.0633 / +0.0633 | 8 mm over each view's crown; the side view's top y 111 (z 1.620, 14 mm over its crown) is drawing noise |
| ear-tuft base | front | outer 1810 / 2070, inner 1855 / 2028, y ~180 | x -0.0799..-0.0523 / +0.0541..+0.0799, z 1.5775 | base width ~0.028 |
| ear-tuft depth | side | x 3652-3692 at y 132; centre 3672; back edge 3699-3700 at y 150-177 | y -0.0018..+0.0228 at y 132; 28-30 mm deep lower down, 31-33 mm at the base | light inner face on the front edge (cupped forward) |
| hair crown | front/side/back | y 131 / 135 / 136 | z 1.6076 / 1.6051 / 1.6045 | mean row 133 -> z 1.6064 (the scale is set here) |
| hair at the eyes | front | y 366: x 1746-2133 | z 1.4631, hw 0.1190 | the bob keeps widening below: hw 0.123 at y 400-420 (z 1.43) is the bell's widest, not tip flare (the tips are at y 454-462) |
| hair front / back | side | y 316-340: x 3439 / 3826 | y -0.1328 / +0.1052 | fringe front / back of the bob; depth 0.238 |
| bob side tips | front | y 454-462 (x 1747, 2132) | z 1.4040..1.4090 | outer layered tips |
| bob back hem | back | centre y 505, sides y 456-464 | z 1.3776 (nape) / 1.4053 (sides) | inverted bell; braids emerge at x ±0.051, y 479 |
| bob front tips | side | y 448-472, x 3456-3499 | z 1.3979..1.4127, y -0.1224..-0.0959 | A-line bob: the front locks reach the jaw front |
| centre lock (B) tip | front | x 1945, y 355 | x +0.0031, z 1.4698 | between the eyes (the blunt bottom of lock B) |
| fringe tips (her left) | front | y 345-350 | z 1.4729..1.4760 | at the upper lash line |
| parting (apex of the bare forehead) | front | x 1895, y 193 | x -0.0277, z 1.5695 | on her right |
| brow (her right) | front | (1852, 302) -> (1895, 312) | x -0.0541..-0.0277, z 1.5024..1.4963 | inner end lower; the left brow is under the fringe |
| upper lash line | front | y 345-356; x 1833-1903 / 1977-2050 | z 1.4692..1.4760; x -0.0658..-0.0228 / +0.0228..+0.0677 | |
| iris (red, her right) | front | x 1853-1895, y 352-394 | cx -0.0406, z 1.4459..1.4717 | width 0.0258 |
| iris (blue, her left) | front | x 1987-2028, y 351-393 | cx +0.0415, z 1.4465..1.4723 | |
| eye centre | front | y 372 | z 1.4594 | |
| eye (iris) in profile | side | x 3523-3544, y 355-395 | y -0.0812..-0.0683 | her left eye |
| nose | front / side | dot y 405-409 / tip (3468, 412-415) | z 1.4379 / 1.4336, y -0.1150 | |
| mouth | front / side | x 1913-1968, y 440-448 / (3487, 440) | x -0.0166..+0.0172, z 1.4127..1.4176; y -0.1033 | closed smile |
| blush | front | 3 hatch strokes under each eye, y ~405-415 | z 1.4329..1.4391 | |
| chin | front / side | y 490 / 484 (x 3522) | z 1.3868 / 1.3905, y -0.0818 | |
| jaw underside -> neck | side | y 484-488: x 3522 -> 3592 | y -0.0818 -> -0.0387 | |
| face skin hw | front | y 354 / 396 / 420 / 450 / 468 / 480 | 1.4705:0.0664 / 1.4446:0.0600 / 1.4299:0.0523 / 1.4114:0.0474 / 1.4004:0.0314 / 1.3930:0.0160 | inside the curtains |
| face profile | side | x at y 316 / 372 / 414 / 440 / 470 / 480 | 1.4938:-0.1138 / 1.4594:-0.1021 / 1.4336:-0.1150 / 1.4176:-0.1033 / 1.3991:-0.0873 / 1.3930:-0.0818 | forehead / bridge / nose / mouth / chin front / chin |
| neck | front / side | x 1904-1976 (y 494-518) / front x 3594 | hw 0.0221; y -0.0375 | |
| braid start | front / side | (1855, 470) (2025, 470) / (3653, 497) | x -0.0523 / +0.0523, z 1.3991; y -0.0012 | under the side hair, behind the jaw |
| braid tie | front / side | (1838, 540) / (3690, 553) | x -0.0627, z 1.3561; y +0.0215 | 3 lobes visible above it |
| braid tuft end | front / side | (1785, 547), (1802, 570) / (3740, 577) | x -0.0953..-0.0849, z 1.3376..1.3518; y +0.0523 | kicks outward and back |
| mock-neck rim | front / OFF / side | y 527-531 / 524 / 528 (x 3577-3701 at 540) | z 1.3616..1.3659; hw 0.0280; y -0.0480..+0.0283 | lettuce edge ~6 waves across the front |
| mock neck -> shoulders | OFF | flare y 556-572 (hw 58 -> 102 px) | z 1.3364..1.3462, hw 0.0357->0.0627 | |
| shoulder slope | OFF | hw at y 580/592/604/616/628/640 | 1.3315:0.0683 / 1.3241:0.0855 / 1.3167:0.0972 / 1.3093:0.1046 / 1.3020:0.1089 / 1.2946:0.1113 | outer white shoulder / upper arm |
| shoulder point | OFF / side | hw 181 px at y 640-700; side 3542-3745 at y 640 | hw 0.1113; y -0.0695..+0.0553 | |
| straps | OFF | x 900-955 / 1133-1189, from y 576 | x -0.0547..-0.0886 / +0.0547..+0.0892, top z 1.3339 | width 0.0332 |
| square neckline | OFF | y 668-673 (between the straps) | z 1.2743..1.2774 | |
| bodice top at the side | OFF | y 700 (x 894 / 1195) | z 1.2577, hw 0.0929 | armpit level |
| bodice hw | OFF | y 720 / 760 / 820 / 880 / 930 | 1.2454:0.0925 / 1.2208:0.0913 / 1.1839:0.0824 / 1.1470:0.0756 / 1.1162:0.0705 | the arms cover the sides above y 930 |
| bust front | side | navy front x 3458 / 3452 at y 760 / 800 | y -0.1212 / -0.1248 | |
| high-waist seam | OFF | line y 940-945; narrowest navy hw 0.0705 at y 930 | z 1.1070..1.1101 | |
| dress buttons | OFF | 17 drops, cy 734 ... 2117, 11 x 20 px | z 1.2368 ... 0.3862; 0.0068 x 0.0123 | pointed end up; spacing 75-104 px; the two at y 892 / 994 are under the cardigan |
| skirt hw | front | y 1100/1200/.../2040 | 1.0117:0.0929 / 0.9502:0.1064 / 0.8887:0.1196 / 0.8272:0.1325 / 0.7657:0.1439 / 0.7042:0.1565 / 0.6427:0.1694 / 0.5812:0.1827 / 0.5197:0.1950 / 0.4582:0.2057 / 0.4336:0.2097 | OFF and front identical |
| skirt front / back | side | y 1100..2040 | 1.0117:-0.1230 / 0.9502:-0.1341,+0.0523 / 0.8887:-0.1439,+0.0689 / 0.8272:-0.1550,+0.0836 / 0.7657:-0.1642,+0.1002 / 0.7042:-0.1734,+0.1168 / 0.6427:-0.1839,+0.1298 / 0.5812:-0.1956,+0.1451 / 0.5197:-0.2060,+0.1581 / 0.4582:-0.2146,+0.1710 / 0.4336:-0.2183,+0.1759 | back hidden above y 1160 |
| skirt hem | front / side | front sides y 2132-2140, centre lowest 2187; side extremes 2068 / 2085, near side 2196 | z 0.3721..0.3770; 0.3432; 0.4059 / 0.4164; 0.3376 | the curve is the sheet's look-down convention (Decision 9) |
| cardigan back neckline | back | top edge y 607-610 (x 2839), 599 (x 2720), 594 (x 2680) | z 1.3130 / 1.3198 / 1.3229 | ribbed band to y 645 (1.2915) |
| cardigan front V | front | inner edges y 720: 1810 / 2070; y 800: 1871 / 2007; cross y ~875 x 1951 | 1.2454: -0.0799 / +0.0799; 1.1962: -0.0424 / +0.0412; cross z 1.1501, x +0.0068 | |
| cardigan top at the shoulder | front | y 595-600 at x 1762-1790 / 2085-2131 | z 1.3204, x -0.0922..-0.1095 / +0.0892..+0.1175 | |
| cardigan button | front / side | (1938, 942), 22 x 18 px / x 3424 | x -0.0012, z 1.1088; y -0.1421 | on her right front, which laps over |
| over-lap edge | front | band end x 1973 at y 900-980 | x +0.020, z 1.10-1.15 | |
| cardigan front hem | front | centre y 1002; x 1876 y 1020; x 1808 y 1060; x 1787 y 1100 | 1.0719 / -0.0394:1.0609 / -0.0812:1.0363 / -0.0941:1.0117 | rounded front corners |
| cardigan back hem band | back | y 1072-1125 (x 2839) | z 0.9963..1.0289 | |
| cardigan front | side | x 3417 at y 860-880 (bulge), 3424 at 930 | y -0.1464 / -0.1421 | |
| cardigan back drape | side | x 3760 (y 720) -> 3825 (y 1180) | y +0.0646 -> +0.1046 | the side view shows no forearm / hand |
| sleeve outer / inner | back | her left y 1140: 2532-2678; y 1280: 2482-2645 | 0.9871: +0.0990..+0.1888; 0.9010: +0.1193..+0.2196 | |
| sleeve widest | front | y 1270-1290: x 1602-1604 / 2301-2304 | z 0.8948..0.9071; -0.2073 / +0.2226 | |
| ribbed cuff | front | y 1295-1385 | z 0.8364..0.8917 | covers the wrist and the upper palm |
| white sleeve | OFF | centre x at y 990 / 1100 / 1200 / 1290: 870.5 / 840 / 812 / 785; end y 1305 | 1.0793:-0.1067 / 1.0117:-0.1255 / 0.9502:-0.1427 / 0.8948:-0.1593; wrist z 0.8856 | forearm ~16° out; elbow ~y 920-950 |
| hand | OFF | wrist (785, 1305), knuckles (745, 1395), middle tip (690, 1470) | (-0.1593, 0.8856) (-0.1839, 0.8302) (-0.2177, 0.7841) | palm forward, thumb out, fingers fanned |
| legs below the hem | front / side | 1780-1907 & 1973-2101 at y 2192; side 3592-3722 | centres -0.0593 / +0.0597, r 0.0391; y -0.0387..+0.0412 | |
| sock cuff | front / side | y 2336-2414 (w 121 px) / 2345-2440 | z 0.2036..0.2515, r 0.0372; z 0.1876..0.2460 | navy star on the outer side |
| sock leg / ankle | front | w 87 px y 2420-2564; 80 px at y 2500 | r 0.0268 / 0.0246 | |
| shoe | front / side | x 1791-1910 (y 2700); toe 3411, heel 3712, heel block 3636-3711 y 2690-2745, topline 2585 | centre -0.0550, w 0.0732; y -0.1501 / +0.0351; heel -0.0117..+0.0344, z 0..0.0338; topline z 0.0984 | |

**Second-pass measurements** (the spec audit; same mappings, each confirmed on zoomed crops of both sides where the
sheet draws both):

| item | view | pixels | metres | note |
| --- | --- | --- | --- | --- |
| ear-tuft outline | front | tip (1836, 119); outer contour (1830, 121) → (1820, 127) → (1812, 140) → (1810, 155-162) → (1813, 173) → junction (1817, 182); inner edge straight to the notch (1847.5, 152.5) | bulge 10.0-10.5 mm from the tip-junction chord (all four front / back tufts) | a rounded fin, the point at its top-inner corner; no hook (only the restyled in-shadow image curls one) |
| ear-tuft light face | front / side / back | #ffdfd2 on 73 % of (1812-1826, 140-170); side sliver x 3647-3660, y 150-185 | | the cup's outer half; none from the back |
| crown between the tufts | front / back | drop below each view's own crown at x 0.025 / 0.037 / 0.049 / 0.057 / 0.075 / 0.081 / 0.085 | 2.5 / 5.5 / 9.2 / 12.8 / 32.0 / 39.2 / 46.4 mm | front and back agree within 0.3 mm |
| lash band lower edge | front, both eyes | her left x 0.0246 → 0.0652: rows 352, 350, 350, 351, 353, 356, 360; her right mirrored | z 1.4711, 1.4723, 1.4723, 1.4717, 1.4705, 1.4686, 1.4662 → 1.4643 | highest at x 0.03-0.04, the outer end 6-8 mm lower: droop 9.5-11° (tare-me) |
| lash band height | front, her right eye | | 4.3 mm at x 0.027, 4.9-5.5 mm in the middle, 4.9 mm at 0.059 | the fringe covers the top of her left band |
| fringe | front | swept lock (1897, 190) → tip (1838, 352); lock A tip (1926, 352); lock B flat bottom x 1928-1953 at y 352; notch (1955, 335), lock C tip (1962, 350); lock D's lower edge on the lash band y 340-348 to x 2040 | SL tip (-0.063, 1.4717); A (-0.009, 1.4717); B -0.007 ... +0.008 at 1.4717; C (0.014, 1.4729); D on the band to x 0.062 | a swept lock + 4 wide locks, split by strand lines |
| bob bell | front / back | row scans 1700-2180 | hw 0.1196 (1.459), 0.1221 (1.445), 0.1233 (1.422-1.437), 0.1215 (1.415), 0.1190 (1.410), 0.1175 (1.408); tips from 1.405 | back view the same; the outermost lock stands 1-2 mm off the main mass at the eyes, 6-12 mm near the tips |
| bob back profile | side | back edge | y 0.1046 / 0.1021 / 0.0984 / 0.0947 / 0.0904 / 0.065 / 0.058 / 0.049 at z 1.445 / 1.430 / 1.415 / 1.408 / 1.403 / 1.400 / 1.390 / 1.386 | the back curls in under to the nape |
| curtains' inner edges | front | 1800-2080 × 380-510 | x ±0.060 (1.445), ±0.052-0.055 (1.430), ±0.049-0.052 (1.415), ±0.044-0.047 (1.413); innermost tips (1875, 457) / (2004, 457) | tips x ±0.039-0.040 at z 1.408, on the jaw outline |
| lavender spikes | front | (1882-1905, 472-490), #e1d7ef | x -0.036 ... -0.022, z 1.387-1.398 | between the jaw and the braid; the 3D render shows them on both sides of the neck |
| braid | side | emerges x 3650-3690; tie x 3690-3705; lobe centres (3670, 503) → (3683, 528) → (3697, 555) | y -0.003 ... +0.0215 (centre +0.009); tie +0.022 ... +0.031 | the lobes lean 23-27° back; the tie band ~14 px (9 mm) in front |
| hand | OFF | wrist (790, 1320); tips (637, 1431), (655, 1467), (692, 1474), (772, 1470), (796, 1427) | 54 / 43 / 32 / 7 / -3° at 116 / 122 / 112 / 93 / 66 mm | all five digits leave through the cuff's mouth (front and back cuffs) |
| ribbed cuff | front / back | front right mouth line (1596, 1382) → (1719, 1414) | dia 65 → 73 (front right), 65 → 76 (back right), 76 → 86 (front left), 76 → 85 (back left) mm; 54-65 mm long | cones flaring to the mouth |
| dress buttons | OFF | centres y 735, 810, 894, then 995 ... 2119 | z 1.236 / 1.190 / 1.138, then 1.076 ... | a 101 px gap across the seam (80-88 px elsewhere) |
| placket lines | OFF | x 1017-1018 and 1070-1072, neckline to hem | x -0.0166 / +0.0166 | two ink lines framing the button line |
| skirt hem lobes | OFF | hem steps 21 / 12 / 40 px at dx -256 / +57 / +327 px | 13 / 7 / 25 mm | about 3 valleys across the front |
| lettuce rim | OFF | | ~5 humps across the front, 9-10 mm wide, 1-4 mm high | |
| sock cuff | OFF | top edges y 2328-2333, fold y 2412-2418 | z 0.256-0.253 / 0.205-0.201 | |
| loafer | side | forefoot sole y 2718-2745; toe top y 2655-2662; heel block x 3638-3716 (ground) / 3628-3716 (top); heel stack y 2688-2745 | sole 13.5-15 mm; toe z 0.051-0.055; block 48 / 54 mm long; stack 35 mm | |
| feet | OFF | apron centrelines vertical; shoe centres ±89.5 px | | the feet parallel |

**Palette swatches** (x 0-185, exact pixel values): 1 `#f2b5a7` (y 2024-2107, hair), 2 `#a66b63` (2149-2232,
cardigan), 3 `#d99559` (2267-2350, buttons), 4 `#91643c` (2387-2470, loafers), 5 `#184059` (2503-2586, dress), 6
`#6387a6` (2619-2702, steel blue: the blue iris), 7 `#ffc1b3` (2739-2822, light pink: the red iris's lower part and the
blush). **Eye colours** (front view): red iris `#d25754` / `#d76f71`, its dark top `#9f2a29`, its lower part `#ffc1b3`;
blue iris `#2b485c` (dark) / `#6387a6` (middle) / `#c4e3e6` (lower); lash line `#3f2924`.

**Overlays.** The landmark table and every section model were drawn over the scaled front and side views of the sheet
(`overlay_front.png`, `overlay_side.png` in the spec agent's scratch work) and adjusted until they matched; the
remaining differences are the Decisions above (4, 8, 9, 15, 16).
