#!/usr/bin/env bash
# One-time setup of a fresh Ubuntu/Debian VM as the production host. Run as root ON the VM:
#   sudo ./provision_vm.sh
# Idempotent: safe to re-run. NOT YET RUN: this is production-ready code for a host that does not exist yet.
#
# What it does: installs k3s (single-node Kubernetes, pinned version), installs Argo Rollouts (pinned), creates the
# llm-serve namespace, applies the least-privilege deployer ServiceAccount, and writes a kubeconfig for it that the
# deploy workflow uses over SSH. The deploy key can then manage the llm-serve namespace and nothing else.
#
# You still do by hand, once: create the Cloudflare tunnel and store its token (see deploy/production/cloudflared.yaml).
set -euo pipefail

K3S_VERSION="${K3S_VERSION:-v1.30.5+k3s1}"
ARGO_ROLLOUTS_VERSION="${ARGO_ROLLOUTS_VERSION:-v1.7.2}"
DEPLOY_USER="${DEPLOY_USER:-deploy}"
NS=llm-serve

[ "$(id -u)" = 0 ] || { echo "run as root"; exit 1; }
K="k3s kubectl"

if ! command -v k3s >/dev/null; then
  # --disable traefik / servicelb: traffic arrives through the Cloudflare Tunnel, so no ingress or LB is needed.
  curl -sfL https://get.k3s.io | INSTALL_K3S_VERSION="$K3S_VERSION" INSTALL_K3S_EXEC="--disable traefik --disable servicelb" sh -
fi
until $K get nodes 2>/dev/null | grep -q " Ready"; do sleep 3; done

$K create namespace argo-rollouts --dry-run=client -o yaml | $K apply -f -
$K apply -n argo-rollouts --server-side -f \
  "https://github.com/argoproj/argo-rollouts/releases/download/$ARGO_ROLLOUTS_VERSION/install.yaml"
$K -n argo-rollouts rollout status deployment/argo-rollouts --timeout=240s

$K create namespace $NS --dry-run=client -o yaml | $K apply -f -

# The deployer identity, applied from the same file CI validates.
$K apply -n $NS -f "$(dirname "$0")/../deploy/production/deployer-rbac.yaml"

id "$DEPLOY_USER" >/dev/null 2>&1 || useradd --create-home --shell /bin/bash "$DEPLOY_USER"
install -d -m 700 -o "$DEPLOY_USER" -g "$DEPLOY_USER" "/home/$DEPLOY_USER/.kube" "/home/$DEPLOY_USER/.ssh"
TOKEN=$($K -n $NS create token deployer --duration=8760h)
SERVER="https://127.0.0.1:6443"
CA=$(base64 -w0 /var/lib/rancher/k3s/server/tls/server-ca.crt)
cat > "/home/$DEPLOY_USER/.kube/deployer.yaml" <<KUBECONFIG
apiVersion: v1
kind: Config
clusters: [{name: k3s, cluster: {server: $SERVER, certificate-authority-data: $CA}}]
users: [{name: deployer, user: {token: $TOKEN}}]
contexts: [{name: deployer, context: {cluster: k3s, user: deployer, namespace: $NS}}]
current-context: deployer
KUBECONFIG
chown "$DEPLOY_USER:$DEPLOY_USER" "/home/$DEPLOY_USER/.kube/deployer.yaml"
chmod 600 "/home/$DEPLOY_USER/.kube/deployer.yaml"
# kubectl for the deploy user: k3s ships one binary; expose it as `kubectl`.
[ -e /usr/local/bin/kubectl ] || ln -s "$(command -v k3s)" /usr/local/bin/kubectl

cat <<'NEXT'

Done. Remaining one-time steps:
  1. Add the GitHub Actions public deploy key to /home/deploy/.ssh/authorized_keys.
  2. Create the Cloudflare tunnel, route api.<your-domain> to http://llm-serve.llm-serve.svc:80, then:
       k3s kubectl -n llm-serve create secret generic cloudflared-token --from-literal=token=<TOKEN>
  3. If the GHCR package is private, also create an image pull secret; or make the package public.
  4. In GitHub: environment "production" (required reviewer) with secrets PROD_HOST, PROD_SSH_USER,
     PROD_SSH_KEY, PROD_SSH_KNOWN_HOSTS and variable PROD_URL. Then run the "deploy-production" workflow.
NEXT
