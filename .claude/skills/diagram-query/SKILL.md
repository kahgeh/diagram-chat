---
name: diagram-query
description: Query and measure rooms in DXF/DWG floor plans using the Plan-Check API. Use when the user asks about room sizes, dimensions, bathroom measurements, or wants to analyze architectural drawings.
---

# Diagram Query Skill

This skill helps answer questions about architectural floor plans (DXF/DWG files) using the Plan-Check API running at `http://localhost:3000`.

## Prerequisites

Ensure the API server is running:
```bash
source .venv/bin/activate && python api_server.py &
```

## Workflow for Measuring Rooms

### Step 1: Load the Drawing

```bash
# Upload a drawing
curl -X POST "http://localhost:3000/drawings" -F "file=@path/to/file.dxf"

# Or list existing drawings
curl -s "http://localhost:3000/drawings"
```

### Step 2: Identify Regions and Fixtures

```bash
# Get detected regions (floor plans, elevations, etc.)
curl -s "http://localhost:3000/drawings/{id}/regions"

# Find room fixtures (toilets, sinks, etc.) to locate specific rooms
curl -s "http://localhost:3000/drawings/{id}/blocks?layer=WC"
curl -s "http://localhost:3000/drawings/{id}/blocks?layer=SANITARY"
```

### Step 3: Export and Visually Verify

Always export the area first to see what you're measuring:

```bash
curl -s -X POST "http://localhost:3000/drawings/{id}/export" \
  -H "Content-Type: application/json" \
  -d '{"format":"png","width":1500,"backend":"ezdxf","region":{"min":{"x":-120000,"y":27000},"max":{"x":-112000,"y":35000}}}'
```

Download and view the image to confirm you're looking at the correct room.

### Step 4: Query Wall Geometry

Get wall lines to identify room boundaries:

```bash
curl -s "http://localhost:3000/drawings/{id}/geometry?layer=WALL&type=line"
```

Filter walls in the target area and identify:
- **Horizontal walls**: Define top/bottom boundaries (same Y, different X)
- **Vertical walls**: Define left/right boundaries (same X, different Y)

### Step 5: Identify Enclosing Walls (Critical)

**Do NOT simply pick the nearest wall to a fixture.** Instead:

1. Look at wall segment lengths - longer segments (2-4m) are more likely room boundaries
2. Check if walls form a closed perimeter
3. Verify the boundary contains ALL fixtures (bathtub, toilet, sink)
4. Look for door swing arcs - room walls have door openings

**Red flags for wrong boundaries:**
- Boundary cuts through a fixture
- A fixture extends outside the boundary
- Door swing arc extends outside
- No door opening on any wall

### Step 6: Calculate and Annotate

Once you have the correct boundaries, use the annotated export:

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
    "backend": "ezdxf"
  }'
```

## Key API Endpoints

| Endpoint | Purpose |
|----------|---------|
| `GET /drawings` | List loaded drawings |
| `GET /drawings/{id}/regions` | Get detected diagram regions |
| `GET /drawings/{id}/blocks` | Get fixture blocks (furniture, sanitary) |
| `GET /drawings/{id}/geometry` | Get raw geometry (lines, arcs) |
| `GET /drawings/{id}/annotations` | Get text labels |
| `POST /drawings/{id}/export` | Export image with optional region crop |
| `POST /drawings/{id}/export/annotated` | Export with measurements and boundaries |

## Common Room Types and Fixture Layers

| Room Type | Fixture Layers | Block Types |
|-----------|---------------|-------------|
| Bathroom | WC, SANITARY | Toilet, sink, bathtub |
| Kitchen | FURNITURE, APPLIANCES | Stove, fridge, sink |
| Bedroom | FURNITURE | Bed, wardrobe |

## Example Questions This Skill Handles

- "What are the bathroom sizes?"
- "How big is the master bedroom?"
- "Show me the kitchen dimensions"
- "What's the total floor area?"
- "Identify all rooms in this floor plan"

## Reference

- `docs/API.md` - Full API documentation with all endpoints and parameters
- `docs/llm.md` - Workflow guidance for measuring rooms and avoiding common mistakes
