# Production deployment: HTTPS Cloudflare Tunnel + GDAL

## Prerequisites
- A Linux Docker host or VPS with at least 4 GiB RAM, 10 GiB free disk (increase with area/bands).
- A domain/subdomain managed in Cloudflare; an authorized Cloudflare Tunnel token and NASA Earthdata bearer token.
- Deployment is **not automatic from GitHub**; repository permissions do not grant access to the Docker host, Cloudflare account, or NASA credentials.

## Run

```sh
git clone https://github.com/xulytiengviet/VNview.git
cd VNview/earthdata-raster
cp .env.example .env
chmod 600 .env
# Put the private EARTHDATA_TOKEN and CLOUDFLARE_TUNNEL_TOKEN in .env
docker compose build
docker compose up -d earthdata-api
curl -f http://127.0.0.1:8000/api/health
```

In Cloudflare Zero Trust, create a remotely managed Tunnel and route a hostname, e.g. `earthdata-api.example.com`, to service `http://earthdata-api:8000`; obtain the tunnel token privately. With the route set:

```sh
docker compose --profile tunnel up -d
curl -f https://earthdata-api.example.com/api/health
```

Configure Cloudflare Access authentication, rate limits and a restrictive CORS allowlist before enabling public access. For browsers, Access might require a same-origin proxy or interactive login. Because processing endpoints otherwise share one server-side Earthdata token, never expose this service openly. Do not publish a public API URL until authentication is configured.

Set **Máy chủ GDAL API** in VNview `satellite-clip` to your HTTPS hostname. No token appears in browser code.

## Test
Run inside API container:
```sh
docker compose exec earthdata-api python3 -m unittest discover -s tests -v
```
(or `python3 -m unittest discover -s tests -v` in a local Python environment). Tests are synthetic and do not validate authentication to NASA.

### Real NASA end-to-end acceptance
1. Select a specific verified commune boundary from the ClipMap index in Vĩnh Long (inspect name, administration code and coordinates).
2. Search `HLSS30` on a day where CMR has an intersecting HLS granule.
3. Use URLs for **B04, B08/B8A, B11 and Fmask from the same granule**, download through authenticated server and clip to 2×2 cells.
4. Verify ZIP: 16 TIFFs and `manifest.json` (unless some cells outside granule footprint, in which case document expected gaps); each TIFF has CRS, pixel values, band metadata, and boundary intersection. Confirm no other errors.
5. Compare geotransform with AOI, nodata and scale/offset against NASA HLS user guide. Do not confuse the test's synthetic values with scientific measurements.

**Not completed** until an accessible HTTPS Docker server, Earthdata credentials, actual valid satellite granule and remote TIFF validation have all been demonstrated.

## Important constraints
- GitHub Pages cannot host Docker/GDAL.
- Cloudflare Tunnel requires an existing account and secure token configured by the server operator.
- No public raw Earthdata token; no auto redirects from untrusted URLs.
- Worker queue/object storage/mosaicking/QA analysis remain future operational improvements.
