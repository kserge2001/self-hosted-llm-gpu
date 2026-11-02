"""Prepare the supplied model workflow from saved foundation and image outputs."""
import argparse
import hashlib
import json
import re
from pathlib import Path

import yaml

from build_pipeline import build
from pipeline_artifacts import put_json
from pipeline_artifacts import read_pinned_json, s3_location
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
    pipeline.add_argument('--include-evaluation', action='store_true', help='Optional separate evaluation outside the infrastructure lab')
    pipeline.add_argument('--output', default='evidence/pipeline-config.json')
    request = sub.add_parser('request')
    request.add_argument('release_id')
    request.add_argument('--intake-log', default='evidence/intake.log')
    request.add_argument('--version', default='evidence/pipeline-version.json')
    collect = sub.add_parser('collect-validation')
    collect.add_argument('--execution-arn', required=True)
    collect.add_argument('--output', default='evidence/validation-reference.json')
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
        elif args.stage == 'collect-validation':
            import boto3
            from publish_lab_model import check_validation
            client = boto3.client('sagemaker', region_name='us-east-1')
            steps = client.list_pipeline_execution_steps(PipelineExecutionArn=args.execution_arn)['PipelineExecutionSteps']
            matches = [step for step in steps if step['StepName'] == 'Validate' and step['StepStatus'] == 'Succeeded']
            if len(matches) != 1:
                raise ValueError('The validation step has not succeeded')
            job_arn = matches[0]['Metadata']['ProcessingJob']['Arn']
            job = client.describe_processing_job(ProcessingJobName=job_arn.rsplit('/', 1)[-1])
            if (job['ProcessingJobStatus'] != 'Completed'
                    or job['RoleArn'] != outputs['model_pipeline']['validation_role_arn']
                    or job['AppSpecification']['ImageUri'] != images['validation']['image']):
                raise ValueError('Validation job does not match this foundation and image record')
            execution_id = args.execution_arn.rsplit('/', 1)[-1]
            bucket = outputs['model_pipeline']['evidence_bucket']
            output_uri = f's3://{bucket}/pipeline/{execution_id}/validate-output/'
            reports = [output for output in job['ProcessingOutputConfig']['Outputs'] if output['OutputName'] == 'report']
            if len(reports) != 1 or reports[0]['S3Output']['S3Uri'] != output_uri:
                raise ValueError('Validation output is outside this execution')
            s3 = boto3.client('s3', region_name='us-east-1')
            response = s3.get_object(Bucket=bucket, Key=f'pipeline/{execution_id}/validate-output/validation.json')
            with response['Body'] as source:
                raw = source.read(4 * 1024 * 1024 + 1)
            if len(raw) > 4 * 1024 * 1024:
                raise ValueError('Validation output is too large')
            reference = json.loads(raw)['evidence']
            if s3_location(reference['uri']) != (bucket, f'pipeline/{execution_id}/validation.json'):
                raise ValueError('Validation reference is outside this execution')
            check_validation(read_pinned_json(s3, **reference), images['runtime']['image'])
            body = json.dumps(reference, indent=2)
        else:
            import boto3
            s3 = boto3.client('s3', region_name='us-east-1')
            config = dict(outputs['model_pipeline'], validation_image=images['validation']['image'],
                          runtime_image=images['runtime']['image'], evaluation_instance_type=args.evaluation_instance)
            if not args.include_evaluation:
                config['workflow_scope'] = 'infrastructure_lab'
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
