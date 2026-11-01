# Import your project repository

Create your own GitHub repository before the first exercise. Your pull requests, workflows, deployment settings and Argo CD configuration will use that repository.

**Step 1: Import into your GitHub account**

1. Sign in to GitHub and open [Import repository](https://github.com/new/import).
2. Use the [Astra starter repository](https://github.com/kserge2001/self-hosted-llm-gpu.git) as the source URL.
3. Select your own GitHub account or an organization where you can create repositories. Name the new repository self-hosted-llm-gpu and choose the visibility permitted by your organization.
4. Select Begin import and wait until GitHub reports that the import has completed.
5. Open the new repository under your account. Check that infra, k8s, tests and .github/workflows are present.

Open main in your imported repository and make it the default branch if necessary. The starter now includes main. If your import contains only the classroom branch, create main from codex/astra-classroom-readiness first. The lab's pull requests and release workflow use main.

**Step 2: Open your imported repository locally**

The import creates the repository in your GitHub account. Now get a local working copy of that repository. Replace YOUR_GITHUB_NAME with its owner; if you chose a different repository name, change it below as well.

```bash
git clone https://github.com/YOUR_GITHUB_NAME/self-hosted-llm-gpu.git
cd self-hosted-llm-gpu
git switch main
git remote -v
python -m venv .venv
source .venv/bin/activate
python -m pip install --requirement requirements.lock
python -m unittest discover -s tests -v
```

Use Python 3.13. The origin address must point to your imported repository. Open feature branches and pull requests there. Python implementations are supplied as files; Kubernetes YAML is under k8s. For later sessions, activate the same virtual environment before running the exercise's script.

**Step 3: Connect your CI/CD settings**

Importing brings in the code and Git history. Configure your own repository protections, deployment environment, variables and AWS OIDC trust during AWS Foundation. Set Argo CD's repository URL to your imported repository and replace CODEOWNERS with your authorized reviewers. Keep AWS credentials and application secrets outside Git.

**Verify**

The repository belongs to your account, main contains the imported files, origin points to that repository, and the local tests pass. In the first feature PR, confirm that the checks run in your repository's Actions tab.
