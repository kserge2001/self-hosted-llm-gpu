"""Copy exact model object versions and verify their destination bytes."""
import hashlib

from artifact_loader import CHUNK_SIZE


def verify_copy(s3, bucket, item):
    response = s3.get_object(Bucket=bucket, Key=item["key"], VersionId=item["version_id"])
    digest = hashlib.sha256()
    count = 0
    with response["Body"] as source:
        while chunk := source.read(CHUNK_SIZE):
            count += len(chunk)
            if count > item["bytes"]:
                raise ValueError("Promoted object exceeds its expected size")
            digest.update(chunk)
    if count != item["bytes"] or digest.hexdigest() != item["sha256"]:
        raise ValueError("Promoted object failed its integrity check")


def copy_version(s3, source_bucket, destination_bucket, item, key):
    """Copy the pinned source version, including model shards above 5 GiB."""
    source = {"Bucket": source_bucket, "Key": item["key"], "VersionId": item["version_id"]}
    if item["bytes"] <= 5 * 1024 ** 3:
        return s3.copy_object(Bucket=destination_bucket, Key=key, CopySource=source,
                              MetadataDirective="REPLACE", Metadata={"sha256": item["sha256"]},
                              TaggingDirective="REPLACE")
    upload = s3.create_multipart_upload(Bucket=destination_bucket, Key=key,
                                        Metadata={"sha256": item["sha256"]})
    upload_id = upload["UploadId"]
    try:
        parts = []
        part_size = 1024 ** 3
        for number, start in enumerate(range(0, item["bytes"], part_size), 1):
            end = min(start + part_size, item["bytes"]) - 1
            part = s3.upload_part_copy(Bucket=destination_bucket, Key=key,
                UploadId=upload_id, PartNumber=number, CopySource=source,
                CopySourceRange=f"bytes={start}-{end}")
            parts.append({"PartNumber": number, "ETag": part["CopyPartResult"]["ETag"]})
        return s3.complete_multipart_upload(Bucket=destination_bucket, Key=key,
            UploadId=upload_id, MultipartUpload={"Parts": parts})
    except Exception:
        s3.abort_multipart_upload(Bucket=destination_bucket, Key=key, UploadId=upload_id)
        raise
