# Projector for Blender

Create physically based projectors in Blender, configure them with familiar
projector specifications, and use them to cast test patterns, colours, images,
or video textures in a scene.

![Projector add-on title image](.github/gifs/title.jpg)

## Requirements

- Blender 4.2 or newer.
- Cycles for image projection. The add-on displays a shortcut to switch the
  scene to Cycles when Eevee is active.

## Features

### Create and manage projectors

- Add a projector from **3D Viewport → Add → Light → Projector**, or from the
  **Projector** tab in the 3D Viewport sidebar (`N`).
- Place a new projector at the 3D Cursor, inheriting the cursor rotation.
- A projector is a camera controller with a child spot light. Move and rotate
  the camera object to place and aim the complete projector.
- Remove one or more selected projectors together with their complete internal
  hierarchy.
- Projectors duplicated with Blender's normal duplicate command receive local
  data, so their settings and materials can be edited independently.

### Optical and light controls

- **Throw ratio** controls the field of view and projected image size.
- **Lumens** controls the spot-light energy.
- **Horizontal** and **vertical lens shift** reposition the projection without
  moving the projector object.
- Select a built-in aspect ratio/resolution:
  - 16:10: 1280×800, 1440×900, 1920×1200
  - 16:9: 1280×720, 1920×1080, 3840×2160
  - 4:3: 800×600, 1024×768, 1400×1050, 1600×1200
  - 17:9: 4096×2160
  - Square: 1000×1000
- When using a custom image, optionally let its dimensions define the
  projector resolution.
- Enable a pixel grid to visualize individual pixels at the selected
  resolution.

### Projection content

- **Checker** test pattern, with editable colour and a one-click random-colour
  action.
- **Color Grid** test pattern.
- **Custom Texture**, using Blender's image selector; image sequences and
  movie files supported by Blender can be used through that image texture.

### Projector body and emitter

- Create a projector with no body, a configurable box body, or a duplicate of
  the active mesh object.
- Set the default body length, depth, and height.
- Offset and rotate the body relative to the projector.
- Offset and rotate the emitter independently, allowing the visible model and
  projection origin to be aligned precisely.

### Projection-cone previews

- Show a transparent frustum that reflects the throw ratio, lens shift, aspect
  ratio, and selected cone length.
- Display screen metrics on the preview.
- While the cone preview is enabled, the projection light is disabled; turning
  the preview off restores it.
- Create a world-space, independent copy of the selected projector's cone.
- Copy cones from every projector in the scene into a **Projector Cone Copies**
  collection, with an option to assign each copy a random transparent colour.
- Cone copies include separate edge geometry in **Projector Cone Edges** for a
  clearer technical drawing or layout view.

### Saved projector models

- Save the complete configuration of a selected projector under a
  **Manufacturer** and **Model** name.
- Saved models include optical settings, output pattern, colour, pixel-grid
  state, body and emitter transforms, and cone settings.
- A custom body is saved as an embedded native Blender snapshot, preserving its
  mesh geometry, UVs, modifiers, shape keys, vertex groups, material node
  trees, and packed material textures. This can make model-library JSON files
  substantially larger.
- Create a new projector directly from a saved model in the creation dialog.
- Applying a saved model to an existing projector is also available through the
  `projector.apply_saved_model` operator.
- The model library persists as JSON in Blender's user configuration directory.
- Export the library to a JSON file, import a library, refresh it from disk, or
  delete individual saved models.

### Projector arrays

- Build **linear**, **grid**, or **radial** arrays from a selected projector.
- Linear arrays use a count and local offset; grid arrays use row/column counts
  and separate offsets; radial arrays support radius, arc, start angle, and
  optional rotation along the arc.
- Arrays can remain linked to their source: changes to the source projector's
  configuration automatically propagate to the array members.
- Edit the layout of a linked array later.
- Create arrays with independent settings from the outset, or convert a linked
  array to independent projectors at any time.

## Quick start

1. In Blender, open the 3D Viewport sidebar and select the **Projector** tab.
2. Click **New** (or use **Add → Light → Projector**).
3. In the creation dialog, choose a body, set the emitter transform, and
   optionally enable the projection cone.
4. Select the new projector. Use **Projector Settings** to set lumens, throw
   ratio, resolution, lens shift, and projection content.
5. Use **Projector Body** for the body, emitter, cone, and cone-copy controls.
6. For rendered image projection, switch the scene render engine to Cycles.

## Interface reference

The main controls are in **3D Viewport → Sidebar → Projector** when exactly one
projector is selected. The same panel also contains creation/removal controls,
array tools, and saved-model library actions. The **Projected Color** subpanel
is shown when the Checker output is active.

## Installation

1. Download the add-on ZIP from the [latest GitHub release](https://github.com/lubasampa/Projectors_addon_blender/releases/latest).
2. In Blender, open **Edit → Preferences → Add-ons** and choose **Install from
   Disk**.
3. Select the downloaded ZIP and enable **Projector**.

Do not install GitHub's **Code → Download ZIP** archive: it contains source and
development files rather than the packaged add-on.

## Development and releases

The add-on manifest currently declares version `2026.5.2`. Pushing a version
tag runs the release workflow and publishes a clean add-on ZIP.

## Support

Report bugs or suggest improvements through the [issue tracker](https://github.com/lubasampa/Projectors_addon_blender/issues).
