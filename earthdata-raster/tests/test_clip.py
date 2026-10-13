"""No NASA login required: GDAL scientific raster clipping smoke test."""
import tempfile
import unittest
from pathlib import Path
import numpy as np
import rasterio
from rasterio.transform import from_origin
from shapely.geometry import mapping, box
from app import clipped_tif

class ClippingSmokeTest(unittest.TestCase):
    def test_four_science_bands_two_by_two(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            roi=box(105.05,10.05,105.15,10.15)
            for band in ("B04","B08","B11","Fmask"):
                source=root/(band+".tif")
                data=np.ones((100,100),dtype=np.uint16)*(25 if band=="Fmask" else 1200)
                with rasterio.open(source,"w",driver="GTiff",height=100,width=100,count=1,dtype="uint16",crs="EPSG:4326",transform=from_origin(105,10.2,.002,.002),nodata=0) as dst:
                    dst.write(data,1)
                    dst.update_tags(scale_factor="0.0001",band=band)
                for row in range(2):
                    for col in range(2):
                        cell=box(105.05+col*.05,10.05+row*.05,105.1+col*.05,10.1+row*.05)
                        output=root/f"{band}_{row}_{col}.tif"
                        clipped_tif(source,mapping(roi.intersection(cell)),output,"native")
                        with rasterio.open(output) as result:
                            self.assertEqual(result.crs.to_epsg(),4326)
                            self.assertEqual(result.count,1)
                            self.assertGreater(result.width,0)
                            self.assertGreater(result.height,0)
                            self.assertEqual(result.tags()["band"],band)
                            self.assertEqual(int(result.read(1).max()),25 if band=="Fmask" else 1200)

if __name__=="__main__": unittest.main()
