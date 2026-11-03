"""Open this foundation's managed MLflow UI using a short-lived AWS sign-in."""
import argparse
import json
import webbrowser
from pathlib import Path

import boto3


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--outputs', default='foundation-outputs.json')
    args = parser.parse_args()
    arn = json.loads(Path(args.outputs).read_bytes())['mlflow']['value']['arn']
    name = arn.rsplit('/', 1)[-1]
    response = boto3.client('sagemaker', region_name='us-east-1').create_presigned_mlflow_tracking_server_url(
        TrackingServerName=name, SessionExpirationDurationInSeconds=1800, ExpiresInSeconds=300)
    if not webbrowser.open(response['AuthorizedUrl']):
        raise RuntimeError('No browser opened. Use the AWS CLI sign-in command in the guide from your workstation.')
    print('Opened managed MLflow in your browser. The sign-in URL is not saved or printed.')


if __name__ == '__main__':
    main()
