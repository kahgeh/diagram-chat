# Plan-Check API Documentation

A REST API for analyzing DXF/DWG CAD drawings, extracting dimensions, annotations, and geometry, and exporting high-quality images.

**Base URL:** `http://localhost:3000`

---

## Quick Start

1. **Upload a drawing:**

   ```bash
   curl -X POST "http://localhost:3000/drawings" \
     -F "file=@floor_plan.dxf"
   ```

   Response: `{"id": "a1b2c3d4", "filename": "floor_plan.dxf", "message": "Drawing uploaded"}`

2. **Get drawing summary:**

   ```bash
   curl "http://localhost:3000/drawings/a1b2c3d4"
   ```

3. **Extract dimensions:**

   ```bash
   curl "http://localhost:3000/drawings/a1b2c3d4/dimensions"
   ```

4. **Export to PNG:**
   ```bash
   curl -X POST "http://localhost:3000/drawings/a1b2c3d4/export" \
     -H "Content-Type: application/json" \
     -d '{"format": "png", "width": 2000}'
   ```

---

## Endpoints

### Drawing Management

#### `GET /drawings`

List all available drawings in the system.

**Response:**

```json
[
  { "id": "a1b2c3d4", "filename": "floor_plan.dxf" },
  { "id": "e5f6g7h8", "filename": "elevation.dxf" }
]
```

#### `POST /drawings`

Upload a new DXF or DWG file.

**Request:** `multipart/form-data` with `file` field

**Response:**

```json
{
  "id": "a1b2c3d4",
  "filename": "floor_plan.dxf",
  "message": "Drawing uploaded successfully"
}
```

#### `GET /drawings/{drawing_id}`

Get summary information about a drawing.

**Response:**

```json
{
  "id": "a1b2c3d4",
  "filename": "floor_plan.dxf",
  "units": "mm",
  "bounds": {
    "min": { "x": 0.0, "y": 0.0, "z": 0.0 },
    "max": { "x": 15000.0, "y": 10000.0, "z": 0.0 }
  },
  "layouts": [{ "name": "Model", "type": "model_space", "entity_count": 1250 }],
  "layer_count": 15,
  "entity_count": 1250,
  "dimension_count": 45
}
```

#### `DELETE /drawings/{drawing_id}`

Remove a drawing from the cache.

---

### Drawing Structure

#### `GET /drawings/{drawing_id}/layouts`

Get all layouts (Model space and Paper spaces).

**Response:**

```json
[
  { "name": "Model", "type": "model_space", "entity_count": 1250 },
  { "name": "Layout1", "type": "paper_space", "entity_count": 50 }
]
```

#### `GET /drawings/{drawing_id}/layers`

Get all layers with entity counts.

**Response:**

```json
[
  { "name": "WALL", "color": 7, "entity_count": 320 },
  { "name": "DIMENSION", "color": 1, "entity_count": 45 },
  { "name": "TEXT", "color": 2, "entity_count": 80 }
]
```

#### `GET /drawings/{drawing_id}/extents`

Get the bounding box of the drawing.

**Query Parameters:**

- `layer` (optional): Filter to specific layer

**Response:**

```json
{
  "bounds": {
    "min": { "x": 0.0, "y": 0.0, "z": 0.0 },
    "max": { "x": 15000.0, "y": 10000.0, "z": 0.0 }
  },
  "width": 15000.0,
  "height": 10000.0,
  "unit": "mm"
}
```

---

### Entity Extraction

#### `GET /drawings/{drawing_id}/dimensions`

Extract all dimension entities with computed measurements.

**Query Parameters:**

- `layer` (optional): Filter to specific layer

**Response:**

```json
[
  {
    "id": "D0001",
    "type": "linear",
    "value": 3500.0,
    "unit": "mm",
    "display_text": "3500",
    "point_from": { "x": 0.0, "y": 0.0, "z": 0.0 },
    "point_to": { "x": 3500.0, "y": 0.0, "z": 0.0 },
    "midpoint": { "x": 1750.0, "y": 100.0, "z": 0.0 },
    "layer": "DIMENSION"
  }
]
```

**Dimension Types:**

- `linear` - Horizontal or vertical measurement
- `aligned` - Measurement along an angled line
- `angular` - Angle measurement
- `diameter` - Circle diameter
- `radius` - Circle/arc radius
- `ordinate` - X or Y coordinate value

#### `GET /drawings/{drawing_id}/annotations`

Extract all text and MTEXT entities.

**Query Parameters:**

- `layer` (optional): Filter to specific layer

**Response:**

```json
[
  {
    "id": "A0001",
    "type": "text",
    "content": "LIVING ROOM",
    "position": { "x": 5000.0, "y": 3000.0, "z": 0.0 },
    "height": 150.0,
    "layer": "TEXT"
  },
  {
    "id": "A0002",
    "type": "mtext",
    "content": "Floor Area: 45 m²",
    "position": { "x": 5000.0, "y": 2800.0, "z": 0.0 },
    "height": 100.0,
    "layer": "TEXT"
  }
]
```

#### `GET /drawings/{drawing_id}/blocks`

Extract all block insertions (symbols, fixtures, furniture).

**Query Parameters:**

- `layer` (optional): Filter to specific layer

**Response:**

```json
[
  {
    "id": "B0001",
    "block_name": "DOOR_SINGLE",
    "position": { "x": 2000.0, "y": 0.0, "z": 0.0 },
    "scale": 1.0,
    "rotation": 0.0,
    "layer": "DOOR"
  },
  {
    "id": "B0002",
    "block_name": "TOILET",
    "position": { "x": 8500.0, "y": 7000.0, "z": 0.0 },
    "scale": 1.0,
    "rotation": 90.0,
    "layer": "SANITARY"
  }
]
```

#### `GET /drawings/{drawing_id}/geometry`

Extract geometric entities (lines, circles, arcs).

**Query Parameters:**

- `layer` (optional): Filter to specific layer
- `type` (optional): Filter by entity type (`line`, `circle`, `arc`)

**Response:**

```json
[
  {
    "id": "G0001",
    "type": "line",
    "layer": "WALL",
    "start": { "x": 0.0, "y": 0.0, "z": 0.0 },
    "end": { "x": 5000.0, "y": 0.0, "z": 0.0 },
    "length": 5000.0
  },
  {
    "id": "G0002",
    "type": "circle",
    "layer": "COLUMN",
    "center": { "x": 3000.0, "y": 3000.0, "z": 0.0 },
    "radius": 300.0
  }
]
```

---

### Semantic Analysis

#### `GET /drawings/{drawing_id}/regions`

Detect separate drawing regions (useful for multi-unit floor plans).

The API uses a grid-based clustering algorithm to identify distinct regions separated by gaps.

**Response:**

```json
[
  {
    "id": "R001",
    "bounds": {
      "min": { "x": 0.0, "y": 0.0, "z": 0.0 },
      "max": { "x": 8000.0, "y": 6000.0, "z": 0.0 }
    },
    "width": 8000.0,
    "height": 6000.0,
    "area": 48.0,
    "entity_count": 450,
    "nearby_labels": ["UNIT 1", "LIVING ROOM", "BEDROOM 1"],
    "contained_blocks": ["DOOR_SINGLE", "TOILET", "BASIN"]
  }
]
```

#### `GET /drawings/{drawing_id}/spaces`

Identify rooms and spaces by analyzing text labels.

**Response:**

```json
[
  {
    "id": "S001",
    "name": "LIVING ROOM",
    "confidence": 0.9,
    "source": "text_label",
    "bounds": {
      "min": { "x": 1000.0, "y": 1000.0, "z": 0.0 },
      "max": { "x": 6000.0, "y": 5000.0, "z": 0.0 }
    },
    "width": 5000.0,
    "height": 4000.0,
    "area": 20.0,
    "fixtures": []
  },
  {
    "id": "S002",
    "name": "BATHROOM",
    "confidence": 0.85,
    "source": "text_label",
    "bounds": {
      "min": { "x": 7000.0, "y": 1000.0, "z": 0.0 },
      "max": { "x": 9000.0, "y": 3000.0, "z": 0.0 }
    },
    "width": 2000.0,
    "height": 2000.0,
    "area": 4.0,
    "fixtures": ["TOILET", "BASIN", "SHOWER"]
  }
]
```

**Recognized Space Types:**

- ROOM, BATHROOM, KITCHEN, BEDROOM, LIVING, DINING
- GARAGE, OFFICE, TOILET, WC, HALL, CORRIDOR

**Recognized Fixtures:**

- TOILET, BASIN, SINK, SHOWER, TUB, DOOR, WINDOW

#### `GET /drawings/{drawing_id}/building`

Get building-level summary with floor information.

**Response:**

```json
{
  "floors": [
    {
      "name": "Ground Floor",
      "bounds": {
        "min": { "x": 0.0, "y": 0.0, "z": 0.0 },
        "max": { "x": 15000.0, "y": 10000.0, "z": 0.0 }
      },
      "width": 15000.0,
      "height": 10000.0,
      "spaces": ["LIVING ROOM", "KITCHEN", "BATHROOM", "BEDROOM 1"]
    }
  ],
  "overall_width": 15000.0,
  "overall_height": 10000.0,
  "unit": "mm"
}
```

#### `POST /drawings/{drawing_id}/query/point`

Query entities near a specific point (useful for investigating specific areas).

**Request:**

```json
{
  "x": 5000.0,
  "y": 3000.0,
  "radius": 1000.0
}
```

**Response:**

```json
{
  "nearby_texts": ["LIVING ROOM", "45 m²"],
  "nearby_blocks": ["DOOR_SINGLE", "WINDOW_DOUBLE"],
  "nearby_dimensions": [
    {
      "id": "D0015",
      "type": "linear",
      "value": 5000.0,
      "unit": "mm",
      "layer": "DIMENSION"
    }
  ]
}
```

#### `POST /drawings/{drawing_id}/measurements/query`

**Query dimensions with filters and get an annotated image.** This is the primary endpoint for LLM-powered measurement queries.

This endpoint allows flexible filtering of dimensions and returns both structured data and a visual representation with the queried dimensions highlighted.

**Request:**

```json
{
  "filters": {
    "min_value": 1000,
    "max_value": 10000,
    "orientation": "horizontal",
    "layers": ["DIM"],
    "region_id": "R001",
    "bounds": {
      "min": { "x": 0, "y": 0 },
      "max": { "x": 10000, "y": 10000 }
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

**Filter Parameters:**
| Field | Type | Description |
|-------|------|-------------|
| `min_value` | float | Minimum dimension value (in drawing units, typically mm) |
| `max_value` | float | Maximum dimension value |
| `orientation` | string | `"horizontal"`, `"vertical"`, or `"diagonal"` |
| `layers` | string[] | Filter by layer names (e.g., `["DIM", "DIMENSIONS"]`) |
| `region_id` | string | Limit to a detected region (use `GET /regions` first) |
| `bounds` | object | Spatial bounding box `{min: {x, y}, max: {x, y}}` |

**Output Parameters:**
| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `include_image` | bool | `true` | Generate annotated image |
| `image_format` | string | `"base64"` | `"base64"` (embedded) or `"url"` (separate fetch) |
| `image_width` | int | `2000` | Output image width in pixels |
| `highlight_color` | string | `"red"` | Color for markers: red, blue, green, orange, purple, cyan, magenta, yellow, black |
| `background` | string | `"white"` | Image background: white, black, transparent |
| `backend` | string | `"librecad"` | Render backend: ezdxf or librecad |

**Response:**

```json
{
  "query_summary": {
    "total_dimensions": 17,
    "matched_dimensions": 5,
    "filters_applied": ["min_value=1000.0", "orientation=horizontal"]
  },
  "dimensions": [
    {
      "id": "D0001",
      "type": "linear",
      "value": 3880.0,
      "unit": "mm",
      "display_text": null,
      "point_from": { "x": 100.0, "y": 200.0, "z": 0.0 },
      "point_to": { "x": 3980.0, "y": 200.0, "z": 0.0 },
      "midpoint": { "x": 2040.0, "y": 200.0, "z": 0.0 },
      "layer": "DIM"
    }
  ],
  "statistics": {
    "count": 5,
    "min_value": 1000.0,
    "max_value": 16175.0,
    "average": 4521.3,
    "total": 22606.5
  },
  "image": {
    "format": "base64",
    "data": "iVBORw0KGgo...",
    "url": null,
    "width": 2000,
    "height": 1500,
    "scale": 0.15
  }
}
```

**Example Use Cases for LLMs:**

1. **"What are the bathroom dimensions?"**
   - First call `GET /spaces` to find bathroom bounds
   - Then query with those bounds:

   ```json
   {
     "filters": {
       "bounds": {
         "min": { "x": 7000, "y": 1000 },
         "max": { "x": 9000, "y": 3000 }
       }
     }
   }
   ```

2. **"Show all dimensions over 3 meters"**

   ```json
   { "filters": { "min_value": 3000 } }
   ```

3. **"What are the horizontal dimensions in the ground floor?"**

   ```json
   { "filters": { "orientation": "horizontal", "region_id": "R001" } }
   ```

4. **"How wide is the building?"**
   - Query horizontal dimensions and look at the largest value in statistics

---

### Export

#### `POST /drawings/{drawing_id}/export`

Export drawing or region to PNG image.

**Request:**

```json
{
  "format": "png",
  "layout": "Model",
  "layers": ["WALL", "DOOR", "WINDOW"],
  "width": 2000,
  "scale": null,
  "background": "white",
  "region": null,
  "backend": "ezdxf"
}
```

**Parameters:**
| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `format` | string | `"png"` | Output format (currently only PNG) |
| `layout` | string | `"Model"` | Layout to export |
| `layers` | string[] | `null` | Layers to include (null = all) |
| `width` | int | `null` | Output width in pixels |
| `scale` | float | `null` | Pixels per drawing unit |
| `background` | string | `"white"` | `"white"`, `"black"`, or `"transparent"` |
| `region` | Bounds | `null` | Crop to specific region |
| `backend` | string | `"ezdxf"` | `"ezdxf"` (fast) or `"librecad"` (high quality) |

**Response:**

```json
{
  "url": "/exports/a1b2c3d4_export_1234567890.png",
  "filename": "a1b2c3d4_export_1234567890.png",
  "width": 2000,
  "height": 1333,
  "scale": 0.133,
  "drawing_width": 15000.0,
  "drawing_height": 10000.0,
  "drawing_bounds": {
    "min": { "x": -500.0, "y": -500.0, "z": 0.0 },
    "max": { "x": 15500.0, "y": 10500.0, "z": 0.0 }
  },
  "backend": "ezdxf"
}
```

**Response Fields:**
| Field | Type | Description |
|-------|------|-------------|
| `url` | string | URL path to fetch the exported image |
| `filename` | string | Filename of the exported image |
| `width` | int | Image width in pixels |
| `height` | int | Image height in pixels |
| `scale` | float | Pixels per drawing unit |
| `drawing_width` | float | Drawing width in drawing units |
| `drawing_height` | float | Drawing height in drawing units |
| `drawing_bounds` | Bounds | Actual drawing coordinates of the image (for coordinate mapping) |
| `backend` | string | Render backend used |

A corresponding `.json` metadata file is saved alongside each exported PNG with the same information, useful for coordinate mapping when annotating images.

#### `POST /drawings/{drawing_id}/regions/{region_id}/export`

Export a specific detected region.

**Query Parameters:**

- `width` (optional): Output width in pixels
- `backend` (optional): `"ezdxf"` or `"librecad"`

#### `POST /drawings/{drawing_id}/export/annotated`

Export with measurement annotations overlaid.

**Request:**

```json
{
  "region_id": "R001",
  "measurements": [
    {
      "start_x": 0.0,
      "start_y": 0.0,
      "end_x": 5000.0,
      "end_y": 0.0,
      "value": 5000.0,
      "label": "Wall Length"
    }
  ],
  "backend": "librecad"
}
```

**Response:**

```json
{
  "url": "/exports/a1b2c3d4_annotated_1234567890.png",
  "filename": "a1b2c3d4_annotated_1234567890.png",
  "width": 2000,
  "height": 1500,
  "measurements_drawn": 1
}
```

#### `GET /exports/{filename}`

Serve an exported PNG file.

**Response:** PNG image file

---

## Render Backends

### ezdxf (Default)

- Fast rendering using matplotlib
- Good for quick previews
- May miss some complex entities

### librecad (High Quality)

- Uses LibreCAD's `dxf2pdf` for accurate rendering
- Requires LibreCAD and poppler (pdftoppm) installed
- Better handling of complex drawings
- Recommended for final exports

---

## Common Workflows

### LLM Workflow: Answering Measurement Questions

This section shows how an LLM should use the API to answer natural language questions about measurements and dimensions.

#### Example 1: "What are the sizes of the bathrooms?"

**Step 1:** Get identified spaces to find bathrooms

```bash
GET /drawings/{id}/spaces
```

Response includes bathroom bounds:

```json
[
  {
    "name": "BATHROOM",
    "bounds": {
      "min": { "x": 7000, "y": 1000 },
      "max": { "x": 9000, "y": 3000 }
    },
    "fixtures": ["toilet", "sink"]
  },
  {
    "name": "BATHROOM 2",
    "bounds": {
      "min": { "x": 12000, "y": 1000 },
      "max": { "x": 14000, "y": 2500 }
    },
    "fixtures": ["toilet", "shower"]
  }
]
```

**Step 2:** Query dimensions within each bathroom's bounds

```bash
POST /drawings/{id}/measurements/query
{
  "filters": {
    "bounds": {"min": {"x": 7000, "y": 1000}, "max": {"x": 9000, "y": 3000}}
  },
  "output": {"include_image": true, "image_format": "base64"}
}
```

Response includes dimensions and annotated image.

**Step 3:** LLM synthesizes answer

> "The building has 2 bathrooms:
>
> - **Bathroom 1**: 2.0m × 2.0m (4.0 m²) - contains toilet and sink
> - **Bathroom 2**: 2.0m × 1.5m (3.0 m²) - contains toilet and shower
>
> [Annotated image showing bathroom dimensions]"

---

#### Example 2: "How many floors does the building have?"

**Step 1:** Get detected regions to understand drawing structure

```bash
GET /drawings/{id}/regions
```

Response shows separate regions with labels:

```json
[
  { "id": "R001", "nearby_labels": ["GROUND FLOOR", "PLANTA BAJA"] },
  { "id": "R002", "nearby_labels": ["FIRST FLOOR", "PLANTA ALTA"] },
  { "id": "R003", "nearby_labels": ["FACADE E-A", "ELEVATION"] }
]
```

**Step 2:** Query vertical dimensions from an elevation view

```bash
POST /drawings/{id}/measurements/query
{
  "filters": {"region_id": "R003", "orientation": "vertical"},
  "output": {"include_image": true, "image_format": "base64"}
}
```

Response includes floor heights.

**Step 3:** Get annotations for floor level labels

```bash
GET /drawings/{id}/annotations
```

Look for elevation markers like "+0.00", "+2.70", "+5.40"

**Step 4:** LLM synthesizes answer

> "The building has **2 floors**:
>
> - Ground Floor (elevation +0.00m)
> - First Floor (elevation +2.70m)
> - Roof level at +5.40m
>
> Floor-to-floor height: 2.7m
>
> [Annotated elevation image showing floor heights]"

---

#### Example 3: "What is the total width of the building?"

**Step 1:** Query all horizontal dimensions

```bash
POST /drawings/{id}/measurements/query
{
  "filters": {"orientation": "horizontal"},
  "output": {"include_image": true, "image_format": "base64"}
}
```

**Step 2:** Check statistics in response

```json
{
  "statistics": {
    "count": 14,
    "min_value": 1000.0,
    "max_value": 19760.0,
    "average": 8527.0,
    "total": 119379.0
  }
}
```

**Step 3:** LLM synthesizes answer

> "The building's maximum horizontal dimension is **19.76 meters** (19,760 mm).
>
> The total of all horizontal dimensions is 119.4 meters, distributed across 14 measurements.
>
> [Annotated image showing horizontal dimensions]"

---

### Analyze a Floor Plan

1. Upload the drawing
2. Get the summary to understand structure
3. Extract dimensions to get measurements
4. Extract annotations to get room labels
5. Use `/spaces` to identify rooms
6. Export regions as needed

```bash
# 1. Upload
DRAWING_ID=$(curl -s -X POST "http://localhost:3000/drawings" \
  -F "file=@floor_plan.dxf" | jq -r '.id')

# 2. Get summary
curl "http://localhost:3000/drawings/$DRAWING_ID"

# 3. Get dimensions
curl "http://localhost:3000/drawings/$DRAWING_ID/dimensions"

# 4. Get room labels
curl "http://localhost:3000/drawings/$DRAWING_ID/annotations"

# 5. Identify spaces
curl "http://localhost:3000/drawings/$DRAWING_ID/spaces"

# 6. Export high-quality PNG
curl -X POST "http://localhost:3000/drawings/$DRAWING_ID/export" \
  -H "Content-Type: application/json" \
  -d '{"width": 4000, "backend": "librecad"}'
```

### Extract Specific Measurements

1. Get all dimensions
2. Filter by layer if needed
3. Query specific points for nearby dimensions

```bash
# Get dimensions from DIMENSION layer only
curl "http://localhost:3000/drawings/$DRAWING_ID/dimensions?layer=DIMENSION"

# Query what's near a specific point
curl -X POST "http://localhost:3000/drawings/$DRAWING_ID/query/point" \
  -H "Content-Type: application/json" \
  -d '{"x": 5000, "y": 3000, "radius": 500}'
```

### Export Multiple Regions

1. Detect regions
2. Export each region separately

```bash
# Get regions
curl "http://localhost:3000/drawings/$DRAWING_ID/regions"

# Export region R001
curl -X POST "http://localhost:3000/drawings/$DRAWING_ID/regions/R001/export?width=2000"

# Export region R002
curl -X POST "http://localhost:3000/drawings/$DRAWING_ID/regions/R002/export?width=2000"
```

---

## Error Responses

| Status | Description                                            |
| ------ | ------------------------------------------------------ |
| 400    | Invalid file format, conversion failed, or bad request |
| 404    | Drawing, region, or layer not found                    |
| 500    | Server error (missing dependencies, rendering failure) |

**Example Error:**

```json
{
  "detail": "Drawing not found: a1b2c3d4"
}
```

---

## Data Types Reference

### Point

```json
{ "x": 0.0, "y": 0.0, "z": 0.0 }
```

### Bounds

```json
{
  "min": { "x": 0.0, "y": 0.0, "z": 0.0 },
  "max": { "x": 15000.0, "y": 10000.0, "z": 0.0 }
}
```

### Units

All measurements are in drawing units (typically millimeters for architectural drawings). The `unit` field indicates the unit when available.

---

## Dependencies

- **Required:** Python 3.9+, FastAPI, ezdxf, matplotlib, Pillow
- **Optional (for high-quality export):** LibreCAD, poppler-utils (pdftoppm)
- **Optional (for DWG support):** ODA File Converter

---

## Known Limitations & Troubleshooting

### ACAD_PROXY_ENTITY (Incomplete Exports)

**Problem:** Exports may be missing building walls, hatches, or other geometry.

**Cause:** DXF files created with AutoCAD vertical products (AutoCAD Architecture, AutoCAD MEP, etc.) often contain `ACAD_PROXY_ENTITY` entities. These are proprietary entities that wrap custom objects like:

- AEC walls and doors
- Intelligent building components
- Custom hatches

**Detection:** Check if your drawing has proxy entities:

```bash
curl "http://localhost:3000/drawings/{id}" | jq '.entity_count'
# Then check entity types via direct inspection
```

If the drawing contains ACAD_PROXY_ENTITY, the proxy graphics may not contain renderable geometry (only 8 bytes of header data with no actual drawing commands).

**Solutions:**

1. **Use LibreCAD backend** (recommended):

   ```bash
   # Install LibreCAD
   brew install librecad  # macOS
   apt install librecad   # Ubuntu/Debian

   # Export with LibreCAD backend
   curl -X POST "http://localhost:3000/drawings/{id}/export" \
     -H "Content-Type: application/json" \
     -d '{"backend": "librecad", "width": 4000}'
   ```

2. **Re-export from AutoCAD:**
   - Open the DXF in AutoCAD
   - Use `EXPORTTOAUTOCAD` command to convert AEC objects to standard geometry
   - Or use `AECEXPORTTOAUTOCAD` for architectural objects
   - Save as DXF (AutoCAD 2018 format recommended)

3. **Use ODA File Converter:**
   - Download from [ODA](https://www.opendesign.com/guestfiles/oda_file_converter)
   - Convert DWG to DXF which may flatten some proxy objects

### Entity Types Supported by ezdxf Backend

| Entity Type       | Rendered | Notes                                    |
| ----------------- | -------- | ---------------------------------------- |
| LINE              | ✅       | Full support                             |
| CIRCLE            | ✅       | Full support                             |
| ARC               | ✅       | Full support                             |
| POLYLINE          | ✅       | Full support                             |
| LWPOLYLINE        | ✅       | Full support                             |
| ELLIPSE           | ✅       | Full support                             |
| SPLINE            | ✅       | Full support                             |
| TEXT              | ✅       | Full support                             |
| MTEXT             | ✅       | Full support                             |
| DIMENSION         | ✅       | Full support                             |
| INSERT (blocks)   | ✅       | Full support                             |
| HATCH             | ⚠️       | Basic support, complex patterns may fail |
| ACAD_PROXY_ENTITY | ❌       | Cannot render without proxy graphics     |
| ACAD_TABLE        | ⚠️       | Partial support                          |
| IMAGE             | ⚠️       | Requires image files                     |
