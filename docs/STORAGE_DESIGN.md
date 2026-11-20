# Storage Design

## Provider interface

`backend/omnimcp/storage.py` defines `StorageProvider` (ABC) with:
`save_stream`, `open_stream(start)`, `stat`, `delete`, `iter_objects`.

Implementations:

- **LocalStorageProvider** — VPS local disk (default). 1 MiB streaming chunks, SHA-256
  computed inline, write-to-temp + rename. *(Tested)*
- **GCSStorageProvider** — google-cloud-storage SDK behind the adapter; raises
  `NotConfigured` if the SDK/env (`OMNIMCP_GCS_BUCKET` + credentials) is absent.
  *(Live integration unverified — no credentials in dev sandbox)*
- **HFStorageProvider** — huggingface_hub behind the adapter for model/dataset artifacts;
  `OMNIMCP_HF_REPO`. *(Live integration unverified)*

Provider selection: `choose_provider(kind, size)` — model/dataset → hf, backup/archive →
gcs, else local. `get_providers()` instantiates from env; unknown/unconfigured providers
are skipped, never fatal.

## Large uploads (>10 GB) — never through the VPS

`POST /api/v1/storage/upload-sessions` with `provider=gcs` and expected size > 10 GB
creates a **direct** resumable-upload session: the control plane asks GCS for a signed
resumable URL (scoped, server-controlled) and returns it to the client; the client streams
bytes straight to GCS. Only the finalize call re-enters the control plane to record the
`StorageObject` and verify size/SHA metadata. The control plane never buffers the object.

Chunked resumable uploads through the VPS (for objects < 10 GB or local provider) use
`POST /storage/upload-sessions` + `PUT /storage/upload-sessions/{id}` per chunk +
`POST .../finalize` with sha256 verification on mismatch rejection. *(Tested)*

## Constraints honored

- HF is for models/datasets/checkpoints only, not general backup (routing rule).
- Quotas (~10 TB GCS / ~10 TB HF claimed by the operator) are **not verified** by this
  project; treat as unverified capacity until confirmed in console/billing.
- Retention/versioning fields exist on `StorageObject` (retention_policy, version);
  enforcement/GC is not implemented yet.
