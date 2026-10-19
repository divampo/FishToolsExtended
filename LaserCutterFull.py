import cv2
import numpy as np
import torch
import svgwrite
from skimage import measure
from PIL import Image, ImageDraw
import vtracer
import lxml.etree as ET
import re
import os
try:
    import folder_paths  # ComfyUI output-dir helper (present at runtime)
except ImportError:  # keep the module importable in standalone tests
    folder_paths = None

class LaserCutterFull:
    def __init__(self):
        pass

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "outlines": ("IMAGE",),
                "depthmap": ("IMAGE",),
                "num_divisions": ("INT", {
                    "default": 6, 
                    "min": 2, 
                    "max": 10, 
                    "step": 1, 
                    "display": "number"
                }),
                "use_approximation": ("BOOLEAN", {"default": False}),
                "approximation_epsilon": ("FLOAT", {"default": 0.01, "min": 0.001, "max": 1.0, "step": 0.001}),
                "shape_similarity_threshold": ("FLOAT", {"default": 0.01, "min": 0.0, "max": 1.0, "step": 0.001}),
                "min_shape_area": ("FLOAT", {"default": 5000.0, "min": 0.0, "max": 100000.0, "step": 10.0}),
                "apply_blur": ("BOOLEAN", {"default": False}),
                "corner_threshold" : ("INT", {
                    "default": 60, 
                    "min": 0, 
                    "max": 100, 
                    "step": 1, 
                    "display": "number"
                }),
                "length_threshold": ("FLOAT", {"default": 4.0, "min": 0.0, "max": 10.0, "step": 0.1}),
                "max_iterations" : ("INT", {
                    "default": 10, 
                    "min": 1, 
                    "max": 20, 
                    "step": 1, 
                    "display": "number"
                }),
                "splice_threshold" : ("INT", {
                    "default": 45, 
                    "min": 1, 
                    "max": 100, 
                    "step": 1, 
                    "display": "number"
                }),
                "path_precision" : ("INT", {
                    "default": 3, 
                    "min": 1, 
                    "max": 10, 
                    "step": 1, 
                    "display": "number"
                }),
                # When True, min_shape_area and speckle are multiplied to the
                # input resolution (calibrated for a ~1024px long edge). Off by
                # default: on a large image this scales min_shape_area up a lot
                # (e.g. ~24x at 5000px), which can wipe out thin line-art
                # shapes. Leave off and set min_shape_area directly, or turn on
                # only for solid-region inputs where you want size-invariance.
                "auto_scale_detail": ("BOOLEAN", {"default": False}),
                          
            },
            "optional": {
                # base_layer is the solid bottom/backing slab. Leave it
                # unconnected for landscapes / scenes with no clear subject:
                # a blank white image the same size as outlines is used, so
                # the backing is the full frame.
                "base_layer": ("IMAGE",),
                # How layers are formed:
                #  "outline_shapes" (default) - trace shapes from `outlines`
                #    and bucket each by depth. Can produce disconnected islands.
                #  "depth_bands" - slice the DEPTH MAP into num_divisions
                #    cumulative bands (topographic style). Each layer is a
                #    connected, edge-to-edge region at depth >= its threshold.
                #    Ignores `outlines`; great for landscapes.
                #  "manual_layers" - you supply each layer image yourself via
                #    layer_img_0..9 (e.g. objects masked in Lightroom). Each
                #    connected slot becomes one layer, in slot order. Ignores
                #    outlines/depthmap entirely.
                "layer_mode": (["outline_shapes", "depth_bands", "manual_layers"], {"default": "outline_shapes"}),
                # manual_layers inputs: wire a Load Image into as many as you
                # have; empty slots are skipped. Slot N -> layer N, in order.
                "layer_img_0": ("IMAGE",),
                "layer_img_1": ("IMAGE",),
                "layer_img_2": ("IMAGE",),
                "layer_img_3": ("IMAGE",),
                "layer_img_4": ("IMAGE",),
                "layer_img_5": ("IMAGE",),
                "layer_img_6": ("IMAGE",),
                "layer_img_7": ("IMAGE",),
                "layer_img_8": ("IMAGE",),
                "layer_img_9": ("IMAGE",),
                # Write the combined SVG straight to ComfyUI/output as a real
                # .svg file (no SaveText + rename needed). On by default.
                "save_svg": ("BOOLEAN", {"default": True}),
                "svg_filename_prefix": ("STRING", {"default": "lasercut"}),
            },
        }

    RETURN_TYPES = ("IMAGE", "IMAGE", "IMAGE", "IMAGE", "IMAGE", "IMAGE", "IMAGE", "IMAGE", "IMAGE", "IMAGE", "IMAGE", "STRING", "STRING")
    RETURN_NAMES = ("layer0", "layer1", "layer2", "layer3", "layer4", "layer5", "layer6", "layer7", "layer8", "layer9", "base_layer", "combined_svg", "debug_info")

    FUNCTION = "run"
    CATEGORY = "FishTools"

    def preprocess_image(self, image, to_gray=True, threshold=240):
        if len(image.shape) == 3 and to_gray:
            image = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        _, binary_image = cv2.threshold(image, threshold, 255, cv2.THRESH_BINARY_INV)
        return binary_image

    def extract_contours(self, binary_image, use_approximation=False, approximation_epsilon=0.01):
        contours, _ = cv2.findContours(binary_image, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
        if use_approximation:
            contours = [cv2.approxPolyDP(contour, approximation_epsilon * cv2.arcLength(contour, True), True) for contour in contours]
        return contours

    def build_depth_band_layers(self, depthmap, num_divisions, min_shape_area,
                                use_approximation, approximation_epsilon, debug_info):
        """Topographic layering: slice the depth map into num_divisions
        CUMULATIVE bands and trace each as connected edge-to-edge regions.

        Layer k contains every pixel with depth >= threshold_k (thresholds are
        evenly spaced over the depth map's own min..max range). Because each
        band is a filled region of the whole frame, the traced contours are
        connected zones that stack like a staircase - not scattered islands.
        Returns (layer_images, layer_contours) in the same shape the SVG
        builder expects. `outlines` is intentionally not used here.
        """
        if depthmap.ndim == 3:
            depth_gray = cv2.cvtColor(depthmap, cv2.COLOR_BGR2GRAY)
        else:
            depth_gray = depthmap
        shape = depth_gray.shape
        svg_colors = ['red', 'green', 'blue', 'yellow', 'cyan', 'magenta', 'purple', 'teal', 'olive', 'orange']
        colors = [
            (255, 0, 0), (0, 255, 0), (0, 0, 255),
            (255, 255, 0), (0, 255, 255), (255, 0, 255),
            (128, 0, 128), (0, 128, 128), (128, 128, 0), (255, 165, 0)
        ]

        dmin = int(depth_gray.min())
        dmax = int(depth_gray.max())
        debug_info.append(f"Depth-bands mode: depth range {dmin}..{dmax}, {num_divisions} bands")
        if dmax <= dmin:
            debug_info.append("Depth map is flat (no range) - no bands produced.")
            return {}, {}

        layer_images = {}
        layer_contours = {}
        band_counts = {}
        for k in range(num_divisions):
            # Cumulative threshold: deeper layers include everything at least
            # this near. k=0 is the whole frame; higher k is the nearer core.
            thresh = dmin + (dmax - dmin) * k / num_divisions
            mask = (depth_gray >= thresh).astype(np.uint8) * 255
            # Clean tiny specks so bands stay connected.
            mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))

            cnts, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            cnts = [c for c in cnts if cv2.contourArea(c) >= min_shape_area]
            if use_approximation:
                cnts = [cv2.approxPolyDP(c, approximation_epsilon * cv2.arcLength(c, True), True) for c in cnts]
            band_counts[k] = len(cnts)
            if not cnts:
                continue

            color = colors[k % len(colors)]
            svg_color = svg_colors[k % len(svg_colors)]
            img = np.zeros((shape[0], shape[1], 3), dtype=np.uint8)
            cv2.drawContours(img, cnts, -1, color, thickness=cv2.FILLED)
            layer_images[k] = img
            layer_contours[k] = [(c, svg_color) for c in cnts]

        debug_info.append(f"regions per band: {band_counts}")
        return layer_images, layer_contours

    def build_manual_layers(self, layer_tensors, min_shape_area,
                            use_approximation, approximation_epsilon, debug_info):
        """Each supplied image becomes one layer, in the order given.

        layer_tensors is a list of ComfyUI IMAGE tensors (already order-filtered
        for the connected slots). Each is thresholded dark-on-light (same rule
        as `outlines`), traced to vectors, and placed as its own layer. Nothing
        is bucketed or inferred - you control exactly what each layer is.
        Returns (layer_images, layer_contours) for the SVG builder.
        """
        svg_colors = ['red', 'green', 'blue', 'yellow', 'cyan', 'magenta', 'purple', 'teal', 'olive', 'orange']
        colors = [
            (255, 0, 0), (0, 255, 0), (0, 0, 255),
            (255, 255, 0), (0, 255, 255), (255, 0, 255),
            (128, 0, 128), (0, 128, 128), (128, 128, 0), (255, 165, 0)
        ]
        layer_images = {}
        layer_contours = {}
        counts = {}
        for k, t in enumerate(layer_tensors):
            img = (t[0].cpu().numpy().copy() * 255).astype(np.uint8)
            binary = self.preprocess_image(img, threshold=200)  # dark-on-light -> shapes
            cnts, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            cnts = [c for c in cnts if cv2.contourArea(c) >= min_shape_area]
            if use_approximation:
                cnts = [cv2.approxPolyDP(c, approximation_epsilon * cv2.arcLength(c, True), True) for c in cnts]
            counts[k] = len(cnts)
            if not cnts:
                continue
            color = colors[k % len(colors)]
            svg_color = svg_colors[k % len(svg_colors)]
            canvas = np.zeros((binary.shape[0], binary.shape[1], 3), dtype=np.uint8)
            cv2.drawContours(canvas, cnts, -1, color, thickness=cv2.FILLED)
            layer_images[k] = canvas
            layer_contours[k] = [(c, svg_color) for c in cnts]
        debug_info.append(f"Manual layers: {len(layer_tensors)} supplied, shapes per layer: {counts}")
        return layer_images, layer_contours

    def calculate_intensities(self, contours, depthmap, min_shape_area):
        shape_intensity = []
        img_h, img_w = depthmap.shape[:2]
        for i, contour in enumerate(contours):
            if cv2.contourArea(contour) < min_shape_area:
                continue
            x, y, w, h = cv2.boundingRect(contour)
            # Skip the whole-frame border shape: relative to the actual
            # image size, not a hardcoded 1024, so any resolution works.
            if w > (0.9 * img_w) and h > (0.9 * img_h):
                continue
            mask = np.zeros_like(depthmap)
            cv2.drawContours(mask, [contour], -1, (255), thickness=cv2.FILLED)
            labels = measure.label(mask, connectivity=2, background=0)
            unique_labels = np.unique(labels)
            for label in unique_labels:
                if label == 0:
                    continue
                shape_mask = np.zeros_like(depthmap)
                shape_mask[labels == label] = 255
                shape_pixels = depthmap[shape_mask == 255]
                if len(shape_pixels) == 0:
                    continue
                mode_intensity_value = np.bincount(np.ravel(shape_pixels)).argmax()
                shape_intensity.append((i, mode_intensity_value, contour))
        return shape_intensity

    def assign_shapes_to_layers(self, shape_intensity, binary_image, num_divisions):
        combined_image = np.zeros((binary_image.shape[0], binary_image.shape[1], 3), dtype=np.uint8)
        layer_images = {}
        layer_contours = {}
        colors = [
            (255, 0, 0), (0, 255, 0), (0, 0, 255), 
            (255, 255, 0), (0, 255, 255), (255, 0, 255),
            (128, 0, 128), (0, 128, 128), (128, 128, 0), (255, 165, 0)
        ]
        svg_colors = ['red', 'green', 'blue', 'yellow', 'cyan', 'magenta', 'purple', 'teal', 'olive', 'orange']
        
        shapes_in_layers = {i: [] for i in range(num_divisions)}
        layer_masks = [np.zeros_like(binary_image) for _ in range(num_divisions)]
        for i, (shape_index, mode_intensity_value, contour) in enumerate(shape_intensity):
            shape_mask = np.zeros_like(binary_image)
            cv2.drawContours(shape_mask, [contour], -1, (255), thickness=cv2.FILLED)
            mask_indices = np.where(shape_mask == 255)

            # Assign the shape to a layer BY ITS DEPTH, not by first-free-slot.
            # mode_intensity_value is the shape's depth (0..255); split that
            # range into num_divisions equal bands so near shapes and far
            # shapes land on different layers (the whole point of the node).
            layer_index = int(mode_intensity_value * num_divisions // 256)
            if layer_index >= num_divisions:
                layer_index = num_divisions - 1

            layer_masks[layer_index][mask_indices] = 1
            color = colors[layer_index % len(colors)]
            svg_color = svg_colors[layer_index % len(svg_colors)]

            color_mask = np.zeros_like(combined_image)
            color_mask[mask_indices] = color
            combined_image[mask_indices[0], mask_indices[1], :] = color

            if layer_index not in layer_images:
                layer_images[layer_index] = np.zeros_like(combined_image)
                layer_contours[layer_index] = []

            layer_images[layer_index][mask_indices[0], mask_indices[1], :] = color
            layer_contours[layer_index].append((contour, svg_color))
            color_mask_alpha = np.full_like(combined_image, 255)
            color_mask_alpha[mask_indices[0], mask_indices[1], :] = (0, 0, 0)
            combined_image[mask_indices[0], mask_indices[1], :] = cv2.addWeighted(
                combined_image[mask_indices[0], mask_indices[1], :], 1 - 0.25,
                color_mask_alpha[mask_indices[0], mask_indices[1], :], 0.25, 0)
            cv2.drawContours(combined_image, [contour], -1, color, 2)

            shapes_in_layers[layer_index].append(shape_index)

        return layer_images, layer_contours, shapes_in_layers

    def contours_to_image(self, contours, shape, debug_info):
        image = Image.new('L', (shape[1], shape[0]), 255)
        draw = ImageDraw.Draw(image)
        
        for contour_info in contours:
            if isinstance(contour_info, tuple):
                contour = contour_info[0]  # Extract the contour if it's a tuple
            else:
                contour = contour_info  # Use the contour directly if it's not a tuple
            try:
                # Attempt to handle different possible structures of the contour points
                points = [(int(point[0][0]), int(point[0][1])) for point in contour]  # Common structure
            except TypeError:
                points = [(int(point[0]), int(point[1])) for point in contour]  # Fallback structure
            # A polygon needs at least 3 points; PIL raises
            # "coordinate list must contain at least 2 coordinates" on
            # degenerate (1-point) contours. Skip those.
            if len(points) < 3:
                continue
            # debug_info.append(f"Points list {points}")
            draw.polygon(points, outline=0, width=3)
            
        debug_info.append(f"Converted {len(contours)} contours to image.")
        return image

    def _save_svg_file(self, svg_text, filename_prefix, debug_info):
        """Write the combined SVG to ComfyUI/output as a real .svg file.

        Uses folder_paths' counter scheme (prefix_00001.svg, _00002.svg, ...)
        so runs don't overwrite each other. Returns the absolute path, or None
        if saving failed (logged to debug_info rather than crashing the graph).
        """
        try:
            if folder_paths is not None:
                full_output_folder, filename, counter, subfolder, _ = folder_paths.get_save_image_path(
                    filename_prefix, folder_paths.get_output_directory(), 1, 1
                )
            else:
                # Standalone/test fallback: write next to this module.
                full_output_folder = os.path.dirname(os.path.abspath(__file__))
                filename, counter = filename_prefix, 1
            os.makedirs(full_output_folder, exist_ok=True)
            file = f"{filename}_{counter:05}.svg"
            filepath = os.path.join(full_output_folder, file)
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(svg_text)
            return filepath
        except Exception as e:  # noqa: BLE001 - never let a save failure abort the graph
            debug_info.append(f"SVG save failed: {e}")
            return None
    

    def convert_to_svg(self, layer_contours, base_layer_contours, shape, debug_info,
                       corner_threshold, length_threshold, max_iterations, splice_threshold, path_precision,
                       colormode="binary", hierarchical="cutout", mode="spline", 
                       filter_speckle=4, color_precision=6, layer_difference=16, 
                      ):
        # Convert layer contours to images
        layer_images = {layer_index: self.contours_to_image(contours, shape, debug_info) for layer_index, contours in layer_contours.items()}
        base_layer_image = self.contours_to_image(base_layer_contours, shape, debug_info)

        svg_strings = []

        # Process each layer
        for layer_index, image in layer_images.items():
            image = image.convert("RGBA")
            pixels = list(image.getdata())

            # Convert the pixels list back to an Image object
            width, height = image.size
            new_image = Image.new("RGBA", (width, height))
            new_image.putdata(pixels)

            size = image.size
            color = layer_contours[layer_index][0][1] if layer_contours[layer_index] else "black"
            svg_str = vtracer.convert_pixels_to_svg(
                pixels,
                size=size,
                colormode=colormode,
                hierarchical=hierarchical,
                mode=mode,
                filter_speckle=filter_speckle,
                color_precision=color_precision,
                layer_difference=layer_difference,
                corner_threshold=corner_threshold,
                length_threshold=length_threshold,
                max_iterations=max_iterations,
                splice_threshold=splice_threshold,
                path_precision=path_precision
            )

             # Perform string manipulations
            svg_str = re.sub(r'(<path[^>]*?) fill="[^"]*"', rf'\1 fill="none" stroke="{color}"', svg_str)
            path_pattern = re.compile(r'(<path[^>]*?d=".*?M.*?)(M.*?)(?=".*?fill=)')
            
            # Function to process each match
            def process_match(match):
                # Keep everything before the second "M" and add fill and stroke attributes
                return f'{match.group(1)}'
            
            # Replace the matches in the SVG string
            svg_str = re.sub(path_pattern, process_match, svg_str)

             # Remove <svg>, </svg>, and <?xml> tags
            svg_str = re.sub(r'<\?xml[^>]*\?>', '', svg_str)  # Remove <?xml ... ?> tags
            svg_str = re.sub(r'<svg[^>]*>', '', svg_str)      # Remove <svg ... > tags
            svg_str = re.sub(r'</svg>', '', svg_str)          # Remove </svg> tags

            svg_strings.append(f'<g id="layer_{layer_index}" data-name="layer_{layer_index}">{svg_str.strip()}</g>')

        # Process the base layer
        # Use an explicit color for the base outline rather than leaking the
        # last layer's `color`: with no depth layers (e.g. a landscape whose
        # shapes all land on one band) the layer loop above never runs and
        # `color` would be unbound. The base is a cut outline -> black.
        base_color = "black"
        base_layer_image = base_layer_image.convert("RGBA")
        pixels = list(base_layer_image.getdata())
        size = base_layer_image.size
        debug_info.append(f"Pixels length: {len(pixels)}")

        base_svg_str = vtracer.convert_pixels_to_svg(
            pixels,
            size=size,
            colormode=colormode,
            hierarchical=hierarchical,
            mode=mode,
            filter_speckle=filter_speckle,
            color_precision=color_precision,
            layer_difference=layer_difference,
            corner_threshold=corner_threshold,
            length_threshold=length_threshold,
            max_iterations=max_iterations,
            splice_threshold=splice_threshold,
            path_precision=path_precision
        )

        # Perform string manipulations
        base_svg_str = re.sub(r'(<path[^>]*?) fill="[^"]*"', rf'\1 fill="none" stroke="{base_color}"', base_svg_str)
        path_pattern = re.compile(r'(<path[^>]*?d=".*?M.*?)(M.*?)(?=".*?fill=)')
        
        # Function to process each match
        def process_match(match):
            # Keep everything before the second "M" and add fill and stroke attributes
            return f'{match.group(1)}'
        
        # Replace the matches in the SVG string
        base_svg_str = re.sub(path_pattern, process_match, base_svg_str)

            # Remove <svg>, </svg>, and <?xml> tags
        base_svg_str = re.sub(r'<\?xml[^>]*\?>', '', base_svg_str)  # Remove <?xml ... ?> tags
        base_svg_str = re.sub(r'<svg[^>]*>', '', base_svg_str)      # Remove <svg ... > tags
        base_svg_str = re.sub(r'</svg>', '', base_svg_str)          # Remove </svg> tags

         # Combine all SVG strings into one document.
         # Use the real input dimensions (not a hardcoded 1024) so any image
         # size produces a correctly-proportioned, full-size SVG.
        svg_h, svg_w = shape[0], shape[1]
        combined_svg = (
            f'<?xml version="1.0" encoding="UTF-8"?>'
            f'<svg id="Layer_1" data-name="Layer 1" xmlns="http://www.w3.org/2000/svg" '
            f'version="1.1" xmlns:ev="http://www.w3.org/2001/xml-events" '
            f'width="{svg_w}" height="{svg_h}" viewBox="0 0 {svg_w} {svg_h}">'
        )

        for svg_str in svg_strings:
            combined_svg += svg_str

        combined_svg += f'<g id="layer_base" data-name="layer_base">{base_svg_str.strip()}</g>'
        combined_svg += '</svg>'

        debug_info.append("SVG conversion complete.")

        return combined_svg

    def run(self, outlines, depthmap, num_divisions, use_approximation, approximation_epsilon, 
            shape_similarity_threshold, min_shape_area, apply_blur, 
            corner_threshold, length_threshold, max_iterations, splice_threshold, path_precision,
            base_layer=None, auto_scale_detail=False, layer_mode="outline_shapes",
            layer_img_0=None, layer_img_1=None, layer_img_2=None, layer_img_3=None,
            layer_img_4=None, layer_img_5=None, layer_img_6=None, layer_img_7=None,
            layer_img_8=None, layer_img_9=None,
            save_svg=True, svg_filename_prefix="lasercut"):
        debug_info = []

        # Section 1: Convert inputs to NumPy arrays
        outlines = (outlines[0].cpu().numpy().copy() * 255).astype(np.uint8)
        depthmap = (depthmap[0].cpu().numpy().copy() * 255).astype(np.uint8)
        if base_layer is not None:
            base_layer = (base_layer[0].cpu().numpy().copy() * 255).astype(np.uint8)
        else:
            # No base_layer connected (e.g. a landscape): synthesize a blank
            # white backing the same size as outlines, so the base is the
            # full frame.
            base_layer = np.full_like(outlines, 255)

        if apply_blur:
            depthmap = cv2.GaussianBlur(depthmap, (5, 5), 0)

        # Preprocess images
        outlines_binary = self.preprocess_image(outlines, threshold=200)
        base_layer_binary = self.preprocess_image(base_layer, threshold=200)

        # Extract contours
        contours = self.extract_contours(outlines_binary, use_approximation, approximation_epsilon)
        base_layer_contours = self.extract_contours(base_layer_binary, use_approximation, approximation_epsilon)
        

        # Optionally scale detail filters to the input resolution (OFF by
        # default). When on, min_shape_area and speckle are multiplied so the
        # relative filtering matches a ~1024px baseline at any size. This is
        # right for solid-region inputs but can erase thin line-art shapes on a
        # large image, so it is opt-in: with it off, min_shape_area is used
        # exactly as you set it.
        long_edge = max(outlines_binary.shape[0], outlines_binary.shape[1])
        if auto_scale_detail:
            size_scale = long_edge / 1024.0
            scaled_min_shape_area = min_shape_area * (size_scale ** 2)
            scaled_filter_speckle = max(1, int(round(4 * size_scale)))
            debug_info.append(
                f"Detail auto-scale ON: long_edge={long_edge}, scale={size_scale:.2f}, "
                f"min_shape_area {min_shape_area}->{scaled_min_shape_area:.0f}, "
                f"filter_speckle 4->{scaled_filter_speckle}"
            )
        else:
            scaled_min_shape_area = min_shape_area
            scaled_filter_speckle = 4
            debug_info.append(
                f"Detail auto-scale OFF: long_edge={long_edge}, "
                f"min_shape_area={min_shape_area} (as set), filter_speckle=4"
            )

        # Build layers by the selected mode.
        if layer_mode == "manual_layers":
            supplied = [t for t in (layer_img_0, layer_img_1, layer_img_2, layer_img_3,
                                    layer_img_4, layer_img_5, layer_img_6, layer_img_7,
                                    layer_img_8, layer_img_9) if t is not None]
            debug_info.append(f"Layer mode: manual_layers ({len(supplied)} slots connected)")
            layer_images, layer_contours = self.build_manual_layers(
                supplied, scaled_min_shape_area,
                use_approximation, approximation_epsilon, debug_info)
            # In manual mode, output layer count follows the slots supplied.
            num_divisions = max(num_divisions, len(supplied))
        elif layer_mode == "depth_bands":
            debug_info.append("Layer mode: depth_bands (topographic, cumulative)")
            layer_images, layer_contours = self.build_depth_band_layers(
                depthmap, num_divisions, scaled_min_shape_area,
                use_approximation, approximation_epsilon, debug_info)
        else:
            debug_info.append("Layer mode: outline_shapes")
            # Calculate intensities
            shape_intensity = self.calculate_intensities(contours, depthmap, scaled_min_shape_area)

            # Assign shapes to layers
            layer_images, layer_contours, shapes_in_layers = self.assign_shapes_to_layers(shape_intensity, outlines_binary, num_divisions)
            # Diagnostics: how many shapes were found and how they spread across
            # depth layers. All-zero-but-one here means the depth map has no tonal
            # range over the shapes; zero total means outlines isn't dark-on-light.
            per_layer = {k: len(v) for k, v in sorted(shapes_in_layers.items())}
            debug_info.append(f"Shapes found: {len(shape_intensity)}")
            debug_info.append(f"shapes per layer: {per_layer}")

        # Canvas shape for the SVG + previews. outline_shapes uses the outlines
        # image; manual_layers / depth_bands use the actual layer source size so
        # the viewBox and previews match what was traced.
        canvas_shape = outlines_binary.shape
        if layer_mode in ("manual_layers", "depth_bands") and layer_images:
            first = next(iter(layer_images.values()))
            canvas_shape = first.shape[:2]

        # Convert to SVG
        combined_svg = self.convert_to_svg(layer_contours, base_layer_contours, 
                                           canvas_shape, debug_info, 
                                           corner_threshold, length_threshold, max_iterations, splice_threshold, path_precision,
                                           filter_speckle=scaled_filter_speckle)

        # Prepare the output images. Use a canvas matching the traced source
        # (outlines for outline_shapes; the layer images for manual/depth).
        def _blank():
            return np.full((canvas_shape[0], canvas_shape[1]), 255, dtype=np.uint8)

        layer_images_result = []
        for layer_index in range(num_divisions):
            if layer_index in layer_images:
                gray_layer_image = cv2.cvtColor(layer_images[layer_index], cv2.COLOR_BGR2GRAY)
                _, binary_layer_image = cv2.threshold(gray_layer_image, 1, 255, cv2.THRESH_BINARY)
                final_contours, _ = cv2.findContours(binary_layer_image, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
                outline_layer_image = _blank()
                cv2.drawContours(outline_layer_image, final_contours, -1, (0), 2)
                outline_layer_image = np.stack([outline_layer_image]*3, axis=-1)
                layer_images_result.append(torch.tensor(outline_layer_image).unsqueeze(0).float() / 255.0)
            else:
                blank_image = np.stack([_blank()]*3, axis=-1)
                layer_images_result.append(torch.tensor(blank_image).unsqueeze(0).float() / 255.0)

        while len(layer_images_result) < 10:
            blank_image = np.stack([_blank()]*3, axis=-1)
            layer_images_result.append(torch.tensor(blank_image).unsqueeze(0).float() / 255.0)

        debug_info.append(f"Created SVGs")
        # Add base layer output
        base_layer_image = np.full_like(base_layer_binary, 255)
        cv2.drawContours(base_layer_image, base_layer_contours, -1, (0), 2)
        base_layer_image = np.stack([base_layer_image]*3, axis=-1)
        base_layer_image = torch.tensor(base_layer_image).unsqueeze(0).float() / 255.0

        # Debug info
        if layer_mode == "outline_shapes":
            for layer_index in range(num_divisions):
                debug_info.append(f"Shapes in layer {layer_index}: {shapes_in_layers[layer_index]}")
            debug_info.append(f"Total shapes processed: {len(shape_intensity)}")
        debug_info.append(f"Number of layers returned: {len(layer_images_result)}")

        # Optionally write the combined SVG straight to disk as a real .svg
        # file, so no SaveText node + rename is needed.
        if save_svg:
            saved_path = self._save_svg_file(combined_svg, svg_filename_prefix, debug_info)
            if saved_path:
                debug_info.append(f"Saved SVG: {saved_path}")

        debug_info_string = "\n".join(debug_info)

        return tuple(layer_images_result[:10]) + (base_layer_image, combined_svg, debug_info_string)

NODE_CLASS_MAPPINGS = {
    "LaserCutterFull": LaserCutterFull
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "LaserCutterFull": "LaserCutterFull"
}
