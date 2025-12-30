# LLM Instructions for Plan-Check API

This document contains patterns and guidelines for AI assistants working with the Plan-Check API.

---

## Quick Reference: New Endpoints

These endpoints provide enhanced capabilities for analyzing drawings:

| Endpoint | Use Case |
|----------|----------|
| `GET /drawings/{id}/polylines` | Get wall boundaries as connected line segments |
| `GET /drawings/{id}/entities` | Unified entity list with bounds and properties |
| `GET /drawings/{id}/blocks/{name}/contents` | Explode blocks to see internal geometry |
| `POST /drawings/{id}/entities/query` | Spatial query with filtering and block explosion |
| `POST /drawings/{id}/boundaries/detect` | Auto-detect closed room perimeters |

---

## Counting Rooms (e.g., "How many bathrooms?")

### Strategy 1: Search Text Annotations

Look for room labels in text annotations:

```bash
curl -s ".../annotations" | python3 -c "
import json, sys
data = json.load(sys.stdin)
keywords = ['BATH', 'WC', 'TOILET', 'BANYO', 'LAVABO', 'SS.HH.']
for a in data:
    text = a.get('content', '').upper()
    if any(kw in text for kw in keywords):
        print(f\"{a['content']} at ({a['position']['x']:.0f}, {a['position']['y']:.0f})\")
"
```

### Strategy 2: Search Block Names for Fixtures

Many drawings use named blocks for fixtures:

```bash
curl -s ".../blocks" | python3 -c "
import json, sys
from collections import Counter
data = json.load(sys.stdin)

# Find bathroom-related blocks
keywords = ['TOILET', 'WC', 'SINK', 'BASIN', 'BATH', 'TUB', 'SHOWER', 'LAVABO']
bathroom_blocks = [b for b in data if any(kw in b['block_name'].upper() for kw in keywords)]

# Group by location to identify unique bathrooms
print(f'Found {len(bathroom_blocks)} bathroom fixture blocks')
for b in bathroom_blocks:
    print(f\"  {b['block_name']} at ({b['position']['x']:.0f}, {b['position']['y']:.0f})\")
"
```

### Strategy 3: Explode Blocks to Identify Fixtures

When block names aren't descriptive, inspect their contents:

```bash
# List all unique blocks
curl -s ".../blocks" | python3 -c "
import json, sys
from collections import Counter
data = json.load(sys.stdin)
counts = Counter(b['block_name'] for b in data)
for name, count in counts.most_common(20):
    print(f'{name}: {count}')
"

# Inspect a specific block's geometry
curl -s ".../blocks/BLOCK_NAME/contents" | python3 -m json.tool
```

### Strategy 4: Use Boundary Detection

Detect enclosed rooms automatically:

```bash
curl -s -X POST ".../boundaries/detect" \
  -H "Content-Type: application/json" \
  -d '{
    "layers": ["WALL", "MURO"],
    "min_area": 1000000
  }'
```

Then correlate detected boundaries with nearby labels and fixtures.

### Strategy 5: Visual Inspection with Cairo Renderer

Export accurate images for visual analysis:

```bash
curl -s -X POST ".../export" \
  -H "Content-Type: application/json" \
  -d '{"backend": "cairo", "width": 4000}'
```

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
  -d '{"backend":"cairo","width":1500,"region":{"min":{"x":163,"y":71},"max":{"x":167,"y":75}}}'
```

**Important:** Always visually inspect the exported image to confirm you are looking at the correct room. Look for identifying fixtures (toilets, sinks, stoves, beds, etc.).

### Step 2: Use Spatial Query to Get Wall Geometry

Query all wall entities in the room area:

```bash
curl -s -X POST ".../entities/query" \
  -H "Content-Type: application/json" \
  -d '{
    "bounds": {"min": {"x": 163, "y": 71}, "max": {"x": 167, "y": 75}},
    "types": ["LINE", "LWPOLYLINE", "POLYLINE"],
    "layers": ["WALL", "MURO"]
  }'
```

### Step 3: Get Closed Polylines (Room Boundaries)

Polylines often represent complete wall boundaries:

```bash
curl -s ".../polylines?layer=WALL&closed_only=true"
```

### Step 4: Use Automatic Boundary Detection

Let the API detect closed room perimeters:

```bash
curl -s -X POST ".../boundaries/detect" \
  -H "Content-Type: application/json" \
  -d '{
    "region": {"min": {"x": 163, "y": 71}, "max": {"x": 167, "y": 75}},
    "layers": ["WALL", "MURO"],
    "min_area": 500000,
    "tolerance": 50
  }'
```

The response includes:
- `vertices`: The boundary polygon points
- `width`, `height`, `area`: Computed dimensions
- `nearby_labels`: Text found inside the boundary
- `is_rectangular`: Whether it's a simple rectangle

### Step 5: Identify enclosing walls (not just nearest walls)

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

### Step 6: Apply sanity checks before finalizing

**Red flags that indicate wrong boundaries:**
- Boundary line passes through the middle of any fixture
- A fixture extends outside the boundary
- Door swing arc extends outside the boundary
- No door opening visible on any boundary wall (rooms need entry points)
- Boundary walls don't form a closed rectangle (missing a side)

### Step 7: Calculate room dimensions from wall coordinates

```
Room Width  = rightmost_wall_x - leftmost_wall_x
Room Depth  = topmost_wall_y - bottommost_wall_y
```

### Step 8: Verify by drawing measurements on the image

Always export an annotated image with the calculated measurements overlaid:

```bash
curl -s -X POST ".../export/annotated" \
  -H "Content-Type: application/json" \
  -d '{
    "region": {"min": {"x": 163, "y": 71}, "max": {"x": 167, "y": 75}},
    "boundaries": [
      {"min_x": 163.5, "min_y": 71.5, "max_x": 166.5, "max_y": 74.5, "color": "red"}
    ],
    "measurements": [
      {"start_x": 163.5, "start_y": 71, "end_x": 166.5, "end_y": 71, "value": 3000, "color": "red"}
    ],
    "unit_format": "m",
    "backend": "cairo"
  }'
```

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

## Render Backends

| Backend | When to Use |
|---------|-------------|
| `cairo` | Default - accurate Python-native rendering, supports all standard entity types |
| `librecad` | Complex hatches (requires LibreCAD installed) |

**Recommendation:** Use `cairo` (default) for most cases - it provides accurate rendering of all standard entity types without requiring external dependencies.

---

## Useful Layer Names

Common layer names in architectural drawings:
- **MURO** / **WALL** - Wall lines
- **COTAS** / **DIMENSIONS** - Dimension entities
- **TEXTOS PLANTA** / **TEXT** - Text annotations and labels
- **PUERTAS** / **DOORS** - Door symbols
- **VENTANAS** / **WINDOWS** - Window symbols
- **WC** / **SANITARY** / **BATH** - Bathroom fixtures

---

## Example: Counting Bathrooms

1. Search annotations for bathroom labels ("BATH", "WC", "SS.HH.", etc.)
2. Search blocks for fixture names ("TOILET", "SINK", "TUB", etc.)
3. If block names are cryptic, explode them to inspect geometry
4. Use boundary detection to find enclosed rooms
5. Cross-reference detected boundaries with fixture positions
6. Export with Cairo for visual verification
7. Count unique bathroom locations (fixtures clustered together = 1 bathroom)

---

## Example: Measuring a Bathroom

1. Search for "SS.HH.", "BATH", "WC" labels in annotations, or locate toilet/sink blocks on SANITARY/WC layers
2. Export the region around the fixture positions using Cairo backend
3. Visually confirm you see bathroom fixtures (toilet, sink, bathtub/shower)
4. Use spatial query to get WALL/MURO entities in that region
5. Use boundary detection to find the enclosing room perimeter
6. If boundary detection fails, manually identify wall segments:
   - Identify horizontal walls and note their lengths - longer segments are more likely room boundaries
   - Identify vertical walls that connect to form a closed perimeter
7. Verify the boundary rectangle encloses ALL fixtures and any door swing arcs
8. Calculate: width = right_x - left_x, depth = top_y - bottom_y
9. Export annotated image with boundary rectangle and verify it:
   - Aligns with visible wall lines
   - Contains all fixtures completely (nothing cut off)
   - Includes door opening
