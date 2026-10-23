"""
SolidWorks self-review tool for generated results.

Purpose:
    After generating or modifying CAD, export multi-view previews and collect a
    basic model summary, so an agent can judge from screenshots or exported BMPs
    whether the geometry matches the user's intent.
"""
import os
import json
import argparse
import tempfile
from pathlib import Path

try:
    from .sw_connect import connect_solidworks, get_com_member, open_document
except ImportError:
    from sw_connect import connect_solidworks, get_com_member, open_document


try:
    from .sw_evidence import artifact_metadata, atomic_write_json
except ImportError:
    from sw_evidence import artifact_metadata, atomic_write_json


STANDARD_VIEWS = {
    "front": 1,
    "back": 2,
    "left": 3,
    "right": 4,
    "top": 5,
    "bottom": 6,
    "isometric": 7,
    "trimetric": 8,
    "dimetric": 9,
}


def _expand_path(path):
    """Expand an output path."""
    return Path(os.path.expandvars(str(path))).expanduser().resolve()


def _file_info(path):
    """Return file existence and size info."""
    return artifact_metadata(_expand_path(path))


def _read_bmp_size(path):
    """
    Read BMP width and height.

    Returns:
        (width, height); returns (None, None) on read failure.
    """
    try:
        with open(path, "rb") as file:
            header = file.read(26)
        if len(header) < 26 or header[:2] != b"BM":
            return None, None
        width = int.from_bytes(header[18:22], "little", signed=True)
        height = int.from_bytes(header[22:26], "little", signed=True)
        return abs(width), abs(height)
    except Exception:
        return None, None


def inspect_bmp_preview(path, sample_limit=200000):
    """
    Do a lightweight check on a BMP preview image.

    This check does not replace human/vision-model judgment; it only catches
    obvious problems such as blank images, undersized files, or export failure.
    """
    info = _file_info(path)
    info.update({
        "width": None,
        "height": None,
        "unique_sample_values": 0,
        "likely_blank": True,
    })
    if not info["exists"] or info["size_bytes"] <= 0:
        return info

    width, height = _read_bmp_size(path)
    info["width"] = width
    info["height"] = height

    try:
        with open(path, "rb") as file:
            data = file.read()
        sample = data[54:54 + sample_limit] if len(data) > 54 else data
        info["unique_sample_values"] = len(set(sample))
        info["likely_blank"] = info["unique_sample_values"] < 8
    except Exception as exc:
        info["error"] = str(exc)
    return info


def zoom_to_fit(model):
    """Zoom to fit the window and redraw the graphics."""
    get_com_member(model, "ViewZoomtofit2")
    get_com_member(model, "GraphicsRedraw2")


def set_standard_view(model, view_name="isometric"):
    """
    Set the standard view orientation.

    Args:
        view_name: "isometric", "front", "top", "right", or a SolidWorks view name.
    """
    view_id = STANDARD_VIEWS.get(str(view_name).lower())
    if view_id is None:
        model.ShowNamedView2(str(view_name), -1)
    else:
        model.ShowNamedView2("", view_id)
    zoom_to_fit(model)


def save_preview(model, output_path, view_name="isometric", width=1600, height=1000):
    """
    Export a preview image of the current model.

    Args:
        model: IModelDoc2 object
        output_path: BMP output path
        view_name: standard view orientation
        width: exported image width
        height: exported image height

    Returns:
        Output path string.
    """
    output_path = _expand_path(output_path)
    if output_path.suffix.lower() != ".bmp":
        output_path = output_path.with_suffix(".bmp")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    set_standard_view(model, view_name)
    fd, temporary = tempfile.mkstemp(suffix=".bmp", dir=output_path.parent)
    os.close(fd)
    try:
        ok = model.SaveBMP(temporary, int(width), int(height))
        if not ok or Path(temporary).stat().st_size <= 0:
            raise RuntimeError(f"preview export failed: {output_path}")
        os.replace(temporary, output_path)
    finally:
        if Path(temporary).exists():
            Path(temporary).unlink()
    return str(output_path)


def save_review_previews(model, output_dir, basename="review", views=None):
    """
    Export multi-view preview images.

    Args:
        model: IModelDoc2 object
        output_dir: output directory
        basename: file name prefix
        views: list of views; defaults to isometric, front, top, right

    Returns:
        List of preview image paths.
    """
    views = views or ("isometric", "front", "top", "right")
    output_dir = _expand_path(output_dir)
    return [
        save_preview(model, output_dir / f"{basename}_{view}.bmp", view)
        for view in views
    ]


def collect_model_summary(model):
    """
    Collect a basic model summary.

    Returns:
        dict containing title, type, feature count, save path, and similar info.
    """
    features = []
    # Unexpected COM errors propagate; partial summaries cannot pass review.
    feature = get_com_member(model, "FirstFeature")
    while feature:
        features.append({"name": get_com_member(feature, "Name"),
                         "type": get_com_member(feature, "GetTypeName2")})
        feature = get_com_member(feature, "GetNextFeature")

    summary = {
        "title": get_com_member(model, "GetTitle"),
        "path": get_com_member(model, "GetPathName"),
        "type": get_com_member(model, "GetType"),
        "feature_count": len(features),
        "features": features,
    }
    return summary


def build_review_report(model, output_dir, basename="review", views=None, expected_outputs=None):
    """
    Generate structured review report data.

    Args:
        model: IModelDoc2 object
        output_dir: output directory for previews and the report
        basename: output file name prefix
        views: list of views to export
        expected_outputs: list of output files expected to exist, e.g. sldprt, step, stl

    Returns:
        dict review report.
    """
    output_dir = _expand_path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    if not get_com_member(model, "ForceRebuild3", False):
        raise RuntimeError("ForceRebuild3 failed during review")
    zoom_to_fit(model)

    views = views or ("isometric", "front", "top", "right")
    preview_paths = save_review_previews(model, output_dir, basename=basename, views=views)
    previews = [inspect_bmp_preview(path) for path in preview_paths]
    expected = [_file_info(path) for path in (expected_outputs or [])]
    summary = collect_model_summary(model)

    checks = {
        "rebuild_succeeded": True,
        "model_available": model is not None,
        "previews_created": all(item["exists"] and item["size_bytes"] > 0 for item in previews),
        "previews_not_blank": all(not item["likely_blank"] for item in previews),
        "expected_outputs_exist": all(item["exists"] and item["size_bytes"] > 0 for item in expected) if expected else None,
        "feature_summary_available": "feature_error" not in summary,
    }

    review_notes = [
        "A human or vision model must still check the previews for the main body, "
        "proportions, orientation, key parts, and overlap/floating-part issues.",
        "If previews_not_blank is false, first check view zoom, whether the model is "
        "empty, and whether SaveBMP succeeded.",
        "If expected_outputs_exist is false, first check the save/export paths and "
        "COM error codes.",
    ]

    report = {
        "model": summary,
        "previews": previews,
        "expected_outputs": expected,
        "checks": checks,
        "review_notes": review_notes,
    }
    report["evaluation"] = evaluate_review_report(report)
    return report


def evaluate_review_report(report):
    """
    Apply rule-based scoring to a structured review report.

    Returns:
        dict containing status, score, issues, recommendations, manual_review_required.
    """
    checks = report.get("checks", {})
    previews = report.get("previews", [])
    expected_outputs = report.get("expected_outputs", [])
    issues = []
    recommendations = []
    score = 100
    hard_fail = False

    def add_issue(code, severity, message, recommendation, penalty):
        nonlocal score, hard_fail
        issues.append({
            "code": code,
            "severity": severity,
            "message": message,
        })
        recommendations.append(recommendation)
        score -= penalty
        if severity == "fail":
            hard_fail = True

    if checks.get("rebuild_succeeded") is not True:
        add_issue("rebuild_failed_or_missing", "fail", "Rebuild not proven successful.",
                  "Run a checked rebuild.", 40)

    if not checks.get("model_available"):
        add_issue(
            "model_missing",
            "fail",
            "No SolidWorks model object available to review.",
            "Confirm the connection succeeded and a valid document was opened or created.",
            40,
        )

    if not checks.get("previews_created"):
        add_issue(
            "previews_missing",
            "fail",
            "Preview images were not generated successfully.",
            "Check SaveBMP, output directory permissions, and whether the model view is visible.",
            35,
        )

    if checks.get("previews_created") and not checks.get("previews_not_blank"):
        add_issue(
            "previews_blank",
            "fail",
            "At least one preview image appears blank.",
            "Check whether the model is empty, whether it is zoomed to fit, and whether it is stuck in sketch mode.",
            35,
        )

    if checks.get("expected_outputs_exist") is False:
        add_issue(
            "expected_outputs_missing",
            "fail",
            "An expected output file is missing or has zero size.",
            "Recheck the save/export path and the SolidWorks SaveAs error code.",
            30,
        )

    if checks.get("expected_outputs_exist") is None:
        add_issue(
            "expected_outputs_not_declared",
            "warn",
            "No expected output files were declared, so delivery completeness cannot be verified.",
            "Pass expected_outputs when calling run_review().",
            8,
        )

    if not checks.get("feature_summary_available"):
        add_issue(
            "feature_summary_unavailable",
            "fail",
            "Could not read the feature tree summary.",
            "If the geometry preview looks fine this can be ignored; to debug the feature tree, check COM member compatibility.",
            8,
        )

    if len(previews) < 2:
        add_issue(
            "too_few_previews",
            "warn",
            "Too few preview views to judge the 3D geometry.",
            "Export at least four views: isometric, front, top, right.",
            8,
        )

    for preview in previews:
        if preview.get("exists") and preview.get("size_bytes", 0) < 10000:
            add_issue(
                "preview_file_too_small",
                "warn",
                f"Preview file is too small: {preview.get('path')}",
                "Confirm the BMP export completed; re-export the preview if needed.",
                5,
            )
        if preview.get("width") and preview.get("height"):
            if preview["width"] < 640 or preview["height"] < 480:
                add_issue(
                    "preview_resolution_low",
                    "warn",
                    f"Preview resolution is low: {preview.get('path')}",
                    "Export at the default 1600x1000 or higher resolution.",
                    4,
                )

    for output in expected_outputs:
        if output.get("exists") and output.get("size_bytes", 0) < 1024:
            add_issue(
                "output_file_too_small",
                "warn",
                f"Output file is too small: {output.get('path')}",
                "Check whether the file is an empty shell or leftover from a failed export.",
                6,
            )

    score = max(0, min(100, score))
    if hard_fail:
        status = "fail"
    elif issues:
        status = "warn"
    else:
        status = "pass"

    return {
        "status": status,
        "score": score,
        "scope": "delivery hygiene only; not engineering or manufacturing qualification",
        "release_status": "pending_visual_review",
        "issues": issues,
        "recommendations": list(dict.fromkeys(recommendations)),
        "manual_review_required": True,
        "manual_review_reason": "Rule-based scoring only catches obvious failures; whether the "
        "final geometry matches the user's intent still requires viewing the previews or screenshots.",
    }


def write_review_report(report, output_path):
    """
    Write the JSON review report.

    Returns:
        Report path string.
    """
    output_path = _expand_path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(output_path, report)
    return str(output_path)


def write_markdown_summary(report, output_path):
    """
    Write the Markdown review summary.

    Returns:
        Summary path string.
    """
    output_path = _expand_path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    evaluation = report.get("evaluation", {})
    checks = report.get("checks", {})
    lines = [
        "# SolidWorks Review Summary",
        "",
        f"- Status: `{evaluation.get('status', 'unknown')}`",
        f"- Score: `{evaluation.get('score', 0)}`",
        f"- Manual review required: `{evaluation.get('manual_review_required', True)}`",
        "",
        "## Checks",
        "",
    ]
    for key, value in checks.items():
        lines.append(f"- `{key}`: `{value}`")

    lines.extend(["", "## Issues", ""])
    issues = evaluation.get("issues", [])
    if issues:
        for issue in issues:
            lines.append(f"- `{issue.get('severity')}` `{issue.get('code')}`: {issue.get('message')}")
    else:
        lines.append("- No rule-based issues.")

    lines.extend(["", "## Recommendations", ""])
    recommendations = evaluation.get("recommendations", [])
    if recommendations:
        for item in recommendations:
            lines.append(f"- {item}")
    else:
        lines.append("- Inspect generated previews and confirm geometry matches the user request.")

    lines.extend(["", "## Previews", ""])
    for preview in report.get("previews", []):
        lines.append(f"- `{preview.get('path')}`")

    with open(output_path, "w", encoding="utf-8") as file:
        file.write("\n".join(lines) + "\n")
    return str(output_path)


def run_review(model, output_dir, basename="review", views=None, expected_outputs=None):
    """
    Run the self-review end to end and write `review_report.json`.

    Returns:
        (report, report_path)
    """
    output_dir = _expand_path(output_dir)
    report = build_review_report(
        model,
        output_dir=output_dir,
        basename=basename,
        views=views,
        expected_outputs=expected_outputs,
    )
    report_path = write_review_report(report, output_dir / f"{basename}_review_report.json")
    summary_path = write_markdown_summary(report, output_dir / f"{basename}_review_summary.md")
    report["summary_path"] = summary_path
    write_review_report(report, report_path)
    return report, report_path


def _parse_args():
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(description="Export SolidWorks multi-view previews and generate a structured self-review report.")
    parser.add_argument("--file", help="SolidWorks file to open and review; if omitted, reviews the current active document.")
    parser.add_argument("--output-dir", required=True, help="Output directory for previews and review_report.json.")
    parser.add_argument("--basename", default="review", help="Output file name prefix.")
    parser.add_argument("--views", default="isometric,front,top,right", help="Comma-separated list of views.")
    parser.add_argument("--expected", action="append", default=[], help="Expected output file; may be given multiple times.")
    parser.add_argument("--version", type=int, help="SolidWorks year, e.g. 2024.")
    parser.add_argument("--silent-open", action="store_true", help="Open --file silently.")
    parser.add_argument("--fail-on-warn", action="store_true", help="Also return a nonzero exit code on warn.")
    return parser.parse_args()


def main():
    """Command-line entry point."""
    args = _parse_args()
    sw, model = connect_solidworks(version=args.version)
    if args.file:
        model = open_document(sw, args.file, silent=args.silent_open, raise_on_error=True)
    if model is None:
        raise RuntimeError("No active SolidWorks document available to review")

    views = [item.strip() for item in args.views.split(",") if item.strip()]
    report, report_path = run_review(
        model,
        output_dir=args.output_dir,
        basename=args.basename,
        views=views,
        expected_outputs=args.expected,
    )
    evaluation = report["evaluation"]
    print(f"Report: {report_path}")
    print(f"Summary: {report.get('summary_path')}")
    print(f"Status: {evaluation['status']} / Score: {evaluation['score']}")
    if evaluation["issues"]:
        print("Issues:")
        for issue in evaluation["issues"]:
            print(f"- [{issue['severity']}] {issue['code']}: {issue['message']}")
    if evaluation["status"] == "fail":
        return 2
    if args.fail_on_warn and evaluation["status"] == "warn":
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
