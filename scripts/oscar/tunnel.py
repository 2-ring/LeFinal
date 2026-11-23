"""Forward a local LeRobot client to its Oscar job over an existing SSH master.

Usage: python3 scripts/oscar/tunnel.py JOB_ID USER@ssh.ccv.brown.edu
"""

import argparse
from pathlib import Path
import shlex
import socketserver
import subprocess


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("job_id", type=int)
    parser.add_argument("login")
    parser.add_argument("--socket", type=Path)
    parser.add_argument("--port", type=int, default=17448)
    args = parser.parse_args()
    remote_port = 24000 + args.job_id % 18000
    socket = args.socket or Path.home() / ".ssh" / f"lefinal-oscar-{args.login}.sock"
    ssh = ["ssh", "-T", "-o", "BatchMode=yes", "-S", str(socket), "--", args.login]
    # Obtain the host key through the allocation before using SSH's binary
    # forwarding channel. Slurm's own stdout transport can buffer small packets.
    lookup = f'squeue -h --jobs={args.job_id} --states=RUNNING -o "%N"'
    node = subprocess.check_output(ssh + [lookup], text=True).strip()
    if not node or not node.replace("-", "").replace(".", "").isalnum():
        parser.error("Expected one allocated compute node for this running job")
    setup = "; ".join([
        "set -eu", "umask 077", 'keyfile=$(mktemp)',
        "trap 'rm -f \"$keyfile\"' EXIT",
        f'printf "%s " {shlex.quote(node)} > "$keyfile"',
        f'srun --jobid={args.job_id} --overlap -N1 -n1 -c1 '
        'cat /etc/ssh/ssh_host_ed25519_key.pub </dev/null >> "$keyfile"',
        'ssh -T -o BatchMode=yes -o StrictHostKeyChecking=yes '
        f'-o UserKnownHostsFile="$keyfile" -W 127.0.0.1:{remote_port} {shlex.quote(node)}',
    ])

    class Relay(socketserver.BaseRequestHandler):
        def handle(self):
            subprocess.run(ssh + [setup], stdin=self.request, stdout=self.request, check=True)

    class LocalServer(socketserver.ThreadingTCPServer):
        allow_reuse_address = True
        daemon_threads = True

    with LocalServer(("127.0.0.1", args.port), Relay) as server:
        print(f"Listening on 127.0.0.1:{args.port} for Oscar job {args.job_id}", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
