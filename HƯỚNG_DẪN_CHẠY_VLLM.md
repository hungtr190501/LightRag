# Hướng dẫn chạy LightRAG vLLM Demo

## 1. Chạy qua venv

### Bước 1: Kích hoạt venv
```bash
# Từ folder gốc LightRAG
source .venv/bin/activate
```

### Bước 2: Cài đặt dependencies (nếu chưa có)
```bash
pip install -e .
pip install python-dotenv
```

### Bước 3: Chuẩn bị dữ liệu
Tạo file `Data/book-small.txt` hoặc sử dụng file khác:
```bash
mkdir -p Data
# Thêm file text của bạn vào Data/book-small.txt
```

### Bước 4: Chạy demo
```bash
# Cách 1: Sử dụng .env file
export DOTENV_FILE=.env.vllm
python examples/lightrag_vllm_demo.py

# Cách 2: Sử dụng environment variables trực tiếp
export LLM_BINDING_HOST=http://192.168.2.181:9061/v1
export EMBEDDING_BINDING_HOST=http://192.168.2.181:9061/v1
export RERANK_BINDING_HOST=http://192.168.2.182:8787/api/v1/rerank
python examples/lightrag_vllm_demo.py
```

## 2. Chạy qua Docker

### Bước 1: Tạo Dockerfile
```dockerfile
FROM python:3.11-slim

WORKDIR /app

# Cài đặt dependencies
RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*

# Copy project
COPY . .

# Cài đặt LightRAG
RUN pip install --no-cache-dir -e .
RUN pip install --no-cache-dir python-dotenv

# Tạo folder data
RUN mkdir -p Data rag_storage

# Expose port (nếu cần API server)
EXPOSE 8000

# Default command
CMD ["python", "examples/lightrag_vllm_demo.py"]
```

### Bước 2: Build Docker image
```bash
docker build -t lightrag-vllm:latest .
```

### Bước 3: Chạy Docker container
```bash
docker run --rm \
  -e LLM_BINDING_HOST=http://192.168.2.181:9061/v1 \
  -e EMBEDDING_BINDING_HOST=http://192.168.2.181:9061/v1 \
  -e RERANK_BINDING_HOST=http://192.168.2.182:8787/api/v1/rerank \
  -v $(pwd)/Data:/app/Data \
  -v $(pwd)/rag_storage:/app/rag_storage \
  --network host \
  lightrag-vllm:latest
```

### Bước 4: Chạy với docker-compose (tuỳ chọn)
Tạo `docker-compose.vllm.yml`:
```yaml
version: '3.8'

services:
  lightrag:
    build: .
    environment:
      - LLM_BINDING_HOST=http://192.168.2.181:9061/v1
      - EMBEDDING_BINDING_HOST=http://192.168.2.181:9061/v1
      - RERANK_BINDING_HOST=http://192.168.2.182:8787/api/v1/rerank
      - KV_STORAGE=JsonKVStorage
      - DOC_STATUS_STORAGE=JsonDocStatusStorage
      - VECTOR_STORAGE=JsonVectorStorage
      - GRAPH_STORAGE=NetworkxStorage
    volumes:
      - ./Data:/app/Data
      - ./rag_storage:/app/rag_storage
    networks:
      - lightrag-net
    restart: unless-stopped

networks:
  lightrag-net:
    driver: bridge
```

Chạy:
```bash
docker-compose -f docker-compose.vllm.yml up
```

## 3. Lưu ý quan trọng

- **Network**: Nếu chạy trong Docker và vLLM server ở máy khác, đảm bảo network có thể kết nối.
  - Nếu vLLM ở local machine, dùng `--network host` hoặc thay `localhost` bằng IP máy
  - Nếu vLLM ở máy khác, sử dụng IP cố định như bạn đã cung cấp

- **Storage**: Để dễ quản lý, sử dụng `JsonKVStorage`, `JsonVectorStorage`, `JsonDocStatusStorage`, `NetworkxStorage` (không cần database phức tạp)

- **Model name**: API của bạn trả về model `qwen3-14b`, nên sử dụng tên đó trong config

- **Reranker API**: Kiểm tra API endpoint của bạn có đúng format không. Endpoint là `/api/v1/rerank` chứ không phải `/v1/rerank`

## 4. Troubleshooting

### Connection Error
```bash
# Kiểm tra kết nối vLLM
curl http://192.168.2.181:9061/v1/models

# Kiểm tra kết nối Reranker  
curl -X POST http://192.168.2.182:8787/api/v1/rerank \
  -H "Content-Type: application/json" \
  -d '{"query":"test","documents":[{"id":1,"text":"test"}]}'
```

### Import Error
Cài đặt lại dependencies:
```bash
pip install --upgrade lightrag
```

### Storage Error
Nếu gặp lỗi storage, thử xóa folder `rag_storage/` và chạy lại
