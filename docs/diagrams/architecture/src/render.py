"""Rasterize diagram HTML files to PNG (svg element only, transparent background).

usage: python render.py <out_dir> file1.html file2.html ...   (scale via SCALE env, default 2)
"""
import os
import pathlib
import sys

from playwright.sync_api import sync_playwright

out = pathlib.Path(sys.argv[1])
scale = float(os.environ.get("SCALE", "2"))
with sync_playwright() as p:
    b = p.chromium.launch()
    for src in sys.argv[2:]:
        src = pathlib.Path(src)
        page = b.new_page(device_scale_factor=scale, viewport={"width": 2400, "height": 1400})
        page.goto("file://" + str(src.resolve()))
        page.wait_for_load_state("networkidle")
        page.evaluate("document.fonts.ready")
        target = out / (src.stem + ".png")
        page.locator("svg").first.screenshot(path=str(target), omit_background=True)
        print("wrote", target)
        page.close()
    b.close()
