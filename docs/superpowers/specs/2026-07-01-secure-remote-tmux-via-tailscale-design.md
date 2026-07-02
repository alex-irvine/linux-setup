# Secure Remote tmux via Tailscale Design

Date: 2026-07-01
Repo: `linux-setup` (primary), `dotfiles` (secondary)
Status: Approved in chat, pending final spec review

## 1. Objective

Provide secure, low-friction remote access to running tmux sessions from mobile devices, without relying on the existing Muxile public relay model.

Primary goals:
- Strong security posture for remote terminal access.
- Fast setup and low ongoing maintenance.
- Works when laptop is on corporate network/VPN and phone is not.
- Keep mobile requirements explicit in documentation (not scripted).

## 2. Decision Summary

### Chosen direction

Adopt Tailscale-based remote access as v1 baseline:
- Use Tailscale private network connectivity.
- Use SSH into host over tailnet.
- Use existing tmux sessions on host (`tmux ls`, attach/create).

No Muxile code changes in v1.

### Why this direction

Compared options considered:

1) Tailscale + SSH + tmux (chosen)
- Pros: lowest implementation effort, strong security, no public relay exposure, resilient networking via Tailscale relay fallback.
- Cons: requires mobile SSH app and Tailscale app.

2) Hardened Muxile fork (mTLS + short-lived token + optional PIN)
- Pros: browser-first UX.
- Cons: significantly higher engineering and operational complexity (PKI lifecycle, authn/authz, relay hardening).

3) Managed access products (ShellHub/Teleport)
- Pros: strong policy and auditing features.
- Cons: heavier setup/ops for this personal/targeted use case.

## 3. Scope

### In scope

`linux-setup`:
- Install Tailscale package.
- Ensure tailscaled service is enabled/running.
- Add idempotent `setup-tailscale.sh`.
- Add `TAILSCALE.md` runbook.
- Update `README.md` with concise remote-tmux entrypoint and doc links.

`dotfiles`:
- Add shell UX helpers for tmux session attach/list flows.
- Add short usage notes in `dotfiles` docs.

Documentation:
- Explicit mobile app requirements for iOS/Android.
- Clear first-use flow and troubleshooting.

### Out of scope

- Building mTLS-based Muxile relay in v1.
- Public internet exposure of terminal endpoints.
- Advanced enterprise controls (session recording, SIEM integration).

## 4. Architecture

### 4.1 High-level

1. Host runs `tailscaled` and joins tailnet.
2. Phone runs Tailscale client and joins same tailnet.
3. Phone SSH client connects to host tailnet address/name.
4. User enters tmux session on host.

Trust model:
- Remote path remains private to tailnet.
- Authentication/authorization handled by Tailscale and SSH policy.
- No third-party terminal relay for v1.

### 4.2 Preferred auth posture

Preferred: Tailscale SSH policy-managed access.

Fallback: OpenSSH over tailnet using key-based auth only.

Baseline hardening guidance in docs:
- Disable password SSH login where practical.
- Restrict allowed users.
- Use least-privilege non-root user for normal shell access.

## 5. Components and Responsibilities

### 5.1 `linux-setup/endeavouros-setup.sh`

Changes:
- Install `tailscale` package.
- Enable/start `tailscaled` service.
- Call `setup-tailscale.sh`.

Constraints:
- Idempotent reruns.
- Keep non-interactive flow where possible, but support manual login step.

### 5.2 `linux-setup/setup-tailscale.sh` (new)

Responsibilities:
- Check prerequisites (`tailscale`, `systemctl`).
- Ensure daemon active.
- Detect auth state via `tailscale status`.
- If not authenticated, print exact next command and guidance.
- If authenticated, print tailnet identity summary and SSH readiness hints.

Design principle:
- Script should guide, not guess hidden org policy.
- No secret/token output in logs.

### 5.3 `linux-setup/TAILSCALE.md` (new)

Sections:
- What this setup provides.
- Host setup steps.
- Mobile app requirements (documented, not scripted).
- First-connect instructions.
- Daily usage for tmux.
- Troubleshooting for corp network edge cases.
- Lost-device response checklist.

### 5.4 `linux-setup/README.md`

Add:
- Short "Remote tmux via Tailscale" section.
- Link to full runbook in `TAILSCALE.md`.

### 5.5 `dotfiles`

Add light UX helpers only:
- list tmux sessions quickly.
- attach to named session.
- create-or-attach default session.

No security-critical policy logic in dotfiles.

## 6. User Flows

### 6.1 Host bootstrap flow

1. User runs setup script.
2. Tailscale installed and daemon started.
3. If unauthenticated, script prints next-step command.
4. User authenticates once.
5. Script (or rerun) confirms status and prints host tailnet endpoint info.

### 6.2 Mobile first-use flow

1. Install mobile apps:
   - Tailscale app.
   - SSH client app.
2. Sign in to tailnet in Tailscale app.
3. Connect via SSH to host tailnet name/IP.
4. Run `tmux ls`, then attach/create session.

### 6.3 Daily usage flow

1. Open SSH app on phone.
2. Connect to host over tailnet.
3. Use tmux helper command to resume session.
4. Disconnect at any time; tmux persists.

### 6.4 Corp/VPN mismatch flow

Expected behavior:
- Phone can be off corp VPN and still reach host through tailnet.
- If direct path blocked, Tailscale relay path may still work with higher latency.

If blocked by policy/network controls:
- Follow troubleshooting in `TAILSCALE.md`.
- Use alternate network or approved org method.

## 7. Error Handling Strategy

`setup-tailscale.sh` should handle and report:
- Missing binary.
- Daemon not running and restart failure.
- Unauthenticated state.
- Non-ready SSH posture.

Output style:
- concise status + exact corrective command.
- explicit next action.
- non-zero exit only for true failure states.

## 8. Verification Strategy

### 8.1 Functional checks

- Fresh-machine path works.
- Re-run path remains clean and idempotent.
- `tailscale status` healthy after setup.
- SSH reachability from second tailnet node.
- Phone smoke test: connect, `tmux ls`, attach/create session.

### 8.2 Negative checks

- tailscaled stopped.
- user not authenticated.
- restricted network path.

### 8.3 Documentation checks

- New user can follow docs without hidden assumptions.
- Mobile manual steps explicit and separated from scripts.

## 9. Security Posture and Residual Risk

Security gains vs current Muxile default:
- Removes hosted terminal relay trust dependency for v1 path.
- Avoids URL-only bearer access model.
- Keeps remote access on private tailnet path.

Residual risks:
- Compromised mobile device with valid tailnet and SSH access.
- Misconfigured SSH policy.
- User-level credential/key hygiene issues.

Mitigations:
- Device removal from tailnet on loss.
- key rotation and policy review.
- least-privilege host account.

## 10. Implementation Readiness

This design is ready to convert into an implementation plan.

Planned execution order:
1. `linux-setup` scripts and docs.
2. `dotfiles` UX helpers and docs.
3. end-to-end verification on host and mobile.
