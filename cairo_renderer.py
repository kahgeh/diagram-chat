"""
Cairo-based DXF renderer for accurate SVG/PNG output.

This module provides a pure Python renderer using PyCairo that handles
DXF entities with high accuracy, similar to cad-viewer's approach.

Supported entity types:
- LINE, LWPOLYLINE, POLYLINE, SPLINE
- CIRCLE, ARC, ELLIPSE
- TEXT, MTEXT
- INSERT (block references with explosion)
- DIMENSION
- HATCH (pattern fills with line-based rendering)
- POINT
"""
import cairo
import math
from dataclasses import dataclass, field
from typing import Optional, Callable
from enum import Enum
import ezdxf
from ezdxf.entities import DXFEntity
from ezdxf import bbox as ezdxf_bbox


class LineType(Enum):
    """Common CAD line types."""
    CONTINUOUS = "CONTINUOUS"
    DASHED = "DASHED"
    DOTTED = "DOTTED"
    DASHDOT = "DASHDOT"
    CENTER = "CENTER"
    HIDDEN = "HIDDEN"


@dataclass
class RenderStyle:
    """Style settings for rendering entities."""
    stroke_color: tuple[float, float, float] = (0.0, 0.0, 0.0)  # RGB 0-1
    stroke_width: float = 1.0
    fill_color: Optional[tuple[float, float, float]] = None
    fill_alpha: float = 1.0
    line_type: LineType = LineType.CONTINUOUS


@dataclass
class RenderBounds:
    """Bounding box for rendering."""
    x_min: float
    x_max: float
    y_min: float
    y_max: float

    @property
    def width(self) -> float:
        return self.x_max - self.x_min

    @property
    def height(self) -> float:
        return self.y_max - self.y_min

    @property
    def center(self) -> tuple[float, float]:
        return ((self.x_min + self.x_max) / 2, (self.y_min + self.y_max) / 2)

    def expand(self, padding: float) -> "RenderBounds":
        """Return expanded bounds with padding."""
        return RenderBounds(
            self.x_min - padding,
            self.x_max + padding,
            self.y_min - padding,
            self.y_max + padding
        )

    def contains_point(self, x: float, y: float, padding: float = 0) -> bool:
        """Check if point is within bounds."""
        return (self.x_min - padding <= x <= self.x_max + padding and
                self.y_min - padding <= y <= self.y_max + padding)


# =============================================================================
# Hatch Pattern Rendering Helpers
# =============================================================================

def _point_in_polygon(x: float, y: float, polygon: list[tuple[float, float]]) -> bool:
    """
    Check if a point is inside a polygon using ray casting algorithm.

    Args:
        x, y: Point coordinates
        polygon: List of (x, y) vertices

    Returns:
        True if point is inside polygon
    """
    n = len(polygon)
    if n < 3:
        return False

    inside = False
    j = n - 1

    for i in range(n):
        xi, yi = polygon[i]
        xj, yj = polygon[j]

        if ((yi > y) != (yj > y)) and (x < (xj - xi) * (y - yi) / (yj - yi + 1e-10) + xi):
            inside = not inside
        j = i

    return inside


def _line_segment_intersection(
    p1: tuple[float, float], p2: tuple[float, float],
    p3: tuple[float, float], p4: tuple[float, float]
) -> tuple[float, float] | None:
    """
    Find intersection point of two line segments.

    Args:
        p1, p2: First line segment endpoints
        p3, p4: Second line segment endpoints

    Returns:
        Intersection point (x, y) or None if no intersection
    """
    x1, y1 = p1
    x2, y2 = p2
    x3, y3 = p3
    x4, y4 = p4

    denom = (x1 - x2) * (y3 - y4) - (y1 - y2) * (x3 - x4)
    if abs(denom) < 1e-10:
        return None  # Lines are parallel

    t = ((x1 - x3) * (y3 - y4) - (y1 - y3) * (x3 - x4)) / denom
    u = -((x1 - x2) * (y1 - y3) - (y1 - y2) * (x1 - x3)) / denom

    if 0 <= t <= 1 and 0 <= u <= 1:
        x = x1 + t * (x2 - x1)
        y = y1 + t * (y2 - y1)
        return (x, y)

    return None


def _clip_line_to_polygon(
    line_start: tuple[float, float],
    line_end: tuple[float, float],
    polygon: list[tuple[float, float]]
) -> list[tuple[tuple[float, float], tuple[float, float]]]:
    """
    Clip a line segment to a polygon boundary.

    Uses a simplified approach: find all intersection points with polygon edges,
    then return segments that are inside the polygon.

    Args:
        line_start: Start point of line (x, y)
        line_end: End point of line (x, y)
        polygon: List of polygon vertices

    Returns:
        List of (start, end) tuples for line segments inside polygon
    """
    if len(polygon) < 3:
        return []

    # Collect all intersection points with polygon edges
    intersections = []
    n = len(polygon)

    for i in range(n):
        p3 = polygon[i]
        p4 = polygon[(i + 1) % n]

        intersection = _line_segment_intersection(line_start, line_end, p3, p4)
        if intersection:
            # Calculate parameter t along the line
            dx = line_end[0] - line_start[0]
            dy = line_end[1] - line_start[1]
            if abs(dx) > abs(dy):
                t = (intersection[0] - line_start[0]) / (dx + 1e-10)
            else:
                t = (intersection[1] - line_start[1]) / (dy + 1e-10)
            intersections.append((t, intersection))

    # Add start and end points if they're inside polygon
    start_inside = _point_in_polygon(line_start[0], line_start[1], polygon)
    end_inside = _point_in_polygon(line_end[0], line_end[1], polygon)

    if start_inside:
        intersections.append((0.0, line_start))
    if end_inside:
        intersections.append((1.0, line_end))

    # Sort by parameter t
    intersections.sort(key=lambda x: x[0])

    # Remove duplicates (points very close together)
    unique_intersections = []
    for t, pt in intersections:
        if not unique_intersections or abs(t - unique_intersections[-1][0]) > 1e-6:
            unique_intersections.append((t, pt))

    # Build segments: pairs of consecutive points where midpoint is inside polygon
    segments = []
    for i in range(len(unique_intersections) - 1):
        t1, p1 = unique_intersections[i]
        t2, p2 = unique_intersections[i + 1]

        # Check if midpoint is inside polygon
        mid_x = (p1[0] + p2[0]) / 2
        mid_y = (p1[1] + p2[1]) / 2

        if _point_in_polygon(mid_x, mid_y, polygon):
            segments.append((p1, p2))

    return segments


def _generate_hatch_lines(
    bbox: RenderBounds,
    angle_deg: float,
    spacing: float,
    base_point: tuple[float, float] = (0, 0),
    dash_pattern: list[float] | None = None
) -> list[tuple[tuple[float, float], tuple[float, float], list[float] | None]]:
    """
    Generate parallel lines covering a bounding box for hatch pattern.

    Args:
        bbox: Bounding box to cover
        angle_deg: Angle of lines in degrees (0 = horizontal, 90 = vertical)
        spacing: Distance between parallel lines
        base_point: Origin point for the line family
        dash_pattern: Optional dash pattern [dash, gap, dash, gap, ...]

    Returns:
        List of ((x1, y1), (x2, y2), dash_pattern) tuples
    """
    if spacing <= 0:
        spacing = 1.0  # Prevent division by zero

    angle_rad = math.radians(angle_deg)

    # Direction vector along line
    dx = math.cos(angle_rad)
    dy = math.sin(angle_rad)

    # Perpendicular offset direction (for spacing between lines)
    perp_dx = -dy
    perp_dy = dx

    # Calculate diagonal of bounding box (maximum extent needed)
    bbox_diagonal = math.sqrt(bbox.width ** 2 + bbox.height ** 2)

    # Calculate center of bounding box
    center_x = (bbox.x_min + bbox.x_max) / 2
    center_y = (bbox.y_min + bbox.y_max) / 2

    # Number of lines needed to cover the entire bbox
    num_lines = int(bbox_diagonal / spacing) + 2

    lines = []
    for i in range(-num_lines, num_lines + 1):
        offset = i * spacing

        # Line passes through base_point offset in perpendicular direction
        # Adjusted to be relative to bbox center for better coverage
        px = center_x + offset * perp_dx
        py = center_y + offset * perp_dy

        # Extend line to cover entire bbox
        x1 = px - bbox_diagonal * dx
        y1 = py - bbox_diagonal * dy
        x2 = px + bbox_diagonal * dx
        y2 = py + bbox_diagonal * dy

        lines.append(((x1, y1), (x2, y2), dash_pattern))

    return lines


def _get_polygon_bbox(polygon: list[tuple[float, float]]) -> RenderBounds | None:
    """Get bounding box of a polygon."""
    if not polygon:
        return None

    xs = [p[0] for p in polygon]
    ys = [p[1] for p in polygon]

    return RenderBounds(min(xs), max(xs), min(ys), max(ys))


# Standard hatch pattern definitions (angle, spacing in drawing units)
# These are fallback definitions for common patterns
STANDARD_HATCH_PATTERNS = {
    # ANSI patterns (iron, steel, brass, etc.)
    "ANSI31": [(45, 3.175, None)],  # 45° diagonal lines
    "ANSI32": [(45, 9.525, None)],  # Wider 45° diagonal
    "ANSI33": [(45, 6.35, None)],   # Medium 45° diagonal
    "ANSI34": [(45, 19.05, None)],  # Wide 45° diagonal
    "ANSI35": [(0, 3.175, None)],   # Horizontal lines
    "ANSI36": [(45, 3.175, None), (135, 3.175, None)],  # Crosshatch
    "ANSI37": [(45, 3.175, None), (135, 3.175, None)],  # Crosshatch
    "ANSI38": [(45, 3.175, None), (135, 3.175, None)],  # Crosshatch

    # Architectural patterns
    "AR-B816": [(0, 200, None), (90, 300, None)],  # Brick pattern
    "AR-B816C": [(0, 200, None), (90, 300, None)],
    "AR-B88": [(0, 200, None), (90, 200, None)],
    "AR-BRELM": [(0, 200, None)],
    "AR-BRSTD": [(0, 200, None)],
    "AR-CONC": [(45, 100, None), (135, 150, None)],  # Simplified concrete
    "AR-HBONE": [(45, 150, None), (135, 150, None)],  # Herringbone
    "AR-PARQ1": [(0, 300, None), (90, 300, None)],
    "AR-RROOF": [(0, 300, None)],  # Roof shingles
    "AR-RSHKE": [(0, 250, None)],  # Roof shakes
    "AR-SAND": [(45, 50, [25, 25])],  # Sand (dashed)

    # Other common patterns
    "BRICK": [(0, 200, None), (90, 300, None)],
    "CROSS": [(0, 100, None), (90, 100, None)],
    "DASH": [(0, 100, [50, 50])],
    "DOTS": [(0, 50, [0, 25])],
    "GRASS": [(90, 75, [100, 50])],
    "HONEY": [(0, 100, None), (60, 100, None), (120, 100, None)],
    "HOUND": [(0, 100, None), (90, 100, None)],
    "LINE": [(0, 100, None)],
    "MUDST": [(0, 150, [100, 50, 25, 50])],
    "NET": [(0, 100, None), (90, 100, None)],
    "NET3": [(0, 100, None), (60, 100, None), (120, 100, None)],
    "PLAST": [(0, 75, [50, 25])],
    "PLASTI": [(0, 75, [50, 25])],
    "SACNCR": [(45, 50, None)],
    "SQUARE": [(0, 100, None), (90, 100, None)],
    "STARS": [(0, 50, None), (60, 50, None), (120, 50, None)],
    "STEEL": [(45, 75, None)],
    "SWAMP": [(0, 150, [100, 50]), (90, 150, [100, 50])],
    "TRANS": [(0, 50, None)],
    "TRIANG": [(0, 100, None), (60, 100, None), (120, 100, None)],
    "ZIGZAG": [(0, 100, [50, 50, 50, 50])],
}


# AutoCAD Color Index (ACI) to RGB mapping
# Standard 256-color palette (subset of most common colors)
ACI_COLORS = {
    0: (0, 0, 0),         # ByBlock
    1: (255, 0, 0),       # Red
    2: (255, 255, 0),     # Yellow
    3: (0, 255, 0),       # Green
    4: (0, 255, 255),     # Cyan
    5: (0, 0, 255),       # Blue
    6: (255, 0, 255),     # Magenta
    7: (0, 0, 0),         # White/Black - using black for white background
    8: (128, 128, 128),   # Dark gray
    9: (192, 192, 192),   # Light gray
    10: (255, 0, 0),
    11: (255, 127, 127),
    12: (204, 0, 0),
    13: (204, 102, 102),
    14: (153, 0, 0),
    15: (153, 76, 76),
    16: (127, 0, 0),
    17: (127, 63, 63),
    18: (76, 0, 0),
    19: (76, 38, 38),
    20: (255, 63, 0),
    21: (255, 159, 127),
    22: (204, 51, 0),
    23: (204, 127, 102),
    24: (153, 38, 0),
    25: (153, 95, 76),
    30: (255, 127, 0),
    40: (255, 191, 0),
    50: (255, 255, 0),
    60: (191, 255, 0),
    70: (127, 255, 0),
    80: (63, 255, 0),
    90: (0, 255, 0),
    100: (0, 255, 63),
    110: (0, 255, 127),
    120: (0, 255, 191),
    130: (0, 255, 255),
    140: (0, 191, 255),
    150: (0, 127, 255),
    160: (0, 63, 255),
    170: (0, 0, 255),
    180: (63, 0, 255),
    190: (127, 0, 255),
    200: (191, 0, 255),
    210: (255, 0, 255),
    220: (255, 0, 191),
    230: (255, 0, 127),
    240: (255, 0, 63),
    250: (51, 51, 51),
    251: (80, 80, 80),
    252: (105, 105, 105),
    253: (130, 130, 130),
    254: (190, 190, 190),
    255: (255, 255, 255),
    256: (0, 0, 0),  # ByLayer - use black as default
}


def aci_to_rgb(aci: int) -> tuple[float, float, float]:
    """Convert AutoCAD Color Index to RGB (0-1 range)."""
    if aci in ACI_COLORS:
        r, g, b = ACI_COLORS[aci]
    else:
        # Fallback for unmapped colors - use black
        r, g, b = 0, 0, 0
    return (r / 255.0, g / 255.0, b / 255.0)


def get_entity_color(entity: DXFEntity, doc) -> tuple[float, float, float]:
    """Get RGB color for an entity, resolving ByLayer/ByBlock."""
    try:
        color = entity.dxf.color if hasattr(entity.dxf, 'color') else 256

        # ByLayer (256) - get color from layer
        if color == 256:
            layer_name = entity.dxf.layer if hasattr(entity.dxf, 'layer') else "0"
            if layer_name in doc.layers:
                layer = doc.layers.get(layer_name)
                color = layer.dxf.color if hasattr(layer.dxf, 'color') else 7

        # ByBlock (0) - use black for now
        if color == 0:
            color = 7

        return aci_to_rgb(color)
    except:
        return (0.0, 0.0, 0.0)  # Default to black


class CairoRenderer:
    """
    Cairo-based renderer for DXF drawings.

    Renders to SVG or PNG with high accuracy.
    """

    def __init__(
        self,
        width: int,
        height: int,
        bounds: RenderBounds,
        background: str = "white",
        output_format: str = "png"
    ):
        """
        Initialize renderer.

        Args:
            width: Output width in pixels
            height: Output height in pixels
            bounds: Drawing bounds to render
            background: Background color ("white", "black", "transparent")
            output_format: "png" or "svg"
        """
        self.width = width
        self.height = height
        self.bounds = bounds
        self.background = background
        self.output_format = output_format

        # Calculate scale and transformation
        self.scale_x = width / bounds.width
        self.scale_y = height / bounds.height
        self.scale = min(self.scale_x, self.scale_y)  # Uniform scale

        # Track cumulative block scale for line width compensation
        self.block_scale_stack = [1.0]

        # Create surface based on format
        if output_format == "svg":
            self.surface = None  # Will be created when saving
            self._svg_path = None
        else:
            self.surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, width, height)

        self.ctx = cairo.Context(self.surface) if self.surface else None

        # Track rendered entities for debugging
        self.rendered_count = 0
        self.skipped_types = set()

        # Block definitions cache
        self._block_cache = {}

        if self.ctx:
            self._setup_context()

    def _setup_context(self):
        """Set up the Cairo context with proper transformation."""
        # Fill background
        if self.background == "white":
            self.ctx.set_source_rgb(1, 1, 1)
        elif self.background == "black":
            self.ctx.set_source_rgb(0, 0, 0)
        else:  # transparent
            self.ctx.set_source_rgba(0, 0, 0, 0)
        self.ctx.paint()

        # Set up transformation: DXF coordinates -> pixel coordinates
        # DXF has Y pointing up, Cairo has Y pointing down
        # Translate to center the drawing, then flip Y
        self.ctx.translate(0, self.height)
        self.ctx.scale(self.scale, -self.scale)
        self.ctx.translate(-self.bounds.x_min, -self.bounds.y_min)

        # Default stroke settings
        self.ctx.set_line_width(0.5 / self.scale)  # Thin lines
        self.ctx.set_line_cap(cairo.LINE_CAP_ROUND)
        self.ctx.set_line_join(cairo.LINE_JOIN_ROUND)

    def _to_pixel_coords(self, x: float, y: float) -> tuple[float, float]:
        """Convert DXF coordinates to pixel coordinates."""
        px = (x - self.bounds.x_min) * self.scale
        py = self.height - (y - self.bounds.y_min) * self.scale
        return (px, py)

    def _set_style(self, style: RenderStyle):
        """Apply style to context."""
        self.ctx.set_source_rgb(*style.stroke_color)
        # Compensate line width for block scale transformations
        # Block transforms scale everything including line width, so we need to
        # divide by the cumulative block scale to maintain consistent line thickness
        current_block_scale = self.block_scale_stack[-1] if self.block_scale_stack else 1.0
        self.ctx.set_line_width(style.stroke_width / self.scale / current_block_scale)

        # Apply line type (dash pattern)
        if style.line_type == LineType.DASHED:
            self.ctx.set_dash([10/self.scale, 5/self.scale])
        elif style.line_type == LineType.DOTTED:
            self.ctx.set_dash([2/self.scale, 3/self.scale])
        elif style.line_type == LineType.DASHDOT:
            self.ctx.set_dash([10/self.scale, 3/self.scale, 2/self.scale, 3/self.scale])
        elif style.line_type == LineType.CENTER:
            self.ctx.set_dash([20/self.scale, 5/self.scale, 5/self.scale, 5/self.scale])
        elif style.line_type == LineType.HIDDEN:
            self.ctx.set_dash([5/self.scale, 3/self.scale])
        else:
            self.ctx.set_dash([])  # Continuous

    def render_line(self, start: tuple[float, float], end: tuple[float, float], style: RenderStyle = None):
        """Render a line segment."""
        if style:
            self._set_style(style)

        self.ctx.move_to(start[0], start[1])
        self.ctx.line_to(end[0], end[1])
        self.ctx.stroke()
        self.rendered_count += 1

    def render_polyline(self, points: list[tuple[float, float]], closed: bool = False, style: RenderStyle = None):
        """Render a polyline (connected line segments)."""
        if len(points) < 2:
            return

        if style:
            self._set_style(style)

        self.ctx.move_to(points[0][0], points[0][1])
        for p in points[1:]:
            self.ctx.line_to(p[0], p[1])

        if closed:
            self.ctx.close_path()

        self.ctx.stroke()
        self.rendered_count += 1

    def render_circle(self, center: tuple[float, float], radius: float, style: RenderStyle = None):
        """Render a circle."""
        if style:
            self._set_style(style)

        # Start a new sub-path to avoid connecting from previous path position
        self.ctx.new_sub_path()
        self.ctx.arc(center[0], center[1], radius, 0, 2 * math.pi)

        if style and style.fill_color:
            self.ctx.set_source_rgba(*style.fill_color, style.fill_alpha)
            self.ctx.fill_preserve()
            self.ctx.set_source_rgb(*style.stroke_color)

        self.ctx.stroke()
        self.rendered_count += 1

    def render_arc(
        self,
        center: tuple[float, float],
        radius: float,
        start_angle: float,
        end_angle: float,
        style: RenderStyle = None
    ):
        """Render an arc. Angles in radians."""
        if style:
            self._set_style(style)

        # Start a new sub-path to avoid connecting from previous path position
        self.ctx.new_sub_path()
        # Cairo uses counter-clockwise arcs when Y points up
        # DXF uses counter-clockwise with angles from positive X axis
        self.ctx.arc(center[0], center[1], radius, start_angle, end_angle)
        self.ctx.stroke()
        self.rendered_count += 1

    def render_ellipse(
        self,
        center: tuple[float, float],
        major_axis: tuple[float, float],
        ratio: float,
        start_param: float = 0,
        end_param: float = 2 * math.pi,
        style: RenderStyle = None
    ):
        """Render an ellipse or elliptical arc."""
        if style:
            self._set_style(style)

        # Calculate ellipse parameters
        major_length = math.sqrt(major_axis[0]**2 + major_axis[1]**2)
        rotation = math.atan2(major_axis[1], major_axis[0])
        minor_length = major_length * ratio

        # Save context for transformation
        self.ctx.save()
        self.ctx.translate(center[0], center[1])
        self.ctx.rotate(rotation)
        self.ctx.scale(major_length, minor_length)

        # Start a new sub-path to avoid connecting from previous path position
        self.ctx.new_sub_path()
        # Draw as unit circle arc
        if abs(end_param - start_param) >= 2 * math.pi - 0.001:
            self.ctx.arc(0, 0, 1, 0, 2 * math.pi)
        else:
            self.ctx.arc(0, 0, 1, start_param, end_param)

        self.ctx.restore()
        self.ctx.stroke()
        self.rendered_count += 1

    def render_spline(self, control_points: list[tuple[float, float]], style: RenderStyle = None):
        """Render a spline as approximated line segments."""
        if len(control_points) < 2:
            return

        if style:
            self._set_style(style)

        # For now, just connect control points
        # TODO: Implement proper B-spline interpolation
        self.ctx.move_to(control_points[0][0], control_points[0][1])
        for p in control_points[1:]:
            self.ctx.line_to(p[0], p[1])
        self.ctx.stroke()
        self.rendered_count += 1

    def render_point(self, position: tuple[float, float], style: RenderStyle = None):
        """Render a point as a small circle."""
        if style:
            self._set_style(style)

        point_size = 2 / self.scale  # 2 pixels
        self.ctx.arc(position[0], position[1], point_size, 0, 2 * math.pi)
        self.ctx.fill()
        self.rendered_count += 1

    def render_text(
        self,
        text: str,
        position: tuple[float, float],
        height: float,
        rotation: float = 0,
        style: RenderStyle = None
    ):
        """Render text."""
        if not text:
            return

        if style:
            self.ctx.set_source_rgb(*style.stroke_color)

        self.ctx.save()
        self.ctx.translate(position[0], position[1])

        # Scale and flip for text (text needs Y pointing up in its local space)
        self.ctx.scale(1, -1)
        self.ctx.rotate(-math.radians(rotation))

        # Set font size
        self.ctx.set_font_size(height)
        self.ctx.select_font_face("sans-serif", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_NORMAL)

        # Move to origin (transformed position) before showing text
        # show_text draws at the current point, not at (0,0)
        self.ctx.move_to(0, 0)
        self.ctx.show_text(text)
        self.ctx.restore()
        self.rendered_count += 1

    def render_hatch(self, boundary_points: list[tuple[float, float]], style: RenderStyle = None):
        """Render a hatch (filled area)."""
        if len(boundary_points) < 3:
            return

        self.ctx.move_to(boundary_points[0][0], boundary_points[0][1])
        for p in boundary_points[1:]:
            self.ctx.line_to(p[0], p[1])
        self.ctx.close_path()

        if style and style.fill_color:
            self.ctx.set_source_rgba(*style.fill_color, style.fill_alpha)
            self.ctx.fill_preserve()

        if style:
            self.ctx.set_source_rgb(*style.stroke_color)
        self.ctx.stroke()
        self.rendered_count += 1

    def render_dxf_entity(self, entity: DXFEntity, doc, explode_blocks: bool = True):
        """
        Render a DXF entity.

        Args:
            entity: The DXF entity to render
            doc: The DXF document (for resolving layers, blocks, etc.)
            explode_blocks: If True, render block contents; if False, skip INSERTs
        """
        entity_type = entity.dxftype()
        color = get_entity_color(entity, doc)
        style = RenderStyle(stroke_color=color)

        try:
            if entity_type == "LINE":
                start = entity.dxf.start
                end = entity.dxf.end
                self.render_line((start.x, start.y), (end.x, end.y), style)

            elif entity_type == "LWPOLYLINE":
                points = [(p[0], p[1]) for p in entity.get_points(format='xy')]
                closed = entity.closed
                self.render_polyline(points, closed, style)

            elif entity_type == "POLYLINE":
                points = [(v.dxf.location.x, v.dxf.location.y) for v in entity.vertices]
                closed = entity.is_closed
                self.render_polyline(points, closed, style)

            elif entity_type == "CIRCLE":
                center = entity.dxf.center
                radius = entity.dxf.radius
                self.render_circle((center.x, center.y), radius, style)

            elif entity_type == "ARC":
                center = entity.dxf.center
                radius = entity.dxf.radius
                start_angle = math.radians(entity.dxf.start_angle)
                end_angle = math.radians(entity.dxf.end_angle)
                self.render_arc((center.x, center.y), radius, start_angle, end_angle, style)

            elif entity_type == "ELLIPSE":
                center = entity.dxf.center
                major_axis = entity.dxf.major_axis
                ratio = entity.dxf.ratio
                start_param = entity.dxf.start_param
                end_param = entity.dxf.end_param
                self.render_ellipse(
                    (center.x, center.y),
                    (major_axis.x, major_axis.y),
                    ratio, start_param, end_param, style
                )

            elif entity_type == "SPLINE":
                # Get flattened points for spline
                try:
                    points = list(entity.flattening(0.1))  # Tolerance in drawing units
                    pts = [(p.x, p.y) for p in points]
                    if pts:
                        self.render_polyline(pts, False, style)
                except:
                    # Fallback to control points
                    ctrl_pts = [(p.x, p.y) for p in entity.control_points]
                    if ctrl_pts:
                        self.render_spline(ctrl_pts, style)

            elif entity_type == "POINT":
                location = entity.dxf.location
                self.render_point((location.x, location.y), style)

            elif entity_type == "TEXT":
                text = entity.dxf.text
                pos = entity.dxf.insert
                height = entity.dxf.height
                rotation = entity.dxf.rotation if hasattr(entity.dxf, 'rotation') else 0
                self.render_text(text, (pos.x, pos.y), height, rotation, style)

            elif entity_type == "MTEXT":
                # Use plain_text() to strip MTEXT formatting codes like {\fArial|b0|i0|...}
                text = entity.plain_text() if hasattr(entity, 'plain_text') else entity.text
                pos = entity.dxf.insert
                height = entity.dxf.char_height if hasattr(entity.dxf, 'char_height') else 2.5
                rotation = entity.dxf.rotation if hasattr(entity.dxf, 'rotation') else 0
                self.render_text(text, (pos.x, pos.y), height, rotation, style)

            elif entity_type == "INSERT":
                if explode_blocks:
                    self._render_block_insert(entity, doc)
                # else: skip silently (internal call, don't mark as skipped)

            elif entity_type == "HATCH":
                self._render_hatch_entity(entity, style)

            elif entity_type == "DIMENSION":
                self._render_dimension(entity, doc, style)

            elif entity_type == "SOLID":
                # 2D solid (filled triangle/quadrilateral)
                points = []
                for attr in ['vtx0', 'vtx1', 'vtx2', 'vtx3']:
                    if hasattr(entity.dxf, attr):
                        p = getattr(entity.dxf, attr)
                        points.append((p.x, p.y))
                if len(points) >= 3:
                    fill_style = RenderStyle(
                        stroke_color=color,
                        fill_color=color,
                        fill_alpha=0.3
                    )
                    self.render_hatch(points, fill_style)

            elif entity_type == "TRACE":
                # Similar to SOLID
                points = []
                for attr in ['vtx0', 'vtx1', 'vtx2', 'vtx3']:
                    if hasattr(entity.dxf, attr):
                        p = getattr(entity.dxf, attr)
                        points.append((p.x, p.y))
                if len(points) >= 3:
                    self.render_hatch(points, style)

            elif entity_type == "3DFACE":
                points = []
                for attr in ['vtx0', 'vtx1', 'vtx2', 'vtx3']:
                    if hasattr(entity.dxf, attr):
                        p = getattr(entity.dxf, attr)
                        points.append((p.x, p.y))
                if len(points) >= 3:
                    self.render_polyline(points, True, style)

            elif entity_type in ("LEADER", "MLEADER"):
                # Render leader lines
                try:
                    if hasattr(entity, 'vertices'):
                        points = [(v.x, v.y) for v in entity.vertices]
                        self.render_polyline(points, False, style)
                except:
                    pass

            else:
                # Track unhandled types
                self.skipped_types.add(entity_type)

        except Exception as e:
            # Log error but continue rendering
            self.skipped_types.add(f"{entity_type}(error:{str(e)[:30]})")

    def _render_block_insert(self, insert_entity, doc):
        """Render a block reference (INSERT entity) by exploding its contents."""
        block_name = insert_entity.dxf.name

        # Skip internal blocks
        if block_name.startswith("*"):
            return

        try:
            block = doc.blocks.get(block_name)
            if not block:
                return

            # Get transformation parameters
            insert_point = insert_entity.dxf.insert
            x_scale = insert_entity.dxf.xscale if hasattr(insert_entity.dxf, 'xscale') else 1.0
            y_scale = insert_entity.dxf.yscale if hasattr(insert_entity.dxf, 'yscale') else 1.0
            rotation = insert_entity.dxf.rotation if hasattr(insert_entity.dxf, 'rotation') else 0.0

            # Track cumulative scale for line width compensation
            # Use average of x/y scale (assuming mostly uniform scaling)
            block_scale = (abs(x_scale) + abs(y_scale)) / 2
            current_scale = self.block_scale_stack[-1] if self.block_scale_stack else 1.0
            self.block_scale_stack.append(current_scale * block_scale)

            # Save context and apply transformation
            self.ctx.save()
            self.ctx.translate(insert_point.x, insert_point.y)
            self.ctx.rotate(math.radians(rotation))
            self.ctx.scale(x_scale, y_scale)

            # Render block contents
            for entity in block:
                if entity.dxftype() != "INSERT":  # Avoid infinite recursion
                    self.render_dxf_entity(entity, doc, explode_blocks=True)
                elif entity.dxf.name != block_name:  # Nested block (different name)
                    self._render_block_insert(entity, doc)

            self.ctx.restore()
            self.block_scale_stack.pop()
            self.rendered_count += 1

        except Exception as e:
            self.skipped_types.add(f"INSERT({block_name}:error)")
            # Make sure to pop scale on error too
            if len(self.block_scale_stack) > 1:
                self.block_scale_stack.pop()

    def _render_hatch_entity(self, hatch_entity, style: RenderStyle):
        """Render a HATCH entity with proper pattern fills."""
        try:
            # Extract hatch properties
            pattern_name = hatch_entity.dxf.pattern_name if hasattr(hatch_entity.dxf, 'pattern_name') else "SOLID"
            solid_fill = hatch_entity.dxf.solid_fill if hasattr(hatch_entity.dxf, 'solid_fill') else 1
            pattern_angle = hatch_entity.dxf.pattern_angle if hasattr(hatch_entity.dxf, 'pattern_angle') else 0
            pattern_scale = hatch_entity.dxf.pattern_scale if hasattr(hatch_entity.dxf, 'pattern_scale') else 1.0

            # Ensure pattern_scale is valid
            if pattern_scale <= 0:
                pattern_scale = 1.0

            # Get boundary paths
            all_boundaries = []
            for path in hatch_entity.paths:
                points = self._extract_hatch_boundary_points(path)
                if len(points) >= 3:
                    all_boundaries.append(points)

            if not all_boundaries:
                return

            # Determine rendering approach
            is_solid = solid_fill == 1 or pattern_name.upper() == "SOLID"

            if is_solid:
                # Render as solid fill
                fill_style = RenderStyle(
                    stroke_color=style.stroke_color,
                    fill_color=style.stroke_color,
                    fill_alpha=0.3
                )
                for boundary in all_boundaries:
                    self.render_hatch(boundary, fill_style)
            else:
                # Render as pattern fill with lines
                self._render_hatch_pattern(
                    all_boundaries,
                    pattern_name,
                    pattern_angle,
                    pattern_scale,
                    hatch_entity,
                    style
                )

        except Exception as e:
            self.skipped_types.add(f"HATCH(error:{str(e)[:20]})")

    def _extract_hatch_boundary_points(self, path) -> list[tuple[float, float]]:
        """Extract boundary points from a hatch path."""
        points = []

        if hasattr(path, 'vertices'):
            # Polyline path
            points = [(v[0], v[1]) for v in path.vertices]
        elif hasattr(path, 'edges'):
            # Edge path - convert edges to points
            for edge in path.edges:
                if edge.EDGE_TYPE == 'LineEdge':
                    points.append((edge.start.x, edge.start.y))
                    points.append((edge.end.x, edge.end.y))
                elif edge.EDGE_TYPE == 'ArcEdge':
                    # Approximate arc with line segments
                    center = (edge.center.x, edge.center.y)
                    radius = edge.radius
                    start = math.radians(edge.start_angle)
                    end = math.radians(edge.end_angle)

                    # Generate arc points
                    steps = max(8, int(abs(end - start) / (math.pi / 16)))
                    for i in range(steps + 1):
                        t = start + (end - start) * i / steps
                        x = center[0] + radius * math.cos(t)
                        y = center[1] + radius * math.sin(t)
                        points.append((x, y))
                elif edge.EDGE_TYPE == 'EllipseEdge':
                    # Approximate ellipse arc
                    center = (edge.center.x, edge.center.y)
                    major_x, major_y = edge.major_axis.x, edge.major_axis.y
                    ratio = edge.ratio if hasattr(edge, 'ratio') else 1.0
                    start_param = edge.start_param if hasattr(edge, 'start_param') else 0
                    end_param = edge.end_param if hasattr(edge, 'end_param') else 2 * math.pi

                    major_length = math.sqrt(major_x**2 + major_y**2)
                    rotation = math.atan2(major_y, major_x)

                    steps = max(16, int(abs(end_param - start_param) / (math.pi / 16)))
                    for i in range(steps + 1):
                        t = start_param + (end_param - start_param) * i / steps
                        # Parametric ellipse
                        ex = major_length * math.cos(t)
                        ey = major_length * ratio * math.sin(t)
                        # Rotate and translate
                        x = center[0] + ex * math.cos(rotation) - ey * math.sin(rotation)
                        y = center[1] + ex * math.sin(rotation) + ey * math.cos(rotation)
                        points.append((x, y))
                elif edge.EDGE_TYPE == 'SplineEdge':
                    # Approximate spline with control points
                    if hasattr(edge, 'control_points'):
                        for cp in edge.control_points:
                            points.append((cp.x, cp.y))
                    elif hasattr(edge, 'fit_points'):
                        for fp in edge.fit_points:
                            points.append((fp.x, fp.y))

        return points

    def _render_hatch_pattern(
        self,
        boundaries: list[list[tuple[float, float]]],
        pattern_name: str,
        pattern_angle: float,
        pattern_scale: float,
        hatch_entity,
        style: RenderStyle
    ):
        """Render hatch pattern as line fills within boundaries."""
        # Try to get pattern definition from the hatch entity itself
        # Pattern lines: (angle, spacing, dash, base_point, already_scaled)
        pattern_lines = []
        from_entity = False

        if hasattr(hatch_entity, 'pattern') and hatch_entity.pattern:
            try:
                for pline in hatch_entity.pattern.lines:
                    angle = pline.angle if hasattr(pline, 'angle') else 0
                    base_pt = (0, 0)
                    if hasattr(pline, 'base_point'):
                        base_pt = (pline.base_point.x, pline.base_point.y)

                    # Get offset (spacing between lines)
                    # NOTE: The offset from entity.pattern.lines is ALREADY scaled by pattern_scale
                    spacing = 100  # Default spacing
                    if hasattr(pline, 'offset'):
                        offset = pline.offset
                        spacing = math.sqrt(offset.x**2 + offset.y**2)
                        if spacing <= 0:
                            spacing = 100

                    # Get dash pattern (also already scaled)
                    dash = None
                    if hasattr(pline, 'dash_length_items') and pline.dash_length_items:
                        dash = list(pline.dash_length_items)

                    pattern_lines.append((angle, spacing, dash, base_pt))

                if pattern_lines:
                    from_entity = True
            except Exception:
                pass

        # Fall back to standard patterns if no lines defined
        if not pattern_lines:
            pattern_upper = pattern_name.upper()
            if pattern_upper in STANDARD_HATCH_PATTERNS:
                for angle, spacing, dash in STANDARD_HATCH_PATTERNS[pattern_upper]:
                    pattern_lines.append((angle, spacing, dash, (0, 0)))
            else:
                # Default: single diagonal line pattern
                pattern_lines.append((45, 100, None, (0, 0)))

        # Render each boundary
        for boundary in boundaries:
            bbox = _get_polygon_bbox(boundary)
            if not bbox:
                continue

            # Set line style
            self.ctx.set_source_rgb(*style.stroke_color)
            self.ctx.set_line_width(0.5 / self.scale)

            # Render each line family in the pattern
            for line_angle, line_spacing, dash_pattern, base_point in pattern_lines:
                # Apply pattern angle
                final_angle = line_angle + pattern_angle

                # Apply pattern scale only if using fallback patterns (not from entity)
                # Entity patterns already have scale applied to their offsets
                if from_entity:
                    final_spacing = line_spacing
                else:
                    final_spacing = line_spacing * pattern_scale

                # Limit spacing to reasonable values
                min_spacing = max(bbox.width, bbox.height) / 500
                max_spacing = max(bbox.width, bbox.height) / 2
                final_spacing = max(min_spacing, min(final_spacing, max_spacing))

                # Generate lines covering the bounding box
                lines = _generate_hatch_lines(
                    bbox,
                    final_angle,
                    final_spacing,
                    base_point,
                    dash_pattern
                )

                # Set dash pattern if specified
                # DXF dash patterns: positive=line, negative=gap, 0=dot
                # Cairo requires all positive values
                if dash_pattern:
                    scaled_dash = []
                    for d in dash_pattern:
                        if d == 0:
                            # Dot: use small line segment
                            scaled_dash.append(1 / self.scale)
                        else:
                            # Use absolute value
                            # If from entity, dash values are already scaled
                            # If from fallback, multiply by pattern_scale
                            dash_val = abs(d)
                            if not from_entity:
                                dash_val *= pattern_scale
                            scaled_dash.append(dash_val / self.scale)
                    if scaled_dash and all(v > 0 for v in scaled_dash):
                        self.ctx.set_dash(scaled_dash)
                    else:
                        self.ctx.set_dash([])
                else:
                    self.ctx.set_dash([])

                # Clip each line to boundary and draw
                for line_start, line_end, _ in lines:
                    segments = _clip_line_to_polygon(line_start, line_end, boundary)
                    for seg_start, seg_end in segments:
                        self.ctx.move_to(seg_start[0], seg_start[1])
                        self.ctx.line_to(seg_end[0], seg_end[1])
                        self.ctx.stroke()
                        self.rendered_count += 1

            # Reset dash pattern
            self.ctx.set_dash([])

    def _render_dimension(self, dim_entity, doc, style: RenderStyle):
        """Render a DIMENSION entity."""
        try:
            # Render the dimension's virtual block (contains the actual geometry)
            if hasattr(dim_entity, 'virtual_entities'):
                for virtual_entity in dim_entity.virtual_entities():
                    self.render_dxf_entity(virtual_entity, doc, explode_blocks=False)
            else:
                # Fallback: render dimension lines manually
                if hasattr(dim_entity.dxf, 'defpoint') and hasattr(dim_entity.dxf, 'defpoint2'):
                    p1 = dim_entity.dxf.defpoint2
                    p2 = dim_entity.dxf.defpoint3 if hasattr(dim_entity.dxf, 'defpoint3') else dim_entity.dxf.defpoint
                    self.render_line((p1.x, p1.y), (p2.x, p2.y), style)
        except Exception as e:
            self.skipped_types.add(f"DIMENSION(error)")

    def render_modelspace(self, doc, msp, layers: list[str] = None, region: RenderBounds = None):
        """
        Render all entities in modelspace.

        Args:
            doc: DXF document
            msp: Modelspace
            layers: Optional list of layer names to include (None = all)
            region: Optional region bounds to filter entities
        """
        for entity in msp:
            # Filter by layer
            if layers:
                entity_layer = entity.dxf.layer if hasattr(entity.dxf, 'layer') else "0"
                if entity_layer not in layers:
                    continue

            # Filter by region (using entity bounds)
            if region:
                try:
                    bbox = ezdxf_bbox.extents([entity])
                    if bbox.has_data:
                        # Check if entity intersects region
                        if (bbox.extmax.x < region.x_min or bbox.extmin.x > region.x_max or
                            bbox.extmax.y < region.y_min or bbox.extmin.y > region.y_max):
                            continue
                except:
                    pass

            self.render_dxf_entity(entity, doc)

    def save(self, filepath: str):
        """Save the rendered image."""
        if self.output_format == "svg":
            # Create SVG surface and re-render
            self.surface = cairo.SVGSurface(filepath, self.width, self.height)
            self.ctx = cairo.Context(self.surface)
            self._setup_context()
            # Note: For SVG, you need to call render_modelspace again
            self.surface.finish()
        else:
            self.surface.write_to_png(filepath)

    def get_png_data(self) -> bytes:
        """Get PNG data as bytes."""
        import io
        buf = io.BytesIO()
        self.surface.write_to_png(buf)
        return buf.getvalue()


def render_dxf_to_png(
    doc,
    msp,
    output_path: str,
    width: int = 4096,
    height: int = None,
    bounds: RenderBounds = None,
    background: str = "white",
    layers: list[str] = None,
    cache = None
) -> tuple[int, int, RenderBounds]:
    """
    Render a DXF drawing to PNG using Cairo.

    Args:
        doc: ezdxf document
        msp: Modelspace
        output_path: Path to save PNG
        width: Output width in pixels
        height: Output height (auto-calculated if None)
        bounds: Drawing bounds (auto-detected if None)
        background: Background color
        layers: Layers to include (None = all)
        cache: ezdxf bbox cache

    Returns:
        Tuple of (actual_width, actual_height, actual_bounds)
    """
    # Calculate bounds if not provided
    if bounds is None:
        if cache:
            bbox = ezdxf_bbox.extents(msp, cache=cache)
        else:
            bbox = ezdxf_bbox.extents(msp)

        if not bbox.has_data:
            raise ValueError("No geometry found in drawing")

        # Add padding
        padding = max(500, max(bbox.size.x, bbox.size.y) * 0.02)
        bounds = RenderBounds(
            bbox.extmin.x - padding,
            bbox.extmax.x + padding,
            bbox.extmin.y - padding,
            bbox.extmax.y + padding
        )

    # Calculate height maintaining aspect ratio
    if height is None:
        aspect_ratio = bounds.height / bounds.width
        height = int(width * aspect_ratio)

    # Limit maximum dimensions
    max_dim = 16384
    if width > max_dim or height > max_dim:
        scale = max_dim / max(width, height)
        width = int(width * scale)
        height = int(height * scale)

    # Create renderer and render
    renderer = CairoRenderer(width, height, bounds, background)
    renderer.render_modelspace(doc, msp, layers)
    renderer.save(output_path)

    # Log any skipped entity types
    if renderer.skipped_types:
        print(f"Cairo renderer: skipped entity types: {renderer.skipped_types}")
    print(f"Cairo renderer: rendered {renderer.rendered_count} entities")

    return (width, height, bounds)


def render_dxf_to_svg(
    doc,
    msp,
    output_path: str,
    width: int = 4096,
    height: int = None,
    bounds: RenderBounds = None,
    layers: list[str] = None,
    cache = None
) -> tuple[int, int, RenderBounds]:
    """
    Render a DXF drawing to SVG using Cairo.

    Args:
        doc: ezdxf document
        msp: Modelspace
        output_path: Path to save SVG
        width: Output width in pixels
        height: Output height (auto-calculated if None)
        bounds: Drawing bounds (auto-detected if None)
        layers: Layers to include (None = all)
        cache: ezdxf bbox cache

    Returns:
        Tuple of (actual_width, actual_height, actual_bounds)
    """
    # Calculate bounds if not provided
    if bounds is None:
        if cache:
            bbox = ezdxf_bbox.extents(msp, cache=cache)
        else:
            bbox = ezdxf_bbox.extents(msp)

        if not bbox.has_data:
            raise ValueError("No geometry found in drawing")

        padding = max(500, max(bbox.size.x, bbox.size.y) * 0.02)
        bounds = RenderBounds(
            bbox.extmin.x - padding,
            bbox.extmax.x + padding,
            bbox.extmin.y - padding,
            bbox.extmax.y + padding
        )

    # Calculate height maintaining aspect ratio
    if height is None:
        aspect_ratio = bounds.height / bounds.width
        height = int(width * aspect_ratio)

    # Create SVG surface
    surface = cairo.SVGSurface(output_path, width, height)
    ctx = cairo.Context(surface)

    # Create renderer with pre-created surface
    renderer = CairoRenderer.__new__(CairoRenderer)
    renderer.width = width
    renderer.height = height
    renderer.bounds = bounds
    renderer.background = "white"
    renderer.output_format = "svg"
    renderer.scale_x = width / bounds.width
    renderer.scale_y = height / bounds.height
    renderer.scale = min(renderer.scale_x, renderer.scale_y)
    renderer.surface = surface
    renderer.ctx = ctx
    renderer.rendered_count = 0
    renderer.skipped_types = set()
    renderer._block_cache = {}

    renderer._setup_context()
    renderer.render_modelspace(doc, msp, layers)

    surface.finish()

    if renderer.skipped_types:
        print(f"Cairo SVG renderer: skipped entity types: {renderer.skipped_types}")
    print(f"Cairo SVG renderer: rendered {renderer.rendered_count} entities")

    return (width, height, bounds)
