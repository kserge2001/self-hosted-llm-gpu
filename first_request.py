"""Send one real request through the deployed Astra gateway."""
import argparse
import json
from pathlib import Path

import boto3
from openai import OpenAI


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--outputs', default='foundation-outputs.json')
    parser.add_argument('--application', choices=['k8s-assistant', 'aws-assistant'], default='k8s-assistant')
    parser.add_argument('--question', default='Explain a Kubernetes Service in two sentences.')
    args = parser.parse_args()
    outputs = {key: value['value'] for key, value in json.loads(Path(args.outputs).read_bytes()).items()}
    host = outputs['domain_configuration']['hosts']['inference']
    secret_arn = outputs['application_secrets'][args.application]['secret_arn']
    secret = boto3.client('secretsmanager', region_name='us-east-1').get_secret_value(SecretId=secret_arn)
    key = json.loads(secret['SecretString'])['OPENAI_API_KEY']
    with OpenAI(base_url='https://' + host + '/v1', api_key=key, timeout=120, max_retries=0) as client:
        response = client.chat.completions.create(model='astra', messages=[{'role': 'user', 'content': args.question}], max_tokens=160)
    answer = response.choices[0].message.content
    if not answer or not answer.strip():
        raise RuntimeError('Astra returned no text answer')
    print(answer)


if __name__ == '__main__':
    main()
