I want to make a new program called FastCuller, which is like FastRawViewer for culling photos, but I get more control because it's mine.

Architecture: Similar to ~/Documents/AutoCropper: a Flask web application. Manage it using rye.

Helpful imports, as per ~/Documents/Autocropper/main.py:
```
#!/usr/bin/env python3

import argparse
import io
import re
import struct
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import rawpy
import torch
from PIL import Image
from tqdm import tqdm
```

It might also be useful to look at  ~/Documents/Autocropper/web.py.

Include a test suite and test frequently.

Appearance:
Base the CSS on the CSS in ~/Documents/Autocropper.

Begins with a folder selection screen.

After loading, the main page has header bar with various settings. One is a 'copy photos' button.
A main panel with the current image to be evaluated - take the JPEG preview from the CR3 file. See extract_preview_image from ~/Documents/Autocropper/main.py.
On the bottom, a strip view where all photos are displayed in capture time order (as per metadata not file creation date). The current image is centred with a highlight/border. The strip can be scrolled left/right, and thumbnails will load (load a reasonable number of thumbnails left/right but keep loaded thumbnails limited to a setting, default 100). If the main image changes, re-centre the strip on the new main image. The strip is clickable to navigate and also displays the # stars per photo as an overlay.

Behaviour:
Finding photos in the folder selection is recursive, if there are subfolders. Upon folder selection, all photos are ordered in the strip by metadata capture time (DO NOT use exiftool). Initialise with the first photo taken.

Pressing '1' will rate 1 star to the current photo and go to the next photo. Pressing '`' (grave accent?) will assign 0 and go to the next photo. Pressing left+1 will go to the previous photo with 1 star. Pressing right+1 goes to the next photo with one star. Same with left/right + grave accent for 0 stars.

To keep performance quick as the user navigates, the server should supply the browser with all of:
The current image
The next and previous images with 0 stars
The next and previous images with 1 star

When a rating is assigned, write an XMP file with the rating next to the CR3 file. If an XMP file already exists, add the rating to the XMP file. You can refer to the write_xmp function from ~/Documents/Autocropper/main.py although that's for different metadata.

When finished (or at any point), I can click the 'Copy photos' button. It will give me an option for what to select (e.g. photos with 1 star) and then I can choose a photo to copy them (and the XMP files) to.

Make a plan in a README and then execute it.