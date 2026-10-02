"""One-time fetch of the public dcaribou/transfermarkt-datasets export that
pipeline/real_source.py reads from data_raw/. ~241MB zip, CC0-licensed; see
https://github.com/dcaribou/transfermarkt-datasets for the source project.

    python -m pipeline.download_real_data
"""

from __future__ import annotations

import gzip
import io
import os
import urllib.request
import zipfile

URL = "https://pub-e682421888d945d684bcae8890b0ec20.r2.dev/data/transfermarkt-datasets.zip"
DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data_raw")


def main() -> None:
    os.makedirs(DATA_DIR, exist_ok=True)
    print(f"Downloading {URL} ...")
    with urllib.request.urlopen(URL) as resp:
        payload = resp.read()
    print(f"Got {len(payload):,} bytes, extracting to {DATA_DIR} ...")
    with zipfile.ZipFile(io.BytesIO(payload)) as zf:
        for info in zf.infolist():
            if not info.filename.endswith(".csv.gz"):
                continue
            name = os.path.basename(info.filename)
            with zf.open(info) as src, open(os.path.join(DATA_DIR, name), "wb") as dst:
                dst.write(src.read())
            # sanity-check it's a readable gzip, not a truncated/corrupt download
            with gzip.open(os.path.join(DATA_DIR, name), "rt", encoding="utf-8") as f:
                f.readline()
            print(f"  wrote {name}")
    print("Done.")


if __name__ == "__main__":
    main()
