"""Publish file-validated model artifacts for the infrastructure-only lab.

File preparation is complete only after the copies are verified. The lab also
requires a request through the deployed Astra gateway.
"""
import argparse
import json
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from artifact_loader import validate_manifest
from pipeline_artifacts import put_json, read_pinned_json, s3_location, validate_candidate
from model_storage import copy_version, verify_copy

FILE_CHECKS = {'provenance', 'license', 'file_integrity', 'file_format', 'malware', 'runtime_scan'}


def check_validation(report, runtime_image, now=None):
    now = now or datetime.now(timezone.utc)
    if report.get('passed') is not True or any(report.get('checks', {}).get(key) != 'PASS' for key in FILE_CHECKS):
        raise ValueError('All file, provenance and runtime scan checks must pass')
    expires = datetime.fromisoformat(report['valid_until'].replace('Z', '+00:00'))
    if expires.tzinfo is None or expires <= now:
        raise ValueError('Validation or the approved runtime exception has expired')
    if report['runtime_image'] != runtime_image or report['subject']['runtime_digest'] != runtime_image.rsplit('@', 1)[-1]:
        raise ValueError('Runtime differs from the validated image')
    if report['candidate']['sha256'] != report['subject']['manifest_sha256']:
        raise ValueError('Candidate differs from the validated subject')


def publish(s3, reference, settings, runtime_image):
    bucket, key = s3_location(reference['uri'])
    if bucket != settings['evidence_bucket'] or not key.startswith('pipeline/') or not key.endswith('/validation.json'):
        raise ValueError('Use this foundation\'s versioned validation report')
    report = read_pinned_json(s3, **reference)
    check_validation(report, runtime_image)
    if s3_location(report['candidate']['uri'])[0] != settings['quarantine_bucket']:
        raise ValueError('Candidate is outside the foundation quarantine bucket')
    candidate = read_pinned_json(s3, **report['candidate'])
    files = validate_candidate(candidate, report['release_id'], settings['quarantine_bucket'])
    prefix = 'releases/' + report['release_id']
    def copy_file(item):
        key = prefix + '/files/' + item['path']
        copied = copy_version(s3, settings['quarantine_bucket'], settings['release_bucket'], item, key)
        if not copied.get('VersionId') or copied['VersionId'] == 'null':
            raise ValueError('Release objects must be versioned')
        entry = dict(item, key=key, version_id=copied['VersionId'])
        verify_copy(s3, settings['release_bucket'], entry)
        return entry
    # Copy independent shards concurrently. Every future must succeed before
    # the manifest can be published, and each destination version is hashed.
    with ThreadPoolExecutor(max_workers=4) as workers:
        promoted = list(workers.map(copy_file, files))
    check_validation(report, runtime_image)
    manifest = {'schema': 1, 'release_id': report['release_id'], 'runtime_image': runtime_image,
                'files': promoted, 'subject': report['subject'], 'candidate': report['candidate'],
                'source_repository': candidate['source_repository'], 'source_revision': candidate['source_revision'],
                'license_label': candidate['license_label'],
                'publication': {'scope': 'infrastructure_lab', 'validation': reference,
                                'live_inference': 'pending',
                                'runtime_valid_until': report['valid_until']}}
    validate_manifest(manifest)
    return put_json(s3, settings['release_bucket'], prefix + '/release-manifest.json', manifest, IfNoneMatch='*')


def main():
    import boto3
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--scope', required=True, choices=['infrastructure-lab'])
    parser.add_argument('--validation-reference', required=True)
    parser.add_argument('--outputs', default='foundation-outputs.json')
    parser.add_argument('--images', default='evidence/images.json')
    args = parser.parse_args()
    settings = json.loads(Path(args.outputs).read_bytes())['model_pipeline']['value']
    runtime = json.loads(Path(args.images).read_bytes())['runtime']['image']
    reference = json.loads(Path(args.validation_reference).read_bytes())
    credentials = boto3.client('sts', region_name='us-east-1').assume_role(
        RoleArn=settings['promotion_role_arn'], RoleSessionName='astra-infrastructure-lab', DurationSeconds=3600)['Credentials']
    session = boto3.Session(region_name='us-east-1', aws_access_key_id=credentials['AccessKeyId'],
        aws_secret_access_key=credentials['SecretAccessKey'], aws_session_token=credentials['SessionToken'])
    print(json.dumps(publish(session.client('s3'), reference, settings, runtime)))


if __name__ == '__main__':
    main()
