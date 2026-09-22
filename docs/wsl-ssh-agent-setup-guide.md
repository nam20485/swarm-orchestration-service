# WSL SSH Agent Setup Guide

_Imported from `nam20485/workflow-launch2/docs/` during the launcher fold. The launch pipeline needs it: `Invoke-GitClone` (`scripts/repo-functions.ps1`) clones new repos over `git@github.com:`, so a running SSH agent is a hard prerequisite on WSL/Linux._

This guide covers two native WSL SSH agent setups:

1. `systemd` user service (preferred when available)
2. `.bashrc` managed agent (works without systemd)

Use one option at a time.

## Prerequisites

```bash
sudo apt update
sudo apt install -y openssh-client
```

Confirm your key exists:

```bash
ls -l ~/.ssh/id_ed25519 ~/.ssh/id_rsa
```

## Option 1: systemd User Service

Check that systemd is enabled in your WSL distro:

```bash
systemctl --user --version
```

Create the user service and environment file:

```bash
mkdir -p ~/.config/systemd/user ~/.config/environment.d

cat > ~/.config/systemd/user/ssh-agent.service <<'EOF'
[Unit]
Description=SSH agent

[Service]
Type=simple
Environment=SSH_AUTH_SOCK=%t/ssh-agent.socket
ExecStart=/usr/bin/ssh-agent -D -a ${SSH_AUTH_SOCK}

[Install]
WantedBy=default.target
EOF

cat > ~/.config/environment.d/10-ssh-agent.conf <<'EOF'
SSH_AUTH_SOCK=${XDG_RUNTIME_DIR}/ssh-agent.socket
EOF
```

Enable and start:

```bash
systemctl --user daemon-reload
systemctl --user enable --now ssh-agent.service
systemctl --user status ssh-agent.service --no-pager
```

Export socket in current shell (new shells should inherit automatically):

```bash
export SSH_AUTH_SOCK="$XDG_RUNTIME_DIR/ssh-agent.socket"
```

Load your key once per agent lifetime:

```bash
ssh-add ~/.ssh/id_ed25519
ssh-add -l
```

## Option 2: `.bashrc` Managed Agent

Add this block to `~/.bashrc`:

```bash
export SSH_AUTH_SOCK="$HOME/.ssh/agent.sock"

ssh-add -l >/dev/null 2>&1
if [ $? -eq 2 ]; then
  rm -f "$SSH_AUTH_SOCK"
  eval "$(ssh-agent -a "$SSH_AUTH_SOCK")" >/dev/null
fi
```

Reload shell config:

```bash
source ~/.bashrc
```

Load your key:

```bash
ssh-add ~/.ssh/id_ed25519
ssh-add -l
```

## Verify Either Option

```bash
echo "$SSH_AUTH_SOCK"
ssh-add -l
ssh -T git@github.com
```

Expected behavior:

1. `ssh-add -l` lists one or more identities.
2. GitHub responds with a successful auth message (no shell access).

## Quick Troubleshooting

If agent is unreachable:

```bash
echo "$SSH_AUTH_SOCK"
ls -l "$SSH_AUTH_SOCK"
ssh-add -l
```

If using systemd and it is down:

```bash
systemctl --user restart ssh-agent.service
systemctl --user status ssh-agent.service --no-pager
```

If using `.bashrc` mode and socket is stale, open a new shell or run:

```bash
rm -f ~/.ssh/agent.sock
eval "$(ssh-agent -a ~/.ssh/agent.sock)"
ssh-add ~/.ssh/id_ed25519
```
