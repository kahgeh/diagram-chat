"""DXF API Server - Exposes DXF drawing data for AI agents."""
import ezdxf
from ezdxf import bbox as ezdxf_bbox
from ezdxf.addons.drawing import RenderContext, Frontend
from ezdxf.addons.drawing.matplotlib import MatplotlibBackend
from fastapi import FastAPI, HTTPException, Query, UploadFile, File
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import Optional
from collections import defaultdict
import matplotlib
matplotlib.use('Agg')  # Non-interactive backend
import matplotlib.pyplot as plt
import math
import os
import platform
import subprocess
import tempfile
import uuid
import shutil
from enum import Enum

app = FastAPI(title="DXF API", description="API for accessing DXF/DWG drawing data for AI agents")


# ============== DWG TO DXF CONVERSION ==============

def find_oda_converter() -> str | None:
    """Find the ODA File Converter executable on the system."""
    system = platform.system()

    if system == "Darwin":  # macOS
        possible_paths = [
            "/Applications/ODAFileConverter.app/Contents/MacOS/ODAFileConverter",
            os.path.expanduser("~/Applications/ODAFileConverter.app/Contents/MacOS/ODAFileConverter"),
        ]
    elif system == "Windows":
        possible_paths = [
            r"C:\Program Files\ODA\ODAFileConverter\ODAFileConverter.exe",
            r"C:\Program Files (x86)\ODA\ODAFileConverter\ODAFileConverter.exe",
        ]
    else:  # Linux
        possible_paths = [
            "/usr/bin/ODAFileConverter",
            "/usr/local/bin/ODAFileConverter",
            os.path.expanduser("~/ODAFileConverter/ODAFileConverter"),
        ]

    for path in possible_paths:
        if os.path.isfile(path):
            return path

    result = shutil.which("ODAFileConverter")
    return result


def find_librecad() -> str | None:
    """Find LibreCAD executable on the system."""
    system = platform.system()

    if system == "Darwin":  # macOS
        possible_paths = [
            "/Applications/LibreCAD.app/Contents/MacOS/LibreCAD",
            os.path.expanduser("~/Applications/LibreCAD.app/Contents/MacOS/LibreCAD"),
        ]
    elif system == "Windows":
        possible_paths = [
            r"C:\Program Files\LibreCAD\LibreCAD.exe",
            r"C:\Program Files (x86)\LibreCAD\LibreCAD.exe",
        ]
    else:  # Linux
        possible_paths = [
            "/usr/bin/librecad",
            "/usr/local/bin/librecad",
        ]

    for path in possible_paths:
        if os.path.isfile(path):
            return path

    result = shutil.which("librecad") or shutil.which("LibreCAD")
    return result


def find_pdftoppm() -> str | None:
    """Find pdftoppm executable (from poppler)."""
    return shutil.which("pdftoppm")


def convert_dwg_to_dxf(input_path: str, output_path: str, dxf_version: str = "ACAD2018") -> bool:
    """
    Convert a DWG file to DXF format using ODA File Converter.

    Args:
        input_path: Path to input DWG file
        output_path: Path to output DXF file
        dxf_version: Output DXF version (ACAD2018, ACAD2013, etc.)

    Returns:
        True if conversion was successful, False otherwise
    """
    converter = find_oda_converter()

    if not converter:
        print("Error: ODA File Converter not found!")
        print("Download from: https://www.opendesign.com/guestfiles/oda_file_converter")
        return False

    input_path = os.path.abspath(input_path)
    output_path = os.path.abspath(output_path)

    if not os.path.exists(input_path):
        print(f"Error: Input file does not exist: {input_path}")
        return False

    input_filename = os.path.basename(input_path)
    output_dir = os.path.dirname(output_path)
    output_filename = os.path.basename(output_path)

    # ODA converter works with directories, so use temp directories
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_input = os.path.join(temp_dir, "input")
        temp_output = os.path.join(temp_dir, "output")
        os.makedirs(temp_input)
        os.makedirs(temp_output)

        # Copy input file to temp directory
        shutil.copy(input_path, os.path.join(temp_input, input_filename))

        # Run converter
        cmd = [
            converter,
            temp_input,
            temp_output,
            dxf_version,
            "DXF",
            "0",  # Recurse folders: 0 = no
            "1",  # Audit: 1 = yes
            input_filename
        ]

        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)

            # Check if output was created
            input_stem = os.path.splitext(input_filename)[0]
            converted_file = os.path.join(temp_output, input_stem + ".dxf")

            if os.path.exists(converted_file):
                os.makedirs(output_dir, exist_ok=True)
                shutil.move(converted_file, output_path)
                print(f"Successfully converted: {input_filename} -> {output_filename}")
                return True
            else:
                print(f"Error: Conversion failed for {input_filename}")
                if result.stderr:
                    print(f"Error output: {result.stderr}")
                return False

        except subprocess.TimeoutExpired:
            print(f"Error: Conversion timed out for {input_filename}")
            return False
        except Exception as e:
            print(f"Error during conversion: {e}")
            return False

# Storage for uploaded drawings
UPLOAD_DIR = "outputs/uploads"
EXPORT_DIR = "outputs/exports"
CONVERTED_DIR = "outputs/converted"  # DWG files converted to DXF

# In-memory cache of loaded drawings
drawings: dict = {}


class Point(BaseModel):
    x: float
    y: float
    z: float = 0.0


class Bounds(BaseModel):
    min: Point
    max: Point


class LayoutInfo(BaseModel):
    name: str
    type: str
    entity_count: int


class LayerInfo(BaseModel):
    name: str
    color: int
    entity_count: int


class DimensionInfo(BaseModel):
    id: str
    type: str
    value: float
    unit: str = "mm"
    display_text: Optional[str] = None
    point_from: Optional[Point] = None
    point_to: Optional[Point] = None
    midpoint: Optional[Point] = None
    layer: str


class AnnotationInfo(BaseModel):
    id: str
    type: str
    content: str
    position: Point
    height: Optional[float] = None
    layer: str


class BlockInsertInfo(BaseModel):
    id: str
    block_name: str
    position: Point
    scale: float = 1.0
    rotation: float = 0.0
    layer: str


class GeometryInfo(BaseModel):
    id: str
    type: str
    layer: str
    start: Optional[Point] = None
    end: Optional[Point] = None
    center: Optional[Point] = None
    radius: Optional[float] = None
    length: Optional[float] = None


class DrawingSummary(BaseModel):
    id: str
    filename: str
    units: str
    bounds: Bounds
    layouts: list[LayoutInfo]
    layer_count: int
    entity_count: int
    dimension_count: int


class DrawingUploadResponse(BaseModel):
    id: str
    filename: str
    message: str


class DrawingListItem(BaseModel):
    id: str
    filename: str


class ExtentsInfo(BaseModel):
    bounds: Bounds
    width: float
    height: float
    unit: str = "mm"


class RenderBackend(str, Enum):
    """Render backend for PNG export."""
    EZDXF = "ezdxf"  # Fast, but may miss some entity types (ACAD_PROXY_ENTITY, complex hatches)
    LIBRECAD = "librecad"  # Higher quality, renders most entities correctly


class ExportRequest(BaseModel):
    format: str = "png"
    layout: str = "Model"
    layers: Optional[list[str]] = None
    width: Optional[int] = None  # Output width in pixels (ignored if scale is set)
    scale: Optional[float] = None  # Pixels per drawing unit (e.g., 0.1 = 1px per 10mm)
    background: str = "white"
    region: Optional[Bounds] = None
    backend: RenderBackend = RenderBackend.EZDXF  # Render backend to use


class ExportResponse(BaseModel):
    url: str
    filename: str
    width: int  # Output image width in pixels
    height: int  # Output image height in pixels
    scale: float  # Actual pixels per drawing unit used
    drawing_width: float  # Drawing width in drawing units
    drawing_height: float  # Drawing height in drawing units
    drawing_bounds: Bounds  # Actual drawing bounds (for coordinate mapping)
    backend: str  # Render backend used


class RegionInfo(BaseModel):
    id: str
    bounds: Bounds
    width: float
    height: float
    area: float
    entity_count: int
    nearby_labels: list[str]
    contained_blocks: list[str]


class SpaceInfo(BaseModel):
    id: str
    name: str
    confidence: float
    source: str
    bounds: Bounds
    width: float
    height: float
    area: float
    fixtures: list[str]


class FloorInfo(BaseModel):
    name: str
    bounds: Bounds
    width: float
    height: float
    spaces: list[str]


class BuildingSummary(BaseModel):
    floors: list[FloorInfo]
    overall_width: float
    overall_height: float
    unit: str = "mm"


class PointQuery(BaseModel):
    x: float
    y: float
    radius: float = 1000.0


class PointQueryResult(BaseModel):
    nearby_texts: list[str]
    nearby_blocks: list[str]
    nearby_dimensions: list[DimensionInfo]


class MeasurementAnnotation(BaseModel):
    """A measurement to annotate on an image."""
    start_x: float  # Start point X in drawing units
    start_y: float  # Start point Y in drawing units
    end_x: float    # End point X in drawing units
    end_y: float    # End point Y in drawing units
    value: float    # Measurement value in mm
    label: Optional[str] = None  # Optional custom label


class AnnotatedExportRequest(BaseModel):
    """Request to export an image with measurement annotations."""
    region_id: Optional[str] = None  # Region to export (if None, exports full drawing)
    measurements: list[MeasurementAnnotation]  # Measurements to annotate
    backend: RenderBackend = RenderBackend.LIBRECAD


class AnnotatedExportResponse(BaseModel):
    url: str
    filename: str
    width: int
    height: int
    measurements_drawn: int


# ============== MEASUREMENTS QUERY MODELS ==============

class MeasurementFilterBounds(BaseModel):
    """Spatial bounds for filtering dimensions."""
    min: Point
    max: Point


class MeasurementFilters(BaseModel):
    """Filters for querying dimensions."""
    min_value: Optional[float] = None  # Minimum dimension value (in drawing units, typically mm)
    max_value: Optional[float] = None  # Maximum dimension value
    orientation: Optional[str] = None  # horizontal, vertical, diagonal, or None for all
    layers: Optional[list[str]] = None  # Filter by layer names
    region_id: Optional[str] = None  # Limit to a detected region
    bounds: Optional[MeasurementFilterBounds] = None  # Spatial bounding box


class MeasurementOutputOptions(BaseModel):
    """Output options for the measurements query."""
    include_image: bool = True  # Generate annotated image
    image_format: str = "base64"  # base64 or url
    image_width: int = 2000  # Pixel width
    highlight_color: str = "red"  # Color for marking dimensions
    background: str = "white"  # white, black, or transparent
    backend: RenderBackend = RenderBackend.LIBRECAD  # Render backend


class MeasurementsQueryRequest(BaseModel):
    """Request body for querying measurements."""
    filters: Optional[MeasurementFilters] = None
    output: Optional[MeasurementOutputOptions] = None


class MeasurementStatistics(BaseModel):
    """Statistics about queried dimensions."""
    count: int
    min_value: Optional[float] = None
    max_value: Optional[float] = None
    average: Optional[float] = None
    total: Optional[float] = None


class QuerySummary(BaseModel):
    """Summary of the query results."""
    total_dimensions: int
    matched_dimensions: int
    filters_applied: list[str]


class ImageOutput(BaseModel):
    """Image output information."""
    format: str  # base64 or url
    data: Optional[str] = None  # Base64 data if format is base64
    url: Optional[str] = None  # URL if format is url
    width: int
    height: int
    scale: float


class MeasurementsQueryResponse(BaseModel):
    """Response from measurements query."""
    query_summary: QuerySummary
    dimensions: list[DimensionInfo]
    statistics: MeasurementStatistics
    image: Optional[ImageOutput] = None


@app.on_event("startup")
async def startup():
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    os.makedirs(EXPORT_DIR, exist_ok=True)
    os.makedirs(CONVERTED_DIR, exist_ok=True)

    # Load any existing DXF/DWG files from inputs folder
    inputs_dir = "inputs"
    if os.path.exists(inputs_dir):
        for filename in os.listdir(inputs_dir):
            filepath = os.path.join(inputs_dir, filename)
            drawing_id = os.path.splitext(filename)[0].lower().replace(' ', '-').replace('_', '-')

            if filename.lower().endswith('.dxf'):
                # Load DXF directly
                try:
                    load_drawing(drawing_id, filepath, filename)
                    print(f"Loaded drawing: {drawing_id} from {filepath}")
                except Exception as e:
                    print(f"Failed to load {filepath}: {e}")

            elif filename.lower().endswith('.dwg'):
                # Convert DWG to DXF first
                dxf_filename = os.path.splitext(filename)[0] + ".dxf"
                dxf_path = os.path.join(CONVERTED_DIR, dxf_filename)

                # Check if already converted
                if not os.path.exists(dxf_path):
                    print(f"Converting DWG to DXF: {filename}...")
                    if not convert_dwg_to_dxf(filepath, dxf_path):
                        print(f"Failed to convert {filename}")
                        continue

                try:
                    load_drawing(drawing_id, dxf_path, filename)
                    print(f"Loaded drawing: {drawing_id} from {filename} (converted)")
                except Exception as e:
                    print(f"Failed to load converted {filename}: {e}")


def load_drawing(drawing_id: str, filepath: str, original_filename: str):
    """Load a DXF file and cache it."""
    doc = ezdxf.readfile(filepath)
    msp = doc.modelspace()
    cache = ezdxf_bbox.Cache()

    drawings[drawing_id] = {
        'doc': doc,
        'msp': msp,
        'cache': cache,
        'filepath': filepath,
        'filename': original_filename,
    }


def get_drawing(drawing_id: str):
    """Get a loaded drawing by ID."""
    if drawing_id not in drawings:
        raise HTTPException(status_code=404, detail=f"Drawing '{drawing_id}' not found. Use GET /drawings to list available drawings.")
    return drawings[drawing_id]


def get_entity_bounds(entity, cache):
    """Get bounding box for an entity."""
    try:
        bbox = ezdxf_bbox.extents([entity], cache=cache)
        if bbox.has_data:
            return bbox
    except:
        pass
    return None


def get_entity_center(entity, cache):
    """Get center point of an entity."""
    bbox = get_entity_bounds(entity, cache)
    if bbox:
        return (
            (bbox.extmin.x + bbox.extmax.x) / 2,
            (bbox.extmin.y + bbox.extmax.y) / 2
        )
    return None


def count_entities_by_layer(msp):
    """Count entities per layer."""
    counts = {}
    for entity in msp:
        layer = entity.dxf.layer if hasattr(entity.dxf, 'layer') else "0"
        counts[layer] = counts.get(layer, 0) + 1
    return counts


def is_in_bounds(point, bounds, padding=0):
    """Check if a point is within bounds."""
    if point is None:
        return False
    return (bounds.min.x - padding <= point[0] <= bounds.max.x + padding and
            bounds.min.y - padding <= point[1] <= bounds.max.y + padding)


def detect_regions(msp, cache):
    """Detect separate drawing regions based on entity clustering."""
    entities_with_bounds = []
    for entity in msp:
        center = get_entity_center(entity, cache)
        if center:
            entities_with_bounds.append({
                'entity': entity,
                'center': center,
            })

    if not entities_with_bounds:
        return []

    all_x = [e['center'][0] for e in entities_with_bounds]
    all_y = [e['center'][1] for e in entities_with_bounds]
    min_x, max_x = min(all_x), max(all_x)
    min_y, max_y = min(all_y), max(all_y)
    width = max_x - min_x
    height = max_y - min_y

    if width == 0 or height == 0:
        return []

    grid_size = 40
    grid = defaultdict(int)

    for e in entities_with_bounds:
        gx = int((e['center'][0] - min_x) / width * grid_size)
        gy = int((e['center'][1] - min_y) / height * grid_size)
        gx = min(gx, grid_size - 1)
        gy = min(gy, grid_size - 1)
        grid[(gx, gy)] += 1

    x_counts = defaultdict(int)
    y_counts = defaultdict(int)
    for (gx, gy), count in grid.items():
        x_counts[gx] += count
        y_counts[gy] += count

    x_threshold = max(x_counts.values()) * 0.02 if x_counts else 0
    x_gap_regions = []
    in_gap = False
    gap_start = None

    for x in range(grid_size):
        if x_counts[x] <= x_threshold:
            if not in_gap:
                in_gap = True
                gap_start = x
        else:
            if in_gap:
                x_gap_regions.append((gap_start, x - 1))
                in_gap = False

    y_threshold = max(y_counts.values()) * 0.02 if y_counts else 0
    y_gap_regions = []
    in_gap = False
    gap_start = None

    for y in range(grid_size):
        if y_counts[y] <= y_threshold:
            if not in_gap:
                in_gap = True
                gap_start = y
        else:
            if in_gap:
                y_gap_regions.append((gap_start, y - 1))
                in_gap = False

    x_boundaries = [0]
    for g in x_gap_regions:
        if g[1] - g[0] >= 1:
            midpoint = (g[0] + g[1] + 1) // 2
            x_boundaries.append(midpoint)
    x_boundaries.append(grid_size)

    y_boundaries = [0]
    for g in y_gap_regions:
        if g[1] - g[0] >= 1:
            midpoint = (g[0] + g[1] + 1) // 2
            y_boundaries.append(midpoint)
    y_boundaries.append(grid_size)

    regions = []
    region_idx = 1

    for i in range(len(x_boundaries) - 1):
        for j in range(len(y_boundaries) - 1):
            x_start = x_boundaries[i]
            x_end = x_boundaries[i + 1]
            y_start = y_boundaries[j]
            y_end = y_boundaries[j + 1]

            region_count = sum(grid[(x, y)] for x in range(x_start, x_end) for y in range(y_start, y_end))

            if region_count > 30:
                world_x_min = min_x + (x_start / grid_size) * width
                world_x_max = min_x + (x_end / grid_size) * width
                world_y_min = min_y + (y_start / grid_size) * height
                world_y_max = min_y + (y_end / grid_size) * height

                region_entities = [e for e in entities_with_bounds
                                   if world_x_min <= e['center'][0] <= world_x_max
                                   and world_y_min <= e['center'][1] <= world_y_max]

                if region_entities:
                    actual_min_x = min(e['center'][0] for e in region_entities) - 500
                    actual_max_x = max(e['center'][0] for e in region_entities) + 500
                    actual_min_y = min(e['center'][1] for e in region_entities) - 500
                    actual_max_y = max(e['center'][1] for e in region_entities) + 500

                    regions.append({
                        'id': f"R{region_idx:03d}",
                        'bounds': Bounds(
                            min=Point(x=actual_min_x, y=actual_min_y),
                            max=Point(x=actual_max_x, y=actual_max_y)
                        ),
                        'entity_count': region_count,
                    })
                    region_idx += 1

    return regions


# ============== DRAWING MANAGEMENT ==============

@app.get("/drawings", response_model=list[DrawingListItem])
async def list_drawings():
    """List all available drawings."""
    return [
        DrawingListItem(id=drawing_id, filename=data['filename'])
        for drawing_id, data in drawings.items()
    ]


@app.post("/drawings", response_model=DrawingUploadResponse)
async def upload_drawing(file: UploadFile = File(...)):
    """Upload a new DXF or DWG drawing."""
    filename_lower = file.filename.lower()

    if not (filename_lower.endswith('.dxf') or filename_lower.endswith('.dwg')):
        raise HTTPException(status_code=400, detail="File must be a .dxf or .dwg file")

    # Generate unique ID
    drawing_id = uuid.uuid4().hex[:8]

    is_dwg = filename_lower.endswith('.dwg')

    if is_dwg:
        # Save DWG file temporarily
        temp_dwg_path = os.path.join(UPLOAD_DIR, f"{drawing_id}.dwg")
        with open(temp_dwg_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        # Convert to DXF
        dxf_path = os.path.join(CONVERTED_DIR, f"{drawing_id}.dxf")
        if not convert_dwg_to_dxf(temp_dwg_path, dxf_path):
            os.remove(temp_dwg_path)
            raise HTTPException(status_code=400, detail="Failed to convert DWG to DXF. Ensure ODA File Converter is installed.")

        # Load the converted DXF
        try:
            load_drawing(drawing_id, dxf_path, file.filename)
        except Exception as e:
            os.remove(temp_dwg_path)
            os.remove(dxf_path)
            raise HTTPException(status_code=400, detail=f"Failed to parse converted DXF file: {str(e)}")

        # Keep the original DWG file
        filepath = temp_dwg_path
    else:
        # Save DXF file directly
        filepath = os.path.join(UPLOAD_DIR, f"{drawing_id}.dxf")
        with open(filepath, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        # Load drawing
        try:
            load_drawing(drawing_id, filepath, file.filename)
        except Exception as e:
            os.remove(filepath)
            raise HTTPException(status_code=400, detail=f"Failed to parse DXF file: {str(e)}")

    return DrawingUploadResponse(
        id=drawing_id,
        filename=file.filename,
        message=f"Drawing uploaded successfully. Access it at /drawings/{drawing_id}"
    )


@app.delete("/drawings/{drawing_id}")
async def delete_drawing(drawing_id: str):
    """Delete a drawing."""
    if drawing_id not in drawings:
        raise HTTPException(status_code=404, detail="Drawing not found")

    # Remove from cache
    data = drawings.pop(drawing_id)

    # Remove file if it's in uploads folder
    if data['filepath'].startswith(UPLOAD_DIR):
        try:
            os.remove(data['filepath'])
        except:
            pass

    return {"message": f"Drawing '{drawing_id}' deleted"}


# ============== CORE ENDPOINTS ==============

@app.get("/drawings/{drawing_id}", response_model=DrawingSummary)
async def get_drawing_summary(drawing_id: str):
    """Get summary of the drawing."""
    data = get_drawing(drawing_id)
    doc, msp, cache = data['doc'], data['msp'], data['cache']

    overall_bbox = ezdxf_bbox.extents(msp, cache=cache)
    entity_count = len(list(msp))
    dim_count = sum(1 for e in msp if e.dxftype() == "DIMENSION")

    layouts = []
    for layout in doc.layouts:
        layout_entities = len(list(layout))
        layouts.append(LayoutInfo(
            name=layout.name,
            type="model_space" if layout.name == "Model" else "paper_space",
            entity_count=layout_entities
        ))

    return DrawingSummary(
        id=drawing_id,
        filename=data['filename'],
        units="mm",
        bounds=Bounds(
            min=Point(x=overall_bbox.extmin.x, y=overall_bbox.extmin.y, z=overall_bbox.extmin.z),
            max=Point(x=overall_bbox.extmax.x, y=overall_bbox.extmax.y, z=overall_bbox.extmax.z)
        ),
        layouts=layouts,
        layer_count=len(doc.layers),
        entity_count=entity_count,
        dimension_count=dim_count
    )


@app.get("/drawings/{drawing_id}/layouts", response_model=list[LayoutInfo])
async def get_layouts(drawing_id: str):
    """Get all layouts in the drawing."""
    data = get_drawing(drawing_id)
    doc = data['doc']

    layouts = []
    for layout in doc.layouts:
        layout_entities = len(list(layout))
        layouts.append(LayoutInfo(
            name=layout.name,
            type="model_space" if layout.name == "Model" else "paper_space",
            entity_count=layout_entities
        ))
    return layouts


@app.get("/drawings/{drawing_id}/layers", response_model=list[LayerInfo])
async def get_layers(drawing_id: str):
    """Get all layers in the drawing."""
    data = get_drawing(drawing_id)
    doc, msp = data['doc'], data['msp']

    entity_counts = count_entities_by_layer(msp)

    layers = []
    for layer in doc.layers:
        layers.append(LayerInfo(
            name=layer.dxf.name,
            color=layer.dxf.color if hasattr(layer.dxf, 'color') else 7,
            entity_count=entity_counts.get(layer.dxf.name, 0)
        ))
    return layers


@app.get("/drawings/{drawing_id}/dimensions", response_model=list[DimensionInfo])
async def get_dimensions(
    drawing_id: str,
    layer: Optional[str] = Query(None, description="Filter by layer name")
):
    """Get all dimension entities."""
    data = get_drawing(drawing_id)
    msp = data['msp']

    dimensions = []
    dim_idx = 0

    for entity in msp:
        if entity.dxftype() != "DIMENSION":
            continue

        entity_layer = entity.dxf.layer if hasattr(entity.dxf, 'layer') else "0"
        if layer and entity_layer != layer:
            continue

        dim_idx += 1

        dim_type_code = entity.dxf.dimtype if hasattr(entity.dxf, 'dimtype') else 0
        dim_types = {0: "linear", 1: "aligned", 2: "angular", 3: "diameter", 4: "radius", 5: "angular_3pt", 6: "ordinate"}
        dim_type = dim_types.get(dim_type_code & 0x0F, "unknown")

        point_from = None
        point_to = None
        midpoint = None

        try:
            p1 = entity.dxf.defpoint
            p2 = entity.dxf.defpoint2
            point_from = Point(x=p2.x, y=p2.y, z=getattr(p2, 'z', 0.0))
            point_to = Point(x=p1.x, y=p1.y, z=getattr(p1, 'z', 0.0))
            midpoint = Point(
                x=(p1.x + p2.x) / 2,
                y=(p1.y + p2.y) / 2,
                z=(getattr(p1, 'z', 0.0) + getattr(p2, 'z', 0.0)) / 2
            )
        except:
            pass

        value = 0.0
        try:
            if point_from and point_to:
                dx = point_to.x - point_from.x
                dy = point_to.y - point_from.y
                value = math.sqrt(dx*dx + dy*dy)
        except:
            pass

        display_text = None
        try:
            display_text = entity.dxf.text if entity.dxf.text else None
        except:
            pass

        dimensions.append(DimensionInfo(
            id=f"D{dim_idx:04d}",
            type=dim_type,
            value=value,
            display_text=display_text,
            point_from=point_from,
            point_to=point_to,
            midpoint=midpoint,
            layer=entity_layer
        ))

    return dimensions


@app.get("/drawings/{drawing_id}/annotations", response_model=list[AnnotationInfo])
async def get_annotations(
    drawing_id: str,
    layer: Optional[str] = Query(None, description="Filter by layer name")
):
    """Get all text annotations (TEXT and MTEXT entities)."""
    data = get_drawing(drawing_id)
    msp = data['msp']

    annotations = []
    ann_idx = 0

    for entity in msp:
        entity_type = entity.dxftype()
        if entity_type not in ("TEXT", "MTEXT"):
            continue

        entity_layer = entity.dxf.layer if hasattr(entity.dxf, 'layer') else "0"
        if layer and entity_layer != layer:
            continue

        ann_idx += 1

        content = ""
        position = Point(x=0, y=0, z=0)
        height = None

        try:
            if entity_type == "TEXT":
                content = entity.dxf.text
                pos = entity.dxf.insert
                position = Point(x=pos.x, y=pos.y, z=getattr(pos, 'z', 0.0))
                height = entity.dxf.height if hasattr(entity.dxf, 'height') else None
            else:
                content = entity.text
                pos = entity.dxf.insert
                position = Point(x=pos.x, y=pos.y, z=getattr(pos, 'z', 0.0))
                height = entity.dxf.char_height if hasattr(entity.dxf, 'char_height') else None
        except:
            continue

        annotations.append(AnnotationInfo(
            id=f"A{ann_idx:04d}",
            type=entity_type.lower(),
            content=content,
            position=position,
            height=height,
            layer=entity_layer
        ))

    return annotations


@app.get("/drawings/{drawing_id}/blocks", response_model=list[BlockInsertInfo])
async def get_blocks(
    drawing_id: str,
    layer: Optional[str] = Query(None, description="Filter by layer name")
):
    """Get all block insertions."""
    data = get_drawing(drawing_id)
    msp = data['msp']

    blocks = []
    blk_idx = 0

    for entity in msp:
        if entity.dxftype() != "INSERT":
            continue

        entity_layer = entity.dxf.layer if hasattr(entity.dxf, 'layer') else "0"
        if layer and entity_layer != layer:
            continue

        blk_idx += 1

        try:
            pos = entity.dxf.insert
            block_name = entity.dxf.name

            if block_name.startswith("*"):
                continue

            try:
                block_name.encode('utf-8')
            except UnicodeEncodeError:
                block_name = block_name.encode('utf-8', errors='replace').decode('utf-8')

            blocks.append(BlockInsertInfo(
                id=f"B{blk_idx:04d}",
                block_name=block_name,
                position=Point(x=pos.x, y=pos.y, z=getattr(pos, 'z', 0.0)),
                scale=entity.dxf.xscale if hasattr(entity.dxf, 'xscale') else 1.0,
                rotation=entity.dxf.rotation if hasattr(entity.dxf, 'rotation') else 0.0,
                layer=entity_layer
            ))
        except:
            continue

    return blocks


@app.get("/drawings/{drawing_id}/extents", response_model=ExtentsInfo)
async def get_extents(
    drawing_id: str,
    layer: Optional[str] = Query(None, description="Filter by layer name")
):
    """Get drawing extents, optionally filtered by layer."""
    data = get_drawing(drawing_id)
    msp, cache = data['msp'], data['cache']

    if layer:
        entities = [e for e in msp if hasattr(e.dxf, 'layer') and e.dxf.layer == layer]
        if not entities:
            raise HTTPException(status_code=404, detail=f"Layer '{layer}' not found or has no entities")
        bbox = ezdxf_bbox.extents(entities, cache=cache)
    else:
        bbox = ezdxf_bbox.extents(msp, cache=cache)

    if not bbox.has_data:
        raise HTTPException(status_code=404, detail="No geometry found")

    return ExtentsInfo(
        bounds=Bounds(
            min=Point(x=bbox.extmin.x, y=bbox.extmin.y, z=bbox.extmin.z),
            max=Point(x=bbox.extmax.x, y=bbox.extmax.y, z=bbox.extmax.z)
        ),
        width=bbox.size.x,
        height=bbox.size.y,
        unit="mm"
    )


@app.get("/drawings/{drawing_id}/geometry", response_model=list[GeometryInfo])
async def get_geometry(
    drawing_id: str,
    layer: Optional[str] = Query(None, description="Filter by layer name"),
    type: Optional[str] = Query(None, description="Filter by entity type (line, circle, arc)")
):
    """Get geometry entities (lines, circles, arcs)."""
    data = get_drawing(drawing_id)
    msp = data['msp']

    geometry = []
    geo_idx = 0

    for entity in msp:
        entity_type = entity.dxftype()
        if entity_type not in ("LINE", "CIRCLE", "ARC"):
            continue

        if type and entity_type.lower() != type.lower():
            continue

        entity_layer = entity.dxf.layer if hasattr(entity.dxf, 'layer') else "0"
        if layer and entity_layer != layer:
            continue

        geo_idx += 1
        geo = GeometryInfo(id=f"G{geo_idx:04d}", type=entity_type.lower(), layer=entity_layer)

        try:
            if entity_type == "LINE":
                start = entity.dxf.start
                end = entity.dxf.end
                geo.start = Point(x=start.x, y=start.y, z=getattr(start, 'z', 0.0))
                geo.end = Point(x=end.x, y=end.y, z=getattr(end, 'z', 0.0))
                dx = end.x - start.x
                dy = end.y - start.y
                geo.length = math.sqrt(dx*dx + dy*dy)

            elif entity_type == "CIRCLE":
                center = entity.dxf.center
                geo.center = Point(x=center.x, y=center.y, z=getattr(center, 'z', 0.0))
                geo.radius = entity.dxf.radius

            elif entity_type == "ARC":
                center = entity.dxf.center
                geo.center = Point(x=center.x, y=center.y, z=getattr(center, 'z', 0.0))
                geo.radius = entity.dxf.radius
        except:
            continue

        geometry.append(geo)

    return geometry


# ============== PNG EXPORT ENDPOINT ==============

def enhance_image_contrast(img):
    """Enhance image contrast to make faint CAD lines more visible."""
    from PIL import ImageEnhance, ImageOps

    # Convert to RGB if needed
    if img.mode != 'RGB':
        img = img.convert('RGB')

    # Method 1: Auto-contrast to stretch histogram
    img = ImageOps.autocontrast(img, cutoff=1)

    # Method 2: Increase contrast
    enhancer = ImageEnhance.Contrast(img)
    img = enhancer.enhance(1.5)  # 1.5x contrast

    # Method 3: Darken the image slightly (make lines darker)
    enhancer = ImageEnhance.Brightness(img)
    img = enhancer.enhance(0.95)  # Slightly darker

    return img


def draw_measurement_annotation(
    img,
    start_point: tuple[int, int],  # (x, y) in pixels
    end_point: tuple[int, int],    # (x, y) in pixels
    value: float,                   # measurement value
    unit: str = "mm",
    color: tuple = (255, 0, 0),    # Red
    line_width: int = 3
):
    """Draw a measurement annotation on an image."""
    from PIL import ImageDraw, ImageFont

    draw = ImageDraw.Draw(img)
    x1, y1 = start_point
    x2, y2 = end_point

    # Draw the main dimension line
    draw.line([(x1, y1), (x2, y2)], fill=color, width=line_width)

    # Draw end markers (perpendicular ticks)
    tick_size = 15
    dx = x2 - x1
    dy = y2 - y1
    length = math.sqrt(dx*dx + dy*dy)
    if length > 0:
        # Perpendicular direction
        px = -dy / length * tick_size
        py = dx / length * tick_size

        # Start tick
        draw.line([(x1 - px, y1 - py), (x1 + px, y1 + py)], fill=color, width=line_width)
        # End tick
        draw.line([(x2 - px, y2 - py), (x2 + px, y2 + py)], fill=color, width=line_width)

    # Draw the text label
    midx = (x1 + x2) / 2
    midy = (y1 + y2) / 2

    # Format measurement text
    if value >= 1000:
        text = f"{value/1000:.2f} m"
    else:
        text = f"{value:.0f} {unit}"

    # Try to load a font, fall back to default
    try:
        font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 20)
    except:
        font = ImageFont.load_default()

    # Get text bounding box
    bbox = draw.textbbox((0, 0), text, font=font)
    text_width = bbox[2] - bbox[0]
    text_height = bbox[3] - bbox[1]

    # Position text above the line with white background
    text_x = midx - text_width / 2
    text_y = midy - text_height - 10

    # Draw white background rectangle
    padding = 4
    draw.rectangle([
        text_x - padding, text_y - padding,
        text_x + text_width + padding, text_y + text_height + padding
    ], fill=(255, 255, 255))

    # Draw text
    draw.text((text_x, text_y), text, fill=color, font=font)

    return img


def annotate_image_with_dimensions(
    img_path: str,
    output_path: str,
    dimensions: list[dict],  # List of {start: (x,y), end: (x,y), value: float}
    img_bounds: tuple[float, float, float, float],  # (x_min, x_max, y_min, y_max) in drawing units
):
    """
    Annotate an image with dimension markers.

    Args:
        img_path: Path to source image
        output_path: Path to save annotated image
        dimensions: List of dimensions to annotate
        img_bounds: Drawing bounds corresponding to the image
    """
    from PIL import Image

    with Image.open(img_path) as img:
        img = img.convert('RGB')
        img_width, img_height = img.size
        x_min, x_max, y_min, y_max = img_bounds

        draw_width = x_max - x_min
        draw_height = y_max - y_min

        for dim in dimensions:
            # Convert drawing coordinates to pixel coordinates
            start = dim.get('start', (0, 0))
            end = dim.get('end', (0, 0))
            value = dim.get('value', 0)

            px_start = (
                int((start[0] - x_min) / draw_width * img_width),
                int((y_max - start[1]) / draw_height * img_height)  # Y inverted
            )
            px_end = (
                int((end[0] - x_min) / draw_width * img_width),
                int((y_max - end[1]) / draw_height * img_height)  # Y inverted
            )

            img = draw_measurement_annotation(img, px_start, px_end, value)

        img.save(output_path, 'PNG')
        return img.size


def detect_content_bounds(img_array, threshold=250):
    """Detect bounds of non-white content in image."""
    import numpy as np

    if len(img_array.shape) == 3:
        non_white = np.any(img_array < threshold, axis=2)
    else:
        non_white = img_array < threshold

    rows = np.any(non_white, axis=1)
    cols = np.any(non_white, axis=0)

    if np.any(rows) and np.any(cols):
        ymin, ymax = np.where(rows)[0][[0, -1]]
        xmin, xmax = np.where(cols)[0][[0, -1]]
        return (xmin, xmax, ymin, ymax)
    return None


def crop_image_to_region(
    input_path: str,
    output_path: str,
    drawing_bounds: tuple[float, float, float, float],  # (x_min, x_max, y_min, y_max) of full drawing
    region_bounds: tuple[float, float, float, float],   # (x_min, x_max, y_min, y_max) of region to crop
) -> tuple[int, int, tuple[float, float, float, float]]:
    """
    Crop an image to a specific region based on drawing coordinates.
    Automatically detects content bounds to handle LibreCAD margin padding.

    Args:
        input_path: Path to input image
        output_path: Path to save cropped image
        drawing_bounds: Full drawing bounds (x_min, x_max, y_min, y_max)
        region_bounds: Region bounds to crop (x_min, x_max, y_min, y_max)

    Returns:
        Tuple of (width, height, actual_drawing_bounds) where actual_drawing_bounds
        is (x_min, x_max, y_min, y_max) corresponding to the cropped image
    """
    from PIL import Image
    import numpy as np

    with Image.open(input_path) as img:
        img_width, img_height = img.size
        draw_x_min, draw_x_max, draw_y_min, draw_y_max = drawing_bounds
        reg_x_min, reg_x_max, reg_y_min, reg_y_max = region_bounds

        # Detect actual content bounds in the image (LibreCAD adds margins)
        arr = np.array(img)
        content_bounds = detect_content_bounds(arr)

        if content_bounds:
            cx_min, cx_max, cy_min, cy_max = content_bounds
            content_width = cx_max - cx_min
            content_height = cy_max - cy_min
        else:
            # Fallback to full image
            cx_min, cy_min = 0, 0
            content_width, content_height = img_width, img_height

        draw_width = draw_x_max - draw_x_min
        draw_height = draw_y_max - draw_y_min

        # Map drawing coordinates to content pixel coordinates
        # X maps directly, Y is inverted
        px_left = cx_min + int((reg_x_min - draw_x_min) / draw_width * content_width)
        px_right = cx_min + int((reg_x_max - draw_x_min) / draw_width * content_width)
        px_top = cy_min + int((draw_y_max - reg_y_max) / draw_height * content_height)
        px_bottom = cy_min + int((draw_y_max - reg_y_min) / draw_height * content_height)

        # Clamp to image bounds with some padding
        padding = 20
        px_left_padded = max(0, px_left - padding)
        px_right_padded = min(img_width, px_right + padding)
        px_top_padded = max(0, px_top - padding)
        px_bottom_padded = min(img_height, px_bottom + padding)

        # Ensure we have a valid crop region
        if px_right_padded <= px_left_padded or px_bottom_padded <= px_top_padded:
            # Return full image if crop region is invalid
            enhanced = enhance_image_contrast(img)
            enhanced.save(output_path, 'PNG')
            return (enhanced.size[0], enhanced.size[1], drawing_bounds)

        # Calculate the actual drawing bounds that correspond to the cropped pixels
        # Convert pixel crop bounds back to drawing coordinates
        # px = cx_min + (draw_coord - draw_x_min) / draw_width * content_width
        # Solving for draw_coord: draw_coord = draw_x_min + (px - cx_min) / content_width * draw_width
        actual_x_min = draw_x_min + (px_left_padded - cx_min) / content_width * draw_width
        actual_x_max = draw_x_min + (px_right_padded - cx_min) / content_width * draw_width
        # For Y (inverted): px = cy_min + (draw_y_max - draw_coord) / draw_height * content_height
        # Solving: draw_coord = draw_y_max - (px - cy_min) / content_height * draw_height
        actual_y_max = draw_y_max - (px_top_padded - cy_min) / content_height * draw_height
        actual_y_min = draw_y_max - (px_bottom_padded - cy_min) / content_height * draw_height

        # Crop, enhance contrast, and save
        cropped = img.crop((px_left_padded, px_top_padded, px_right_padded, px_bottom_padded))
        enhanced = enhance_image_contrast(cropped)
        enhanced.save(output_path, 'PNG')

        return (enhanced.size[0], enhanced.size[1], (actual_x_min, actual_x_max, actual_y_min, actual_y_max))


def export_with_librecad(dxf_filepath: str, output_png_path: str, width: int = 4000, height: int = 3000) -> bool:
    """
    Export DXF to PNG using LibreCAD's dxf2png command.

    This produces higher quality output than ezdxf, especially for drawings
    containing ACAD_PROXY_ENTITY entities (common in AutoCAD Architecture files).

    Args:
        dxf_filepath: Path to DXF file (must be absolute)
        output_png_path: Path for output PNG (must be absolute)
        width: Output width in pixels (default 4000)
        height: Output height in pixels (default 3000)

    Returns:
        True if successful, False otherwise
    """
    librecad = find_librecad()

    if not librecad:
        raise HTTPException(
            status_code=500,
            detail="LibreCAD not installed. Install with: brew cask install librecad (macOS) or apt install librecad (Linux)"
        )

    # LibreCAD has a bug where it prepends the input file's directory to the output path.
    # Workaround: use a temp directory for output, then move the file.
    with tempfile.TemporaryDirectory() as temp_dir:
        # LibreCAD outputs to input_dir/output_filename, so we use a simple filename
        temp_output_name = "output.png"

        cmd = [
            librecad,
            "dxf2png",
            "-o", temp_output_name,
            "-r", f"{width}x{height}",
            os.path.abspath(dxf_filepath)
        ]

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=120,
                cwd=temp_dir  # Run from temp dir to avoid path issues
            )

            # LibreCAD puts output in the input file's directory (bug)
            input_dir = os.path.dirname(os.path.abspath(dxf_filepath))
            actual_output = os.path.join(input_dir, temp_output_name)

            if os.path.exists(actual_output):
                shutil.move(actual_output, output_png_path)
                return True
            else:
                # Try expected location (in case bug is fixed)
                expected_output = os.path.join(temp_dir, temp_output_name)
                if os.path.exists(expected_output):
                    shutil.move(expected_output, output_png_path)
                    return True

                print(f"LibreCAD output not found. stderr: {result.stderr}")
                print(f"stdout: {result.stdout}")
                return False

        except subprocess.TimeoutExpired:
            print("LibreCAD conversion timed out")
            return False
        except Exception as e:
            print(f"LibreCAD error: {e}")
            return False


def export_with_ezdxf(
    doc, msp, cache,
    x_min: float, x_max: float, y_min: float, y_max: float,
    output_path: str,
    background: str = "white",
    target_width: int = 4096
) -> tuple[int, int, tuple[float, float, float, float]]:
    """
    Export region to PNG using ezdxf matplotlib backend.

    Returns:
        Tuple of (width, height, actual_bounds) where actual_bounds is
        (x_min, x_max, y_min, y_max) as actually rendered
    """
    drawing_width = x_max - x_min
    drawing_height = y_max - y_min

    # Calculate dimensions maintaining aspect ratio
    aspect_ratio = drawing_height / drawing_width
    output_width = target_width
    output_height = int(target_width * aspect_ratio)

    # Limit maximum size
    max_dimension = 16384
    if output_width > max_dimension or output_height > max_dimension:
        reduction = max_dimension / max(output_width, output_height)
        output_width = int(output_width * reduction)
        output_height = int(output_height * reduction)

    # Use high DPI for crisp output (300 DPI is print quality)
    dpi = 300
    fig_width = output_width / dpi
    fig_height = output_height / dpi

    fig = plt.figure(figsize=(fig_width, fig_height), dpi=dpi)
    ax = fig.add_axes([0, 0, 1, 1])

    if background == "black":
        ax.set_facecolor('black')
        fig.patch.set_facecolor('black')
    elif background == "transparent":
        fig.patch.set_alpha(0)
        ax.patch.set_alpha(0)
    else:
        ax.set_facecolor('white')
        fig.patch.set_facecolor('white')

    ctx = RenderContext(doc)
    out = MatplotlibBackend(ax)
    Frontend(ctx, out).draw_layout(msp, finalize=True)

    # Restore figure size after drawing (ezdxf may have changed it)
    fig.set_size_inches(fig_width, fig_height)

    # Set exact limits after drawing
    ax.set_xlim(x_min, x_max)
    ax.set_ylim(y_min, y_max)
    ax.axis('off')

    # The actual bounds are exactly what we set since we control the figure size
    actual_bounds = (x_min, x_max, y_min, y_max)

    # Save without bbox_inches='tight' to preserve exact dimensions
    fig.savefig(output_path, format='png', dpi=dpi,
                facecolor=fig.get_facecolor(), edgecolor='none')
    plt.close(fig)

    from PIL import Image
    with Image.open(output_path) as img:
        return (img.size[0], img.size[1], actual_bounds)


@app.post("/drawings/{drawing_id}/export", response_model=ExportResponse)
async def export_drawing(drawing_id: str, request: ExportRequest):
    """Export drawing or region to PNG image.

    Backend options:
    - ezdxf: Fast, but may miss some entity types (ACAD_PROXY_ENTITY, complex hatches)
    - librecad: Higher quality, renders most entities correctly (requires LibreCAD + poppler)

    Scale options:
    - scale: pixels per drawing unit (e.g., 0.1 means 1 pixel = 10 drawing units)
    - width: fixed output width in pixels (scale is calculated automatically)

    If neither is provided, defaults to width=4096 for high resolution output.
    If scale is provided, it takes precedence over width.

    The response includes the actual scale used, so you can verify resolution.
    For clear details, aim for scale >= 0.05 (1 pixel per 20mm for mm drawings).
    """
    data = get_drawing(drawing_id)
    doc, msp, cache = data['doc'], data['msp'], data['cache']
    dxf_filepath = data['filepath']

    # Determine region bounds
    if request.region:
        x_min = request.region.min.x
        x_max = request.region.max.x
        y_min = request.region.min.y
        y_max = request.region.max.y
    else:
        bbox = ezdxf_bbox.extents(msp, cache=cache)
        x_min, x_max = bbox.extmin.x, bbox.extmax.x
        y_min, y_max = bbox.extmin.y, bbox.extmax.y

    # Store original bounds before padding (for accurate coordinate mapping)
    orig_x_min, orig_x_max = x_min, x_max
    orig_y_min, orig_y_max = y_min, y_max

    # Add padding (proportional to drawing size) for visual margin
    padding = max(500, (x_max - x_min) * 0.02)
    x_min -= padding
    x_max += padding
    y_min -= padding
    y_max += padding

    drawing_width = x_max - x_min
    drawing_height = y_max - y_min

    # Calculate target dimensions
    if request.scale is not None:
        target_width = int(drawing_width * request.scale)
    elif request.width is not None:
        target_width = request.width
    else:
        target_width = 4096  # Higher default for better quality

    filename = f"{uuid.uuid4().hex[:8]}.png"
    filepath = os.path.join(EXPORT_DIR, filename)
    backend_used = request.backend.value

    if request.backend == RenderBackend.LIBRECAD:
        # Use LibreCAD for high-quality rendering
        # LibreCAD exports the full drawing, so we export first then crop if region specified
        overall_bbox = ezdxf_bbox.extents(msp, cache=cache)

        # Use large output size for detailed rendering
        librecad_width = 6000
        librecad_height = 4000

        # Export full drawing first
        temp_full_path = os.path.join(EXPORT_DIR, f"temp_{uuid.uuid4().hex[:8]}.png")
        success = export_with_librecad(dxf_filepath, temp_full_path, width=librecad_width, height=librecad_height)

        if not success:
            # Fallback to ezdxf
            backend_used = "ezdxf (fallback)"
            actual_width, actual_height, actual_bounds = export_with_ezdxf(
                doc, msp, cache,
                x_min, x_max, y_min, y_max,
                filepath,
                background=request.background,
                target_width=target_width
            )
            # Update bounds to actual rendered bounds
            x_min, x_max, y_min, y_max = actual_bounds
            drawing_width = x_max - x_min
            drawing_height = y_max - y_min
        else:
            # If region is specified, crop the image
            if request.region:
                drawing_bounds = (
                    overall_bbox.extmin.x,
                    overall_bbox.extmax.x,
                    overall_bbox.extmin.y,
                    overall_bbox.extmax.y
                )
                region_bounds = (
                    request.region.min.x,
                    request.region.max.x,
                    request.region.min.y,
                    request.region.max.y
                )
                actual_width, actual_height, actual_bounds = crop_image_to_region(
                    temp_full_path, filepath, drawing_bounds, region_bounds
                )
                # Update bounds to actual cropped bounds
                x_min, x_max, y_min, y_max = actual_bounds
                drawing_width = x_max - x_min
                drawing_height = y_max - y_min
                # Remove temp file
                try:
                    os.remove(temp_full_path)
                except:
                    pass
            else:
                # No region specified - LibreCAD renders with its own margins
                # Detect actual content bounds to compute accurate drawing bounds
                from PIL import Image
                import numpy as np
                with Image.open(temp_full_path) as img:
                    enhanced = enhance_image_contrast(img)
                    enhanced.save(filepath, 'PNG')
                    actual_width, actual_height = enhanced.size

                    # Detect content bounds to compute actual drawing bounds
                    arr = np.array(img)
                    content_bounds = detect_content_bounds(arr)

                    if content_bounds:
                        cx_min, cx_max, cy_min, cy_max = content_bounds
                        content_width = cx_max - cx_min
                        content_height = cy_max - cy_min

                        # LibreCAD renders the full modelspace - use overall bbox
                        overall_bbox = ezdxf_bbox.extents(msp, cache=cache)
                        full_draw_width = overall_bbox.extmax.x - overall_bbox.extmin.x
                        full_draw_height = overall_bbox.extmax.y - overall_bbox.extmin.y

                        # Calculate the scale LibreCAD used (pixels per drawing unit)
                        scale_x = content_width / full_draw_width
                        scale_y = content_height / full_draw_height

                        # Convert image pixel bounds back to drawing coordinates
                        # For full image: drawing bounds span from content edges to full image
                        x_min = overall_bbox.extmin.x - (cx_min / scale_x)
                        x_max = overall_bbox.extmax.x + ((actual_width - cx_max) / scale_x)
                        y_max = overall_bbox.extmax.y + (cy_min / scale_y)
                        y_min = overall_bbox.extmin.y - ((actual_height - cy_max) / scale_y)

                        drawing_width = x_max - x_min
                        drawing_height = y_max - y_min

                # Remove temp file
                try:
                    os.remove(temp_full_path)
                except:
                    pass
    else:
        # Use ezdxf matplotlib backend
        actual_width, actual_height, actual_bounds = export_with_ezdxf(
            doc, msp, cache,
            x_min, x_max, y_min, y_max,
            filepath,
            background=request.background,
            target_width=target_width
        )
        # Update bounds to actual rendered bounds
        x_min, x_max, y_min, y_max = actual_bounds
        drawing_width = x_max - x_min
        drawing_height = y_max - y_min

    # Calculate actual scale
    actual_scale = actual_width / drawing_width

    # Save metadata JSON file alongside the image
    # Use padded bounds for the image, but also include padding so callers can compute original bounds
    metadata_filename = filename.replace('.png', '.json')
    metadata_filepath = os.path.join(EXPORT_DIR, metadata_filename)
    metadata = {
        "image_width": actual_width,
        "image_height": actual_height,
        "drawing_bounds": {
            "x_min": x_min,
            "x_max": x_max,
            "y_min": y_min,
            "y_max": y_max
        },
        "padding": padding,
        "drawing_width": drawing_width,
        "drawing_height": drawing_height,
        "scale": actual_scale,
        "backend": backend_used
    }
    import json
    with open(metadata_filepath, 'w') as f:
        json.dump(metadata, f, indent=2)

    return ExportResponse(
        url=f"/exports/{filename}",
        filename=filename,
        width=actual_width,
        height=actual_height,
        scale=actual_scale,
        drawing_width=drawing_width,
        drawing_height=drawing_height,
        drawing_bounds=Bounds(
            min=Point(x=x_min, y=y_min),
            max=Point(x=x_max, y=y_max)
        ),
        backend=backend_used
    )


@app.get("/exports/{filename}")
async def get_export(filename: str):
    """Serve exported image."""
    filepath = os.path.join(EXPORT_DIR, filename)
    if not os.path.exists(filepath):
        raise HTTPException(status_code=404, detail="Export not found")
    return FileResponse(filepath, media_type="image/png")


@app.post("/drawings/{drawing_id}/regions/{region_id}/export", response_model=ExportResponse)
async def export_region(
    drawing_id: str,
    region_id: str,
    scale: Optional[float] = Query(None, description="Pixels per drawing unit"),
    width: Optional[int] = Query(None, description="Output width in pixels"),
    background: str = Query("white", description="Background color: white, black, transparent"),
    backend: RenderBackend = Query(RenderBackend.EZDXF, description="Render backend: ezdxf (fast) or librecad (high quality)")
):
    """Export a specific region by ID to PNG.

    This is a convenience endpoint that automatically uses the region's bounds.
    Use GET /drawings/{id}/regions to see available region IDs.

    Backend options:
    - ezdxf: Fast rendering, but may miss some entity types
    - librecad: Higher quality, renders hatches and proxy entities correctly
    """
    data = get_drawing(drawing_id)
    msp, cache = data['msp'], data['cache']

    # Get regions and find the requested one
    regions = detect_regions(msp, cache)
    target_region = None
    for r in regions:
        if r['id'] == region_id:
            target_region = r
            break

    if not target_region:
        available = [r['id'] for r in regions]
        raise HTTPException(
            status_code=404,
            detail=f"Region '{region_id}' not found. Available regions: {available}"
        )

    # Build export request with region bounds
    request = ExportRequest(
        scale=scale,
        width=width,
        background=background,
        region=target_region['bounds'],
        backend=backend
    )

    return await export_drawing(drawing_id, request)


@app.post("/drawings/{drawing_id}/export/annotated", response_model=AnnotatedExportResponse)
async def export_with_annotations(drawing_id: str, request: AnnotatedExportRequest):
    """Export drawing with measurement annotations overlaid.

    This endpoint first exports the drawing (or region), then draws
    measurement lines and labels at the specified coordinates.

    Use this when answering questions about dimensions - you can show
    the relevant measurements visually on the drawing.
    """
    data = get_drawing(drawing_id)
    doc, msp, cache = data['doc'], data['msp'], data['cache']
    dxf_filepath = data['filepath']

    # Determine bounds (region or full drawing)
    if request.region_id:
        regions = detect_regions(msp, cache)
        target_region = None
        for r in regions:
            if r['id'] == request.region_id:
                target_region = r
                break
        if not target_region:
            raise HTTPException(status_code=404, detail=f"Region '{request.region_id}' not found")
        bounds = target_region['bounds']
        x_min, x_max = bounds.min.x, bounds.max.x
        y_min, y_max = bounds.min.y, bounds.max.y
    else:
        bbox = ezdxf_bbox.extents(msp, cache=cache)
        x_min, x_max = bbox.extmin.x, bbox.extmax.x
        y_min, y_max = bbox.extmin.y, bbox.extmax.y

    # Add padding
    padding = max(500, (x_max - x_min) * 0.02)
    x_min -= padding
    x_max += padding
    y_min -= padding
    y_max += padding

    # First, export the base image
    base_filename = f"base_{uuid.uuid4().hex[:8]}.png"
    base_filepath = os.path.join(EXPORT_DIR, base_filename)

    if request.backend == RenderBackend.LIBRECAD:
        overall_bbox = ezdxf_bbox.extents(msp, cache=cache)
        temp_full_path = os.path.join(EXPORT_DIR, f"temp_{uuid.uuid4().hex[:8]}.png")
        success = export_with_librecad(dxf_filepath, temp_full_path, width=6000, height=4000)

        if success and request.region_id:
            # Crop to region
            drawing_bounds = (
                overall_bbox.extmin.x,
                overall_bbox.extmax.x,
                overall_bbox.extmin.y,
                overall_bbox.extmax.y
            )
            region_bounds = (x_min, x_max, y_min, y_max)
            _, _, actual_bounds = crop_image_to_region(temp_full_path, base_filepath, drawing_bounds, region_bounds)
            # Update bounds to actual cropped bounds for annotation
            x_min, x_max, y_min, y_max = actual_bounds
            try:
                os.remove(temp_full_path)
            except:
                pass
        elif success:
            # Use full image with contrast enhancement
            # LibreCAD renders with its own margins - detect content bounds
            from PIL import Image
            import numpy as np
            with Image.open(temp_full_path) as img:
                enhanced = enhance_image_contrast(img)
                enhanced.save(base_filepath, 'PNG')
                img_width, img_height = enhanced.size

                # Detect content bounds to compute actual drawing bounds
                arr = np.array(img)
                content_bounds = detect_content_bounds(arr)

                if content_bounds:
                    cx_min, cx_max, cy_min, cy_max = content_bounds
                    content_width = cx_max - cx_min
                    content_height = cy_max - cy_min

                    # LibreCAD renders the full modelspace
                    overall_bbox = ezdxf_bbox.extents(msp, cache=cache)
                    full_draw_width = overall_bbox.extmax.x - overall_bbox.extmin.x
                    full_draw_height = overall_bbox.extmax.y - overall_bbox.extmin.y

                    # Calculate the scale LibreCAD used
                    scale_x = content_width / full_draw_width
                    scale_y = content_height / full_draw_height

                    # Convert image pixel bounds back to drawing coordinates
                    x_min = overall_bbox.extmin.x - (cx_min / scale_x)
                    x_max = overall_bbox.extmax.x + ((img_width - cx_max) / scale_x)
                    y_max = overall_bbox.extmax.y + (cy_min / scale_y)
                    y_min = overall_bbox.extmin.y - ((img_height - cy_max) / scale_y)

            try:
                os.remove(temp_full_path)
            except:
                pass
        else:
            # Fallback to ezdxf
            _, _, actual_bounds = export_with_ezdxf(doc, msp, cache, x_min, x_max, y_min, y_max, base_filepath)
            x_min, x_max, y_min, y_max = actual_bounds
    else:
        _, _, actual_bounds = export_with_ezdxf(doc, msp, cache, x_min, x_max, y_min, y_max, base_filepath)
        x_min, x_max, y_min, y_max = actual_bounds

    # Now annotate with measurements
    annotated_filename = f"annotated_{uuid.uuid4().hex[:8]}.png"
    annotated_filepath = os.path.join(EXPORT_DIR, annotated_filename)

    dimensions = []
    for m in request.measurements:
        dimensions.append({
            'start': (m.start_x, m.start_y),
            'end': (m.end_x, m.end_y),
            'value': m.value
        })

    img_bounds = (x_min, x_max, y_min, y_max)
    width, height = annotate_image_with_dimensions(
        base_filepath, annotated_filepath, dimensions, img_bounds
    )

    # Clean up base image
    try:
        os.remove(base_filepath)
    except:
        pass

    return AnnotatedExportResponse(
        url=f"/exports/{annotated_filename}",
        filename=annotated_filename,
        width=width,
        height=height,
        measurements_drawn=len(dimensions)
    )


# ============== SEMANTIC ENDPOINTS ==============

@app.get("/drawings/{drawing_id}/regions", response_model=list[RegionInfo])
async def get_regions(drawing_id: str):
    """Get detected drawing regions (separate diagrams/views)."""
    data = get_drawing(drawing_id)
    msp, cache = data['msp'], data['cache']

    regions = detect_regions(msp, cache)
    result = []

    for region in regions:
        bounds = region['bounds']
        width = bounds.max.x - bounds.min.x
        height = bounds.max.y - bounds.min.y

        nearby_labels = []
        for entity in msp:
            if entity.dxftype() not in ("TEXT", "MTEXT"):
                continue
            center = get_entity_center(entity, cache)
            if is_in_bounds(center, bounds, padding=500):
                try:
                    content = entity.dxf.text if entity.dxftype() == "TEXT" else entity.text
                    if content and len(content) < 50:
                        # Sanitize content for JSON encoding
                        content = content.encode('utf-8', errors='replace').decode('utf-8')
                        nearby_labels.append(content)
                except:
                    pass

        contained_blocks = []
        for entity in msp:
            if entity.dxftype() != "INSERT":
                continue
            center = get_entity_center(entity, cache)
            if is_in_bounds(center, bounds):
                try:
                    block_name = entity.dxf.name
                    # Sanitize block name for JSON encoding
                    block_name = block_name.encode('utf-8', errors='replace').decode('utf-8')
                    if not block_name.startswith("*") and block_name not in contained_blocks:
                        contained_blocks.append(block_name)
                except:
                    pass

        result.append(RegionInfo(
            id=region['id'],
            bounds=bounds,
            width=width,
            height=height,
            area=width * height / 1_000_000,
            entity_count=region['entity_count'],
            nearby_labels=nearby_labels[:10],
            contained_blocks=contained_blocks[:20]
        ))

    return result


@app.get("/drawings/{drawing_id}/spaces", response_model=list[SpaceInfo])
async def get_spaces(drawing_id: str):
    """Get identified spaces/rooms based on labels and fixtures."""
    data = get_drawing(drawing_id)
    msp = data['msp']

    spaces = []
    space_idx = 0

    room_keywords = ["ROOM", "BATHROOM", "KITCHEN", "BEDROOM", "LIVING", "DINING",
                     "GARAGE", "OFFICE", "TOILET", "WC", "HALL", "CORRIDOR"]

    for entity in msp:
        if entity.dxftype() not in ("TEXT", "MTEXT"):
            continue

        try:
            content = entity.dxf.text if entity.dxftype() == "TEXT" else entity.text
            content_upper = content.upper()

            is_room = any(keyword in content_upper for keyword in room_keywords)
            if not is_room:
                continue

            space_idx += 1
            pos = entity.dxf.insert

            fixtures = []
            fixture_keywords = ["TOILET", "BASIN", "SINK", "SHOWER", "TUB", "DOOR", "WINDOW"]

            for block_entity in msp:
                if block_entity.dxftype() != "INSERT":
                    continue
                try:
                    block_pos = block_entity.dxf.insert
                    dist = math.sqrt((block_pos.x - pos.x)**2 + (block_pos.y - pos.y)**2)
                    if dist < 5000:
                        block_name = block_entity.dxf.name.upper()
                        for kw in fixture_keywords:
                            if kw in block_name and block_name not in fixtures:
                                fixtures.append(block_entity.dxf.name)
                except:
                    pass

            estimated_size = 3000
            bounds = Bounds(
                min=Point(x=pos.x - estimated_size, y=pos.y - estimated_size),
                max=Point(x=pos.x + estimated_size, y=pos.y + estimated_size)
            )

            spaces.append(SpaceInfo(
                id=f"S{space_idx:03d}",
                name=content,
                confidence=0.7,
                source="text_label",
                bounds=bounds,
                width=estimated_size * 2,
                height=estimated_size * 2,
                area=(estimated_size * 2) ** 2 / 1_000_000,
                fixtures=fixtures[:10]
            ))
        except:
            continue

    return spaces


@app.get("/drawings/{drawing_id}/building", response_model=BuildingSummary)
async def get_building_summary(drawing_id: str):
    """Get overall building summary with floor information."""
    data = get_drawing(drawing_id)
    doc, msp, cache = data['doc'], data['msp'], data['cache']

    regions = detect_regions(msp, cache)

    floors = []
    sorted_regions = sorted(regions, key=lambda r: r['bounds'].min.y)

    floor_groups = []
    current_group = []

    for i, region in enumerate(sorted_regions):
        if not current_group:
            current_group.append(region)
        else:
            prev_max_y = max(r['bounds'].max.y for r in current_group)
            if region['bounds'].min.y > prev_max_y + 5000:
                floor_groups.append(current_group)
                current_group = [region]
            else:
                current_group.append(region)

    if current_group:
        floor_groups.append(current_group)

    floor_names = ["Ground Floor", "First Floor", "Second Floor", "Third Floor", "Roof"]
    for i, group in enumerate(floor_groups):
        all_min_x = min(r['bounds'].min.x for r in group)
        all_max_x = max(r['bounds'].max.x for r in group)
        all_min_y = min(r['bounds'].min.y for r in group)
        all_max_y = max(r['bounds'].max.y for r in group)

        space_names = []
        for region in group:
            space_names.extend(region.get('nearby_labels', [])[:5])

        floor_name = floor_names[i] if i < len(floor_names) else f"Floor {i+1}"

        floors.append(FloorInfo(
            name=floor_name,
            bounds=Bounds(
                min=Point(x=all_min_x, y=all_min_y),
                max=Point(x=all_max_x, y=all_max_y)
            ),
            width=all_max_x - all_min_x,
            height=all_max_y - all_min_y,
            spaces=space_names[:10]
        ))

    wall_entities = [e for e in msp if hasattr(e.dxf, 'layer') and e.dxf.layer == 'WALL']
    if wall_entities:
        wall_bbox = ezdxf_bbox.extents(wall_entities, cache=cache)
        overall_width = wall_bbox.size.x
        overall_height = wall_bbox.size.y
    else:
        overall_bbox = ezdxf_bbox.extents(msp, cache=cache)
        overall_width = overall_bbox.size.x
        overall_height = overall_bbox.size.y

    return BuildingSummary(
        floors=floors,
        overall_width=overall_width,
        overall_height=overall_height,
        unit="mm"
    )


@app.post("/drawings/{drawing_id}/query/point", response_model=PointQueryResult)
async def query_point(drawing_id: str, query: PointQuery):
    """Query entities near a specific point."""
    data = get_drawing(drawing_id)
    msp, cache = data['msp'], data['cache']

    nearby_texts = []
    nearby_blocks = []
    nearby_dimensions = []

    for entity in msp:
        center = get_entity_center(entity, cache)
        if not center:
            continue

        dist = math.sqrt((center[0] - query.x)**2 + (center[1] - query.y)**2)
        if dist > query.radius:
            continue

        entity_type = entity.dxftype()

        if entity_type in ("TEXT", "MTEXT"):
            try:
                content = entity.dxf.text if entity_type == "TEXT" else entity.text
                nearby_texts.append(content)
            except:
                pass

        elif entity_type == "INSERT":
            try:
                block_name = entity.dxf.name
                if not block_name.startswith("*"):
                    nearby_blocks.append(block_name)
            except:
                pass

        elif entity_type == "DIMENSION":
            try:
                p1 = entity.dxf.defpoint
                p2 = entity.dxf.defpoint2
                dx = p1.x - p2.x
                dy = p1.y - p2.y
                value = math.sqrt(dx*dx + dy*dy)
                nearby_dimensions.append(DimensionInfo(
                    id="",
                    type="linear",
                    value=value,
                    layer=entity.dxf.layer
                ))
            except:
                pass

    return PointQueryResult(
        nearby_texts=nearby_texts[:20],
        nearby_blocks=nearby_blocks[:20],
        nearby_dimensions=nearby_dimensions[:10]
    )


# ============== MEASUREMENTS QUERY ENDPOINT ==============

def compute_dimension_orientation(point_from: Point, point_to: Point) -> str:
    """Determine if a dimension is horizontal, vertical, or diagonal."""
    if point_from is None or point_to is None:
        return "unknown"

    dx = abs(point_to.x - point_from.x)
    dy = abs(point_to.y - point_from.y)

    # If one direction is much larger than the other (5x), classify accordingly
    if dx > dy * 5:
        return "horizontal"
    elif dy > dx * 5:
        return "vertical"
    else:
        return "diagonal"


def is_point_in_bounds(point: Point, bounds: MeasurementFilterBounds, padding: float = 0) -> bool:
    """Check if a point is within the specified bounds."""
    if point is None:
        return False
    return (bounds.min.x - padding <= point.x <= bounds.max.x + padding and
            bounds.min.y - padding <= point.y <= bounds.max.y + padding)


def get_color_tuple(color_name: str) -> tuple:
    """Convert color name to RGB tuple."""
    colors = {
        "red": (255, 0, 0),
        "blue": (0, 0, 255),
        "green": (0, 128, 0),
        "orange": (255, 165, 0),
        "purple": (128, 0, 128),
        "cyan": (0, 255, 255),
        "magenta": (255, 0, 255),
        "yellow": (255, 255, 0),
        "black": (0, 0, 0),
    }
    return colors.get(color_name.lower(), (255, 0, 0))


@app.post("/drawings/{drawing_id}/measurements/query", response_model=MeasurementsQueryResponse)
async def query_measurements(drawing_id: str, request: MeasurementsQueryRequest):
    """
    Query dimensions with filters and get an annotated image showing the results.

    This endpoint is designed for LLM consumption - it allows flexible filtering
    of dimensions and returns both structured data and a visual representation.

    ## Filters

    - **min_value/max_value**: Filter by dimension value range (in drawing units, typically mm)
    - **orientation**: Filter by direction - "horizontal", "vertical", or "diagonal"
    - **layers**: Filter by layer names (e.g., ["DIM", "DIMENSIONS"])
    - **region_id**: Limit to dimensions within a detected region (use GET /regions first)
    - **bounds**: Limit to dimensions within a spatial bounding box

    ## Output Options

    - **include_image**: Whether to generate an annotated image (default: true)
    - **image_format**: "base64" (embedded in response) or "url" (separate fetch required)
    - **image_width**: Output image width in pixels (default: 2000)
    - **highlight_color**: Color for dimension markers (red, blue, green, etc.)
    - **background**: Image background (white, black, transparent)
    - **backend**: Render backend (ezdxf or librecad)

    ## Response

    Returns matched dimensions with their values, positions, and orientations,
    plus statistics (min, max, average, total) and optionally an annotated image
    with the queried dimensions highlighted.

    ## Example Use Cases

    1. "What are the bathroom dimensions?" - Filter by bounds from /spaces endpoint
    2. "Show all dimensions over 3 meters" - Use min_value: 3000
    3. "What are the horizontal dimensions?" - Use orientation: "horizontal"
    4. "Show dimensions in the ground floor plan" - Use region_id from /regions
    """
    import base64

    data = get_drawing(drawing_id)
    doc, msp, cache = data['doc'], data['msp'], data['cache']
    dxf_filepath = data['filepath']

    # Set default options if not provided
    filters = request.filters or MeasurementFilters()
    output = request.output or MeasurementOutputOptions()

    # Track which filters are applied
    filters_applied = []

    # If region_id is specified, get its bounds
    region_bounds = None
    if filters.region_id:
        regions = detect_regions(msp, cache)
        for r in regions:
            if r['id'] == filters.region_id:
                region_bounds = r['bounds']
                filters_applied.append(f"region_id={filters.region_id}")
                break
        if not region_bounds:
            available = [r['id'] for r in regions]
            raise HTTPException(
                status_code=404,
                detail=f"Region '{filters.region_id}' not found. Available: {available}"
            )

    # Get all dimensions first
    all_dimensions = []
    dim_idx = 0

    for entity in msp:
        if entity.dxftype() != "DIMENSION":
            continue

        entity_layer = entity.dxf.layer if hasattr(entity.dxf, 'layer') else "0"
        dim_idx += 1

        dim_type_code = entity.dxf.dimtype if hasattr(entity.dxf, 'dimtype') else 0
        dim_types = {0: "linear", 1: "aligned", 2: "angular", 3: "diameter", 4: "radius", 5: "angular_3pt", 6: "ordinate"}
        dim_type = dim_types.get(dim_type_code & 0x0F, "unknown")

        point_from = None
        point_to = None
        midpoint = None

        try:
            p1 = entity.dxf.defpoint
            p2 = entity.dxf.defpoint2
            point_from = Point(x=p2.x, y=p2.y, z=getattr(p2, 'z', 0.0))
            point_to = Point(x=p1.x, y=p1.y, z=getattr(p1, 'z', 0.0))
            midpoint = Point(
                x=(p1.x + p2.x) / 2,
                y=(p1.y + p2.y) / 2,
                z=(getattr(p1, 'z', 0.0) + getattr(p2, 'z', 0.0)) / 2
            )
        except:
            pass

        value = 0.0
        try:
            if point_from and point_to:
                dx = point_to.x - point_from.x
                dy = point_to.y - point_from.y
                value = math.sqrt(dx*dx + dy*dy)
        except:
            pass

        display_text = None
        try:
            display_text = entity.dxf.text if entity.dxf.text else None
        except:
            pass

        all_dimensions.append(DimensionInfo(
            id=f"D{dim_idx:04d}",
            type=dim_type,
            value=value,
            display_text=display_text,
            point_from=point_from,
            point_to=point_to,
            midpoint=midpoint,
            layer=entity_layer
        ))

    total_dimensions = len(all_dimensions)

    # Apply filters
    matched_dimensions = all_dimensions.copy()

    # Filter by layer
    if filters.layers:
        matched_dimensions = [d for d in matched_dimensions if d.layer in filters.layers]
        filters_applied.append(f"layers={filters.layers}")

    # Filter by value range
    if filters.min_value is not None:
        matched_dimensions = [d for d in matched_dimensions if d.value >= filters.min_value]
        filters_applied.append(f"min_value={filters.min_value}")

    if filters.max_value is not None:
        matched_dimensions = [d for d in matched_dimensions if d.value <= filters.max_value]
        filters_applied.append(f"max_value={filters.max_value}")

    # Filter by orientation
    if filters.orientation:
        def matches_orientation(dim):
            orientation = compute_dimension_orientation(dim.point_from, dim.point_to)
            return orientation == filters.orientation.lower()

        matched_dimensions = [d for d in matched_dimensions if matches_orientation(d)]
        filters_applied.append(f"orientation={filters.orientation}")

    # Filter by region bounds
    if region_bounds:
        def in_region(dim):
            if dim.midpoint is None:
                return False
            return (region_bounds.min.x <= dim.midpoint.x <= region_bounds.max.x and
                    region_bounds.min.y <= dim.midpoint.y <= region_bounds.max.y)

        matched_dimensions = [d for d in matched_dimensions if in_region(d)]

    # Filter by explicit bounds
    if filters.bounds:
        def in_bounds(dim):
            if dim.midpoint is None:
                return False
            return is_point_in_bounds(dim.midpoint, filters.bounds)

        matched_dimensions = [d for d in matched_dimensions if in_bounds(d)]
        filters_applied.append(f"bounds=({filters.bounds.min.x},{filters.bounds.min.y})-({filters.bounds.max.x},{filters.bounds.max.y})")

    # Compute statistics
    values = [d.value for d in matched_dimensions if d.value > 0]
    statistics = MeasurementStatistics(
        count=len(matched_dimensions),
        min_value=min(values) if values else None,
        max_value=max(values) if values else None,
        average=sum(values) / len(values) if values else None,
        total=sum(values) if values else None
    )

    # Generate image if requested
    image_output = None
    if output.include_image and matched_dimensions:
        # Determine bounds for the image
        if region_bounds:
            x_min, x_max = region_bounds.min.x, region_bounds.max.x
            y_min, y_max = region_bounds.min.y, region_bounds.max.y
        elif filters.bounds:
            x_min, x_max = filters.bounds.min.x, filters.bounds.max.x
            y_min, y_max = filters.bounds.min.y, filters.bounds.max.y
        else:
            # Use the bounds of matched dimensions with padding
            all_x = []
            all_y = []
            for d in matched_dimensions:
                if d.point_from:
                    all_x.append(d.point_from.x)
                    all_y.append(d.point_from.y)
                if d.point_to:
                    all_x.append(d.point_to.x)
                    all_y.append(d.point_to.y)

            if all_x and all_y:
                x_min, x_max = min(all_x), max(all_x)
                y_min, y_max = min(all_y), max(all_y)
            else:
                # Fallback to full drawing
                bbox = ezdxf_bbox.extents(msp, cache=cache)
                x_min, x_max = bbox.extmin.x, bbox.extmax.x
                y_min, y_max = bbox.extmin.y, bbox.extmax.y

        # Add padding
        padding = max(500, (x_max - x_min) * 0.1)
        x_min -= padding
        x_max += padding
        y_min -= padding
        y_max += padding

        drawing_width = x_max - x_min
        drawing_height = y_max - y_min

        # Export base image
        base_filename = f"base_{uuid.uuid4().hex[:8]}.png"
        base_filepath = os.path.join(EXPORT_DIR, base_filename)

        if output.backend == RenderBackend.LIBRECAD:
            overall_bbox = ezdxf_bbox.extents(msp, cache=cache)
            temp_full_path = os.path.join(EXPORT_DIR, f"temp_{uuid.uuid4().hex[:8]}.png")
            success = export_with_librecad(dxf_filepath, temp_full_path, width=6000, height=4000)

            if success:
                drawing_bounds = (
                    overall_bbox.extmin.x, overall_bbox.extmax.x,
                    overall_bbox.extmin.y, overall_bbox.extmax.y
                )
                region_crop_bounds = (x_min, x_max, y_min, y_max)
                _, _, actual_bounds = crop_image_to_region(temp_full_path, base_filepath, drawing_bounds, region_crop_bounds)
                # Update bounds to actual cropped bounds
                x_min, x_max, y_min, y_max = actual_bounds
                drawing_width = x_max - x_min
                drawing_height = y_max - y_min
                try:
                    os.remove(temp_full_path)
                except:
                    pass
            else:
                # Fallback to ezdxf
                _, _, actual_bounds = export_with_ezdxf(doc, msp, cache, x_min, x_max, y_min, y_max, base_filepath,
                                  background=output.background, target_width=output.image_width)
                x_min, x_max, y_min, y_max = actual_bounds
                drawing_width = x_max - x_min
                drawing_height = y_max - y_min
        else:
            _, _, actual_bounds = export_with_ezdxf(doc, msp, cache, x_min, x_max, y_min, y_max, base_filepath,
                              background=output.background, target_width=output.image_width)
            x_min, x_max, y_min, y_max = actual_bounds
            drawing_width = x_max - x_min
            drawing_height = y_max - y_min

        # Annotate with matched dimensions
        annotated_filename = f"query_{uuid.uuid4().hex[:8]}.png"
        annotated_filepath = os.path.join(EXPORT_DIR, annotated_filename)

        dimensions_to_draw = []
        for d in matched_dimensions:
            if d.point_from and d.point_to:
                dimensions_to_draw.append({
                    'start': (d.point_from.x, d.point_from.y),
                    'end': (d.point_to.x, d.point_to.y),
                    'value': d.value
                })

        img_bounds = (x_min, x_max, y_min, y_max)

        # Custom annotation with specified color
        from PIL import Image
        with Image.open(base_filepath) as img:
            img = img.convert('RGB')
            img_width, img_height = img.size

            color = get_color_tuple(output.highlight_color)

            for dim in dimensions_to_draw:
                start = dim['start']
                end = dim['end']
                value = dim['value']

                # Convert drawing coordinates to pixel coordinates
                px_start = (
                    int((start[0] - x_min) / drawing_width * img_width),
                    int((y_max - start[1]) / drawing_height * img_height)
                )
                px_end = (
                    int((end[0] - x_min) / drawing_width * img_width),
                    int((y_max - end[1]) / drawing_height * img_height)
                )

                img = draw_measurement_annotation(img, px_start, px_end, value, color=color)

            img.save(annotated_filepath, 'PNG')
            actual_width, actual_height = img.size

        # Clean up base image
        try:
            os.remove(base_filepath)
        except:
            pass

        # Calculate actual scale
        actual_scale = actual_width / drawing_width

        if output.image_format == "base64":
            # Read and encode image
            with open(annotated_filepath, 'rb') as f:
                image_data = base64.b64encode(f.read()).decode('utf-8')

            image_output = ImageOutput(
                format="base64",
                data=image_data,
                width=actual_width,
                height=actual_height,
                scale=actual_scale
            )

            # Clean up file since we've encoded it
            try:
                os.remove(annotated_filepath)
            except:
                pass
        else:
            image_output = ImageOutput(
                format="url",
                url=f"/exports/{annotated_filename}",
                width=actual_width,
                height=actual_height,
                scale=actual_scale
            )

    return MeasurementsQueryResponse(
        query_summary=QuerySummary(
            total_dimensions=total_dimensions,
            matched_dimensions=len(matched_dimensions),
            filters_applied=filters_applied
        ),
        dimensions=matched_dimensions,
        statistics=statistics,
        image=image_output
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=3000)
