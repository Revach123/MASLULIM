# CMA self-hosted runner (AWS il-central-1)

`probe.py` (see `scripts/cma/`) confirmed the block is by IP, not the WAF's JS
challenge: GitHub-hosted runners sit on Azure US infrastructure and get a
403 from CloudFront before any WAF challenge even loads. A self-hosted
runner on an Israeli AWS region should have an Israeli-allocated IP and pass.

## What `setup_runner.sh` creates

- One `t4g.small` EC2 instance (Amazon Linux 2023, arm64) in `il-central-1`,
  default VPC/subnet.
- A security group with **no inbound rules at all** (egress only) — nothing
  is exposed to the internet. Debugging is via
  `aws ec2 get-console-output --region il-central-1 --instance-id <id>`,
  not SSH.
- A GitHub Actions self-hosted runner installed as a systemd service,
  labeled `il-central-1`, registered to this repo.

Estimated cost: ~$12/month if left running 24/7 (on-demand `t4g.small`,
no reserved pricing). Stop or terminate the instance when not needed to
cut that further.

## Running it

1. Generate a runner registration token (expires in 1 hour):
   `POST /repos/Revach123/MASLULIM/actions/runners/registration-token`
   (or GitHub UI: Settings → Actions → Runners → New self-hosted runner →
   copy the token from the `config.sh` command it shows you).
2. `GH_RUNNER_TOKEN=<token> ./scripts/aws/setup_runner.sh`
   Requires AWS credentials with permission to create EC2 instances and
   security groups in `il-central-1`.
3. Check Settings → Actions → Runners in the repo — the new runner should
   show up as idle within a couple of minutes.
4. Point a workflow at it: `runs-on: [self-hosted, il-central-1]`.

## Teardown

```
aws ec2 terminate-instances --region il-central-1 --instance-ids <id>
aws ec2 delete-security-group --region il-central-1 --group-id <sg-id>
```
