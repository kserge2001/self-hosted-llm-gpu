"""Push the six locally prepared Astra images to this foundation's ECR repositories."""
import argparse
import base64
import json
import re
import subprocess
from pathlib import Path

import boto3

REPOSITORIES = {'runtime': 'evaluation', 'validation': 'evaluation', 'loader': 'loader',
                'assistant': 'assistant', 'gateway-bootstrap': 'assistant', 'intake': 'assistant'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--outputs', default='foundation-outputs.json')
    parser.add_argument('--tag', required=True, help='A new tag suffix for this build, such as class-001')
    parser.add_argument('--local-images', help='Optional JSON mapping of image names to existing local tags')
    parser.add_argument('--output', default='evidence/images.json')
    args = parser.parse_args()
    if not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9_.-]{0,80}', args.tag):
        parser.error('Use a short Docker tag suffix')
    destination = Path(args.output)
    if destination.exists():
        parser.error('Keep the existing image record; choose a new output filename')
    outputs = json.loads(Path(args.outputs).read_bytes())
    repositories = outputs['images']['value']
    local = json.loads(Path(args.local_images).read_bytes()) if args.local_images else {
        name: 'astra-' + name + ':review' for name in REPOSITORIES}
    if set(local) != set(REPOSITORIES):
        parser.error('The local image mapping must contain all six image names')
    for name in REPOSITORIES:
        subprocess.run(['docker', 'image', 'inspect', local[name]], check=True, stdout=subprocess.DEVNULL)
    ecr = boto3.client('ecr', region_name='us-east-1')
    account = boto3.client('sts', region_name='us-east-1').get_caller_identity()['Account']
    registry = account + '.dkr.ecr.us-east-1.amazonaws.com'
    if any(not value.startswith(registry + '/') for value in repositories.values()):
        raise ValueError('Use the ECR repositories owned by the current AWS account in us-east-1')
    token = ecr.get_authorization_token(registryIds=[account])['authorizationData'][0]['authorizationToken']
    username, password = base64.b64decode(token).decode().split(':', 1)
    subprocess.run(['docker', 'login', '--username', username, '--password-stdin', registry], input=password, text=True, check=True)
    result = {}
    for name, repository_key in REPOSITORIES.items():
        repository = repositories[repository_key]
        tag = name + '-' + args.tag
        target = repository + ':' + tag
        subprocess.run(['docker', 'tag', local[name], target], check=True)
        subprocess.run(['docker', 'push', target], check=True)
        detail = ecr.describe_images(repositoryName=repository.split('/', 1)[1], imageIds=[{'imageTag': tag}])['imageDetails'][0]
        result[name] = {'image': repository + '@' + detail['imageDigest'], 'tag': tag}
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print('Saved immutable image references to ' + str(destination))
    print('Images are uploaded. No cluster, model server or GPU job was started.')


if __name__ == '__main__':
    main()
