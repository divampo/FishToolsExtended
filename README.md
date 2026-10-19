# FishTools

## LaserCutterFull

***

### Description

The `LaserCutterFull` node processes an outline image, a depth map, and a base layer image to generate multiple layers for laser cutting. It assigns each layer based on the intensity values from the depth map and creates an SVG output combining all layers.

<img src="Examples/mickey.png" alt="Mickey example" width="300" height="300">
<img src="Examples/mickeyIRL.png" alt="Mickey example" width="300" height="300">

### Inputs

- `outlines`: The outline image (in grayscale). This should be simple line art.
- `depthmap`: The depth map image (in grayscale). Use depth-to-anything with a mask to filter out background noise.
- `base_layer` *(optional)*: The base layer image (in grayscale) — the solid bottom slab of the stack. **Leave it unconnected for landscapes / scenes with no clear subject**: the node then synthesizes a blank full-frame backing the same size as `outlines`. When you do connect it, use a solid silhouette (e.g. the mask from depth-to-anything), not a photo.
- `num_divisions`: The number of layers to divide the depth map into (2–10).
- `use_approximation`: Boolean to toggle the use of contour approximation.
- `approximation_epsilon`: Epsilon value for the contour approximation.
- `shape_similarity_threshold`: Threshold for filtering nearly identical shapes.
- `min_shape_area`: Minimum area (in **pixels²**) for a shape to be kept — the main noise filter. Default **5000**, tuned for large source images (multi-thousand-px). This threshold is **absolute pixels**, so the right value scales with your image size (see *Sizing `min_shape_area`* below). Too high → empty/sparse layers; too low → a flood of tiny meaningless cut paths.
- `apply_blur`: Boolean to apply Gaussian blur to the depth map.
- `corner_threshold`: Threshold for corner detection in the SVG conversion.
- `length_threshold`: Threshold for path length in the SVG conversion.
- `max_iterations`: Maximum number of iterations for the SVG conversion.
- `splice_threshold`: Threshold for splicing paths in the SVG conversion.
- `path_precision`: Precision for path coordinates in the SVG output.
- `auto_scale_detail` *(optional, default off)*: When on, `min_shape_area` and the speckle filter are multiplied to the input resolution (calibrated to a ~1024px long edge), keeping the *relative* amount of detail constant at any size. **Leave it off for line-art / Canny-edge inputs** — on a large image it scales `min_shape_area` up steeply (~24× at 5000px) and can erase thin edge shapes. Turn it on only for solid-region inputs where you want size-invariant filtering without hand-tuning.
- `layer_mode` *(optional, default `outline_shapes`)*: how layers are formed — see *Layer modes* below.
- `layer_img_0` … `layer_img_9` *(optional)*: per-layer images used only in `manual_layers` mode — wire a Load Image into each layer you want, in order. Ignored in the other modes.

#### Layer modes

- **`outline_shapes`** (default): trace discrete shapes from the `outlines` image and bucket each one by its depth. Good when your subject is made of distinct outlined objects. Downside: if the outline has separate regions you get **disconnected islands**, one shape per layer fragment.
- **`depth_bands`** (topographic): ignore `outlines` entirely and slice the **depth map itself** into `num_divisions` **cumulative** bands. Band *k* is every pixel at depth ≥ its threshold, so each layer is a **connected, edge-to-edge region** that stacks like a staircase — no scattered islands. This is the mode for landscapes and any image where you liked the depth but not the fragmented shapes. `base_layer` and `outlines` are not used; the look is driven purely by the depth gradient, and **fewer `num_divisions` (3–5) gives broader, more connected layers**. The `debug_info` output reports `regions per band: {...}` so you can see how each band traced. (Needs a depth map with real tonal range — a near-flat/blown-out depth map makes every band identical.)
- **`manual_layers`** (you supply each layer): ignore `outlines`/`depthmap` and build layers from images **you** provide via the optional `layer_img_0` … `layer_img_9` inputs. Each connected slot becomes one layer, in slot order (slot 0 → layer 0). This is the full-control mode: mask each object yourself (e.g. in Lightroom), export each as a high-contrast **dark-on-light** image at the **same size**, and wire them into the slots. Leave unused slots empty. `base_layer` still works as the backing. `debug_info` reports `Manual layers: N supplied, shapes per layer: {...}`.

#### Sizing `min_shape_area`

`min_shape_area` is in **absolute pixels²**, so its effect depends entirely on your image resolution. The default **5000** suits large sources; drop it for smaller ones. Rough starting points (then adjust by reading `shapes per layer` in `debug_info`):

| Source long edge | Start `min_shape_area` |
|---|---|
| ~1024 px | 250 |
| ~2000 px | 1000 |
| ~3000 px | 2500 |
| ~5000 px | 5000 |
| larger | scale ∝ (long_edge)² — e.g. double the edge → ×4 the area |

Tuning: raise it if layers are noisy with tiny specks; lower it if layers come out empty or sparse. The `debug_info` output reports `Shapes found: N` and `shapes per layer: {...}` — aim for shapes in the tens–hundreds spread across several layers. `Shapes found: 0` means your `outlines` isn't dark-on-light (invert it); everything in one layer means the depth map is flat over the subject.

### Outputs

- `layer0` to `layer9`: Up to ten layers generated for laser cutting (one image output per possible layer; outputs beyond `num_divisions` are returned as blank white images).
- `base_layer`: The base layer image.
- `combined_svg`: The combined SVG string of all layers. *Note* You will need to save this file with a .svg extension. In the example workflow, this is done with a simple Save Text node.
- `debug_info`: Debug information string.

### Variables

- `num_divisions`: Integer specifying the number of depth layers to generate. Minimum is 2, maximum is 10, default is 6.
- `use_approximation`: Boolean to enable or disable the use of contour approximation.
- `approximation_epsilon`: Float specifying the epsilon value for contour approximation. Default is 0.01, range is 0.001 to 1.0.
- `shape_similarity_threshold`: Float specifying the threshold for filtering nearly identical shapes. Default is 0.01, range is 0.0 to 1.0.
- `min_shape_area`: Float specifying the minimum area for a shape to be considered. Default is 250.0, range is 0.0 to 1000.0.
- `apply_blur`: Boolean to apply Gaussian blur to the depth map. Default is False.
- `corner_threshold`: Integer for corner detection in SVG conversion. Default is 60, range is 0 to 100.
- `length_threshold`: Float for path length threshold in SVG conversion. Default is 4.0, range is 0.0 to 10.0.
- `max_iterations`: Integer for maximum iterations in SVG conversion. Default is 10, range is 1 to 20.
- `splice_threshold`: Integer for splicing paths in SVG conversion. Default is 45, range is 1 to 100.
- `path_precision`: Integer for precision of path coordinates in SVG. Default is 3, range is 1 to 10.

### Implementation Details

1. The node preprocesses input images and extracts contours from the outline and base layer images.
2. It calculates intensities for each shape based on the depth map.
3. Shapes are assigned to different layers based on their intensities.
4. The node generates an SVG for each layer and combines them into a single SVG file.
5. The output includes separate image layers, a combined SVG, and debug information.

### Usage Tips

- Ensure your input images (outlines, depth map, and base layer) are properly prepared and aligned.
- Experiment with the `num_divisions` parameter to achieve the desired level of depth separation.
- Adjust `min_shape_area` to filter out small, unwanted shapes.
- Use the `apply_blur` option if the depth map contains noise that affects layer assignment.
- Fine-tune SVG conversion parameters (`corner_threshold`, `length_threshold`, etc.) for optimal vector output.

### Note on SVG Output

The combined SVG output includes all layers and the base layer. Each layer is grouped with a unique ID for easy manipulation in vector graphics software. Remember to save the SVG output with a .svg extension using a Save Text node or similar method in your workflow.

### Getting Started — your first laser-cut SVG

FishTools is a **ComfyUI custom-node pack**, not a standalone program. `LaserCutterFull` is a node you drop onto the ComfyUI canvas, so running it means running ComfyUI and wiring up a small graph. This walkthrough takes you from nothing to one finished SVG with a single picture.

#### 1. Install ComfyUI

If you don't already have it, install ComfyUI (the desktop app or the manual install — see the [ComfyUI repo](https://github.com/comfyanonymous/ComfyUI)). You'll end up with a `ComfyUI/` folder you launch with `python main.py`. Confirm it works on its own first: start it, open `http://127.0.0.1:8188` in your browser, and you should see an empty node canvas.

#### 2. Install FishTools into ComfyUI

Clone this pack into ComfyUI's `custom_nodes` folder and install its Python dependencies:

```bash
cd /path/to/ComfyUI/custom_nodes
git clone https://github.com/divampo/FishToolsExtended.git
cd FishToolsExtended
pip install -r requirements.txt
```

The pack has to live inside ComfyUI's own `custom_nodes` directory (e.g. `ComfyUI/custom_nodes/FishToolsExtended`) — that's the only place ComfyUI scans for nodes.

#### 3. Launch ComfyUI

Start the server from the ComfyUI root (not from the pack folder):

```bash
cd /path/to/ComfyUI
python main.py
```

Watch the startup log — you should see `### Loading: FishTools (0.3)` scroll by, which confirms the node was picked up. When it prints something like `To see the GUI go to: http://127.0.0.1:8188`, open that URL in your browser. On the canvas, right-click → Add Node → **FishTools** should now list **LaserCutterFull**.

> If you use the **ComfyUI desktop app** instead of the command line, you don't run `python main.py` — just drop the pack into the app's `custom_nodes` directory and restart the app. The node appears the same way.

#### 4. Prepare your one picture

`LaserCutterFull` needs **at least two grayscale images — `outlines` and `depthmap` — the same size as each other and aligned**. `base_layer` is optional (see below). They are different *views* of the same source photo:

| Input | What it is | Looks like |
|-------|-----------|-----------|
| `outlines` | clean line art / edges of the subject | black lines on white |
| `depthmap` | how near/far each pixel is | white = near, black = far |
| `base_layer` | the solid bottom/backing slab | white filled shape on black (silhouette for a subject, or a full solid frame for a scene) |

Say you have one **high-res photo** (e.g. 4000×3000). Here's how to turn it into those three, start to finish. Do the **common pre-step first**, then pick **Path A (all inside ComfyUI)** or **Path B (an image editor)** for the three conversions.

**Common pre-step — normalize the source**

1. **Crop to your subject** and remove distractions. Tight framing gives cleaner layers.
2. **Pick a working size.** Output is SVG, so resolution isn't a quality ceiling — but `outlines` and `depthmap` **must be the same size as each other and aligned** (the node samples depth per pixel across both). Larger inputs (e.g. 3000–4000 px) work fine and produce a correspondingly larger SVG; the node auto-scales its detail filters (`min_shape_area`, speckle) to the input size, so you don't get a flood of tiny meaningless cut paths on a big image. Going much smaller than ~1024 px just loses detail. You do **not** need to match `base_layer` to anything if you leave it unconnected.
3. Keep this normalized copy as your working source so `outlines` and `depthmap` stay registered to each other.

**Path A — generate all three inside ComfyUI (recommended; no manual masking)**

This is why FishTools lives in ComfyUI: other nodes make the hard inputs for you.

- `depthmap`: add a **Depth-Anything** node (install via ComfyUI-Manager), feed it your normalized photo. It outputs a depth map directly — near surfaces bright, far ones dark. That's exactly the `depthmap` input.

  **Where the depth model file goes:** download the Depth-Anything checkpoint (e.g. `depth_anything_3_mono_large.safetensors` — a monocular, relative-depth model) and drop it in ComfyUI's **`models/geometry_estimation/`** folder:

  ```
  ComfyUI/models/geometry_estimation/depth_anything_3_mono_large.safetensors
  ```

  Then **restart ComfyUI** (or click Refresh) so it rescans — the file now appears in the depth loader node's model dropdown. Two gotchas: (1) it's the depth *loader* node that reads this folder, not FishTools, so if the file doesn't show up your depth node reads a different path (some third-party packs use `models/depthanything/` or a folder under the custom node); (2) a **V3** checkpoint needs a V3-aware node — a V2-only node won't load it even from the right folder. Don't put it in `models/controlnet/`; that's for ControlNet conditioning models, not depth estimators.
- `base_layer`: this is the **bottom/backing slab** — the solid shape that sits under all the depth layers. Internally the node just thresholds it and traces its outline, so it only cares about the overall filled area, **not** a figure-vs-background split.
  - **Subject photos** (one clear object on a background): a background-removal node (**RemBG** / `Image Remove Background`) fed the normalized photo gives you the subject mask (white subject on black) — a silhouette backing. Good when "the subject" is well-defined.
  - **Landscapes / scenes with no clear background:** don't bother — **leave `base_layer` unconnected**. The node synthesizes a blank full-frame backing the same size as `outlines` automatically, which is exactly what you want for a scene (the base is the whole rectangle). RemBG wouldn't help here anyway — there's no single subject to isolate. All the depth separation comes from the `depthmap`, not from `base_layer`.

  > **Want an engraved photo as the backing instead of a plain slab?** You can't get it out of this node, and it's worth knowing why. `LaserCutterFull` thresholds `base_layer` to black/white, traces it to vector paths, and strips every fill to `fill="none"` — so the base in the output SVG is **only a cut outline**, never a shaded/raster image. A grayscale photo fed here would just be traced into meaningless cut squiggles, not engraved. A laser-engraved picture is a **raster** operation (the laser rasters back and forth varying power per pixel), which is a separate asset you add in your laser software, not in ComfyUI:
  >
  > 1. Run `LaserCutterFull` as usual for the multi-layer **cut** SVG (depth layers + base outline).
  > 2. Separately, take your normalized photo, convert to grayscale, resize it to the base-layer dimensions, boost contrast, and apply **dithering / halftone** (e.g. Floyd–Steinberg or Jarvis) so it engraves cleanly — do this in your laser software or a tool like ImageMagick.
  > 3. In the laser software (LightBurn, etc.) import **both**, aligned to the same frame: the grayscale photo on the bottom set to **raster / engrave** mode, and the cut SVG on top set to **cut / line** mode.
  > 4. The laser engraves the photo into the bottom slab first, then cuts the stacked layers — a shaded background instead of a blank one.
  >
  > If you'd rather the node emit an engrave-ready raster directly (a passthrough output that skips the vector tracing, aligned to the cut), that's a small code change — ask and it can be added.
- `outlines`: add a line-art / edge node (a **Canny** preprocessor, or a line-art preprocessor from the ControlNet aux pack). Feed the normalized photo; out comes black-on-white line art.

Because these nodes all take the *same* normalized image, their outputs are automatically the same size and aligned — no manual registration. Wire them straight into LaserCutterFull (connect node→node instead of using Load Image at all), or save each out and load the files. For a landscape you only need the `outlines` and `depthmap` nodes — leave `base_layer` unconnected.

**Path B — make them by hand in an image editor (Photoshop / GIMP / Affinity)**

If you'd rather not install the extra nodes, produce three files from the normalized source and load them as files:

1. `outlines.png` — duplicate the photo, desaturate, then apply an edge/line filter (GIMP: *Filters → Edge-Detect → Edge*; Photoshop: *Filter → Stylize → Find Edges* then invert to black-on-white). Clean up stray specks. Export same size as the source.
2. `base_layer.png` *(optional)* — the solid bottom slab. For a **subject photo**, select the subject (quick-select / magic wand), fill it white and the background black, export same size. For a **landscape / scene**, you can skip this file entirely and leave the node's `base_layer` input unconnected — it fills in a full-frame white backing for you.
3. `depthmap.png` — the honest catch: a real depth map needs a model. By hand you can only *fake* it — paint a grayscale gradient where parts you want "closer" are brighter and farther parts darker (e.g. brighten the face/front, darken the edges). It won't be physically accurate but it drives the layer split fine for a first cut. For a true depth map, use Path A's Depth-Anything node. Export same size.

**Fastest first test (skip prep entirely)**

To just see the node work before preparing anything, load the bundled sample `Examples/mickey.png` into both `outlines` and `depthmap` (leave `base_layer` empty). The output won't be a meaningful depth cut, but it proves your graph is wired and the node runs.

#### 5. Build the minimal graph

A ComfyUI "graph" is just boxes (nodes) you drop on the canvas and wires you drag between them. The minimum here is **two** image loaders (`outlines`, `depthmap`) feeding one LaserCutterFull node — add a **third** loader for `base_layer` only if you have a subject silhouette; for landscapes leave it off. Work on an empty canvas (if the demo graph is loaded, **Clear** it from the menu first so nothing else is wired in).

**1. Add the Load Image nodes — one each for outlines and depthmap (and base_layer if you have one).**

- Open the Add Node menu: **double-click an empty spot on the canvas** to get the search box (fastest), or **right-click → Add Node → image → Load Image**.
- Type `Load Image` and add it. Make a **separate** Load Image node per input — two for a landscape (`outlines`, `depthmap`), three if you're also supplying `base_layer`. Don't reuse one loader for multiple inputs.
- In each Load Image node, click the image thumbnail (or the **choose file / upload** button) and pick the matching file. Optionally rename each node (double-click its title bar) to `outlines` / `depthmap` / `base_layer` so you can see which is which.
- `outlines` and `depthmap` must be the **same pixel dimensions and aligned** — LaserCutterFull samples them together, so a size mismatch between those two gives misregistered layers. `base_layer`, if used, should match too.

**2. Add the LaserCutterFull node.**

- Double-click the canvas (or right-click → Add Node) and type `LaserCutterFull`, or browse **Add Node → FishTools → LaserCutterFull**. If it isn't in the list, FishTools didn't load — recheck step 2 of Getting Started (the `### Loading: FishTools` line in the launch log) and restart ComfyUI.
- The node drops in with `outlines` and `depthmap` as required image inputs on the **left edge**, plus an **optional** `base_layer` input (shown dashed — you can leave it empty). Its outputs (`layer0`…`layer9`, `base_layer`, `combined_svg`, `debug_info`) are on the **right edge**. The parameters (`num_divisions`, `apply_blur`, etc.) are the widgets in the node body — leave those for step 6.

**3. Connect each Load Image to its matching input on LaserCutterFull.**

- Each Load Image node has an **`IMAGE` output dot on its right edge**. Click-and-drag from that dot to the matching **input dot on LaserCutterFull's left edge**, then release — a wire snaps into place. Inputs and outputs are color-coded by type; the `IMAGE` ports are the same color, so a wire only connects where the types match.
- Make the connections, matching by meaning (not just position):
  - the outlines loader's `IMAGE` → **`outlines`** input
  - the depthmap loader's `IMAGE` → **`depthmap`** input
  - (optional) the base_layer loader's `IMAGE` → **`base_layer`** input — skip for a landscape; the node fills a blank full-frame backing itself.
- Double-check `depthmap` lands on the `depthmap` port specifically — depth is sampled from that port, so a mis-wire cuts nonsense. Hover an input dot and ComfyUI shows its name as a tooltip if the labels are hard to read.
- To fix a wrong wire, drag a new one onto the same input (it replaces the old), or click the input dot and drag the wire off into empty space to detach it.

4. Add a **Save Text** node (from the pysssss pack, or any text-saver) and connect the `combined_svg` output of LaserCutterFull into it. Set its extension to `.svg`. (`combined_svg` is a `STRING` output, so it only connects to a text input — a different color from the IMAGE ports.)
5. Optionally add **Preview Image** nodes and wire `layer0`, `layer1`, … into them to eyeball each layer as a separate preview.

#### 6. Set parameters and run

On the LaserCutterFull node set `num_divisions` to `8`, turn `apply_blur` on, and leave the rest at defaults. Click **Queue Prompt**. ComfyUI runs the graph and the Save Text node writes your colored `.svg` into ComfyUI's `output/` folder — that's the file you send to the laser cutter.

If a layer comes out empty or noisy, check the `debug_info` output (wire it to a Preview or Show Text node): it reports how many shapes landed in each layer, which tells you whether to lower `min_shape_area` or toggle `apply_blur`.

> **Shortcut:** this repo ships a complete `workflow.json` that already builds the entire pipeline — including the Depth-Anything depth estimation, background removal, and line-art extraction — so you don't have to wire it by hand. Load it with the **Load** button in ComfyUI. Note it depends on several extra custom-node packs (Depth-Anything-V2, RemBG, ComfyUI-Easy-Use, Comfyroll, pysssss, line-art preprocessors) plus a Stable Diffusion checkpoint; install any missing ones through **ComfyUI-Manager**, which flags the red "missing node" boxes for you.

### Usage Examples

This fork raises `num_divisions` from 6 to 10, so you can split a depth map into up to ten laser-cut layers. The two examples below walk from a minimal setup to a tuned multi-layer run.

#### Simple start — 8 layers

Good first run to see depth separation working end to end.

1. Prepare the grayscale inputs (`outlines` and `depthmap` the same size and aligned):
   - `outlines` — simple line art (e.g. `Examples/mickey.png`).
   - `depthmap` — a depth map from Depth-Anything, masked so the background is removed.
   - `base_layer` *(optional)* — a masked silhouette for the bottom of the cut; omit it for a landscape and the node fills a full-frame backing.
2. Load them with Load Image nodes and feed them into `LaserCutterFull` (leave the `base_layer` input empty if you're skipping it).
3. Set the parameters:

   | Parameter | Value |
   |---|---|
   | `num_divisions` | `8` |
   | `use_approximation` | `False` |
   | `min_shape_area` | `250.0` |
   | `apply_blur` | `True` (smooths depth-map noise) |

   Leave every other parameter at its default.
4. Wire the `combined_svg` output into a Save Text node and save it with a `.svg` extension.
5. Run. You now have eight depth layers (`layer0`–`layer7`) plus the base, combined into one colored SVG ready for the laser cutter.

<img src="Examples/mickey.png" alt="8-layer input example" width="300" height="300">
<img src="Examples/mickeyIRL.png" alt="8-layer laser-cut result" width="300" height="300">

#### Advanced example — 10 layers, tuned output

Use the full ten layers and tune contour extraction and vector tracing for a clean, detailed cut on a busier subject (e.g. `Examples/sandwich monster.png`).

1. Prepare the same three aligned grayscale inputs at higher resolution.
2. Set the parameters:

   | Parameter | Value | Why |
   |---|---|---|
   | `num_divisions` | `10` | maximum depth separation (the color tables hold exactly 10 entries, so layer colors never repeat) |
   | `apply_blur` | `True` | removes depth-map banding before layer assignment |
   | `use_approximation` | `True` | simplifies contours |
   | `approximation_epsilon` | `0.01` | lower = more faithful, higher = simpler shapes |
   | `min_shape_area` | `400.0` | drops tiny specks that would become uncuttable slivers |
   | `corner_threshold` | `60` | sharper corners in the traced SVG |
   | `length_threshold` | `4.0` | discards very short path segments |
   | `max_iterations` | `10` | vector-fit passes |
   | `splice_threshold` | `45` | path-splicing in the trace |
   | `path_precision` | `3` | coordinate precision in the output SVG |

3. Wire `combined_svg` into a Save Text node (`.svg`).
4. Inspect the `debug_info` output if a layer looks empty — it reports how many shapes landed in each layer and the total processed, which tells you whether to lower `min_shape_area` or adjust `apply_blur`.
5. Run. You get ten depth layers (`layer0`–`layer9`), each a distinct color in the combined SVG.

> **Note on colors:** the per-layer `layerN` image outputs are monochrome outlines (black on white) regardless of layer. The layer colors appear only in the `combined_svg` output, where each layer's paths carry a unique stroke color — that is the file you cut from.

> **Tip:** more layers means thinner depth bands. If adjacent layers look nearly identical, either reduce `num_divisions` or increase depth contrast in the depth map before feeding it in.

***
## AnaglyphCreator

### Description

The `AnaglyphCreator` node generates anaglyph 3D images from a 2D image and its corresponding depth map. It creates a stereoscopic effect by shifting the color channels based on the depth information, resulting in an image that appears three-dimensional when viewed with red-cyan 3D glasses.

<img src="Examples/Baller3D.png" alt="Baller example" width="500" height="500">

### Inputs

- `image`: The original 2D image (in color or grayscale).
- `depthmap`: The depth map image (in grayscale). This represents the relative depth of each pixel in the original image.
- `anaglyph_shift`: A float value determining the intensity of the 3D effect.

### Outputs

- `anaglyph_image`: The final anaglyph 3D image.
- `visualization_image`: A visualization of the pixel shifts applied to create the anaglyph effect for debugging purposes.
- `overlap_mask`: An image showing the overlap between the left and right eye views for debugging purposes.
- `left_debug_image`: The left eye view (cyan channels) for debugging purposes.
- `right_debug_image`: The right eye view (red channel) for debugging purposes.

### Variables

- `anaglyph_shift`: Float specifying the intensity of the 3D effect. Minimum is 0.0, maximum is 20.0, default is 5.0, with a step of 0.1.

### Tips for Best Results

1. Use high-contrast images with clear edges for the best 3D effect.
2. Experiment with the `anaglyph_shift` value to find the right balance between 3D depth and viewing comfort.
3. Ensure your depth map accurately represents the relative depths in your image for the most realistic 3D effect.
4. For color images, be aware that some color information may be lost due to the nature of anaglyph 3D creation.

### Known Limitations

1. Color images may appear slightly blurry in the final anaglyph. This is a known issue that may be addressed in future updates.
2. Very large shift values may cause noticeable artifacts, especially around the edges of the image.

## AnaglyphCreatorPro

### Description

The `AnaglyphCreatorPro` node is an advanced version of the AnaglyphCreator, offering more control and flexibility in creating stereoscopic 3D images. It generates anaglyph 3D images, side-by-side stereo pairs, or top-bottom stereo pairs from a 2D image and its corresponding depth map. This node provides various parameters to fine-tune the 3D effect and offers different fill techniques for handling occlusions.

<img src="Examples/AnaglyphPro/building.png" alt="example" width="500" height="500">
<img src="Examples/AnaglyphPro/building-s.png" alt="example" width="500" height="250">
<img src="Examples/AnaglyphPro/t2.png" alt="example" width="500" height="500">
<img src="Examples/AnaglyphPro/t2-s.png" alt="example" width="500" height="250">


### Inputs

- `image`: The original 2D image (in color).
- `depthmap`: The depth map image (in grayscale). This represents the relative depth of each pixel in the original image.
- `divergence`: A float value determining the intensity of the 3D effect.
- `separation`: A float value controlling the horizontal separation between left and right views.
- `stereo_balance`: A float value balancing the stereo effect between left and right views.
- `stereo_offset_exponent`: A float value controlling the non-linearity of the stereo offset.
- `fill_technique`: The method used to fill occluded areas ("naive", "naive_interpolating", "polylines_soft", "polylines_sharp").
- `output_mode`: The type of output to generate ("red-cyan-anaglyph", "left-right", "top-bottom").

### Outputs

- `IMAGE`: The final stereoscopic image based on the selected output mode.

### Variables

- `divergence`: Float specifying the intensity of the 3D effect. Range: 0.0 to 20.0, default: 5.0, step: 0.1.
- `separation`: Float controlling the horizontal separation. Range: -10.0 to 10.0, default: 0.0, step: 0.1.
- `stereo_balance`: Float balancing left and right views. Range: -1.0 to 1.0, default: 0.0, step: 0.1.
- `stereo_offset_exponent`: Float for non-linear stereo offset. Range: 0.1 to 5.0, default: 1.0, step: 0.1.
- `fill_technique`: String selecting the occlusion fill method. Options: "naive", "naive_interpolating", "polylines_soft", "polylines_sharp".
- `output_mode`: String selecting the output type. Options: "red-cyan-anaglyph", "left-right", "top-bottom".

### Tips for Best Results

1. Experiment with `divergence` and `separation` to find the right balance between 3D depth and viewing comfort.
2. Use `stereo_balance` to adjust the relative shift between left and right views.
3. Adjust `stereo_offset_exponent` to control the non-linearity of the depth effect.
4. Try different `fill_technique` options to handle occlusions effectively, especially for images with large depth variations.
5. Choose the appropriate `output_mode` based on your intended viewing method (anaglyph glasses or stereo displays).

### Known Limitations

1. Very large divergence or separation values may cause noticeable artifacts, especially around the edges of the image.
2. The effectiveness of different fill techniques may vary depending on the image content and depth map quality.

## Deptherize

### **NOTE**:

The current version of LaserCutterFull does not work with Deptherize (which is really only for making a fake preview anyway)

### Description

The `Deptherize` node converts SVG data into a depth map image. Each layer in the SVG data is assigned a grayscale value to represent depth.

### Inputs

- `svg_data`: The SVG data as a string.

### Outputs

- `depth`: The generated depth map image.
- `debug_info`: Debug information string.

### Variables

- `svg_data`: String containing the SVG data.

## Installation

To install the required packages, run:

```bash
pip install -r requirements.txt
```

## Requirements

The required packages are listed in the `requirements.txt` file:

```
torch
numpy
opencv-python-headless
svgwrite
scikit-image
svgtools
vtracer
svgpathtools
```

## License

This project is licensed under the MIT License.

## Contributing

Contributions are welcome! Please open an issue or submit a pull request for any improvements or bug fixes.
