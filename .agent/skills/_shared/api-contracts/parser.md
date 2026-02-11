# Parser API Contracts

## Endpoints

### 1. Create Parsing Job
- **Path**: `/api/v1/parser/jobs`
- **Method**: `POST`
- **Auth**: Required (API Key or JWT)
- **Request (Multipart)**:
  - `files`: List of files (PDF, HWP, DOCX)
  - `target_format`: `markdown` | `json` (Default: `markdown`)
  - `options`: JSON string containing `extract_images` (bool), `extract_formulas` (bool)
- **Response (202 Accepted)**:
  ```json
  {
    "job_id": "uuid-v4",
    "status": "queued",
    "created_at": "ISO-8601"
  }
  ```

### 2. Get Job Status
- **Path**: `/api/v1/parser/jobs/{job_id}`
- **Method**: `GET`
- **Response (200 OK)**:
  ```json
  {
    "job_id": "uuid-v4",
    "status": "processing | completed | failed",
    "progress": 45,
    "files": [
      {
        "filename": "document.pdf",
        "status": "completed",
        "result_url": "https://storage.example.com/results/..."
      }
    ],
    "errors": []
  }
  ```

### 3. Download Job Results (Bulk)
- **Path**: `/api/v1/parser/jobs/{job_id}/download`
- **Method**: `GET`
- **Response (200 OK)**: 
  - `content-type`: `application/zip`
  - Body: Zip file containing all parsed documents.

## Error Codes
- `400`: Unsupported file format
- `413`: File too large
- `500`: Internal processing error
