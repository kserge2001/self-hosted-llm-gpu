"""Prepare the supplied model workflow from saved foundation and image outputs."""
import argparse
import hashlib
import json
import re
from pathlib import Path

import yaml

from build_pipeline import build
from pipeline_artifacts import put_json
from render_manifest import render
from start_release import validate_request

ROOT = Path(__file__).resolve().parent


def read(path):
    return json.loads(Path(path).read_bytes())


def intake_yaml(outputs, images, candidate, release_id):
    if not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,51}[a-z0-9]|[a-z0-9]', release_id):
        raise ValueError('Use a lowercase release ID of at most 53 characters')
    name = 'candidate-' + release_id
    config = {'apiVersion': 'v1', 'kind': 'ConfigMap',
              'metadata': {'name': name, 'namespace': 'model-intake'},
              'data': {'astra-candidate.json': json.dumps(candidate)}}
    values = {'INTAKE_ROLE_ARN': outputs['model_scanning']['intake_role_arn'],
              'INTAKE_IMAGE': images['intake']['image'], 'RELEASE_ID': release_id,
              'INTAKE_JOB_NAME': 'intake-' + release_id, 'CANDIDATE_CONFIGMAP': name,
              'QUARANTINE_BUCKET': outputs['buckets']['quarantine']}
    return render((ROOT / 'k8s/model-intake.yaml').read_text(), values) + '\n---\n' + yaml.safe_dump(config)


def request_from_log(release_id, log, version):
    lines = [line.strip() for line in log.splitlines() if line.strip()]
    if not lines:
        raise ValueError('Intake log is empty')
    reference = json.loads(lines[-1])
    request = dict(reference, release_id=release_id, pipeline_version=version['pipeline_version'])
    validate_request(release_id, request)
    return request


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--outputs', default='foundation-outputs.json')
    parser.add_argument('--images', default='evidence/images.json')
    sub = parser.add_subparsers(dest='stage', required=True)
    intake = sub.add_parser('intake')
    intake.add_argument('release_id')
    intake.add_argument('--candidate', default='astra-candidate.json')
    intake.add_argument('--output', default='k8s/generated/model-intake.yaml')
    pipeline = sub.add_parser('pipeline')
    pipeline.add_argument('--scan', required=True)
    pipeline.add_argument('--exception', help='An already approved, exact-image exception, if required')
    pipeline.add_argument('--evaluation-instance', choices=['ml.g6e.2xlarge', 'ml.g6e.4xlarge'], default='ml.g6e.2xlarge')
    pipeline.add_argument('--output', default='evidence/pipeline-config.json')
    request = sub.add_parser('request')
    request.add_argument('release_id')
    request.add_argument('--intake-log', default='evidence/intake.log')
    request.add_argument('--version', default='evidence/pipeline-version.json')
    args = parser.parse_args()
    if args.stage == 'request':
        value = request_from_log(args.release_id, Path(args.intake_log).read_text(), read(args.version))
        destination = Path('releases') / (args.release_id + '.json')
        body = json.dumps(value, indent=2)
    else:
        destination = Path(args.output)
        if destination.exists():
            parser.error('Keep the existing record; choose another --output')
        outputs = {key: item['value'] for key, item in read(args.outputs).items()}
        images = read(args.images)
        if args.stage == 'intake':
            body = intake_yaml(outputs, images, read(args.candidate), args.release_id)
        else:
            import boto3
            s3 = boto3.client('s3', region_name='us-east-1')
            config = dict(outputs['model_pipeline'], validation_image=images['validation']['image'],
                          runtime_image=images['runtime']['image'], evaluation_instance_type=args.evaluation_instance)
            for field, file in [('runtime_scan', args.scan), ('runtime_exception', args.exception)]:
                if file:
                    raw = read(file)
                    identity = hashlib.sha256(Path(file).read_bytes()).hexdigest()
                    config[field] = put_json(s3, config['evidence_bucket'], f'runtime/{identity}/{field}.json', raw)
            hashes = [hashlib.sha256((ROOT / 'evaluation' / name).read_bytes()).hexdigest() for name in ('policy.json', 'cases.json')]
            build(config, *hashes)
            body = json.dumps(config, indent=2)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open('x', encoding='utf-8') as output:
        output.write(body + '\n')
    print('Prepared ' + str(destination) + '. No job or GPU was started.')


if __name__ == '__main__':
    main()
