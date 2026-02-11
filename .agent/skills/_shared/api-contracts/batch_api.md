# Batch Processing API Contract

## 1. Create Batch Job
- **Endpoint**: `POST /batch/tasks`
- **Description**: Submit multiple files for processing.
- **Request Body**:
  ```json
  {
    "file_paths": ["/path/to/file1.hwp", "/path/to/file2.pdf"],
    "options": {
      "output_dir": "/path/to/output"
    }
  }
  ```
- **Response**:
  ```json
  {
    "batch_id": "uuid-string",
    "total_files": 2,
    "status": "queued"
  }
  ```

## 2. Get Batch Status
- **Endpoint**: `GET /batch/tasks/{batch_id}`
- **Response**:
  ```json
  {
    "batch_id": "uuid-string",
    "status": "processing",
    "progress": {
      "total": 100,
      "processed": 50,
      "success": 48,
      "failed": 2
    },
    "jobs": [
      {
        "file_path": "/path/to/file1.hwp",
        "status": "completed",
        "output_path": "/path/to/output/file1_hwp/file1.md"
      },
      {
        "file_path": "/path/to/file2.pdf",
        "status": "failed",
        "error": "File corrupted"
      }
    ]
  }
  ```

## 3. Retry Failed Jobs
- **Endpoint**: `POST /batch/tasks/{batch_id}/retry`
- **Response**:
  ```json
  {
    "batch_id": "uuid-string",
    "retried_count": 2,
    "status": "queued"
  }
  ```
