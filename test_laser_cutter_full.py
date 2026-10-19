"""
Tests for LaserCutterFull.

These import the module directly (not the package __init__, which also pulls in
the Anaglyph/ShadowMap nodes) and exercise the real run() with synthetic
tensors. They cover the behavior added in this fork:

  * up to 10 layer outputs
  * base_layer is optional (blank full-frame backing synthesized when omitted)
  * any input size -> SVG viewBox/size match the real dimensions (no hardcoded 1024)
  * min_shape_area / filter_speckle auto-scale with input resolution

Run: python3 -m pytest test_laser_cutter_full.py -q
 or: python3 test_laser_cutter_full.py   (no pytest required)
"""
import os
import re
import importlib.util

import numpy as np
import torch

# Import LaserCutterFull.py directly, without triggering the package __init__.
_HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location(
    "laser_cutter_full", os.path.join(_HERE, "LaserCutterFull.py")
)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
LaserCutterFull = _mod.LaserCutterFull


def _img(h, w, fill=255):
    """A ComfyUI IMAGE tensor: [batch, H, W, C], float 0-1."""
    arr = np.full((h, w, 3), fill, dtype=np.float32) / 255.0
    return torch.from_numpy(arr).unsqueeze(0)


def _synthetic_inputs(h, w):
    """outlines with a couple of shapes, a gradient depthmap, a base."""
    outlines = np.full((h, w, 3), 255, dtype=np.float32)
    # two filled dark rectangles -> two shapes the node will pick up
    outlines[h // 5:h // 5 * 2, w // 5:w // 5 * 2] = 0.0
    outlines[h // 2:h // 2 + h // 6, w // 2:w // 2 + w // 6] = 0.0
    outlines_t = torch.from_numpy(outlines / 255.0).unsqueeze(0)

    # horizontal brightness gradient depth map
    grad = np.tile(np.linspace(0, 255, w, dtype=np.float32), (h, 1))
    depth = np.stack([grad] * 3, axis=-1) / 255.0
    depth_t = torch.from_numpy(depth).unsqueeze(0)

    base_t = _img(h, w, fill=255)
    return outlines_t, depth_t, base_t


# Default kwargs for run() other than the images / num_divisions.
_PARAMS = dict(
    use_approximation=False,
    approximation_epsilon=0.01,
    shape_similarity_threshold=0.01,
    min_shape_area=250.0,
    apply_blur=False,
    corner_threshold=60,
    length_threshold=4.0,
    max_iterations=10,
    splice_threshold=45,
    path_precision=3,
)


def test_input_types_base_layer_optional():
    it = LaserCutterFull.INPUT_TYPES()
    assert "base_layer" not in it["required"], "base_layer must not be required"
    assert "base_layer" in it.get("optional", {}), "base_layer must be optional"
    assert it["required"]["num_divisions"][1]["max"] == 10


def test_return_ports_count():
    # 10 layer ports + base_layer + combined_svg + debug_info
    assert len(LaserCutterFull.RETURN_TYPES) == 13
    assert len(LaserCutterFull.RETURN_NAMES) == 13
    assert LaserCutterFull.RETURN_NAMES[9] == "layer9"


def test_run_returns_full_tuple_with_base():
    node = LaserCutterFull()
    outlines, depth, base = _synthetic_inputs(256, 256)
    out = node.run(outlines, depth, num_divisions=8, base_layer=base, **_PARAMS)
    # 10 images + base image + svg + debug
    assert len(out) == 13
    combined_svg = out[11]
    assert combined_svg.strip().startswith("<?xml")
    assert "</svg>" in combined_svg


def test_base_layer_optional_runs_without_it():
    node = LaserCutterFull()
    outlines, depth, _ = _synthetic_inputs(256, 256)
    # No base_layer passed at all -> must not raise, must still return 13.
    out = node.run(outlines, depth, num_divisions=6, **_PARAMS)
    assert len(out) == 13
    assert out[11].strip().startswith("<?xml")


def test_svg_viewbox_matches_input_size_not_1024():
    node = LaserCutterFull()
    # Non-square, non-1024 landscape input.
    h, w = 300, 800
    outlines, depth, base = _synthetic_inputs(h, w)
    out = node.run(outlines, depth, num_divisions=6, base_layer=base, **_PARAMS)
    svg = out[11]
    m = re.search(r'viewBox="0 0 (\d+) (\d+)"', svg)
    assert m, "viewBox missing"
    assert (int(m.group(1)), int(m.group(2))) == (w, h), \
        f"viewBox should be {w}x{h}, got {m.group(1)}x{m.group(2)}"
    # explicit width/height too, and definitely not the old hardcoded 1024
    assert f'width="{w}"' in svg and f'height="{h}"' in svg
    assert 'viewBox="0 0 1024 1024"' not in svg


def test_detail_filters_scale_when_enabled():
    node = LaserCutterFull()
    # 2048 long edge -> scale 2.0 -> min_shape_area *4, filter_speckle 4->8,
    # but ONLY when auto_scale_detail=True.
    outlines, depth, base = _synthetic_inputs(2048, 2048)
    out = node.run(outlines, depth, num_divisions=6, base_layer=base,
                   auto_scale_detail=True, **_PARAMS)
    debug = out[12]
    assert "Detail auto-scale ON" in debug
    assert "scale=2.00" in debug
    assert "min_shape_area 250.0->1000" in debug
    assert "filter_speckle 4->8" in debug


def test_detail_scaling_off_by_default():
    node = LaserCutterFull()
    # Without auto_scale_detail, min_shape_area is used exactly as set,
    # regardless of input size.
    outlines, depth, base = _synthetic_inputs(2048, 2048)
    out = node.run(outlines, depth, num_divisions=6, base_layer=base, **_PARAMS)
    debug = out[12]
    assert "Detail auto-scale OFF" in debug
    assert "min_shape_area=250.0 (as set)" in debug


def test_runs_with_no_depth_layers():
    # A blank-outlines input produces no shapes -> the layer loop never runs.
    # This used to hit UnboundLocalError on `color` in the base-layer block.
    node = LaserCutterFull()
    h, w = 256, 256
    blank_outlines = torch.from_numpy(
        np.full((h, w, 3), 255, dtype=np.float32) / 255.0
    ).unsqueeze(0)
    _, depth, _ = _synthetic_inputs(h, w)
    out = node.run(blank_outlines, depth, num_divisions=6, **_PARAMS)
    assert len(out) == 13
    assert out[11].strip().startswith("<?xml")
    assert "</svg>" in out[11]


def test_shapes_bucket_across_layers_by_depth():
    # Two shapes at clearly different depths must land on DIFFERENT layers,
    # not both dumped on layer 0 (the old first-free-slot bug).
    node = LaserCutterFull()
    h, w = 400, 400
    # outlines: two separate boxes (dark-on-light so the node picks them up)
    outlines = np.full((h, w, 3), 255, dtype=np.float32)
    outlines[40:140, 40:140] = 0.0      # box A (near region)
    outlines[260:360, 260:360] = 0.0    # box B (far region)
    outlines_t = torch.from_numpy(outlines / 255.0).unsqueeze(0)

    # depthmap: box A region bright (near ~230), box B region dark (far ~30)
    depth = np.full((h, w), 10, dtype=np.float32)
    depth[40:140, 40:140] = 230
    depth[260:360, 260:360] = 30
    depth_t = torch.from_numpy(np.stack([depth] * 3, axis=-1) / 255.0).unsqueeze(0)

    p = dict(_PARAMS)
    p["min_shape_area"] = 50.0  # keep both ~100x100 boxes
    out = node.run(outlines_t, depth_t, num_divisions=8, **p)
    debug = out[12]
    # The two boxes must be reported in two different layers.
    import re as _re
    counts = _re.search(r"shapes per layer: (\{[^}]*\})", debug)
    assert counts, f"debug missing per-layer counts:\n{debug}"
    populated = [int(n) for n in _re.findall(r":\s*(\d+)", counts.group(1)) if int(n) > 0]
    assert len(populated) >= 2, f"shapes should span >=2 layers by depth, got {counts.group(1)}"


def test_depth_bands_mode_makes_connected_layers():
    # depth_bands mode slices the depth map itself; a gradient depth map should
    # populate multiple cumulative bands, independent of `outlines`.
    node = LaserCutterFull()
    h, w = 300, 400
    # vertical depth gradient: top far (dark) -> bottom near (bright)
    grad = np.tile(np.linspace(0, 255, h, dtype=np.float32).reshape(h, 1), (1, w))
    depth_t = torch.from_numpy(np.stack([grad] * 3, axis=-1) / 255.0).unsqueeze(0)
    # outlines is irrelevant in this mode; pass a blank
    blank = torch.from_numpy(np.full((h, w, 3), 255, dtype=np.float32) / 255.0).unsqueeze(0)
    p = dict(_PARAMS)
    p["min_shape_area"] = 50.0
    out = node.run(blank, depth_t, num_divisions=5, layer_mode="depth_bands", **p)
    assert len(out) == 13
    debug = out[12]
    assert "depth_bands" in debug
    assert "regions per band" in debug
    svg = out[11]
    # Several band groups should be present in the SVG.
    assert svg.count("layer_") >= 3, f"expected multiple depth bands in SVG:\n{debug}"


def test_layer_mode_defaults_to_outline_shapes():
    it = LaserCutterFull.INPUT_TYPES()
    assert it["optional"]["layer_mode"][1]["default"] == "outline_shapes"
    assert "depth_bands" in it["optional"]["layer_mode"][0]


def test_manual_layers_mode():
    # Each supplied slot becomes its own layer; outlines/depthmap ignored.
    node = LaserCutterFull()
    h, w = 256, 256
    def box(cx, cy, s=60):
        im = np.full((h, w, 3), 255, dtype=np.float32)
        im[cy-s//2:cy+s//2, cx-s//2:cx+s//2] = 0.0
        return torch.from_numpy(im / 255.0).unsqueeze(0)
    blank = torch.from_numpy(np.full((h, w, 3), 255, dtype=np.float32) / 255.0).unsqueeze(0)
    p = dict(_PARAMS)
    p["min_shape_area"] = 50.0
    out = node.run(blank, blank, num_divisions=2, layer_mode="manual_layers",
                   layer_img_0=box(80, 80), layer_img_1=box(180, 180),
                   layer_img_2=box(128, 200), **p)
    assert len(out) == 13
    debug = out[12]
    assert "manual_layers (3 slots connected)" in debug
    svg = out[11]
    # three distinct layer groups present
    for g in ("layer_0", "layer_1", "layer_2"):
        assert g in svg, f"{g} missing from manual-layers SVG:\n{debug}"


def test_manual_layers_in_input_enum():
    it = LaserCutterFull.INPUT_TYPES()
    assert "manual_layers" in it["optional"]["layer_mode"][0]
    for n in range(10):
        assert f"layer_img_{n}" in it["optional"]


def test_saves_svg_file_when_enabled():
    # save_svg=True must write a real .svg file. In standalone mode
    # (folder_paths unavailable) it writes next to the module; assert it lands.
    import glob
    node = LaserCutterFull()
    h, w = 200, 200
    def box(cx, cy, s=60):
        im = np.full((h, w, 3), 255, dtype=np.float32)
        im[cy-s//2:cy+s//2, cx-s//2:cx+s//2] = 0.0
        return torch.from_numpy(im / 255.0).unsqueeze(0)
    blank = torch.from_numpy(np.full((h, w, 3), 255, dtype=np.float32) / 255.0).unsqueeze(0)
    p = dict(_PARAMS)
    p["min_shape_area"] = 50.0
    prefix = "pytest_lasercut"
    for f in glob.glob(os.path.join(_HERE, prefix + "_*.svg")):
        os.remove(f)
    out = node.run(blank, blank, num_divisions=2, layer_mode="manual_layers",
                   layer_img_0=box(80, 80), save_svg=True,
                   svg_filename_prefix=prefix, **p)
    debug = out[12]
    written = glob.glob(os.path.join(_HERE, prefix + "_*.svg"))
    assert written, f"no .svg written; debug:\n{debug}"
    content = open(written[0]).read()
    assert content.startswith("<?xml") and "<svg" in content
    for f in written:
        os.remove(f)


def test_contours_to_image_skips_degenerate_contours():
    # approxPolyDP (or any trace) can reduce a contour to 1-2 points. PIL's
    # draw.polygon raises "coordinate list must contain at least 2 coordinates"
    # on those. contours_to_image must skip them, not crash.
    node = LaserCutterFull()
    debug = []
    one_point = np.array([[[10, 10]]], dtype=np.int32)          # 1 point
    two_point = np.array([[[10, 10]], [[20, 20]]], dtype=np.int32)  # 2 points
    good = np.array([[[5, 5]], [[50, 5]], [[50, 50]], [[5, 50]]], dtype=np.int32)
    # Must not raise, and should still render the valid contour.
    img = node.contours_to_image([one_point, two_point, good], (100, 100), debug)
    assert img.size == (100, 100)


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for fn in fns:
        try:
            fn()
            print(f"PASS {fn.__name__}")
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(f"FAIL {fn.__name__}: {e}")
    print(f"\n{len(fns) - failed}/{len(fns)} passed")
    raise SystemExit(1 if failed else 0)
