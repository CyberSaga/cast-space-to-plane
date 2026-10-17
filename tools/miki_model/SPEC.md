# Hanabishi Miki (花菱美希): character specification

This is the design spec that was written **before modelling**, from the anime frames and from the user's notes on the
character (an analysis of her hair, headband, scarf and cute-face proportions). It fixed the numbers the part builders
in this directory were written against. The model was then **refined in four review rounds**, so where this document
and `rig.py` or the builders disagree, **the code wins**: it is what `examples/miki.json` is generated from. Those
deviations are marked in the comments of `rig.py` and the builders ("spec ..."), and `rig.SPEC_ONLY_FIELDS` lists the
spec values that no builder reads any more. Read this file for the intent and the likeness checklist (§I), and read
`rig.py` for the numbers in force. See `README.md` in this directory for the maintainer guide.

The section letters A-I are cited from the code (for example `SPEC.md §C.6` in `hair.py`). In this repository a bare
"spec §N" means `docs/spec/spec-v0.1.md`, the castplane spec, so cite this document as `SPEC.md §X`. The anime frames
the spec was drawn from are copyrighted screenshots and are not in the repository; they are not needed to use it.

All lengths are in **metres**, in castplane's world frame:
- Z is up and the soles sit on z = 0.
- She faces **−Y**, and her left is **+x**.
- "hw" means half-width in x. `yf` / `yb` are the front (most negative y) and back (most positive y) extents at the
  midline unless stated otherwise.
- Every number here was binding for the builders unless it is marked *(guide)*.

**Sources:**
- The anime frames (close-ups, an upper-body shot, a 3/4 profile, a clean side profile and a high-angle close-up),
  the user's sketches of the headband, bangs and scarf, and the user's notes (pages on hair, headband and scarf, and
  pages on cute-face proportions).
- **Height:** the official profile on MyAnimeList (myanimelist.net/character/3976) gives **height 151 cm**, weight
  42 kg, age 16, blue hair, green eyes.
- No source describes the Hakuō Academy uniform's skirt, socks or shoes. The choices for those are marked
  **Decision** below.

---

## A. Overall proportions

| quantity | value |
| --- | --- |
| total height (sole to skull top) | **1.510 m** (official 151 cm) |
| hair top | 1.528 m (hair is 18 mm thick on the crown) |
| head height (chin to skull top) | **0.255 m** |
| heads tall | 1.510 / 0.255 = **5.92** |
| chin z | 1.255 |
| head depth (forehead to back of skull, skin) | 0.206 (y −0.091 … +0.115 at z 1.40) |
| skull width (skin) | 0.166 (hw 0.083 at z 1.40) |
| hair mass width at the temples | 0.200 (hw 0.100) |

**Face proportions, measured on the frames.** Let E be the distance from the chin to the eye centre: E = 0.087 = 0.34 of
the head height.

| feature | height above the chin |
| --- | --- |
| mouth | 0.36 E |
| nose | 0.66 E |
| brow (mean) | 1.37 E |
| bang cut | 2.03 E |
| headband front | 2.42 E |
| skull top | 2.93 E |

The eyes sit low in a big cranium, and the forehead shows over about 6 cm between the bang cut and the brows. This is
the cute "baby schema" the user's notes ask for.

### Landmark table

Body column = body surface, or the clothing surface where she is clothed. y values are at the midline unless noted.

| landmark | z | hw (x) | yf | yb | surface / note |
| --- | --- | --- | --- | --- | --- |
| hair top | 1.528 | 0 | 0.010 | 0.010 | hair crown |
| skull top | 1.510 | 0 | 0.012 | 0.012 | skin (under hair) |
| headband front | 1.465 | 0.094 (hair) | −0.092 (band) | 0.132 (hair) | band centreline on the midline |
| bang cut | 1.432 | 0.072 (bangs) / 0.098 (hair) | −0.0975 (bangs) | 0.137 (hair) | flat cut |
| brow line | 1.374 | 0.081 (skin) | −0.089 | 0.113 | brows 1.366 inner … 1.381 outer |
| eye centre | 1.342 | 0.076 (skin) | −0.085 | 0.107 | eye centres x = ±0.040 |
| nose tip | 1.312 | 0.071 | −0.093 | 0.093 | |
| mouth | 1.286 | 0.058 | −0.083 | 0.074 | |
| chin | 1.255 | 0.012 (chin pad) | −0.064 (bottom) | — | jaw underside rises to the neck front (y −0.026, z 1.272) |
| neck base | 1.195 | 0.031 (neck) | −0.022 | 0.046 | neck centre y = 0.012; collar inner edge at 1.205–1.212 |
| shoulder line | 1.180 | 0.160 (sleeve cap) | −0.055 | 0.079 (collar flap) | acromion ≈ (±0.150, 0.005, 1.180); shoulder joint (±0.140, 0.005, 1.155) |
| armpit | 1.065 | 0.130 | −0.104 | 0.089 | the sleeve leaves the torso side here |
| bust | 1.040 | 0.132 | −0.110 (apex at x ±0.050) | 0.089 | blouse; modest bust |
| waist | 0.940 | 0.122 (blouse) | −0.098 | 0.076 | body under it: 0.105 / −0.065 / 0.060 |
| blouse hem | 0.900 | 0.130 | −0.100 | 0.080 | loose hem, slight flare |
| hip widest | 0.780 | 0.165 (skirt) | −0.102 | 0.112 | body: 0.150 / −0.075 / 0.090; pleats open below here |
| crotch | 0.690 | 0.180 (skirt) | −0.120 | 0.130 | legs: hip joints (±0.078, 0.005, 0.780) |
| skirt hem | 0.450 | 0.215 (pleat crests) | −0.158 | 0.168 | A-line pleated skirt |
| knee | 0.420 | 0.123 | −0.048 | 0.048 | leg centre x ±0.077, r 0.046 |
| sock top | 0.385 | 0.1245 | −0.049 | 0.049 | sock = leg + 1.5 mm |
| ankle | 0.065 | 0.106 | −0.019 | 0.039 | ankle centre (±0.077, 0.010), r 0.029 |
| sole | 0.000 | 0.130 (shoe outer) | −0.175 (toe) | 0.050 (heel) | feet turned out 8° each |

**Body cross-section model (guide for the lofts).**
- Torso, blouse and hips: the front half is a superellipse with exponent 2.5, semi-axes (hw, −yf). The back half is a
  superellipse with exponent 2.5, semi-axes (hw, yb). The widest point is at y = 0.
- Between table rows, interpolate linearly in z.
- Intermediate torso rows for the blouse (z: hw, yf, yb):
  - 1.215: 0.031 / −0.026 / 0.050 (neck root)
  - 1.130: 0.150 / −0.085 / 0.086
  - 0.990: 0.128 / −0.106 / 0.080
- The blouse is **loose**: from the bust down it drapes straight, so it does not follow the waist.

---

## B. Head and face

### B.1 Skin head profile

This is the skin surface of one closed shell for skull and face. The hair covers everything above the bang cut and
behind the sidelocks.

The cranium above z = 1.40 is the ellipsoid with centre (0, 0.012, 1.405) and semi-axes (0.083, 0.103, 0.105). Below
1.40 the face table takes over.

| z | hw | y_front (midline) | y_back (midline) | note |
| --- | --- | --- | --- | --- |
| 1.510 | 0.000 | 0.012 | 0.012 | top |
| 1.500 | 0.035 | −0.032 | 0.056 | |
| 1.480 | 0.057 | −0.057 | 0.081 | |
| 1.460 | 0.069 | −0.073 | 0.097 | under the headband |
| 1.440 | 0.077 | −0.083 | 0.107 | |
| 1.420 | 0.082 | −0.089 | 0.113 | forehead |
| 1.400 | 0.083 | −0.091 | 0.115 | widest skull, forehead front |
| 1.380 | 0.082 | −0.090 | 0.114 | brow ridge (very soft) |
| 1.360 | 0.079 | −0.087 | 0.111 | |
| 1.342 | 0.076 | −0.085 | 0.107 | eyes; the bridge between them |
| 1.325 | 0.074 | −0.088 | 0.100 | **cheeks fullest** (just below the eyes) |
| 1.312 | 0.071 | −0.093 | 0.093 | nose tip (the bump is local, width ±0.006) |
| 1.300 | 0.066 | −0.085 | 0.085 | under the nose |
| 1.286 | 0.058 | −0.083 | 0.074 | mouth |
| 1.272 | 0.046 | −0.078 | 0.060 | jaw narrows fast; back = nape into the neck |
| 1.262 | 0.030 | −0.073 | (neck) | |
| 1.257 | 0.016 | −0.068 | (neck) | small rounded chin |
| 1.255 | 0.000 | −0.064 | — | chin bottom |

- **Jaw underside:** (y, z) = (−0.064, 1.255) → (−0.050, 1.258) → (−0.038, 1.263) → (−0.026, 1.272), where it meets
  the neck front.
- **Back of the head:** below z 1.30 it curves into the nape, at (y 0.050, z 1.27).
- **Cross-section at height z:**
  - Front half: superellipse `|x/hw|^3 + |(y−c)/(c−yf)|^3 = 1`.
  - Back half: ellipse with semi-axes (hw, yb − c).
  - The widest-point offset c is 0.012 for z ≥ 1.40, 0 for z ≤ 1.33, and linear in between.
  - Exponent 3 keeps the face front fairly flat, so the eyes wrap only about 17 mm in depth across their 42 mm width.
- **Face-surface y at the feature points.** These come from that model; place the features on the surface with these
  values.

  | point (x, z) | y |
  | --- | --- |
  | eye centre (±0.040, 1.342) | −0.0805 |
  | eye inner corner (±0.019) | −0.0845 |
  | eye outer corner (±0.061) | −0.066 |
  | brow inner (±0.020, 1.366) | −0.0874 |
  | brow outer (±0.058, 1.381) | −0.0767 |
  | mouth (0, 1.286) | −0.083 |
  | forehead at the bang cut, x = 0 / 0.04 / 0.06 / 0.07 | −0.0854 / −0.081 / −0.068 / −0.054 |

- **Neck:** an elliptic cylinder with hw 0.031, y from −0.022 to 0.046 (centre 0.012), from z 1.180 (inside the
  torso) to 1.285 (inside the head). It is thin, as the user's notes ask.
  - Its base flares into a **décolleté bib** that fills the collar's V opening down to z 1.165. The bib lies 1 mm
    above the blouse surface between the collar inner edges, so skin, not pink blouse, shows at the throat (close-up
    and upper-body frames).
  - The bib is part of the neck shell.
- **Ears: do not model them.** The side curtain and the sidelocks hide them from every view in the frames (3/4
  profile and side profile), and leaving them out saves about 100 polygons. The ear's position, which the hair must
  cover, is centre (±0.078, 0.010, 1.335), height 0.040.

### B.2 Eyes

The eyes are the most important facial feature. The user's notes ask for a big full eye with a heavy lid pressed down
over it.

| item | value |
| --- | --- |
| eye centre | (±0.040, 1.342); surface y −0.0805 |
| width (inner to outer corner, chord) | 0.042: inner corner x ±0.019, outer corner x ±0.061 |
| spacing between the inner corners | 0.038 (about one eye width, as the user's notes advise) |
| full eye height (if the lid were up) | 0.040 (1.323 to 1.363) |
| **visible opening** | from the lower lid (bottom 1.323 at x 0.040) to the **upper-lid line at z 1.351** (flat) |
| eye axis tilt | 0 (horizontal). The upper-lid line rises 1 mm from inner to outer end (≈ +1.5°) |
| iris | ellipse 0.026 wide × 0.031 tall, centre (±0.040, 1.3375) |
| iris visible part | from the lid line (its top 2.5 mm is hidden under the lid band) down to the lower lid |
| pupil | ellipse 0.012 × 0.016, centre (±0.040, 1.337) |
| highlight *(recommended)* | disc of diameter 0.005 at (cx − 0.008, 1.3445) on **both** eyes, on the same side (her right, −x): the light comes from the upper left of the image in the close-up frame |

**Sclera outline.** The lower boundary is a smooth curve: inner corner (0.019, 1.3435) → (0.028, 1.327) → bottom
(0.040, 1.323) → (0.052, 1.326) → outer corner (0.061, 1.3455). The upper boundary is the lid line.

**Layer stack.** Each layer is a thin closed slab that conforms to the face surface. Its back face sits 0.3 mm below
the skin, and its front face is the stated height above the skin.

| layer | object | front face above the skin |
| --- | --- | --- |
| sclera | `eyes` | 0.6 mm |
| iris | `eyes` | 1.0 mm |
| pupil | `eyes` | 1.3 mm |
| highlight | `eyes` | 1.6 mm |
| upper-lid band | `face_marks` | 1.8 mm, so it overlaps the top of the sclera and iris |
| lower-lid mark | `face_marks` | 1.0 mm |

The slabs are separate shells, never coplanar.

**Upper-lid band.** This is the smug look: thick, flat, dark.
- It runs from the inner corner (±0.018, z 1.3495) to the outer corner (±0.062, z 1.3515).
- Its height (in z) is 0.0035 in the middle and tapers to 0.002 at the inner end.
- At the outer end there is a **downward flick** (the lash hook in the close-up
  frame): 0.007 long, 0.002 wide, pointing down and outward at about 60° below horizontal, so its tip is at about
  (±0.064, 1.343).

**Lower-lid mark.** A 1.0 mm band along the outer 60 % of the lower sclera edge, 0.4 mm outside it, from about x 0.036
to 0.058.

### B.3 Brows

The user's notes ask for brows that are close to the eyes, short, with the inner end low and the outer end high. The
close-up frame agrees: its brows slope strongly up toward the temples, with the inner end lowest.

| | |
| --- | --- |
| inner end | (±0.020, 1.366), y −0.0874: 15 mm above the lid line |
| middle | (±0.039, 1.375): 1.5 mm of upward arch |
| outer end | (±0.058, 1.381), y −0.0767 |
| tilt | about 22° rising outward |
| width | 1.8 mm, tapering to 1.0 mm at the outer end |
| height | raised 0.8 mm (`face_marks`) |

### B.4 Nose and mouth

- **Nose:** a tiny bump in the skin mesh only. The tip is at (0, −0.093, 1.312) and stands 5 mm proud of the cheek
  plane. The bridge starts at z 1.330. There are no nostrils and no mark. In a line drawing it shows only as a side
  silhouette.
- **Mouth:** a small **ω cat mouth**. The user practises this smug ω, and the user's notes ask for it to be small,
  close to the nose and with raised corners.
  - Width 0.014, centre (0, 1.286), y −0.083.
  - It is two arcs, each 0.007 wide with a sag of 1.2 mm. The middle cusp is at z 1.2868 and the corners at 1.2875.
  - Band 1.2 mm, raised 0.8 mm (`face_marks`).
  - *(The close-up frame shows a tiny flat frown 10 mm wide. The ω is a decision for the smug look.)*
- Mouth to nose is 26 mm and mouth to chin is 31 mm, so the lower face is short.

---

## C. Hair (the most important part for likeness)

**Colour:** lavender blue, `#b9c3e6` (frames: pale periwinkle).

**Hair thickness over the scalp (outer hair surface minus skin):**

| place | thickness |
| --- | --- |
| crown / top | 0.018 |
| front under the headband | 0.017 (bangs root and top hair pushing the band out) |
| sides above the ears | 0.0165 |
| back of the skull | 0.022 |
| side curtain and back sheet | 0.020 to 0.026 (table C.6) |

The top hair surface is the offset ellipsoid with centre (0, 0.012, 1.405) and semi-axes (0.0995, 0.1195 front /
0.125 back, 0.123 up). Above the band it is smooth and combed (no lines).

**Hairline:** not visible. It runs under the bangs at z ≈ 1.440 (8 mm above the cut, so no skin gap shows) and then
down the temples behind the sidelocks. The cap's front boundary follows this line.

**Parts.** All parts are closed shells in object `hair`. They may interpenetrate only where the overlap is buried
inside the hair mass:
- H1 dome
- H2 side curtain + back sheet
- H3 bangs
- H4 sidelocks ×2
- H5 stray strand

### C.1 Headband (object `headband`)

The headband is one continuous thin band lying on the corner where the top of the head turns into the forehead (the
user's notes and the side-profile frame).

- **Plane:** it contains the x direction and passes through the front point. It is tilted **12° from horizontal,
  descending toward the back**: `z = 1.465 − tan(12°)·(y + 0.0905)`.
- **Centreline** (on the hair surface + 1.5 mm). Mirror it for −x. Points (x, y, z):
  - (0.000, −0.0918, 1.4652)
  - (0.0155, −0.0905, 1.4650)
  - (0.0331, −0.0850, 1.4638)
  - (0.0503, −0.0750, 1.4617)
  - (0.0618, −0.0650, 1.4596)
  - (0.0705, −0.0550, 1.4575)
  - (0.0773, −0.0450, 1.4553)
  - (0.0827, −0.0350, 1.4532)
  - (0.0869, −0.0250, 1.4511)
  - (0.0901, −0.0150, 1.4490)
  - (0.0915, −0.0050, 1.4469) = the end
- **Visible span:** about x ±0.087. From y ≈ −0.028 back it passes **under the side curtain (H2)**, and its capped ends
  (y −0.005) are buried at least 4 mm inside H2. This is "the ends tuck into the hair".
  - Seen from the front it shows as a gentle arc. It is z 1.465 in the middle and z 1.452 where it disappears at the
    bang ends.
- **Cross-section:** a rectangle 0.008 wide (along the surface, across the band) × 0.003 thick.
  - Its inner face lies on the hair surface. Embed it 0.5 mm into the hair so there is no gap.
  - The band does not stand off the hair; it bulges only because the hair under it is thick.
- **Pink centre line:** a raised ridge 0.002 wide and 0.0006 high, centred on the band's outer face, along the whole
  visible span.
  - Build it as its own thin closed shell in object **`uniform`** (pink-red), so that the GLB/MTL colour is right and
    its two borders draw as the anime's "two thin lines".

### C.2 Bangs (H3)

The bangs are a short, thick, evenly cut fringe below the band (hime-cut style, per the user's notes).

| | |
| --- | --- |
| extent | x −0.072 … +0.072, following the forehead curve (an arc in top view) |
| top edge | tucked under the band (the band's lower edge, z ≈ 1.4615 at the middle, 1.452 at x ±0.072); the slab continues 5 mm up under the band into H1 |
| cut line | **z = 1.432, constant** (straight in the front view); about 6 cm above the brows (big forehead) |
| inner surface | 1 mm off the forehead skin (forehead y at the cut: see B.1) |
| thickness | **0.011, even down to the cut** (the cut shows a thick edge, per the user's notes) |
| outer surface at the midline | y −0.089 at the top, −0.0975 at the cut (leaning forward about 16°, which gives the side-profile frame's flat block face) |
| inward curve | the bottom 4 mm curls 2 mm toward the forehead; the cut face stays flat and perpendicular to the slab; no pointed tips |
| side ends | vertical end faces at x ±0.072, where the sidelock roots begin; a sliver of this end face is visible in 3/4 views (per the user's notes) |

### C.3 Sidelocks (H4, mirrored pair)

The sidelocks are long, straight locks in front of the ears, framing the face and covering the cheek edges in the front
view. Their roots grow out of H1/H2 at the temples, right beside the bang ends.

**Cross-section:** a flat ribbon, 0.026 wide (inner edge to outer edge) × **0.009 thick** (lens/rounded-rectangle).
It is angled to wrap around the head: the inner edge is more forward than the outer edge.

The table gives the edge positions (centre of the thickness) for her left (+x). Mirror for −x.

| z | inner edge (x, y) | outer edge (x, y) | note |
| --- | --- | --- | --- |
| 1.445 | (0.072, −0.060) | (0.098, −0.030) | root, merged into H1/H2 |
| 1.400 | (0.072, −0.068) | (0.098, −0.036) | covers the forehead corner / temple |
| 1.370 | (0.072, −0.066) | (0.098, −0.034) | |
| 1.342 | (0.072, −0.052) | (0.098, −0.026) | 3.3 mm off the skin at the eye level |
| 1.310 | (0.072, −0.046) | (0.098, −0.022) | the face is now narrower than 0.072 |
| 1.270 | (0.073, −0.044) | (0.099, −0.022) | beside the jaw |
| 1.220 | (0.073, −0.054) | (0.099, −0.034) | starts to come forward over the shoulder |
| 1.180 | (0.074, −0.068) | (0.100, −0.052) | ≥ 12 mm in front of the collar/shoulder |
| 1.145 | (0.074, −0.086) | (0.101, −0.072) | lies on the collar lapel |
| 1.120 | (0.074, −0.092) | (0.101, −0.078) | **straight horizontal cut** (upper chest, above the V tip 1.09) |

- **Front view:** the inner edge x 0.072 covers the face outline from the temple down to the cheeks (face hw 0.076 at
  the eyes, 0.074 at the cheeks). Below z 1.31 the jaw narrows inside the frame of hair, as in the upper-body frame.
- **Side view:** the face shows in front of the sidelock's front edge: 28 mm at eye level. The eye is fully visible.
  - **Decision:** the side-profile frame shows more cheek in profile. Here the front-view framing wins, because the
    user's notes call it the most effective slimming device. The trade-off is accepted.
- One shallow strand crease runs along the middle of each sidelock's front face (x ≈ 0.086), from z 1.43 to the cut.

### C.4 Stray strand (H5)

There is exactly **one**, on **her LEFT (+x)**.
- The close-up, upper-body and 3/4 profile frames all show it on the image side that is her left.
- An early description said "her right temple", which reads the close-up from the viewer's side. The frames win.

Centreline (x, y, z). It keeps 3–4 mm clear of the skin, 1.5 mm clear of the bangs and 5 mm clear of the band:

| point | position | where |
| --- | --- | --- |
| P0 | (0.022, −0.086, 1.474) | root on H1, just above/behind the band |
| P1 | (0.030, −0.093, 1.463) | arches over the band |
| P2 | (0.040, −0.096, 1.432) | crosses the bangs, passing their cut |
| P3 | (0.052, −0.086, 1.400) | runs diagonally outward over the forehead |
| P4 | (0.063, −0.074, 1.368) | crosses the outer end of the brow, as in the close-up frame |
| P5 | (0.071, −0.060, 1.335) | passes 8 mm outside the eye's outer corner, in front of the sidelock |
| P6 | (0.074, −0.062, 1.305) | tip, lying on the sidelock's front face |

- Length ≈ 0.19.
- Cross-section 4 mm wide × 2 mm thick (4 to 6 sides), tapering to a point over the last 30 mm.
- Sweep it along a smooth (Catmull-Rom) curve through P0–P6.

### C.5 Dome (H1)

H1 is the offset ellipsoid above. It is closed at the bottom by a flat cap buried inside the skull at about z 1.43.
Its front part under the band is hidden by H3 and the band. It is one smooth surface with no lines.

### C.6 Side curtain and back sheet (H2)

H2 is one lofted shell from z 1.450 down to the tips. The cross-section is a **crescent (horseshoe)** that opens toward
the face.

For z ≥ 1.215, the outer contour is the ellipse with centre (0, cy), semi-axes ax (x) and ay_b (back). The inner
contour is the outer contour offset inward by the thickness t. The crescent ends in **blunt end faces** at y_end (the
curtain's front edge):

| z | cy | ax | outer back y | t | front edge y_end | note |
| --- | --- | --- | --- | --- | --- | --- |
| 1.450 | 0.012 | 0.0985 | 0.136 | 0.020 | −0.034 | starts under H1, behind the sidelock root |
| 1.400 | 0.012 | 0.1000 | 0.137 | 0.020 | −0.034 | covers the ear zone |
| 1.340 | 0.012 | 0.1020 | 0.133 | 0.022 | −0.028 | |
| 1.290 | 0.012 | 0.1035 | 0.128 | 0.024 | −0.022 | |
| 1.250 | 0.020 | 0.1060 | 0.125 | 0.026 | +0.010 | goes behind the jaw; the neck shows between curtain and sidelock (3/4 profile frame) |
| 1.215 | 0.040 | 0.1100 | 0.123 | 0.028 | +0.060 | goes behind the shoulders |

For z ≤ 1.18 H2 becomes the **back sheet**: a curved plate hanging behind the shoulders and back.
- Its inner surface is the blouse/collar back surface offset by **+8 mm** wherever that surface is closer than the
  midline values below. Otherwise it hangs vertically.
- Its lateral edges are blunt faces at x ±hw.

| z | hw | midline inner y | midline outer y | thickness |
| --- | --- | --- | --- | --- |
| 1.180 | 0.122 | 0.090 | 0.121 | 0.020 |
| 1.100 | 0.130 | 0.099 | 0.119 | 0.020 |
| 1.000 | 0.137 | 0.099 | 0.118 | 0.019 |
| 0.920 | 0.143 | 0.099 | 0.117 | 0.018 |
| 0.860 | 0.150 | 0.100 | 0.116 | 0.016 |

- **Width:** 0.244 at the shoulders, flaring slightly to 0.300 at the ends.
- **Length:** to the hips. The flat part ends at z 0.860.
- **Drape:** it hangs straight with gravity. Below the shoulder blades it does not follow the waist inward, so it is
  about 2 cm off the blouse at the waist and 3 mm off the skirt's back at the ends.
  - It covers the back collar flap except the flap's lower corners and the bottom 2 cm.
  - Nothing goes in front of the shoulders except the sidelocks.
- **Ends:** **7 shallow pointed clumps** across the width.
  - The notch roots are at z 0.860 and the tips at **z 0.830**. Tips sit at x = −0.129, −0.086, −0.043, 0, 0.043,
    0.086, 0.129.
  - Each clump's lower end is a flat blunt face, and the clumps end in shallow points (side-profile and
    upper-body frames).
- **Strand creases:** 4 creases on the back sheet's outer surface, between clumps 2/3, 3/4, 4/5 and 5/6. Each is a
  2 mm deep V-groove from z 1.30 to the notch roots.

---

## D. Body and outfit

### D.1 Torso and blouse (object `uniform`)

- The top is one closed solid from the neck root to the hem: the pink-red sailor blouse. It is loose; the bust is
  modest (apex y −0.110 at x ±0.050).
- Use the landmark table and the cross-section model in §A.
- **Hem:** at z 0.900, hw 0.130, front −0.100, back 0.080. The hem bottom is a flat ring/disc. The rim edge is a
  feature line.
- No visible seams or darts.

### D.2 Sailor collar (object `collar`, white)

The collar is a thin shell **4 mm thick**. It lies on the blouse with a 1 mm gap.
- Over the front lapels the gap grows from 1 mm at the neckline edge to the lift listed at O6–O8 (10 / 9 / 6 mm) at
  the outer edge, so the lapel can lie **over the scarf ribbon** (D.3). On the back flap and the shoulder tops the gap
  is 1 mm everywhere.
- It is symmetric. Points are given for her left half; mirror them.
- All points are on the collar **underside** (blouse surface + gap), placed on the torso model of §A. The 4 mm
  thickness grows outward from them.

**Outer edge** (O1 → O9):

| point | position | where |
| --- | --- | --- |
| O1 | (0.000, 0.085, 1.030) | back flap, bottom centre |
| O2 | (0.105, 0.061, 1.030) | back flap bottom corner (a square corner; the flap wraps the back) |
| O3 | (0.105, 0.070, 1.120) | flap side, going up |
| O4 | (0.110, 0.045, 1.188) | turning forward over the shoulder |
| O5 | (0.118, 0.000, 1.192) | on top of the shoulder (torso top at x 0.118 + 1 mm), inside the sleeve seam (acromion x 0.150) |
| O6 | (0.116, −0.058, 1.170) | front of the shoulder (lapel lifted 10 mm over the scarf) |
| O7 | (0.082, −0.084, 1.136) | lift 9 mm |
| O8 | (0.040, −0.097, 1.110) | lift 6 mm |
| O9 | (0.000, −0.099, 1.090) | **V tip** (lift 1 mm; the collar front surface is at −0.103) |

**Inner edge / neckline** (I1 → I7):

| point | position |
| --- | --- |
| I1 | (0.000, 0.052, 1.212) |
| I2 | (0.034, 0.045, 1.210) |
| I3 | (0.042, 0.012, 1.213), on top of the trapezius beside the neck |
| I4 | (0.038, −0.043, 1.195) |
| I5 | (0.030, −0.063, 1.168) |
| I6 | (0.015, −0.087, 1.128) |
| I7 | (0.000, −0.099, 1.090) = O9 |

- **Back flap:** 0.210 wide and 0.18 tall (z 1.030 to 1.212). Its lower edge is at z 1.030, below the shoulder blades.
  The bottom edge is straight across in the back view.
- **Lapel width:** 0.076 over the shoulder (x 0.042 to 0.118), 0.050 at z 1.14, and zero at the V tip.
- **V tip:** **z 1.090**, about 3 cm above the bust line, just above the armpit level.
- **Pink stripe (one):** a band 0.008 wide whose outer border is **0.010 inside the outer edge**. It runs along the
  whole outer edge: the back bottom edge, the flap sides, over the shoulders and down both lapels. The two lapel
  stripes meet in a small V just above the V tip.
  - Build it as a raised band 0.8 mm high, a separate thin shell in object **`uniform`** (pink-red, the frames' stripe
    colour).
  - Cross-check: the upper-body, 3/4 profile and high-angle frames show white / pink / white at the collar edge, so
    there is one stripe. The user's drawing agrees.
- **Dickey (V filler):**
  - A white triangle in object `collar`, 1.5 mm thick. Its mid-thickness corners are (±0.024, −0.066, 1.165) and
    (0, −0.0985, 1.096).
  - It lies 1 mm above the blouse and tucks under the lapels' inner edges.
  - Above it, skin shows (the décolleté bib, B.1).

### D.3 Scarf (object `scarf`, yellow), ring and tips

The scarf runs behind the neck under the collar. That part is **not modelled**, because the collar hides it from every
view.

**Visible ribbons (left and right):** each is swept along this path, from under the collar at the shoulder into the
ring. Each point is the centre of the thickness: blouse surface + 1 mm + half the thickness.

| point | position |
| --- | --- |
| S0 | (0.120, −0.052, 1.176), hidden under the collar |
| S1 | (0.110, −0.064, 1.150), 17 mm below the lapel edge |
| S2 | (0.080, −0.085, 1.120) |
| S3 | (0.044, −0.098, 1.098) |
| S4 | (0.012, −0.104, 1.080) |
| S5 | (0.006, −0.110, 1.070), inside the ring |

- **Cross-section:** a lens (sharp edges, puffy middle). Width 0.045 at S0, narrowing to 0.018 at S4. Thickness
  0.010 at S0 to 0.006 at S4. The width lies in the chest surface.
- The centreline runs about 8 mm outside/below the collar's outer edge, so a **15–20 mm strip of yellow peeks out
  below the lapel edge** from the shoulder to the V (upper-body and high-angle frames, the user's
  sketch). The rest is tucked under the lifted lapel.

**Ring** (object `collar`, white): a rounded box sewn at the V tip.
- Centre (0, −0.112, 1.072). Size 0.036 (x) × 0.024 (z) × 0.016 (y, from −0.104 to −0.120). Corner radius 0.005.
- Top at z 1.084, just under the V tip.
- **Two pink stripes:** horizontal bands around the ring at z 1.068 and 1.076, each 0.003 tall and raised 0.6 mm.
  They are separate shells in object `uniform`.
- The ring is a solid. The ribbons end and the tips start inside it.

**Two pointed tips** below the ring (scarf). Each is a flat blade 4 mm thick lying on the blouse front, 1–2 mm off it
(blouse front: −0.110 at z 1.04, −0.106 at 0.99).

| | tip A (her right, −x) | tip B (her left, +x) |
| --- | --- | --- |
| root (inside the ring) | (−0.008, −0.113, 1.064), width 0.018 | (0.008, −0.116, 1.064), width 0.018 |
| direction | 15° from vertical toward −x | 15° toward +x |
| length | 0.090 | 0.090 |
| widest | 0.034 at 70 % of the length | same |
| end | oblique cut, 45°; the point is on the outer side, at about (−0.031, −0.113, 0.977) | mirrored: (0.031, −0.116, 0.977) |
| layering | behind | **3 mm in front** of tip A where they overlap |

The tips end above the waist (z 0.975), as in the upper-body frame. The symmetric spread is a **decision**;
the frames show motion blowing them aside.

### D.4 Sleeves, cuffs, hands

- **Sleeve** (object `uniform`): a tube along the arm axis.
  - Radius 0.048 at the shoulder joint, 0.045 at mid upper arm, 0.043 at the elbow, 0.044 along the forearm.
  - The top merges into the torso at the armhole (it overlaps inside the torso). The shoulder silhouette is rounded
    and slightly sloped (per the user's notes).
- **Cuff:**
  - The sleeve ends at the **cuff edge, 0.010 beyond the wrist joint** toward the hand. There the tube closes with a
    5 mm rim, turning in to an opening of radius 0.030. A recessed disc closes it 10 mm inside.
  - **Two white stripes** at 0.012–0.020 and 0.028–0.036 from the cuff edge. Each is 0.008 wide, a raised ring 0.8 mm
    high, and a separate shell in object **`collar`**.
  - Between and beyond the stripes the cuff is pink (upper-body, 3/4 profile and high-angle frames).
- **Hands** (object `skin`): relaxed, fingers together. Each hand is one closed mitten shell.
  - Length 0.140 from wrist to middle fingertip. Palm 0.075 long, 0.066 wide, 0.024 thick.
  - The fingers are 0.065 long, merged into one block that tapers to 0.016 thick and curls 20° at the knuckles and
    15° at the middle joints.
  - The thumb is a lobe 0.050 long and 0.018 thick, starting at the index side of the palm base. It lies forward
    (−y) along the index finger.
  - The wrist goes 15 mm inside the sleeve.
  - Orientation: the palm faces the thigh (medial), turned 20° toward the back. The thumb is in front.

### D.5 Skirt and under-skirt (object `uniform`)

- **Skirt:** light pink, pleated, A-line, knee length. It is a **thick tube** with fabric thickness 3 mm, closed by a
  hem rim and a waist rim. The **bottom is open**, so the legs are visible from a low angle.
  - Waist rim at z 0.950 (hidden under the blouse).
  - Hem at **z 0.450**: 3 cm above the knee centre, covering the top of the kneecap.
  - Outer surface rows (z: hw, yf, yb) at the pleat crests:
    - 0.950: 0.108 / −0.068 / 0.062
    - 0.900: 0.122 / −0.088 / 0.075
    - 0.860: 0.138 / −0.093 / 0.086
    - 0.780: 0.165 / −0.102 / 0.112
    - 0.690: 0.180 / −0.120 / 0.130
    - 0.550: 0.200 / −0.142 / 0.152
    - 0.450: 0.215 / −0.158 / 0.168
  - Cross-section: superellipse with exponent 2.2.
  - At z 0.90 the skirt (hw 0.122) is inside the blouse hem (0.130).
- **Pleats:** **16 knife pleats**, all facing the same way (clockwise seen from above). Each spans 22.5°.
  - The outer cross-section is a sawtooth with 32 vertices per ring: crest and valley alternate. The valley is radially
    0.010 inside the crest at the hem.
  - The depth tapers to **0 at z 0.780**. Above that line the pleats are stitched flat and the skirt is smooth.
  - The inner surface is a plain 16-gon at 3 mm inside the valleys.
  - **Decision:** 16 pleats rather than the real 24 keeps the polygon budget and still reads as pleated.
- **Under-skirt block** (a "bloomers" solid, `uniform`): from z 0.950 to 0.700 it has the body hip shape (hw 0.150 at
  0.78, y −0.075/0.090). The legs start inside it at z 0.720. Its bottom shows only from a low angle.

### D.6 Legs, socks, shoes

- **Legs** (`skin`): from z 0.720 (inside the under-skirt block) to the ankle.
  - Axis: hip joint (±0.078, 0.005, 0.780) → knee (±0.077, 0.000, 0.420) → ankle (±0.077, 0.010, 0.065).
  - Circular radius by z: 0.700: 0.072, 0.600: 0.064, 0.500: 0.054, 0.420: 0.046 (knee), 0.320: 0.050 (calf),
    0.200: 0.040, 0.100: 0.030, 0.065: 0.029.
  - The inner gap between the thighs is 12 mm at z 0.70.
- **Socks** (object `socks`): **Decision: white knee socks.**
  - The sock is the leg surface + 1.5 mm from inside the shoe up to the **sock top at z 0.385**, just below the knee.
  - The top rim is a 1.5 mm step, which draws as a line. The visible skin band runs from 0.385 to the skirt hem 0.450.
- **Shoes** (object `shoes`): **Decision: dark brown penny loafers.**
  - Sole outline length 0.225: heel at y +0.050, toe at y −0.175. Width 0.084 at the ball and 0.062 at the heel.
    Each shoe is turned out 8°.
  - Heel centres at x ±0.082.
  - Sole slab 0.012 thick, with a separate smooth group so the sole line draws. The heel block is 0.025 tall at the
    back.
  - Instep height 0.075. The opening (topline) rim is at z 0.055 around the ankle, so the sock shows above it.
  - The toe is rounded and moc-toe-like.
  - The **saddle strap** is a raised band 0.012 wide across the instep at y ≈ −0.07, 1 mm proud.
  - The soles lie exactly on z = 0, and no vertex goes below 0.

---

## E. Pose (relaxed A-pose)

| item | value |
| --- | --- |
| head | straight, facing −Y, no tilt |
| shoulder joints | (±0.140, 0.005, 1.155) |
| upper arm | 0.245 long, **abducted 20°** in the frontal plane, flexed forward 4° |
| elbow | (±0.224, −0.012, 0.925), **bent 15°** forward |
| forearm | 0.210 long; wrist (±0.292, −0.080, 0.738) |
| wrist | extended 10° back relative to the forearm; middle fingertip ≈ (±0.339, −0.102, 0.608) |
| hand orientation | palm medial, 20° toward the back, thumb forward (D.4) |
| clearance | the sleeve leaves the torso at z 1.06 (the armpit); gap to the blouse is 5.6 cm at the elbow, 7 cm at the cuff, ≥ 10 cm from hand to skirt |
| legs | straight, hip joints (±0.078, 0.005, 0.780), ankles (±0.077, 0.010, 0.065) |
| feet | heel centres at x ±0.082, each turned out 8°, soles flat on z = 0 |

The pose is symmetric except for the stray strand, the eye highlights (same side) and the overlap order of the scarf
tips.

---

## F. Lines plan

castplane always draws a **feature edge**: one between different smooth groups, or a group-0 crease above
`smooth_angle_deg`. It draws **smooth edges** only on the silhouette.

Rules:
- Give every smooth surface patch its own non-zero group.
- Make each designed line a group boundary.
- Never let a tessellation edge inside a patch become a feature.

| part | feature lines (group boundaries / creases) | smooth (silhouette only) |
| --- | --- | --- |
| head skin | none on the face (no jaw line, no nose line); the décolleté bib border is a group boundary | skull, face and nose in one group; the neck in its own group |
| eyes | sclera outline, iris outline, pupil outline and highlight outline (each slab: top face one group, side walls another group) | slab top faces |
| face_marks | the outline of every mark (top face and walls in different groups): brows, upper-lid band with flick, lower-lid mark, mouth ω | — |
| hair H1 | its boundary against H2 and the band is not a mesh edge (separate shells) | whole dome |
| hair H2 | blunt front-edge faces, lateral edge faces and clump end faces as separate groups (curtain edges and hair ends draw); 4 back strand grooves | outer surface between grooves |
| bangs H3 | **cut face** (bottom) as its own group: a strong cut line; 5 vertical strand lines (front face split into 6 strips, 3–4° creases), as in the close-up and upper-body frames; the side end faces | each strip |
| sidelocks H4 | the edge walls (both long edges) and the cut face; 1 central strand crease | front and back faces |
| stray strand H5 | none | one group: draws as a thin silhouette pair |
| headband | both band edges (top/bottom walls in their own group); the pink ridge adds 2 inner lines (`uniform` shell) | outer face |
| collar | outer edge and inner edge walls; the pink stripe band (2 lines, `uniform` shell); dickey outline | collar top face |
| blouse | hem rim | torso, sleeves (shoulder seam not drawn) |
| cuffs | cuff rim; the two white stripe bands (4 lines, `collar` shells) | sleeve |
| scarf | both sharp edges of the lens ribbons; the tip blades' outlines (walls in their own group) | ribbon faces |
| ring | box outline (the rounded corners stay in the face groups); the 2 pink stripe bands | — |
| skirt | **16 pleat crests + 16 valleys as creases** from z 0.78 to the hem (each pleat face its own group); hem rim; waist rim (hidden) | the smooth yoke above 0.78 |
| legs | — | legs |
| socks | sock top rim | sock |
| shoes | sole/upper boundary, topline rim, saddle strap band, heel block edge | upper |
| hands | — (the thumb is a separate lobe, so the silhouette suffices) | hands |

**Colour stripes that must be separate thin raised bands** (castplane cannot draw colour borders):

| stripe | object | size |
| --- | --- | --- |
| headband pink line | `uniform` | 2 mm × 0.6 mm |
| collar pink stripe | `uniform` | 8 mm × 0.8 mm |
| ring pink stripes ×2 | `uniform` | 3 mm × 0.6 mm |
| cuff white stripes ×4 | `collar` | 8 mm × 0.8 mm |

The eye layers and the face marks are slabs as well. The skirt-colour difference is not a line: the blouse hem rim
already separates top and skirt.

---

## G. Polygon budget

The target is ≤ 4 850 polygons, mostly quads, which gives ≤ 9 700 triangles. That stays under both limits:
≤ 6 000 polygons and ≤ 10 000 triangles.

| object / part | polygons | priority |
| --- | --- | --- |
| **hair** | **1 300** | |
| H1 dome | 380 | high (head silhouette) |
| H2 curtain + back sheet + 7 clumps + grooves | 520 | high |
| H3 bangs (6 strips) | 160 | **highest** |
| H4 sidelocks ×2 | 180 | **highest** |
| H5 strand | 40 | high |
| margin | 20 | |
| **skin** | **1 050** | |
| head + face + nose | 560 | **highest** (silhouette in every view) |
| neck + bib | 40 | |
| hands ×2 | 240 | medium |
| legs ×2 | 210 | medium |
| **eyes** (per eye: sclera 24, iris 24, pupil 8, highlight 4) | 120 | **highest** |
| **headband** (band 120) | 120 | **highest** |
| **scarf** (ribbons 2×60, tips 2×40) | 200 | high |
| **socks** ×2 | 140 | low |
| **uniform** | **1 250** | |
| torso / blouse | 380 | high |
| sleeves ×2 | 220 | medium |
| skirt (32-sawtooth outer, 16-gon inner, rims) | 400 | high |
| under-skirt block | 50 | low |
| stripes (headband line 40, collar stripe 120, ring stripes 2×20) | 200 | high |
| **collar** (collar 240, dickey 20, cuff stripes 4×24, ring 24) | 380 | **highest** |
| **face_marks** (brows 2×12, lid bands 2×20, lower lids 2×8, mouth 30) | 110 | **highest** |
| **shoes** ×2 | 180 | low |
| **total** | **4 850** | |

If the budget is tight, cut in this order: socks, shoes, legs, hands, under-skirt, sleeves. Never cut the face, eyes,
bangs, sidelocks, headband or collar.

---

## H. Colours (sRGB, for the MTL and GLB)

| object | colour | notes |
| --- | --- | --- |
| hair | `#b9c3e6` | |
| skin | `#fbe3d6` | |
| eyes | `#7fb3a8` | Optional per-face sub-materials if the exporter supports `usemtl` / GLB primitives: sclera `#ffffff`, pupil `#2f5c57`, highlight `#ffffff`. Otherwise all teal. |
| headband | `#f4dce8` | white with a pink cast; the pink line shell is in `uniform` |
| scarf | `#f6c453` | |
| socks | `#f2f2f2` | white (decision) |
| uniform | `#e8667a` | pink-red. Optional sub-material for the skirt and under-skirt: `#f5b9c6` (light pink, upper-body frame) |
| collar | `#fafafa` | |
| face_marks | `#4b3434` | dark brown |
| shoes | `#6b4a3a` | |

---

## I. Likeness checklist (ranked)

Each check is something a reviewer can verify on a render from the named view.

1. **Head-to-body ratio** (front, full figure): the figure is 5.8–6.0 heads tall (chin to skull top = 0.255 of 1.51
   m), and the head is plainly large.
2. **Blunt thick bangs under a thin band** (front and 3/4 front): a straight horizontal cut line at about 1/3 of the
   way from the headband down to the brows (z 1.432). It has a visible cut thickness and no pointed tips.
3. **Headband placement** (side): the band crosses the midline on the top-to-front corner (z 1.465, about 50° up from
   the forehead front). It runs back at a gentle downward slope and disappears into the side hair before the ear
   zone.
4. **Headband reads as two thin lines plus a centre line** (head close-up, front): the band is ≤ 8 mm wide, with its
   two edges and the pink ridge drawn.
5. **Big exposed forehead** (front): the skin from the bang cut to the brows is at least 55 mm tall, about 1/3 of the
   face height from cut to chin.
6. **Long straight sidelocks frame the face** (front): two straight locks from the temples to the upper chest
   (z 1.12) with a straight cut. Their inner edges cover the face outline from the temples to the cheeks.
7. **Big eyes with a heavy flat upper lid** (head close-up, front): the eye is 42 mm wide (≥ 27 % of the face width)
   and the iris diameter is about 26 mm. The flat thick lid line covers the iris top, so the eye reads half-lidded and
   smug.
8. **Eye position** (front): the eye centres are at about 34 % of the head height above the chin, and the inner corners
   are about one eye width apart.
9. **Brows: inner end low, outer end high** (front): thin and close to the eyes, rising outward at about 20°.
10. **Small chin, round cheeks** (front, 3/4 front): the face is widest just below the eyes and narrows quickly to a
    small rounded chin. Mouth to chin is ≤ 32 mm.
11. **Tiny nose, small mouth close to the nose** (head close-up, front and side): the mouth is ≤ 15 mm wide, 26 mm below
    the nose tip. The nose shows only as a side silhouette.
12. **The single stray strand on her left** (front, 3/4 front): one thin strand from just above the band crosses the
    bangs and the forehead diagonally outward and passes outside her left eye. There is none on the right.
13. **Very long straight back hair** (back, side): a sheet from the head to z 0.83 (hips), about 0.24 wide at the
    shoulders and 0.30 at the ends, with pointed clump ends.
14. **Nothing in front of the shoulders except the sidelocks** (3/4 front): the back hair passes behind both shoulders,
    and the neck is visible between the sidelock and the curtain in side view.
15. **Sailor collar** (front, back): a white V reaches z 1.09. The back square flap is 0.21 wide and ends at z 1.03.
    One stripe band runs parallel to the outer edge all round.
16. **Scarf through the ring** (front, low angle): yellow peeks out below both lapels. A white ring with two stripe
    bands sits at the V tip, and two pointed tips hang below it to about z 0.975.
17. **Sleeve cuffs with two stripes** (front, 3/4 front): long loose sleeves end at the wrist with two raised bands near
    the cuff edge.
18. **Light pink pleated skirt** (3/4 front, low angle): knee length (hem z 0.45), with 16 crease pairs starting at the
    hip line (0.78), a smooth yoke above, an A-line flare, and the legs visible from below.
19. **Cast shadow and silhouette in the scene camera** (scene camera): a clean silhouette with no wireframe noise. Lines
    appear only where §F lists them.
20. **Shoes and socks** (side, low angle): white knee socks ending at z 0.385 and brown loafers flat on the ground,
    turned out 8°.

---

## Self-consistency checks (verified on the numbers)

- **Hair outside the scalp:**
  - Dome offset 16.5–22 mm.
  - Bangs 1 mm off the forehead.
  - Sidelock back faces ≥ 3 mm off the skin at every z ≥ 1.31, and ≥ 12 mm in front of the collar/shoulder at z 1.18.
  - Strand 3–4 mm off the skin.
  - Back sheet ≥ 7 mm behind the collar flap (blouse back 0.086 + 5 mm collar at z 1.10), ≥ 10 mm at z 1.18, and
    3 mm off the skirt at its ends.
- **Ear zone** (centre y 0.010, z 1.335): covered by the curtain (front edge y −0.028 at that height, overlapping the
  sidelock's back edge by ≥ 4 mm in side view, so no temple skin shows between them) and by the sidelock in front of
  it.
- **Collar on the shoulders:** every O/I point was evaluated on the torso model of §A and placed at blouse + gap.
  - O5 (z 1.192) is the torso top at x 0.118, plus 1 mm.
  - The V tip underside is −0.099 against the blouse's −0.098 at z 1.09.
  - I4–I6 are 1 mm in front of the blouse.
  - The dickey and the scarf path S0–S4 are on blouse + 1 mm + half their thickness. S1 runs 17 mm below the lapel
    edge, which gives the yellow peek strip.
- **Ring and tips in front of the blouse:** the ring's back face is −0.104 against the blouse's −0.102 at z 1.072.
- **Skirt over the hips:** skirt hw 0.165 against body 0.150 at z 0.78. The skirt is inside the blouse hem at z 0.90.
- **Arms clear in the A-pose:** a numeric check of the arm tube against the torso/skirt half-widths. The sleeve
  separates from the torso at z 1.06. The gap is 3.7 cm at z 0.97, 5.9–7.2 cm along the forearm and 10–13.5 cm at the
  hand.
- **Arms clear of the back hair:** the arms are at y ≤ 0.05; the back sheet is at y ≥ 0.09.
- **Legs:** 12 mm apart at the thighs, inside the skirt (hem hw 0.215 against leg outer x 0.123 at 0.45).
- **Ground:** soles at z = 0; the lowest vertex is z = 0.

## Decisions (not shown in the frames)

1. Height 151 cm, from the official profile as listed on MyAnimeList.
   Head 0.255 m, 5.92 heads.
2. Socks: white knee socks, top at z 0.385. Shoes: dark brown loafers. Skirt: knee length (hem 0.45), 16 knife pleats.
3. Skirt colour: light pink `#f5b9c6`. It stays in object `uniform` (optional sub-material).
4. No ears.
5. Mouth: a small ω, not the close-up frame's flat frown.
6. The stray strand is on her left (+x), from the frames, not the early "right temple" wording.
7. Eye highlights are on the same side (−x) for both eyes, following the close-up frame.
8. The scarf tips spread symmetrically ±15°. Tip B is in front.
9. The collar has one pink stripe.
10. The ring has two pink stripes. The cuffs have two white stripes, at 12–20 and 28–36 mm from the cuff edge.
11. The scarf behind the neck is not modelled.
12. The dickey covers the V from z 1.165 down. Skin shows above it.
13. Sidelocks cover the cheek edges in the front view at the cost of some profile cheek (C.3).
14. The back hair ends at z 0.83 in 7 shallow clumps.
15. Colour stripes are raised bands placed in the object with the matching colour (pink → `uniform`, white →
    `collar`).
