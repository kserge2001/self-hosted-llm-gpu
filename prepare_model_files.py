"""Run the supplied CPU file checks after the model download/upload demo.

Students do not assemble or operate a pipeline. This helper uses the existing
validation implementation, saves progress for retries and never evaluates a GPU.
"""
import argparse
import hashlib
import json
import re
import subprocess
import sys
import time
from pathlib import Path

from pipeline_artifacts import runtime_findings
from prepare_model_pipeline import request_from_log
from start_release import request_arguments

ROOT = Path(__file__).resolve().parent


def read(path):
    return json.loads(Path(path).read_bytes())


def save(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', encoding='utf-8') as output:
        json.dump(value, output, indent=2)
        output.write('\n')


def check_runtime(scan, image, exception=None):
    findings = runtime_findings(scan, image)
    if exception is not None:
        from runtime_exception import apply_exception
        findings, _ = apply_exception(findings, exception, image)
    if findings:
        raise ValueError('Resolve the runtime scan findings before starting file preparation')


def wait_for_checks(client, execution, timeout=2700, interval=15, clock=time.monotonic, sleep=time.sleep):
    deadline = clock() + timeout
    try:
        while True:
            status = client.describe_pipeline_execution(PipelineExecutionArn=execution)['PipelineExecutionStatus']
            if status == 'Succeeded':
                return
            if status in {'Failed', 'Stopped', 'Stopping'}:
                raise RuntimeError('Model file checks did not complete successfully: ' + status)
            if clock() >= deadline:
                raise TimeoutError('File checks exceeded the wait limit; stopping this execution')
            sleep(interval)
    except (KeyboardInterrupt, TimeoutError):
        client.stop_pipeline_execution(PipelineExecutionArn=execution)
        raise


def main():
    import boto3
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('release_id')
    parser.add_argument('--outputs', default='foundation-outputs.json')
    parser.add_argument('--images', default='evidence/images.json')
    parser.add_argument('--intake-log', default='evidence/intake.log')
    parser.add_argument('--scan', default='evidence/runtime-scan.json')
    parser.add_argument('--exception', help='Existing approved exact-image exception, only if required')
    parser.add_argument('--output', default='evidence/validation-reference.json')
    args = parser.parse_args()
    if not re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,51}[a-z0-9])?', args.release_id):
        parser.error('Use the same lowercase release ID as the intake job')
    if Path.cwd().resolve() != ROOT:
        parser.error('Run this helper from the starter repository root')
    # Read required inputs before any upload or paid job. No GPU is started.
    inputs = [args.outputs, args.images, args.intake_log, 'model-policy.json']
    for path in inputs:
        Path(path).read_bytes()
    image = read(args.images)['runtime']['image']
    scan_path = Path(args.scan)
    if not scan_path.exists():
        scan_path.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(['trivy', 'image', '--scanners', 'vuln,secret', '--format', 'json',
                        '--output', str(scan_path), image], check=True)
    exception = read(args.exception) if args.exception else None
    check_runtime(read(args.scan), image, exception)
    inputs += [args.scan] + ([args.exception] if args.exception else [])
    identity = {path: hashlib.sha256(Path(path).read_bytes()).hexdigest() for path in inputs}
    directory = Path('evidence/model-preparation') / args.release_id
    identity_path = directory / 'inputs.json'
    if identity_path.exists():
        if read(identity_path) != identity:
            raise ValueError('Inputs changed. Keep the saved attempt and choose a new release ID')
    else:
        save(identity_path, identity)
    config_path, version_path = directory / 'config.json', directory / 'version.json'
    def run(script, *arguments):
        subprocess.run([sys.executable, script, *map(str, arguments)], check=True)
    if not config_path.exists():
        extra = ['--exception', args.exception] if args.exception else []
        run('prepare_model_pipeline.py', '--outputs', args.outputs, '--images', args.images,
            'pipeline', '--scan', args.scan, '--output', config_path, *extra)
    config = read(config_path)
    if config.get('workflow_scope') != 'infrastructure_lab':
        raise ValueError('This helper only runs infrastructure file checks')
    if not version_path.exists():
        run('deploy_pipeline.py', config_path, '--output', version_path)
    request = request_from_log(args.release_id, Path(args.intake_log).read_text(), read(version_path))
    client = boto3.client('sagemaker', region_name='us-east-1')
    execution_path = directory / 'execution.json'
    if execution_path.exists():
        execution = read(execution_path)['arn']
    else:
        execution = client.start_pipeline_execution(
            **request_arguments(args.release_id, request, config['pipeline_name']))['PipelineExecutionArn']
        save(execution_path, {'arn': execution})
    print('Running the supplied CPU file checks. No serving GPU or model question suite is started.', flush=True)
    wait_for_checks(client, execution)
    reference_path = directory / 'validation-reference.json'
    if not reference_path.exists():
        run('prepare_model_pipeline.py', '--outputs', args.outputs, '--images', args.images,
            'collect-validation', '--execution-arn', execution, '--output', reference_path)
    reference = read(reference_path)
    # Recheck expiration and exact image even when resuming a completed attempt.
    from pipeline_artifacts import read_pinned_json
    from publish_lab_model import check_validation
    report = read_pinned_json(boto3.client('s3', region_name='us-east-1'), **reference)
    check_validation(report, image)
    if report['release_id'] != args.release_id:
        raise ValueError('Validation belongs to another release')
    if Path(args.output).exists():
        if read(args.output) != reference:
            raise FileExistsError('Keep the previous validation record; choose another --output')
    else:
        save(args.output, reference)
    print('File checks passed. Use the saved validation reference to publish the model files.')


if __name__ == '__main__':
    main()
