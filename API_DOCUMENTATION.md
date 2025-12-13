# DXF API Documentation

A REST API for analyzing DXF/DWG architectural drawings, designed for AI agent integration. The API extracts dimensions, annotations, geometry, and spatial information from CAD files and provides visual exports with annotations.

**Base URL**: `http://localhost:3000`

## Table of Contents

1. [Quick Start](#quick-start)
2. [Data Models](#data-models)
3. [Endpoints](#endpoints)
   - [Drawing Management](#drawing-management)
   - [Drawing Analysis](#drawing-analysis)
   - [Spatial Analysis](#spatial-analysis)
   - [Export & Rendering](#export--rendering)
4. [LLM Examples](#llm-examples)

---

## Quick Start

```bash
# Start the server
python api_server.py

# List available drawings
curl http://localhost:3000/drawings

# Get drawing summary
curl http://localhost:3000/drawings/{drawing_id}

# Get all dimensions
curl http://localhost:3000/drawings/{drawing_id}/dimensions
```

---

## Data Models

### Point
```json
{
  "x": 1000.0,
  "y": 2000.0,
  "z": 0.0
}
```

### Bounds
```json
{
  "min": {"x": 0.0, "y": 0.0, "z": 0.0},
  "max": {"x": 10000.0, "y": 8000.0, "z": 0.0}
}
```

### DimensionInfo
```json
{
  "id": "D0001",
  "type": "linear",
  "value": 3500.0,
  "unit": "mm",
  "display_text": "3500",
  "point_from": {"x": 1000.0, "y": 2000.0, "z": 0.0},
  "point_to": {"x": 4500.0, "y": 2000.0, "z": 0.0},
  "midpoint": {"x": 2750.0, "y": 2000.0, "z": 0.0},
  "layer": "DIMENSIONS"
}
```

### AnnotationInfo
```json
{
  "id": "A0001",
  "type": "text",
  "content": "BATHROOM",
  "position": {"x": 5000.0, "y": 3000.0, "z": 0.0},
  "height": 250.0,
  "layer": "TEXT"
}
```

### RegionInfo
```json
{
  "id": "R001",
  "bounds": {"min": {...}, "max": {...}},
  "width": 15000.0,
  "height": 12000.0,
  "area": 180.0,
  "entity_count": 1250,
  "nearby_labels": ["GROUND FLOOR", "BATHROOM", "KITCHEN"],
  "contained_blocks": ["DOOR", "WINDOW", "TOILET"]
}
```

### SpaceInfo
```json
{
  "id": "S001",
  "name": "BATHROOM",
  "confidence": 0.7,
  "source": "text_label",
  "bounds": {"min": {...}, "max": {...}},
  "width": 6000.0,
  "height": 6000.0,
  "area": 36.0,
  "fixtures": ["TOILET", "BASIN", "SHOWER"]
}
```

---

## Endpoints

### Drawing Management

#### List Drawings
```
GET /drawings
```

Returns all loaded drawings.

**Response:**
```json
[
  {"id": "floor-plan", "filename": "floor-plan.dxf"},
  {"id": "building-a", "filename": "Building-A.dwg"}
]
```

---

#### Upload Drawing
```
POST /drawings
Content-Type: multipart/form-data
```

Upload a DXF or DWG file. DWG files are automatically converted to DXF.

**Parameters:**
- `file` (required): The DXF or DWG file

**Response:**
```json
{
  "id": "abc12345",
  "filename": "my-drawing.dxf",
  "message": "Drawing uploaded successfully. Access it at /drawings/abc12345"
}
```

---

#### Get Drawing Summary
```
GET /drawings/{drawing_id}
```

Get overview of a drawing including bounds, layouts, and entity counts.

**Response:**
```json
{
  "id": "floor-plan",
  "filename": "floor-plan.dxf",
  "units": "mm",
  "bounds": {
    "min": {"x": 0.0, "y": 0.0, "z": 0.0},
    "max": {"x": 50000.0, "y": 40000.0, "z": 0.0}
  },
  "layouts": [
    {"name": "Model", "type": "model_space", "entity_count": 5420}
  ],
  "layer_count": 25,
  "entity_count": 5420,
  "dimension_count": 156
}
```

---

#### Delete Drawing
```
DELETE /drawings/{drawing_id}
```

Remove a drawing from the cache.

---

### Drawing Analysis

#### Get Layers
```
GET /drawings/{drawing_id}/layers
```

List all layers with entity counts.

**Response:**
```json
[
  {"name": "WALL", "color": 7, "entity_count": 450},
  {"name": "DIMENSIONS", "color": 3, "entity_count": 156},
  {"name": "TEXT", "color": 1, "entity_count": 89}
]
```

---

#### Get Dimensions
```
GET /drawings/{drawing_id}/dimensions
GET /drawings/{drawing_id}/dimensions?layer=DIMENSIONS
```

Get all dimension entities with their values and positions.

**Query Parameters:**
- `layer` (optional): Filter by layer name

**Response:**
```json
[
  {
    "id": "D0001",
    "type": "linear",
    "value": 3500.0,
    "unit": "mm",
    "display_text": "3500",
    "point_from": {"x": 1000.0, "y": 2000.0, "z": 0.0},
    "point_to": {"x": 4500.0, "y": 2000.0, "z": 0.0},
    "midpoint": {"x": 2750.0, "y": 2000.0, "z": 0.0},
    "layer": "DIMENSIONS"
  }
]
```

---

#### Get Annotations
```
GET /drawings/{drawing_id}/annotations
GET /drawings/{drawing_id}/annotations?layer=TEXT
```

Get all TEXT and MTEXT entities.

**Response:**
```json
[
  {
    "id": "A0001",
    "type": "text",
    "content": "BATHROOM",
    "position": {"x": 5000.0, "y": 3000.0, "z": 0.0},
    "height": 250.0,
    "layer": "TEXT"
  }
]
```

---

#### Get Blocks
```
GET /drawings/{drawing_id}/blocks
GET /drawings/{drawing_id}/blocks?layer=FIXTURES
```

Get all block insertions (doors, windows, fixtures, etc.).

**Response:**
```json
[
  {
    "id": "B0001",
    "block_name": "DOOR_SINGLE",
    "position": {"x": 3000.0, "y": 5000.0, "z": 0.0},
    "scale": 1.0,
    "rotation": 90.0,
    "layer": "DOORS"
  }
]
```

---

#### Get Geometry
```
GET /drawings/{drawing_id}/geometry
GET /drawings/{drawing_id}/geometry?type=line
GET /drawings/{drawing_id}/geometry?layer=WALL
```

Get LINE, CIRCLE, and ARC entities.

**Query Parameters:**
- `layer` (optional): Filter by layer name
- `type` (optional): Filter by type (`line`, `circle`, `arc`)

---

#### Get Extents
```
GET /drawings/{drawing_id}/extents
GET /drawings/{drawing_id}/extents?layer=WALL
```

Get the bounding box of the drawing or a specific layer.

**Response:**
```json
{
  "bounds": {
    "min": {"x": 0.0, "y": 0.0, "z": 0.0},
    "max": {"x": 50000.0, "y": 40000.0, "z": 0.0}
  },
  "width": 50000.0,
  "height": 40000.0,
  "unit": "mm"
}
```

---

### Spatial Analysis

#### Get Regions
```
GET /drawings/{drawing_id}/regions
```

Auto-detect separate drawing regions (e.g., different floor plans or views).

**Response:**
```json
[
  {
    "id": "R001",
    "bounds": {"min": {...}, "max": {...}},
    "width": 15000.0,
    "height": 12000.0,
    "area": 180.0,
    "entity_count": 1250,
    "nearby_labels": ["GROUND FLOOR", "BATHROOM"],
    "contained_blocks": ["DOOR", "WINDOW"]
  },
  {
    "id": "R002",
    "bounds": {"min": {...}, "max": {...}},
    "width": 15000.0,
    "height": 12000.0,
    "area": 180.0,
    "entity_count": 1180,
    "nearby_labels": ["FIRST FLOOR", "BEDROOM"],
    "contained_blocks": ["DOOR", "WINDOW"]
  }
]
```

---

#### Get Spaces
```
GET /drawings/{drawing_id}/spaces
```

Identify rooms/spaces based on text labels (BATHROOM, KITCHEN, etc.).

**Response:**
```json
[
  {
    "id": "S001",
    "name": "BATHROOM",
    "confidence": 0.7,
    "source": "text_label",
    "bounds": {"min": {...}, "max": {...}},
    "width": 6000.0,
    "height": 6000.0,
    "area": 36.0,
    "fixtures": ["TOILET", "BASIN"]
  }
]
```

---

#### Get Building Summary
```
GET /drawings/{drawing_id}/building
```

Get overall building information with detected floors.

**Response:**
```json
{
  "floors": [
    {
      "name": "Ground Floor",
      "bounds": {"min": {...}, "max": {...}},
      "width": 15000.0,
      "height": 12000.0,
      "spaces": ["BATHROOM", "KITCHEN", "LIVING ROOM"]
    }
  ],
  "overall_width": 15000.0,
  "overall_height": 12000.0,
  "unit": "mm"
}
```

---

#### Point Query
```
POST /drawings/{drawing_id}/query/point
Content-Type: application/json
```

Find entities near a specific coordinate.

**Request Body:**
```json
{
  "x": 5000.0,
  "y": 3000.0,
  "radius": 2000.0
}
```

**Response:**
```json
{
  "nearby_texts": ["BATHROOM", "3000 x 2500"],
  "nearby_blocks": ["TOILET", "BASIN"],
  "nearby_dimensions": [
    {"id": "", "type": "linear", "value": 3000.0, "layer": "DIMENSIONS"}
  ]
}
```

---

### Export & Rendering

#### Export Drawing to PNG
```
POST /drawings/{drawing_id}/export
Content-Type: application/json
```

Export full drawing or a region to PNG image.

**Request Body:**
```json
{
  "format": "png",
  "layout": "Model",
  "layers": ["WALL", "DIMENSIONS"],
  "width": 4096,
  "scale": null,
  "background": "white",
  "region": null,
  "backend": "ezdxf"
}
```

**Parameters:**
- `format`: Always "png"
- `layout`: Layout name (default: "Model")
- `layers`: Filter to specific layers (optional)
- `width`: Output width in pixels (default: 4096)
- `scale`: Pixels per drawing unit (overrides width if set)
- `background`: "white", "black", or "transparent"
- `region`: Bounds object to export specific area (optional)
- `backend`: "ezdxf" (fast) or "librecad" (higher quality)

**Response:**
```json
{
  "url": "/exports/abc12345.png",
  "filename": "abc12345.png",
  "width": 4096,
  "height": 3072,
  "scale": 0.08192,
  "drawing_width": 50000.0,
  "drawing_height": 37500.0,
  "drawing_bounds": {"min": {...}, "max": {...}},
  "backend": "ezdxf"
}
```

---

#### Export Region by ID
```
POST /drawings/{drawing_id}/regions/{region_id}/export?width=2000&backend=librecad
```

Convenience endpoint to export a detected region.

**Query Parameters:**
- `scale`: Pixels per drawing unit (optional)
- `width`: Output width in pixels (optional)
- `background`: Background color (optional)
- `backend`: Render backend (optional)

---

#### Export with Annotations
```
POST /drawings/{drawing_id}/export/annotated
Content-Type: application/json
```

Export drawing with measurement lines drawn on top.

**Request Body:**
```json
{
  "region_id": "R001",
  "measurements": [
    {
      "start_x": 1000.0,
      "start_y": 2000.0,
      "end_x": 4500.0,
      "end_y": 2000.0,
      "value": 3500.0,
      "label": "Width"
    }
  ],
  "backend": "librecad"
}
```

---

#### Query Measurements (Advanced)
```
POST /drawings/{drawing_id}/measurements/query
Content-Type: application/json
```

Query dimensions with filters and get an annotated image. This is the most powerful endpoint for answering dimension-related questions.

**Request Body:**
```json
{
  "filters": {
    "min_value": 1000,
    "max_value": 5000,
    "orientation": "horizontal",
    "layers": ["DIMENSIONS"],
    "region_id": "R001",
    "bounds": {
      "min": {"x": 0, "y": 0},
      "max": {"x": 10000, "y": 10000}
    }
  },
  "output": {
    "include_image": true,
    "image_format": "base64",
    "image_width": 2000,
    "highlight_color": "red",
    "background": "white",
    "backend": "librecad"
  }
}
```

**Filter Options:**
- `min_value` / `max_value`: Filter by dimension value range (in mm)
- `orientation`: "horizontal", "vertical", or "diagonal"
- `layers`: Filter by layer names
- `region_id`: Limit to a detected region
- `bounds`: Limit to a spatial bounding box

**Output Options:**
- `include_image`: Generate annotated image (default: true)
- `image_format`: "base64" (embedded) or "url" (separate fetch)
- `image_width`: Output width in pixels
- `highlight_color`: Color for markers (red, blue, green, etc.)
- `background`: "white", "black", or "transparent"
- `backend`: "ezdxf" or "librecad"

**Response:**
```json
{
  "query_summary": {
    "total_dimensions": 156,
    "matched_dimensions": 23,
    "filters_applied": ["min_value=1000", "orientation=horizontal"]
  },
  "dimensions": [
    {
      "id": "D0001",
      "type": "linear",
      "value": 3500.0,
      "point_from": {...},
      "point_to": {...},
      "midpoint": {...},
      "layer": "DIMENSIONS"
    }
  ],
  "statistics": {
    "count": 23,
    "min_value": 1050.0,
    "max_value": 4890.0,
    "average": 2450.0,
    "total": 56350.0
  },
  "image": {
    "format": "base64",
    "data": "iVBORw0KGgoAAAA...",
    "width": 2000,
    "height": 1500,
    "scale": 0.1
  }
}
```

---

#### Serve Export File
```
GET /exports/{filename}
```

Download a previously generated PNG export.

---

## LLM Examples

Below are step-by-step examples showing how an LLM can use this API to answer common questions about architectural drawings.

### Example 1: "What are the dimensions of the bathrooms?"

**Step 1: Get the drawing ID**
```
GET /drawings
```
Response: `[{"id": "floor-plan", "filename": "floor-plan.dxf"}]`

**Step 2: Find bathroom spaces**
```
GET /drawings/floor-plan/spaces
```
Response:
```json
[
  {
    "id": "S001",
    "name": "BATHROOM",
    "bounds": {
      "min": {"x": 15000, "y": 8000},
      "max": {"x": 18500, "y": 11500}
    },
    "width": 3500.0,
    "height": 3500.0,
    "area": 12.25,
    "fixtures": ["TOILET", "BASIN", "SHOWER"]
  },
  {
    "id": "S002",
    "name": "BATHROOM 2",
    "bounds": {
      "min": {"x": 25000, "y": 8000},
      "max": {"x": 27500, "y": 10500}
    },
    "width": 2500.0,
    "height": 2500.0,
    "area": 6.25,
    "fixtures": ["TOILET", "BASIN"]
  }
]
```

**Step 3: Query dimensions within bathroom bounds**
```
POST /drawings/floor-plan/measurements/query
Content-Type: application/json

{
  "filters": {
    "bounds": {
      "min": {"x": 15000, "y": 8000},
      "max": {"x": 18500, "y": 11500}
    }
  },
  "output": {
    "include_image": true,
    "image_format": "url",
    "highlight_color": "blue"
  }
}
```

Response:
```json
{
  "query_summary": {
    "total_dimensions": 156,
    "matched_dimensions": 4,
    "filters_applied": ["bounds=(15000,8000)-(18500,11500)"]
  },
  "dimensions": [
    {"id": "D0045", "type": "linear", "value": 3500.0, "point_from": {...}, "point_to": {...}},
    {"id": "D0046", "type": "linear", "value": 3500.0, "point_from": {...}, "point_to": {...}},
    {"id": "D0047", "type": "linear", "value": 1200.0, "point_from": {...}, "point_to": {...}},
    {"id": "D0048", "type": "linear", "value": 900.0, "point_from": {...}, "point_to": {...}}
  ],
  "statistics": {
    "count": 4,
    "min_value": 900.0,
    "max_value": 3500.0,
    "average": 2275.0
  },
  "image": {
    "format": "url",
    "url": "/exports/query_abc123.png",
    "width": 2000,
    "height": 1500
  }
}
```

**LLM Answer:**
> The main bathroom measures 3500mm x 3500mm (3.5m x 3.5m), with an area of approximately 12.25 square meters. It contains a toilet, basin, and shower. The shower enclosure is 1200mm wide and the toilet area is 900mm.
>
> The second bathroom is smaller at 2500mm x 2500mm (2.5m x 2.5m), approximately 6.25 square meters, containing a toilet and basin.
>
> [View annotated image](/exports/query_abc123.png)

---

### Example 2: "How high is the building?"

**Step 1: Get the drawing summary**
```
GET /drawings/building-section
```

This tells you the overall bounds and if there are dimension entities.

**Step 2: Check for building/elevation data**
```
GET /drawings/building-section/building
```
Response:
```json
{
  "floors": [
    {"name": "Ground Floor", "height": 3000.0},
    {"name": "First Floor", "height": 3000.0},
    {"name": "Second Floor", "height": 3000.0}
  ],
  "overall_width": 15000.0,
  "overall_height": 12500.0,
  "unit": "mm"
}
```

**Step 3: Query vertical dimensions (for section drawings)**
```
POST /drawings/building-section/measurements/query
Content-Type: application/json

{
  "filters": {
    "orientation": "vertical",
    "min_value": 2500
  },
  "output": {
    "include_image": true,
    "highlight_color": "green"
  }
}
```

Response:
```json
{
  "dimensions": [
    {"id": "D0012", "type": "linear", "value": 12500.0, "display_text": "TOTAL HEIGHT"},
    {"id": "D0015", "type": "linear", "value": 3000.0, "display_text": "FLOOR TO FLOOR"},
    {"id": "D0018", "type": "linear", "value": 2700.0, "display_text": "CEILING HEIGHT"}
  ],
  "statistics": {
    "count": 3,
    "max_value": 12500.0
  }
}
```

**LLM Answer:**
> The building has a total height of 12.5 meters (12500mm). It has 3 floors with a floor-to-floor height of 3 meters (3000mm) each. The ceiling height within each floor is 2.7 meters (2700mm).

---

### Example 3: "Show me the ground floor plan"

**Step 1: Detect regions**
```
GET /drawings/floor-plan/regions
```
Response:
```json
[
  {
    "id": "R001",
    "nearby_labels": ["GROUND FLOOR PLAN", "LIVING", "KITCHEN"],
    "bounds": {"min": {"x": 0, "y": 0}, "max": {"x": 20000, "y": 15000}}
  },
  {
    "id": "R002",
    "nearby_labels": ["FIRST FLOOR PLAN", "BEDROOM 1", "BEDROOM 2"],
    "bounds": {"min": {"x": 25000, "y": 0}, "max": {"x": 45000, "y": 15000}}
  }
]
```

**Step 2: Export the ground floor region**
```
POST /drawings/floor-plan/regions/R001/export?width=3000&backend=librecad
```

Response:
```json
{
  "url": "/exports/region_xyz789.png",
  "width": 3000,
  "height": 2250,
  "drawing_bounds": {...}
}
```

**LLM Answer:**
> Here is the ground floor plan showing the living room and kitchen areas.
>
> ![Ground Floor Plan](/exports/region_xyz789.png)

---

### Example 4: "What's near the kitchen area?"

**Step 1: Find the kitchen**
```
GET /drawings/floor-plan/annotations
```
Look for "KITCHEN" in the content.

Response includes:
```json
{
  "id": "A0023",
  "content": "KITCHEN",
  "position": {"x": 8000, "y": 5000}
}
```

**Step 2: Query entities near that point**
```
POST /drawings/floor-plan/query/point
Content-Type: application/json

{
  "x": 8000,
  "y": 5000,
  "radius": 3000
}
```

Response:
```json
{
  "nearby_texts": ["KITCHEN", "PANTRY", "4500 x 3500"],
  "nearby_blocks": ["SINK", "STOVE", "FRIDGE", "DOOR_SINGLE"],
  "nearby_dimensions": [
    {"value": 4500.0, "type": "linear"},
    {"value": 3500.0, "type": "linear"}
  ]
}
```

**LLM Answer:**
> The kitchen area (4500mm x 3500mm) is located adjacent to the pantry. It contains:
> - A sink
> - A stove/cooktop
> - A refrigerator space
> - A single door entrance
>
> The kitchen measures 4.5 meters by 3.5 meters.

---

### Example 5: "List all rooms larger than 20 square meters"

**Step 1: Get all spaces**
```
GET /drawings/floor-plan/spaces
```

**Step 2: Filter in LLM logic**
Filter spaces where `area > 20`.

Response spaces:
```json
[
  {"name": "LIVING ROOM", "area": 35.5, "width": 7100, "height": 5000},
  {"name": "MASTER BEDROOM", "area": 25.0, "width": 5000, "height": 5000},
  {"name": "KITCHEN", "area": 15.75, "width": 4500, "height": 3500}
]
```

**LLM Answer:**
> Rooms larger than 20 square meters:
> 1. **Living Room**: 35.5 m² (7.1m x 5m)
> 2. **Master Bedroom**: 25 m² (5m x 5m)
>
> The kitchen at 15.75 m² does not meet the 20 m² threshold.

---

### Example 6: "What are all the horizontal dimensions on this floor?"

```
POST /drawings/floor-plan/measurements/query
Content-Type: application/json

{
  "filters": {
    "orientation": "horizontal",
    "region_id": "R001"
  },
  "output": {
    "include_image": true,
    "image_format": "base64",
    "highlight_color": "red"
  }
}
```

Response:
```json
{
  "query_summary": {
    "matched_dimensions": 28,
    "filters_applied": ["orientation=horizontal", "region_id=R001"]
  },
  "dimensions": [...],
  "statistics": {
    "count": 28,
    "min_value": 600.0,
    "max_value": 15000.0,
    "average": 3250.5,
    "total": 91014.0
  },
  "image": {
    "format": "base64",
    "data": "iVBORw0KGgoAAAA...",
    "width": 2000,
    "height": 1500
  }
}
```

**LLM Answer:**
> The ground floor has 28 horizontal dimensions ranging from 600mm to 15000mm (the overall width). The average horizontal dimension is 3250mm.
>
> Key horizontal measurements include:
> - Overall building width: 15000mm (15m)
> - Living room width: 7100mm (7.1m)
> - Bedroom widths: 3500mm - 5000mm
>
> [Embedded annotated image showing all horizontal dimensions]

---

## Workflow Summary for LLMs

1. **Start with `/drawings`** to get available drawing IDs
2. **Use `/drawings/{id}`** to understand the drawing scope
3. **Use `/drawings/{id}/regions`** to identify separate plans/views
4. **Use `/drawings/{id}/spaces`** to find named rooms
5. **Use `/drawings/{id}/annotations`** to find text labels
6. **Use `/measurements/query`** with filters to answer dimension questions
7. **Use point queries** to explore specific coordinates
8. **Always request images** to provide visual confirmation

### Filter Strategy

| Question Type | Filters to Use |
|--------------|----------------|
| Room dimensions | `bounds` (from spaces endpoint) |
| Building height | `orientation: "vertical"` |
| Room widths | `orientation: "horizontal"` + `bounds` |
| Large dimensions | `min_value` |
| Specific floor | `region_id` |
| Wall dimensions | `layers: ["WALL"]` |

### Image Output

- Use `image_format: "base64"` for inline display
- Use `image_format: "url"` when you need to reference the image separately
- Use `highlight_color` to make dimensions stand out
- Use `backend: "librecad"` for higher quality (if available)
