"""Render the supplied assistant apps after the first Astra response works."""
import argparse
import json
from pathlib import Path

import boto3

from prepare_deployment import prepare


def read(path):
    return json.loads(Path(path).read_bytes())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--outputs', default='foundation-outputs.json')
    parser.add_argument('--images', default='evidence/images.json')
    parser.add_argument('--release', default='evidence/promoted-release.json')
    parser.add_argument('--source-commit', default='evidence/image-source-commit.txt')
    parser.add_argument('--kubernetes-prompt', default='evidence/kubernetes-prompt.json')
    parser.add_argument('--aws-prompt', default='evidence/aws-prompt.json')
    parser.add_argument('--output', default='deploy')
    args = parser.parse_args()
    values = {key: item['value'] for key, item in read(args.outputs).items()}
    images = read(args.images)
    domain = values['domain_configuration']
    auth = domain['browser_auth']
    if auth['type'] != 'cognito':
        raise ValueError('The supplied assistants require the configured Cognito browser sign-in')
    balancers = boto3.client('elbv2', region_name='us-east-1').describe_load_balancers(
        Names=[domain['cluster_name'] + '-edge'])['LoadBalancers']
    if len(balancers) != 1 or balancers[0]['State']['Code'] != 'active':
        raise ValueError('Publish the healthy shared gateway before configuring assistants')
    settings = {'release': read(args.release), 'release_bucket': values['buckets']['release'],
                'loader_image': images['loader']['image'], 'assistant_image': images['assistant']['image'],
                'serving_role_arn': values['serving_role_arn'], 'assistant_roles': values['assistant_roles'],
                'git_revision': Path(args.source_commit).read_text(encoding='utf-8-sig').strip(),
                'mlflow_arn': values['mlflow']['arn'], 'astra_host': domain['hosts']['inference'],
                'alb_arn': balancers[0]['LoadBalancerArn'],
                'cognito_client_id': auth['parameters']['userPoolClientID'],
                'prompts': {'kubernetes': read(args.kubernetes_prompt), 'aws': read(args.aws_prompt)}}
    result = prepare(boto3.client('s3', region_name='us-east-1'), settings, args.output, component='assistants')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
