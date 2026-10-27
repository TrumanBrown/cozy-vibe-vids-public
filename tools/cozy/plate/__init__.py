"""The steps of tools/plate_prep.py (TASKS.md T16), one module per job, moved verbatim. plate_prep.py keeps the
command line and main(); other tools import a step from its module here.

  image         the 16:9 crop, the x4 upscale and the depth (GPU, torch), the defocus map and the fine depth
  primitives    the guided filter, local variance, soften, Otsu's threshold, sRGB to linear, a polygon's box
  regions       the named animation regions: regions.png, views.png, regions.json and their preview
  weather       the weather masks: outdoors, wet ground, sky, foliage and lights, with gaps, shelters and the waterfalls
  derain        painted rain and other painted transients out of the plate; the pixel-art grid
  lights        the windows and lanterns a scene switches, and their reflections on the wet ground
  sources       where drops, flames and steam start, and what drops must not land on
  pets          pet.png: what breathes

Nothing is imported here, and only image imports torch.
"""
