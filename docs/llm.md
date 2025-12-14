# LLM Instructions for Plan-Check API

This document contains patterns and guidelines for AI assistants working with the Plan-Check API.

---

## Measuring Room Dimensions (Recommended Pattern)

When measuring a specific room (e.g., bathroom, bedroom), **do not rely solely on DIMENSION entities** - they may measure adjacent spaces, wall thicknesses, or unrelated features. Instead, follow this pattern:

### Step 1: Identify the room by its label and fixtures

Find the room label (e.g., "SS.HH." for bathroom) and verify with a visual export:

```bash
# Find room labels
curl -s ".../annotations" | jq '.[] | select(.content == "SS.HH.")'

# Export the area to visually confirm (look for fixtures like toilets, sinks)
curl -X POST ".../export" -H "Content-Type: application/json" \
  -d '{"format":"png","width":800,"region":{"min":{"x":163,"y":71},"max":{"x":167,"y":75}}}'
```

**Important:** Always visually inspect the exported image to confirm you are looking at the correct room. Look for identifying fixtures (toilets, sinks, stoves, beds, etc.).

### Step 2: Find wall lines nearest to fixtures

Query the geometry layer for wall lines (typically "MURO" or "WALL" layer):

```bash
# Get wall lines in the room area
curl -s ".../geometry?type=line" | jq '[.[] | select(
  .layer == "MURO" and
  .start.x > 163 and .start.x < 167 and
  .start.y > 71 and .start.y < 75
)]'
```

### Step 3: Identify vertical and horizontal walls

- **Vertical walls** (same X, different Y): Define left/right room boundaries
- **Horizontal walls** (same Y, different X): Define top/bottom room boundaries

```bash
# Find vertical walls (room width boundaries)
curl -s ".../geometry?type=line" | jq '[.[] | select(.layer == "MURO")
  | select(((.start.x - .end.x) | fabs) < 0.05)] | [.[].start.x] | sort | unique'

# Find horizontal walls (room depth boundaries)
curl -s ".../geometry?type=line" | jq '[.[] | select(.layer == "MURO")
  | select(((.start.y - .end.y) | fabs) < 0.05)] | [.[].start.y] | sort | unique'
```

### Step 4: Identify enclosing walls (not just nearest walls)

**Critical:** Do not simply pick the nearest vertical/horizontal wall segments to the fixture. Instead, identify walls that form a **closed room boundary**:

1. **Look for continuous wall segments** - A room boundary is typically a single wall line or connected segments that span the full width/height of the room.

2. **Check horizontal wall lengths** - If a horizontal wall runs from X₁ to X₂, the room width is likely close to |X₂ - X₁|. Use these lengths as primary indicators.

3. **Verify walls enclose all fixtures** - The boundary must contain:
   - All room fixtures (bathtub, toilet, sink, bed, etc.)
   - Door swing arcs (quarter circles indicating door locations)
   - Any built-in furniture shown in the room

4. **Distinguish room walls from internal partitions** - Internal elements like:
   - Shower enclosures
   - Toilet partitions
   - Vanity units

   These create wall-like lines but are NOT room boundaries.

### Step 5: Apply sanity checks before finalizing

**Red flags that indicate wrong boundaries:**
- Boundary line passes through the middle of any fixture
- A fixture extends outside the boundary
- Door swing arc extends outside the boundary
- No door opening visible on any boundary wall (rooms need entry points)
- Boundary walls don't form a closed rectangle (missing a side)

### Step 6: Calculate room dimensions from wall coordinates

```
Room Width  = rightmost_wall_x - leftmost_wall_x
Room Depth  = topmost_wall_y - bottommost_wall_y
```

### Step 7: Verify by drawing measurements on the image

Always export an annotated image with the calculated measurements overlaid:

1. Draw the room boundary rectangle on the exported image
2. Visually confirm the rectangle:
   - Encloses ALL fixtures in the room
   - Aligns with visible wall lines
   - Includes door opening location
   - Does NOT cut through any fixtures
3. If the boundary looks wrong, return to Step 4 and re-examine wall segments

**Never report dimensions without visual verification.**

---

## Common Mistakes to Avoid

### 1. Trusting DIMENSION entities without verification
DIMENSION entities may measure:
- Adjacent hallways or corridors
- Wall thicknesses
- Spaces outside the target room
- Combined measurements of multiple rooms

The dimension text labels (e.g., "2.00") are separate TEXT entities, not linked to the DIMENSION geometry.

### 2. Relying on coordinates without visual confirmation
Always export and view the image before reporting measurements. Coordinates alone can be misleading.

### 3. Confusing room orientation
Don't assume "width" is horizontal and "length" is vertical. The room's orientation in the drawing may differ from expectations. Be explicit about which axis you're measuring.

### 4. Missing door openings
When calculating room dimensions from walls, account for door openings which appear as gaps in the wall lines.

### 5. Picking nearest wall instead of enclosing wall
**This is the most common error.** When multiple wall segments exist near a fixture:
- Internal partitions (shower walls, vanity backs) appear as walls but don't define room boundaries
- The correct room wall is typically the one that:
  - Has a corresponding wall on the opposite side forming a closed rectangle
  - Has length approximately equal to the room dimension
  - Contains a door opening or connects to a corridor

**How to identify the correct enclosing wall:**

1. Look at horizontal wall segments and note their lengths - a wall spanning 2.5-3m is more likely a room boundary than one spanning 0.5m
2. Check if the wall connects to other walls forming a closed perimeter
3. Look for door swing arcs - the room wall will have a door opening, partitions won't
4. Verify the boundary contains ALL fixtures (if a bathtub is partially outside your boundary, it's wrong)

### 6. Not using fixtures as visual boundary checks
The fixtures drawn in the floor plan are your best validation tool:
- If your boundary rectangle cuts through any fixture, it's wrong
- If a fixture extends outside your boundary, it's wrong
- The drawn fixtures show the actual scale - use them to validate your boundary visually

---

## Useful Layer Names

Common layer names in architectural drawings:
- **MURO** / **WALL** - Wall lines
- **COTAS** / **DIMENSIONS** - Dimension entities
- **TEXTOS PLANTA** / **TEXT** - Text annotations and labels
- **PUERTAS** / **DOORS** - Door symbols
- **VENTANAS** / **WINDOWS** - Window symbols

---

## Example: Measuring a Bathroom

1. Search for "SS.HH.", "BATH", "WC" labels in annotations, or locate toilet/sink blocks on SANITARY/WC layers
2. Export the region around the fixture positions
3. Visually confirm you see bathroom fixtures (toilet, sink, bathtub/shower)
4. Query WALL/MURO layer for wall lines in that region
5. Identify horizontal walls and note their lengths - longer segments are more likely room boundaries than short partitions
6. Identify vertical walls that connect to form a closed perimeter with the horizontal walls
7. Verify the boundary rectangle encloses ALL fixtures and any door swing arcs
8. Calculate: width = right_x - left_x, depth = top_y - bottom_y
9. Draw the boundary rectangle on the exported image and verify it:
   - Aligns with visible wall lines
   - Contains all fixtures completely (nothing cut off)
   - Includes door opening
