# VNview · NASA Earthdata Scientific Raster (HLS / GDAL)

**Trạng thái:** Mã tích hợp đã được thêm vào nhánh main. Máy chủ Docker phải được triển khai riêng; GitHub Pages không thể chạy Python/GDAL. Chưa có kiểm thử tải một granule HLS thật ở môi trường đã xác thực, vì vậy chưa coi là hệ thống vận hành hoàn chỉnh.

## Dữ liệu

- NASA CMR `/search/granules.json`: tìm HLS S30 (Sentinel-2) hoặc HLS L30 (Landsat) theo WGS84 bbox + khoảng ngày.
- Chọn các **tài sản GeoTIFF khoa học**, không dùng WMS/GIBS PNG.
- Máy chủ tải GeoTIFF được phép từ tên miền LP DAAC, dùng `rasterio` (GDAL) để `mask(crop=True)` và đóng gói raster từng ô vào ZIP.
- Cắt polygon, MultiPolygon hoặc M × N ô; giao hình học của mỗi ô với AOI trước khi cắt.
- Bảo toàn giá trị số raster và tags khi xuất native CRS; `EPSG:4326` dùng nearest-neighbour khi tái chiếu (cần xét kỹ cho từng bài toán).
- Các tệp có lỗi hoặc không giao nhau được báo trong `manifest.json`.

## Khởi động

1. Tạo [Earthdata Login](https://urs.earthdata.nasa.gov/) và lấy bearer token hợp lệ theo hướng dẫn Earthdata.
2. Tạo `.env` ở bên ngoài GitHub và gán:
   ```env
   EARTHDATA_TOKEN=YOUR_TOKEN_HERE
   ALLOWED_ORIGINS=https://xulytiengviet.github.io,http://localhost:3000
   MAX_ASSET_BYTES=536870912
   MAX_CELLS=100
   ```
3. Chạy máy chủ (từ thư mục `earthdata-raster`):
   ```bash
   docker build -t vnview-earthdata .
   docker run --rm -p 8000:8000 --env-file .env vnview-earthdata
   ```
4. Thiết lập một HTTPS reverse proxy tới cổng 8000 (ví dụ tên miền API riêng) và hạn chế quyền truy cập. **Không đưa token vào trang web, request từ trình duyệt, GitHub hoặc query string.** Mọi người sử dụng API sẽ dùng cùng quyền truy cập Earthdata của máy chủ; vì vậy chỉ cho nhóm được phép, bổ sung authentication, quota và job queue trước khi public.
5. Trong giao diện `/satellite-clip/` của VNview, điền URL của GDAL API, chọn AOI, ngày, granule và các băng TIFF, bấm tải ZIP.

## API

- `GET /api/health`: trạng thái thư viện GDAL (không công khai token).
- `POST /api/search`: `{"product":"HLSS30","bbox":[105.5,9.5,106.0,10.0],"start":"2026-09-01","end":"2026-09-03","limit":5}`.
- `POST /api/clip`: `{"geometry":{"type":"Polygon","coordinates":[[[105.5,9.5],[106,9.5],[106,10],[105.5,10],[105.5,9.5]]]},"assets":["https://data.lpdaac.earthdatacloud.nasa.gov/...B04.tif"],"rows":2,"cols":2,"mode":"matrix","dst_crs":"native"}`.

URLs ở ví dụ clip mang tính cấu trúc; URL thực phải lấy từ kết quả `/api/search`. CMR trả nhiều liên kết theo từng granule, không phải mọi liên kết đều là TIFF dùng được.

## Giới hạn quan trọng

- NASA HLS L30/S30 có các băng riêng GeoTIFF (COG), reflectance được lượng tử hóa. Kiểm tra product user guide về scale/offset, nodata, Fmask, góc quan sát, dữ liệu thiếu và độ phủ mây trước khi tính NDVI. Không coi DN đã là phản xạ vật lý.
- Cắt nhiều tệp HLS trong từng ô **không** tự động mosaic, align, stack, cloud-mask hoặc tính chỉ số. ZIP gồm các TIFF từng băng có tọa độ khoa học riêng. Nếu vùng cắt trải nhiều tile, cần ghép/mosaic có kiểm soát trước.
- Token Earthdata có thể chưa đủ quyền cho một số asset, dịch vụ có thể redirect; backend cố ý không tự động đi theo redirect của link người dùng cung cấp để tránh SSRF/chuyển tiếp token. Các sản phẩm khác HLS cần bổ sung adapter riêng.
- Hiện chạy đồng bộ, có giới hạn 12 băng, tối đa 100 ô, kích thước băng <=512 MiB; cần job queue + object storage + download có resume cho vận hành thực tế.
- Backend không công khai mặc định: CORS không thay cho xác thực, chỉ dùng trong mạng đáng tin cậy hoặc sau gateway authentication.
- Mã mới do Long Ngo đóng góp theo MIT; mã gốc Worldview và nguồn dữ liệu NASA có điều khoản riêng.
