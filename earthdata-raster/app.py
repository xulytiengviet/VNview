"""NASA Earthdata HLS scientific-band extraction with GDAL (via rasterio)."""
from __future__ import annotations
import io, os, re, tempfile, zipfile, json, ipaddress, socket
from pathlib import Path
from urllib.parse import urlparse
from concurrent.futures import ThreadPoolExecutor
from typing import Literal
import requests
import numpy as np
import rasterio
from rasterio.mask import mask
from rasterio.warp import transform_geom
from rasterio.enums import Resampling
from shapely.geometry import shape, box, mapping
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, field_validator

NASA_CMR = "https://cmr.earthdata.nasa.gov/search/granules.json"
# HLS multispectral science products, not browse imagery.
PRODUCTS = {"HLSL30": "HLSL30", "HLSS30": "HLSS30"}
HOSTS = ("data.lpdaac.earthdatacloud.nasa.gov", "lpdaac.earthdata.nasa.gov")
MAX_BYTES = int(os.getenv("MAX_ASSET_BYTES", str(512 * 1024 * 1024)))
MAX_CELLS = int(os.getenv("MAX_CELLS", "100"))
TOKEN = os.getenv("EARTHDATA_TOKEN", "").strip()
CORS = [x.strip() for x in os.getenv("ALLOWED_ORIGINS", "http://localhost:3000,http://localhost:8000").split(",") if x.strip()]
app = FastAPI(title="VNview NASA Earthdata Scientific Raster API", version="0.1.0")
app.add_middleware(CORSMiddleware, allow_origins=CORS, allow_methods=["GET", "POST"], allow_headers=["Content-Type"])

class Search(BaseModel):
    product: Literal["HLSL30", "HLSS30"] = "HLSS30"
    bbox: tuple[float,float,float,float]
    start: str
    end: str
    limit: int = Field(5, ge=1, le=50)

class Clip(BaseModel):
    geometry: dict
    assets: list[str] = Field(min_length=1, max_length=12)
    rows: int = Field(1, ge=1, le=10)
    cols: int = Field(1, ge=1, le=10)
    mode: Literal["polygon","matrix"] = "polygon"
    dst_crs: Literal["native", "EPSG:4326"] = "native"
    @field_validator("geometry")
    @classmethod
    def polygon_only(cls, v):
        if v.get("type") not in ("Polygon","MultiPolygon"): raise ValueError("Polygon or MultiPolygon required")
        g=shape(v)
        if not g.is_valid or g.is_empty or g.area == 0: raise ValueError("Invalid AOI")
        if any(abs(x)>180 for x in (g.bounds[0],g.bounds[2])) or any(abs(y)>90 for y in (g.bounds[1],g.bounds[3])):
            raise ValueError("AOI must be EPSG:4326 coordinates")
        if (g.bounds[2]-g.bounds[0])*(g.bounds[3]-g.bounds[1]) > 4: raise ValueError("AOI too large; maximum bbox 4 square degrees")
        return v

def auth_headers():
    return {"Authorization": f"Bearer {TOKEN}"} if TOKEN else {}

def safe_asset_url(url):
    u=urlparse(url)
    if u.scheme!="https" or u.username or u.password or u.port not in (None,443): raise ValueError("HTTPS Earthdata URL required")
    if u.hostname not in HOSTS: raise ValueError("Not an approved Earthdata asset host")
    if not u.path.lower().endswith((".tif",".tiff")): raise ValueError("Only GeoTIFF scientific band assets accepted")
    return url

def download(url, folder):
    safe_asset_url(url)
    name = Path(urlparse(url).path).name
    path = folder / name
    with requests.Session() as session:
        r = session.get(url, headers=auth_headers(), stream=True, timeout=(20,90), allow_redirects=False)
        if r.status_code in (301,302,303,307,308):
            raise ValueError("Asset redirected; configure valid Earthdata bearer token and direct HLS science URLs")
        r.raise_for_status()
        count=0
        with path.open("wb") as f:
            for chunk in r.iter_content(1024*1024):
                count+=len(chunk)
                if count>MAX_BYTES: raise ValueError("Asset exceeds download size limit")
                f.write(chunk)
    return path

@app.get("/api/health")
def health():
    return {"status":"ok","gdal":rasterio.__gdal_version__,"token_configured":bool(TOKEN)}

@app.post("/api/search")
def search(req: Search):
    w,s,e,n=req.bbox
    if not (-180<=w<e<=180 and -90<=s<n<=90): raise HTTPException(422,"Invalid WGS84 bbox")
    params={"short_name":req.product, "temporal":f"{req.start}T00:00:00Z,{req.end}T23:59:59Z", "bounding_box":",".join(map(str,req.bbox)),"page_size":req.limit,"sort_key":"-start_date"}
    try:
        r=requests.get(NASA_CMR,params=params,headers={"Client-Id":"VNview-Satellite-Clip",**auth_headers()},timeout=30)
        r.raise_for_status()
        result=[]
        for g in r.json().get("feed",{}).get("entry",[]):
            assets=[]
            for link in g.get("links",[]):
                u=link.get("href","")
                try: safe_asset_url(u)
                except ValueError: continue
                if not link.get("inherited",False):
                    assets.append({"band":Path(urlparse(u).path).name,"url":u})
            result.append({"id":g.get("id"),"title":g.get("title"),"time":g.get("time_start"),"cloud_cover":g.get("cloud_cover"),"assets":assets})
        return {"product":req.product,"granules":result,"note":"HLS science reflectance bands: apply per-product scale, offset and QA before index calculations"}
    except requests.RequestException as e: raise HTTPException(502,f"CMR request failed: {str(e)[:160]}")

def clipped_tif(src_path, geom, out_path, dst_crs):
    with rasterio.open(src_path) as ds:
        if not ds.crs: raise ValueError("Source raster CRS missing")
        g=transform_geom("EPSG:4326",ds.crs,geom,precision=10)
        data,trans=mask(ds,[g],crop=True,filled=True)
        profile=ds.profile.copy()
        profile.update(driver="GTiff",height=data.shape[1],width=data.shape[2],count=data.shape[0],transform=trans,compress="deflate",tiled=(data.shape[1]>=16 and data.shape[2]>=16))
        if not profile["tiled"]: profile.pop("blockxsize",None);profile.pop("blockysize",None)
        with rasterio.open(out_path,"w",**profile) as dst:
            dst.write(data);dst.update_tags(**ds.tags())
            for k in range(1,ds.count+1): dst.update_tags(k,**ds.tags(k))
        if dst_crs=="EPSG:4326":
            from rasterio.warp import calculate_default_transform,reproject
            with rasterio.open(out_path) as r:
                transform,width,height=calculate_default_transform(r.crs,"EPSG:4326",r.width,r.height,*r.bounds)
                meta=r.meta.copy();meta.update(crs="EPSG:4326",transform=transform,width=width,height=height)
                temp=out_path.with_suffix(".wgs84.tif")
                with rasterio.open(temp,"w",**meta) as d:
                    for b in range(1,r.count+1):
                        reproject(source=rasterio.band(r,b),destination=rasterio.band(d,b),src_transform=r.transform,src_crs=r.crs,dst_transform=transform,dst_crs="EPSG:4326",resampling=Resampling.nearest,src_nodata=r.nodata,dst_nodata=r.nodata)
                    d.update_tags(**r.tags())
            temp.replace(out_path)

@app.post("/api/clip")
def clip(req: Clip):
    geom=shape(req.geometry)
    w,s,e,n=geom.bounds
    if req.mode=="matrix" and req.rows*req.cols>MAX_CELLS: raise HTTPException(422,"Too many cells")
    for url in req.assets:
        try: safe_asset_url(url)
        except ValueError as exc: raise HTTPException(422,str(exc))
    try:
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); inputs=[download(url,root) for url in req.assets]
            parts=[("ROI",geom)]
            if req.mode=="matrix":
                parts=[]
                for row in range(req.rows):
                    for col in range(req.cols):
                        cell=box(w+(e-w)*col/req.cols,s+(n-s)*row/req.rows,w+(e-w)*(col+1)/req.cols,s+(n-s)*(row+1)/req.rows)
                        cut=geom.intersection(cell)
                        if cut.is_empty or cut.area==0:continue
                        if cut.geom_type not in ("Polygon","MultiPolygon"):continue
                        parts.append((f"R{row+1:02d}C{col+1:02d}",cut))
            memory=io.BytesIO();ok=[];failed=[]
            with zipfile.ZipFile(memory,"w",compression=zipfile.ZIP_STORED) as archive:
                for ident,part in parts:
                    for inp in inputs:
                        filename=f"{ident}_{inp.stem}.tif"
                        try:
                            dest=root/filename
                            clipped_tif(inp,mapping(part),dest,req.dst_crs)
                            archive.write(dest,filename);dest.unlink()
                            ok.append(filename)
                        except (ValueError, rasterio.errors.RasterioError) as e:
                            failed.append({"file":filename,"reason":str(e)[:250]})
                archive.writestr("manifest.json",json.dumps({"type":"NASA Earthdata science raster","mode":req.mode,"rows":req.rows,"cols":req.cols,"source_urls":req.assets,"successful":ok,"failed":failed,"geometry":req.geometry,"notes":"Pixel values retained; inspect scale/offset, fill value, Fmask and reflectance metadata. Nearest resampling if reprojected."},ensure_ascii=False,indent=2))
            if not ok: raise HTTPException(422,{"message":"No overlapping valid rasters","failed":failed[:12]})
            memory.seek(0)
            return StreamingResponse(memory,media_type="application/zip",headers={"Content-Disposition":'attachment; filename="VNview_Earthdata_GeoTIFF.zip"'})
    except HTTPException:raise
    except (requests.RequestException,ValueError,rasterio.errors.RasterioError) as e:
        raise HTTPException(502,str(e)[:350])
