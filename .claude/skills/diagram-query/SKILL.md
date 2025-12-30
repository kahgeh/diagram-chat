---
name: diagram-query
description: Query and measure rooms in DXF/DWG floor plans using the Plan-Check API. Use when the user asks about room sizes, dimensions, bathroom measurements, or wants to analyze architectural drawings.
---

# Diagram Query Skill

This skill helps answer questions about architectural floor plans (DXF/DWG files) using the Plan-Check API running at `http://localhost:3000`.

## Prerequisites

Ensure the API server is running:

```bash
uv run python api_server.py &
```

## Workflow for Counting/Finding Rooms

### Step 1: List Drawings

```bash
curl -s "http://localhost:3000/drawings"
```

### Step 2: Search for Room Indicators

Use multiple strategies to find rooms like bathrooms:

**Strategy A: Search text annotations for room labels**

```bash
curl -s "http://localhost:3000/drawings/{id}/annotations" | python3 -c "
import json, sys
data = json.load(sys.stdin)
keywords = ['BATH', 'WC', 'TOILET', 'BANYO', 'LAVABO']
for a in data:
    text = a.get('content', '').upper()
    if any(kw in text for kw in keywords):
        print(a)
"
```

**Strategy B: Search block names for fixtures**

```bash
curl -s "http://localhost:3000/drawings/{id}/blocks" | python3 -c "
import json, sys
data = json.load(sys.stdin)
keywords = ['TOILET', 'WC', 'SINK', 'BATH', 'TUB', 'SHOWER', 'LAVABO', 'BANYO']
for b in data:
    name = b['block_name'].upper()
    if any(kw in name for kw in keywords):
        print(b['block_name'], b['position'])
"
```

**Strategy C: Explode blocks to find fixture geometry**

```bash
# First list unique block names
curl -s "http://localhost:3000/drawings/{id}/blocks" | python3 -c "
import json, sys
from collections import Counter
data = json.load(sys.stdin)
counts = Counter(b['block_name'] for b in data)
for name, count in counts.most_common(30):
    print(f'{name}: {count}')
"

# Then inspect a specific block's contents
curl -s "http://localhost:3000/drawings/{id}/blocks/{block_name}/contents"
```

**Strategy D: Use boundary detection to find enclosed rooms**

```bash
curl -s -X POST "http://localhost:3000/drawings/{id}/boundaries/detect" \
  -H "Content-Type: application/json" \
  -d '{"layers":["WALL","MURO"],"min_area":1000000}'
```

### Step 3: Get Regions (Floor Plans)

```bash
curl -s "http://localhost:3000/drawings/{id}/regions"
```

### Step 4: Export with Cairo for Accurate Visualization

```bash
curl -s -X POST "http://localhost:3000/drawings/{id}/export" \
  -H "Content-Type: application/json" \
  -d '{"backend":"cairo","width":2000,"background":"white"}'
```

Or export a specific region:

```bash
curl -s -X POST "http://localhost:3000/drawings/{id}/export" \
  -H "Content-Type: application/json" \
  -d '{"backend":"cairo","width":2000,"region":{"min":{"x":-120000,"y":27000},"max":{"x":-112000,"y":35000}}}'
```

## Workflow for Measuring Rooms

### Step 1: Identify Room Location

Find the room using annotations, blocks, or visual inspection of exports.

### Step 2: Query Geometry in Region

Use spatial query to get all entities in a region:

```bash
curl -s -X POST "http://localhost:3000/drawings/{id}/entities/query" \
  -H "Content-Type: application/json" \
  -d '{
    "bounds": {"min": {"x": -80000, "y": 20000}, "max": {"x": -70000, "y": 35000}},
    "types": ["LINE", "LWPOLYLINE", "POLYLINE"],
    "layers": ["WALL"],
    "include_nested": false
  }'
```

### Step 3: Get Polylines (Wall Boundaries)

Polylines often represent complete wall boundaries:

```bash
curl -s "http://localhost:3000/drawings/{id}/polylines?layer=WALL&closed_only=true"
```

### Step 4: Detect Closed Boundaries

Automatically find closed room perimeters:

```bash
curl -s -X POST "http://localhost:3000/drawings/{id}/boundaries/detect" \
  -H "Content-Type: application/json" \
  -d '{
    "region": {"min": {"x": -80000, "y": 20000}, "max": {"x": -70000, "y": 35000}},
    "layers": ["WALL"],
    "min_area": 500000,
    "tolerance": 100
  }'
```

### Step 5: Export with Annotations

```bash
curl -s -X POST "http://localhost:3000/drawings/{id}/export/annotated" \
  -H "Content-Type: application/json" \
  -d '{
    "region": {"min": {"x": -120000, "y": 27000}, "max": {"x": -112000, "y": 35000}},
    "boundaries": [
      {"min_x": -117779, "min_y": 28570, "max_x": -115379, "max_y": 30290, "color": "red"}
    ],
    "measurements": [
      {"start_x": -117779, "start_y": 28270, "end_x": -115379, "end_y": 28270, "value": 2400, "color": "red"}
    ],
    "unit_format": "m",
    "backend": "cairo"
  }'
```

## Key API Endpoints

| Endpoint                                    | Purpose                                                  |
| ------------------------------------------- | -------------------------------------------------------- |
| `GET /drawings`                             | List loaded drawings                                     |
| `GET /drawings/{id}/regions`                | Get detected diagram regions                             |
| `GET /drawings/{id}/blocks`                 | Get fixture blocks (furniture, sanitary)                 |
| `GET /drawings/{id}/blocks/{name}/contents` | **NEW** Explode block to see internal geometry           |
| `GET /drawings/{id}/geometry`               | Get raw geometry (lines, arcs)                           |
| `GET /drawings/{id}/polylines`              | **NEW** Get polyline entities with points and closure    |
| `GET /drawings/{id}/entities`               | **NEW** Unified entity list with hierarchical model      |
| `GET /drawings/{id}/annotations`            | Get text labels                                          |
| `POST /drawings/{id}/entities/query`        | **NEW** Spatial query with filtering and block explosion |
| `POST /drawings/{id}/boundaries/detect`     | **NEW** Detect closed room boundaries                    |
| `POST /drawings/{id}/export`                | Export image (backends: cairo, librecad)                 |
| `POST /drawings/{id}/export/annotated`      | Export with measurements and boundaries                  |

## Render Backends

| Backend    | Description                                                           |
| ---------- | --------------------------------------------------------------------- |
| `cairo`    | Default - accurate Python-native renderer, handles all entity types   |
| `librecad` | High quality for complex hatches, requires LibreCAD installed         |

## Common Room Types and Fixture Layers

| Room Type | Fixture Layers        | Block Keywords                             |
| --------- | --------------------- | ------------------------------------------ |
| Bathroom  | WC, SANITARY, BATH    | TOILET, WC, SINK, BASIN, BATH, TUB, SHOWER |
| Kitchen   | FURNITURE, APPLIANCES | STOVE, FRIDGE, SINK, OVEN                  |
| Bedroom   | FURNITURE             | BED, WARDROBE, CLOSET                      |

## Example Questions This Skill Handles

- "How many bathrooms are in this floor plan?"
- "What are the bathroom sizes?"
- "How big is the master bedroom?"
- "Show me the kitchen dimensions"
- "What's the total floor area?"
- "Identify all rooms in this floor plan"
- "What fixtures are in this block?"

## Reference

- `docs/API.md` - Full API documentation with all endpoints and parameters
