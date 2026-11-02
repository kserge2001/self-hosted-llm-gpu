"""Preserve this rehearsal's MLflow metadata before removing its server."""
import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from mlflow import MlflowClient
import mlflow

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--outputs', default='foundation-outputs.json')
parser.add_argument('--kubernetes-prompt', default='evidence/kubernetes-prompt.json')
parser.add_argument('--aws-prompt', default='evidence/aws-prompt.json')
parser.add_argument('--output', default='evidence/mlflow-export.json')
args = parser.parse_args()
outputs = json.loads(Path(args.outputs).read_bytes())
mlflow.set_tracking_uri(outputs['mlflow']['value']['arn'])
client = MlflowClient()
result = {'exported_at': datetime.now(timezone.utc).isoformat(), 'experiments': [], 'errors': []}
for experiment in client.search_experiments():
    if not experiment.name.startswith('astra-'):
        continue
    item = {'experiment': dict(experiment), 'runs': [], 'traces': []}
    token = None
    while True:
        runs = client.search_runs([experiment.experiment_id], max_results=100, page_token=token)
        item['runs'].extend(run.to_dictionary() for run in runs)
        token = runs.token
        if not token:
            break
    token = None
    try:
        while True:
            traces = client.search_traces([experiment.experiment_id], max_results=100, page_token=token)
            item['traces'].extend(json.loads(trace.to_json()) for trace in traces)
            token = traces.token
            if not token:
                break
    except Exception as error:
        result['errors'].append({'experiment': experiment.name, 'stage': 'traces', 'error': str(error)[:300]})
    result['experiments'].append(item)
result['prompt_records'] = {
    kind: json.loads(Path(getattr(args, kind + '_prompt')).read_text(encoding='utf-8-sig'))
    for kind in ('kubernetes', 'aws')
}
path = Path(args.output)
path.parent.mkdir(parents=True, exist_ok=True)
path.write_text(json.dumps(result, indent=2, default=str))
print(json.dumps({'experiments': len(result['experiments']), 'runs': sum(len(e['runs']) for e in result['experiments']), 'traces': sum(len(e['traces']) for e in result['experiments']), 'errors': result['errors'], 'saved': str(path)}))
if result['errors']:
    raise SystemExit(1)

