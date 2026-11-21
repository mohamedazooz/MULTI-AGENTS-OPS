<#
.SYNOPSIS
    Phase 0 read-only VPS audit. Runs ONLY non-mutating remote commands.
.DESCRIPTION
    Requires an already-authorized SSH key. Never installs packages, changes
    firewall/SSH/proxy config, restarts services, or runs Docker commands that
    mutate state. Config dumps are redacted before being written locally.
.EXAMPLE
    .\phase0-audit.ps1 -RemoteHost 102.206.132.212 -User machsol -KeyPath "$env:USERPROFILE\.ssh\id_ed25519_solana_hft"
#>
[CmdletBinding()]
param(
  [string]$RemoteHost = '102.206.132.212',
  [string]$User = 'machsol',
  [string]$KeyPath = (Join-Path $env:USERPROFILE '.ssh\id_ed25519'),
  [string]$OutDir = (Join-Path $env:TEMP 'opencode\phase0-raw')
)

$ErrorActionPreference = 'Continue'
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null

# Redacts secret-bearing assignments before config output reaches local logs.
$RedactFilter = "sed -E 's/(password|passwd|secret|token|api[_-]?key|credential|authorization|private[_-]?key|seed|mnemonic|bearer)[^=]*=[^ ]+/\1=***REDACTED***/Ig'"

$KH = Join-Path $env:TEMP 'opencode\vps-known-hosts'
New-Item -ItemType File -Force -Path $KH | Out-Null

$sshCommon = @(
  '-i', $KeyPath,
  '-o', 'BatchMode=yes',
  '-o', 'ConnectTimeout=12',
  '-o', 'StrictHostKeyChecking=accept-new',
  '-o', "UserKnownHostsFile=$KH",
  '-o', 'LogLevel=ERROR'
)

$sections = @(
  @{ n = '01-identity'; c = @'
date -Is
echo "--- HOSTNAMECTL ---"; hostnamectl
echo "--- UNAME ---"; uname -a
echo "--- OS RELEASE ---"; cat /etc/os-release
echo "--- VIRT ---"; (systemd-detect-virt || echo none)
echo "--- VIRT CONTAINER ---"; (systemd-detect-virt --container || echo none)
echo "--- PID1 ---"; ps -p 1 -o pid,comm,args
echo "--- CONTAINER MARKERS ---"; (ls -lah /.dockerenv /run/.containerenv 2>/dev/null || echo "no container marker files")
echo "--- WHOAMI ---"; id; echo "HOME=$HOME"
'@ }
  @{ n = '02-cpu-memory'; c = @'
echo "--- NPROC ---"; nproc
echo "--- LSCPU ---"; lscpu
echo "--- FREE ---"; free -h
echo "--- SWAPON ---"; swapon --show
echo "--- ZRAM ---"; (zramctl 2>/dev/null || echo "zramctl unavailable/no zram")
echo "--- CGROUP V2 CPU ---"; (cat /sys/fs/cgroup/cpu.max 2>/dev/null || echo "n/a")
echo "--- CGROUP V2 MEM ---"; (cat /sys/fs/cgroup/memory.max 2>/dev/null || echo "n/a")
echo "--- CGROUP V1 CPU ---"; (cat /sys/fs/cgroup/cpu/cpu.cfs_quota_us /sys/fs/cgroup/cpu/cpu.cfs_period_us 2>/dev/null || echo "n/a")
echo "--- CGROUP V1 MEM ---"; (cat /sys/fs/cgroup/memory/memory.limit_in_bytes 2>/dev/null || echo "n/a")
'@ }
  @{ n = '03-disk'; c = @'
echo "--- DF ---"; df -hT
echo "--- LSBLK ---"; lsblk
echo "--- MOUNTS ---"; (cat /proc/mounts | grep -v -E "^(proc|sysfs|devpts|tmpfs|cgroup|mqueue|securityfs|debugfs|tracefs|bpf|overlay)" || true)
echo "--- INODE USAGE ---"; df -i
'@ }
  @{ n = '04-network'; c = @'
echo "--- IP ADDR ---"; ip -brief address
echo "--- IP ROUTE ---"; ip route
echo "--- TAILSCALE STATUS ---"; (tailscale status 2>&1 || echo unavailable)
echo "--- TAILSCALE IP ---"; (tailscale ip -4 2>&1 || echo unavailable)
echo "--- SS SOCKETS ---"; (sudo -n ss -lntup 2>&1 || echo "sudo -n failed for ss")
'@ }
  @{ n = '05-firewall'; c = 'sudo -n ufw status verbose 2>&1 || echo "sudo -n failed / ufw absent"' }
  @{ n = '06-docker-readonly'; c = @'
echo "--- DOCKER VERSION ---"; (docker version 2>&1 || echo "docker unavailable")
echo "--- DOCKER PS ---"; (docker ps -a 2>&1 || echo "docker unavailable")
echo "--- COMPOSE ---"; (docker compose version 2>&1 || echo "compose unavailable")
'@ }
  @{ n = '07-tools'; c = @'
for t in rustc cargo rustfmt clippy-driver rust-analyzer solana anchor node npm python3 git curl jq; do
  printf "%-16s " "$t"
  if command -v "$t" >/dev/null 2>&1; then ($t --version 2>&1 | head -1) || echo "version query failed"; else echo "NOT INSTALLED"; fi
done
echo "--- CARGO ENV ---"; (cat "$HOME/.cargo/env" 2>/dev/null || echo "no cargo env")
'@ }
  @{ n = '08-services'; c = @'
echo "--- RUNNING SERVICES ---"; systemctl --type=service --state=running --no-pager 2>&1
echo "--- SSH ---"; (systemctl status ssh --no-pager 2>&1 || true)
echo "--- TAILSCALED ---"; (systemctl status tailscaled --no-pager 2>&1 || true)
echo "--- DOCKER SVC ---"; (systemctl status docker --no-pager 2>&1 || true)
echo "--- ARB-BOT SVC ---"; (systemctl status arb-bot --no-pager 2>&1 || true)
'@ }
  @{ n = '09-processes'; c = @'
echo "--- TOP MEM ---"; ps aux --sort=-%mem | head -20
echo "--- TOP CPU ---"; ps aux --sort=-%cpu | head -20
'@ }
  @{ n = '10-nginx'; c = "echo '--- NGINX -T (REDACTED) ---'; (sudo -n nginx -T 2>&1 | $RedactFilter || echo 'sudo -n failed / nginx absent')" }
  @{ n = '11-caddy'; c = @"
echo '--- CADDY VALIDATE ---'; (sudo -n caddy validate --config /etc/caddy/Caddyfile 2>&1 || echo 'sudo -n failed / caddy absent')
echo '--- CADDY/NGINX LISTINGS ---'; (sudo -n ls -lah /etc/caddy /etc/nginx 2>&1 || echo 'sudo -n failed')
echo '--- CADDYFILE (REDACTED) ---'; (sudo -n cat /etc/caddy/Caddyfile 2>&1 | $RedactFilter || true)
"@ }
  @{ n = '12-git-repos'; c = @'
echo "--- HOME LISTING ---"; ls -lah "$HOME" 2>&1 | head -40
echo "--- GIT DIRS (shallow) ---"; find "$HOME" -maxdepth 4 -type d -name .git 2>/dev/null | head -30
echo "--- GIT STATUS PER REPO ---"
for d in $(find "$HOME" -maxdepth 4 -type d -name .git 2>/dev/null | head -10); do
  r=$(dirname "$d")
  echo "### REPO: $r"
  git -C "$r" status --short --branch 2>&1 | head -20
  git -C "$r" rev-parse HEAD 2>&1 | head -1
done
'@ }
  @{ n = '13-sudo-check'; c = 'sudo -n true 2>&1 && echo "PASSWORDLESS_SUDO=YES" || echo "PASSWORDLESS_SUDO=NO"' }
)

foreach ($s in $sections) {
  $out = @()
  $out += '===== SECTION ' + $s.n + ' ====='
  $out += ('RUN_UTC: ' + (Get-Date).ToUniversalTime().ToString('o'))
  $out += ('TARGET: ' + $User + '@' + $RemoteHost)
  # Normalize here-string line endings: remote bash must receive LF only.
  $cmd = ($s.c -replace "`r`n", "`n")
  $out += (ssh @sshCommon "$User@$RemoteHost" $cmd 2>&1)
  $out += ''
  $out | Set-Content -Path (Join-Path $OutDir ($s.n + '.txt'))
  Write-Host ('captured ' + $s.n)
  Start-Sleep -Milliseconds 500
}

Write-Host ("DONE — raw output in: " + $OutDir)
