# Oak's Lab — First Person

A first-person exploration mini-game recreating Professor Oak's Pokémon Lab from
*Pokémon Yellow* (Pallet Town, Gen 1). Single self-contained HTML file, zero
dependencies, no external assets — open `index.html` in any browser and play.

```
# from this directory; or just double-click index.html
python3 -m http.server 8000   # then open http://localhost:8000
```

## Design

### Concept

Pokémon Yellow is a tile-grid game, so the natural first-person treatment is a
**grid raycaster** (Wolfenstein 3D-style): the Gen 1 tile map *is* the world
geometry. The game renders at 320×200 into a software framebuffer and upscales
with nearest-neighbour, keeping the chunky pixel aesthetic of the source
material. All wall textures and character sprites are procedural pixel art
generated in code at startup — no copyrighted assets are shipped.

### The lab

The floor plan follows the Gen 1 lab layout: a row of lab machines along the
back wall (one PC has a readable e-mail), two double rows of bookshelves
("Crammed full of POKéMON books!") in the middle, two aides, potted plants
flanking the entrance, and the sliding exit door at the south end. Professor
Oak waits at the back beside the table with the one spoken-for Poké Ball —
and a certain shy, wild-caught Pikachu.

### Quest loop (the Yellow opening, replayed in first person)

1. **Find PROF. OAK** — spawn at the entrance, explore freely.
2. **Talk to PIKACHU** — Oak introduces you; until then Pikachu eyes you warily.
3. **Leave the LAB** — once Pikachu joins, it physically follows at your heels
   (with an idle bob). Try to leave early and Oak stops you, exactly as he
   should. Reaching the door with Pikachu rolls the ending.

Everything in the room is interactable: Oak, Pikachu, both aides, the Poké
Ball table, plants, bookshelves, machines, and the door — each with Gen 1
flavour text in a typewriter dialog box styled after the Game Boy text frame.

### Controls

| Input | Action |
|---|---|
| `W A S D` | move / strafe |
| `← →` or mouse (click to lock pointer) | look |
| `E` / `Z` / `Enter` / `Space` / click | interact, advance dialog |
| `P` | toggle authentic 4-shade Game Boy palette |
| `M` | toggle minimap |
| `R` | restart (after the ending) |

## Implementation notes

- **Renderer** (`index.html`, one `<script>`): per-column DDA raycast for
  walls with perspective-correct texturing and side/distance shading;
  per-scanline floor *and* ceiling casting; billboard sprites sorted far-to-near
  and clipped per-column against the wall z-buffer. ~60 fps at 320×200.
- **World**: the map is an ASCII art string array (`#` wall, `M` machine,
  `B` bookshelf, `D` door). Sprites are entities with position, a pixel-art
  texture, a world-height scale, and a per-sprite collision radius (Pikachu's
  is larger so you stop at a distance where a knee-high Pokémon is still in
  frame — a raycaster has no look-down pitch).
- **Art**: wall textures are painted onto offscreen canvases with procedural
  fills; characters are string-map pixel art (one char = one palette colour)
  converted to RGBA buffers with transparency.
- **Dialog/quest**: a paged typewriter dialog queue with an `onClose` callback
  drives the 4-stage quest state machine. Movement locks while dialog is open,
  Gen 1 style.
- **Audio**: tiny WebAudio square-wave blips for text, a two-tone "pika" cry,
  and a four-note jingle when Pikachu joins.
- **Game Boy mode**: post-process pass quantising the framebuffer luminance to
  the classic DMG green palette (`#0f380f → #9bbc0f`).

This is a fan homage for personal/educational use; Pokémon is © Nintendo /
Creatures / GAME FREAK.
