# GitHub SSH Setup

This file explains exactly how to finish GitHub SSH setup for this repo on this Raspberry Pi.

## Current State

Already done:

- a local git repo exists
- the first commit already exists locally
- a dedicated SSH key was created on this Pi
- an SSH config entry for GitHub was added

Files already created on this Pi:

- private key: `~/.ssh/id_ed25519_github_luggage_loader`
- public key: `~/.ssh/id_ed25519_github_luggage_loader.pub`
- SSH config: `~/.ssh/config`

## What You Need To Do

You only need to do one GitHub website step:

1. Log in to GitHub in your browser.
2. Open:
   - `https://github.com/settings/keys`
3. Click `New SSH key`.
4. In `Title`, enter something like:
   - `Raspberry Pi 5 - Luggage Loader System`
5. In `Key type`, leave it as:
   - `Authentication Key`
6. In `Key`, paste the full public key from this file:
   - `~/.ssh/id_ed25519_github_luggage_loader.pub`
7. Click `Add SSH key`.

## Public Key To Paste

Open and copy it with:

```bash
cat ~/.ssh/id_ed25519_github_luggage_loader.pub
```

## After You Add The Key

Run these commands in the repo:

```bash
cd /home/max/Desktop/Steer_Clear
ssh-keyscan github.com >> ~/.ssh/known_hosts
chmod 600 ~/.ssh/known_hosts
ssh -T git@github.com
git remote set-url origin git@github.com:MaxSch17799/Luggage_Loader_System.git
git push -u origin main
```

## What Success Looks Like

These are the expected outcomes:

- `ssh -T git@github.com` says GitHub authenticated you
- `git push -u origin main` succeeds
- the repo files appear on:
  - `https://github.com/MaxSch17799/Luggage_Loader_System`

## Normal Future Pushes

After SSH works, your normal push flow is:

```bash
cd /home/max/Desktop/Steer_Clear
git status
git add .
git commit -m "Describe the milestone"
git push
```

