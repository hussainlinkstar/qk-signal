from __future__ import annotations

from html import escape
from math import cos, pi, sin
from typing import Mapping, Sequence

from .branding import mix_hex_colors, normalize_hex_color
from .labels import report_label, shape_rtl_text
from services.report_i18n_service import is_rtl_report_language


def _safe_score(value: object, *, default: float = 0.0) -> float:
    try:
        score = float(value)
    except (TypeError, ValueError):
        score = default
    return max(0.0, min(100.0, score))


def _series_polygon_points(
    values: Sequence[float],
    *,
    center_x: float,
    center_y: float,
    radius: float,
) -> list[tuple[float, float]]:
    point_count = len(values)
    if point_count == 0:
        return []

    points: list[tuple[float, float]] = []
    for index, value in enumerate(values):
        angle = (-pi / 2) + ((2 * pi * index) / point_count)
        scaled_radius = radius * (_safe_score(value) / 100.0)
        points.append(
            (
                center_x + (scaled_radius * cos(angle)),
                center_y + (scaled_radius * sin(angle)),
            )
        )
    return points


def _format_points(points: Sequence[tuple[float, float]]) -> str:
    return " ".join(f"{x:.2f},{y:.2f}" for x, y in points)


def _smooth_path(points: Sequence[tuple[float, float]], *, closed: bool = True) -> str:
    """Build a smooth cubic bezier path through radar polygon points."""
    n = len(points)
    if n < 2:
        return ""
    parts = [f"M {points[0][0]:.2f},{points[0][1]:.2f}"]
    for i in range(n):
        p0 = points[(i - 1) % n]
        p1 = points[i]
        p2 = points[(i + 1) % n]
        p3 = points[(i + 2) % n]
        tension = 0.3
        cp1x = p1[0] + (p2[0] - p0[0]) * tension
        cp1y = p1[1] + (p2[1] - p0[1]) * tension
        cp2x = p2[0] - (p3[0] - p1[0]) * tension
        cp2y = p2[1] - (p3[1] - p1[1]) * tension
        parts.append(f"C {cp1x:.2f},{cp1y:.2f} {cp2x:.2f},{cp2y:.2f} {p2[0]:.2f},{p2[1]:.2f}")
    if closed:
        parts.append("Z")
    return " ".join(parts)


def _score_color(
    score: float,
    primary: str,
    success: str = "#0F766E",
    warning: str = "#B45309",
    danger: str = "#BE123C",
) -> str:
    if score >= 80:
        return success
    if score >= 60:
        return primary
    if score >= 40:
        return warning
    return danger


def build_score_radar_svg(
    *,
    metrics: Mapping[str, object],
    primary_color: str,
    secondary_color: str,
    comparison_metrics: Mapping[str, object] | None = None,
    comparison_color: str | None = None,
    language: str = "en",
) -> str:
    labels = list(metrics.keys())
    if not labels:
        return ""

    width = 540
    height = 340
    center_x = 196
    center_y = 168
    radius = 120
    primary = normalize_hex_color(primary_color, "#0EA5E9")
    comparison = normalize_hex_color(comparison_color, "#F97316")

    grid_color = "#E2E8F0"
    values = [_safe_score(metrics[label]) for label in labels]
    points = _series_polygon_points(values, center_x=center_x, center_y=center_y, radius=radius)
    comparison_points = None
    if comparison_metrics:
        comparison_values = [_safe_score(comparison_metrics.get(label)) for label in labels]
        comparison_points = _series_polygon_points(
            comparison_values,
            center_x=center_x,
            center_y=center_y,
            radius=radius,
        )

    svg_parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" width="{width}" height="{height}">',
        "<defs>",
        '<linearGradient id="radarFill" x1="0%" y1="0%" x2="100%" y2="100%">',
        f'<stop offset="0%" stop-color="{primary}" stop-opacity="0.22" />',
        f'<stop offset="100%" stop-color="{primary}" stop-opacity="0.06" />',
        "</linearGradient>",
        '<linearGradient id="compFill" x1="0%" y1="0%" x2="100%" y2="100%">',
        f'<stop offset="0%" stop-color="{comparison}" stop-opacity="0.14" />',
        f'<stop offset="100%" stop-color="{comparison}" stop-opacity="0.04" />',
        "</linearGradient>",
        '<filter id="cardShadow" x="-4%" y="-4%" width="108%" height="108%">',
        '<feDropShadow dx="0" dy="2" stdDeviation="6" flood-color="#00040e" flood-opacity="0.06" />',
        "</filter>",
        "</defs>",
        # Background
        f'<rect x="0" y="0" width="{width}" height="{height}" rx="16" fill="#FFFFFF" />',
    ]

    # Grid rings
    for level in range(1, 6):
        ratio = level / 5
        ring_points = _series_polygon_points(
            [ratio * 100] * len(labels),
            center_x=center_x,
            center_y=center_y,
            radius=radius,
        )
        opacity = 0.6 if level == 5 else 0.35
        svg_parts.append(
            f'<polygon points="{_format_points(ring_points)}" fill="none" '
            f'stroke="{grid_color}" stroke-width="0.75" stroke-opacity="{opacity}" />'
        )
        # Scale labels on right axis
        label_y = center_y - (radius * ratio)
        svg_parts.append(
            f'<text x="{center_x + 6}" y="{label_y + 3:.2f}" font-size="8" fill="#94A3B8" font-weight="500">{int(ratio * 100)}</text>'
        )

    # Axes and labels
    for index, label in enumerate(labels):
        angle = (-pi / 2) + ((2 * pi * index) / len(labels))
        axis_x = center_x + (radius * cos(angle))
        axis_y = center_y + (radius * sin(angle))
        label_x = center_x + ((radius + 28) * cos(angle))
        label_y = center_y + ((radius + 22) * sin(angle))
        anchor = "middle"
        if label_x < center_x - 8:
            anchor = "end"
        elif label_x > center_x + 8:
            anchor = "start"
        svg_parts.append(
            f'<line x1="{center_x:.2f}" y1="{center_y:.2f}" x2="{axis_x:.2f}" y2="{axis_y:.2f}" '
            f'stroke="{grid_color}" stroke-width="0.75" />'
        )
        score_val = int(round(values[index]))
        score_clr = _score_color(values[index], primary)
        shaped_label = shape_rtl_text(language, str(label))
        if is_rtl_report_language(language):
            # The shaped run is drawn strictly left to right, so emit the
            # value first for it to sit at the RTL-trailing (left) end.
            run = f'<tspan fill="{score_clr}">{score_val}</tspan> {escape(str(shaped_label))}'
        else:
            run = f'{escape(str(shaped_label))} <tspan fill="{score_clr}">{score_val}</tspan>'
        svg_parts.append(
            f'<text x="{label_x:.2f}" y="{label_y:.2f}" text-anchor="{anchor}" '
            f'font-size="11" font-weight="700" fill="#1E293B">{run}</text>'
        )

    # Primary data polygon
    svg_parts.append(
        f'<path d="{_smooth_path(points)}" fill="url(#radarFill)" stroke="{primary}" stroke-width="2.5" stroke-linejoin="round" />'
    )
    for x, y in points:
        svg_parts.append(
            f'<circle cx="{x:.2f}" cy="{y:.2f}" r="4" fill="#FFFFFF" stroke="{primary}" stroke-width="2" />'
        )

    # Comparison polygon
    if comparison_points is not None:
        svg_parts.append(
            f'<path d="{_smooth_path(comparison_points)}" fill="url(#compFill)" '
            f'stroke="{comparison}" stroke-width="2" stroke-dasharray="6 4" stroke-linejoin="round" />'
        )
        for x, y in comparison_points:
            svg_parts.append(
                f'<circle cx="{x:.2f}" cy="{y:.2f}" r="3" fill="#FFFFFF" stroke="{comparison}" stroke-width="1.5" />'
            )

    # Summary box
    avg_score = int(round(sum(values) / len(values)))
    avg_color = _score_color(avg_score, primary)
    box_x = 348
    box_y = 40
    svg_parts.extend(
        [
            f'<rect x="{box_x}" y="{box_y}" width="168" height="120" rx="12" fill="#FFFFFF" stroke="#E2E8F0" stroke-width="1" filter="url(#cardShadow)" />',
            f'<text x="{box_x + 20}" y="{box_y + 28}" font-size="9" font-weight="700" fill="#94A3B8" letter-spacing="0.08em">{shape_rtl_text(language, report_label(language, "AVERAGE SCORE"))}</text>',
            f'<text x="{box_x + 20}" y="{box_y + 68}" font-size="36" font-weight="800" fill="{avg_color}">{avg_score}</text>',
            f'<text x="{box_x + 20}" y="{box_y + 88}" font-size="10" fill="#64748B">{shape_rtl_text(language, report_label(language, "across all pillars"))}</text>',
        ]
    )

    # Legend
    legend_y = box_y + 140
    svg_parts.extend(
        [
            f'<rect x="{box_x + 4}" y="{legend_y}" width="10" height="10" rx="3" fill="{primary}" />',
            f'<text x="{box_x + 20}" y="{legend_y + 9}" font-size="10" fill="#1E293B" font-weight="600">{shape_rtl_text(language, report_label(language, "Target"))}</text>',
        ]
    )
    if comparison_points is not None:
        svg_parts.extend(
            [
                f'<rect x="{box_x + 4}" y="{legend_y + 20}" width="10" height="10" rx="3" fill="{comparison}" />',
                f'<text x="{box_x + 20}" y="{legend_y + 29}" font-size="10" fill="#1E293B" font-weight="600">{shape_rtl_text(language, report_label(language, "Competitor"))}</text>',
            ]
        )

    svg_parts.append("</svg>")
    return "".join(svg_parts)


def build_breakdown_bar_chart_svg(
    *,
    metrics: Sequence[tuple[str, object]],
    primary_color: str,
    secondary_color: str,
    language: str = "en",
) -> str:
    if not metrics:
        return ""

    bar_height = 20
    row_gap = 16
    label_x = 14
    bar_x = 180
    bar_width = 240
    width = 460
    padding_top = 16
    padding_bottom = 12
    height = padding_top + (len(metrics) * (bar_height + row_gap)) - row_gap + padding_bottom
    primary = normalize_hex_color(primary_color, "#0EA5E9")

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" width="{width}" height="{height}">',
        "<defs>",
        '<linearGradient id="barGrad" x1="0%" y1="0%" x2="100%" y2="0%">',
        f'<stop offset="0%" stop-color="{primary}" />',
        f'<stop offset="100%" stop-color="{mix_hex_colors(primary, "#FFFFFF", 0.3)}" />',
        "</linearGradient>",
        "</defs>",
        f'<rect x="0" y="0" width="{width}" height="{height}" rx="12" fill="#FFFFFF" />',
    ]

    for index, (label, value) in enumerate(metrics):
        score = _safe_score(value)
        y = padding_top + index * (bar_height + row_gap)
        fill_width = max(2, (score / 100.0) * bar_width)
        score_clr = _score_color(score, primary)
        parts.extend(
            [
                f'<text x="{label_x}" y="{y + 14}" font-size="10" font-weight="600" fill="#1E293B">{escape(str(shape_rtl_text(language, str(label))))}</text>',
                f'<rect x="{bar_x}" y="{y}" width="{bar_width}" height="{bar_height}" rx="10" fill="#F1F5F9" />',
                f'<rect x="{bar_x}" y="{y}" width="{fill_width:.2f}" height="{bar_height}" rx="10" fill="url(#barGrad)" />',
                f'<text x="{bar_x + bar_width + 10}" y="{y + 14}" font-size="11" font-weight="700" fill="{score_clr}">{int(round(score))}</text>',
            ]
        )

    parts.append("</svg>")
    return "".join(parts)


def build_trend_line_svg(
    *,
    points: Sequence[Mapping[str, object]],
    primary_color: str,
    secondary_color: str,
    tertiary_color: str,
    language: str = "en",
) -> str:
    if len(points) < 2:
        return ""

    width = 760
    height = 300
    margin_left = 54
    margin_right = 24
    margin_top = 28
    margin_bottom = 50
    plot_width = width - margin_left - margin_right
    plot_height = height - margin_top - margin_bottom

    series = (
        ("geo", report_label(language, "GEO"), normalize_hex_color(primary_color, "#0EA5E9")),
        ("seo", report_label(language, "SEO"), normalize_hex_color(secondary_color, "#64748B")),
        ("aeo", report_label(language, "AEO"), normalize_hex_color(tertiary_color, "#F97316")),
    )

    def _point_x(index: int) -> float:
        denominator = max(1, len(points) - 1)
        return margin_left + ((plot_width * index) / denominator)

    def _point_y(value: object) -> float:
        return margin_top + (plot_height * (1 - (_safe_score(value) / 100.0)))

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" width="{width}" height="{height}">',
        "<defs>",
    ]

    # Area fill gradients per series
    for key, label, color in series:
        parts.extend(
            [
                f'<linearGradient id="areaGrad_{key}" x1="0" y1="0" x2="0" y2="1">',
                f'<stop offset="0%" stop-color="{color}" stop-opacity="0.15" />',
                f'<stop offset="100%" stop-color="{color}" stop-opacity="0.02" />',
                "</linearGradient>",
            ]
        )
    parts.append("</defs>")

    parts.append(f'<rect x="0" y="0" width="{width}" height="{height}" rx="16" fill="#FFFFFF" />')

    # Grid lines
    for tick in range(0, 101, 20):
        y = _point_y(tick)
        parts.extend(
            [
                f'<line x1="{margin_left}" y1="{y:.2f}" x2="{width - margin_right}" y2="{y:.2f}" stroke="#F1F5F9" stroke-width="1" />',
                f'<text x="{margin_left - 8}" y="{y + 3:.2f}" text-anchor="end" font-size="9" font-weight="500" fill="#94A3B8">{tick}</text>',
            ]
        )

    # X-axis labels
    for index, point in enumerate(points):
        x = _point_x(index)
        label = escape(
            str(
                shape_rtl_text(
                    language,
                    str(point.get("label") or f"{report_label(language, 'Run')} {index + 1}"),
                )
            )
        )
        parts.append(
            f'<text x="{x:.2f}" y="{height - 16}" text-anchor="middle" font-size="9" font-weight="500" fill="#64748B">{label}</text>'
        )

    # Series lines with area fills
    for series_index, (key, label, color) in enumerate(series):
        line_path = []
        area_path = []
        for index, point in enumerate(points):
            x = _point_x(index)
            y = _point_y(point.get(key))
            cmd = "M" if index == 0 else "L"
            line_path.append(f"{cmd} {x:.2f} {y:.2f}")
            area_path.append(f"{cmd} {x:.2f} {y:.2f}")

        # Area fill
        last_x = _point_x(len(points) - 1)
        first_x = _point_x(0)
        bottom = margin_top + plot_height
        area_d = (
            " ".join(area_path) + f" L {last_x:.2f} {bottom:.2f} L {first_x:.2f} {bottom:.2f} Z"
        )
        parts.append(f'<path d="{area_d}" fill="url(#areaGrad_{key})" />')

        # Line
        parts.append(
            f'<path d="{" ".join(line_path)}" fill="none" stroke="{color}" stroke-width="2.5" '
            'stroke-linecap="round" stroke-linejoin="round" />'
        )
        # Data points
        for index, point in enumerate(points):
            x = _point_x(index)
            y = _point_y(point.get(key))
            parts.append(
                f'<circle cx="{x:.2f}" cy="{y:.2f}" r="4" fill="#FFFFFF" stroke="{color}" stroke-width="2" />'
            )

        # Legend
        legend_x = width - 150
        legend_y = 28 + (series_index * 22)
        parts.extend(
            [
                f'<rect x="{legend_x}" y="{legend_y - 5}" width="12" height="12" rx="3" fill="{color}" />',
                f'<text x="{legend_x + 18}" y="{legend_y + 5}" font-size="10" font-weight="600" fill="#1E293B">{shape_rtl_text(language, label)}</text>',
            ]
        )

    parts.append("</svg>")
    return "".join(parts)
